"""
XGBoost Discovery — Feature Ranking for New Edge Discovery
===========================================================
Trains XGBoost regressor on the TRAINING WINDOW ONLY (first `--train-days`
of the dataset). Uses SHAP to rank features by consistent predictive power
across walk-forward folds.

KEY DESIGN DECISIONS:
  - Regression target (forward 8-bar continuous return), NOT classification.
    Regression preserves return magnitude — useful for sizing and direction.
  - TRAINING WINDOW ONLY. The last (365 - train_days) days are permanently
    locked as holdout. Never touched until a finalized H-number is ready.
  - Walk-forward on training window: 60-day train / 20-day test / 20-day step.
  - SHAP per fold → aggregate mean ± std. Features with high mean AND low
    coefficient of variation (CV) are consistently predictive, not noise.
  - Output is a ranked feature list. A human then reviews it, asks "does this
    make economic sense?", and writes a clean hypothesis rule → new H-number.

WHAT TO LOOK FOR IN OUTPUT:
  - NEW ★ feature + high mean SHAP + CV < 0.5 + clear economic rationale
    → write a clean H-number hypothesis and run through WF pipeline
  - proxy feature (eth_slope, volume, liq) at top → ML just rediscovered CA/VS/LQ
    → that's a sanity check, not a new finding
  - high CV (> 0.5) → feature importance is noisy / regime-dependent → skip
  - negative mean signed SHAP → feature predicts BEARISH moves on average

WHAT NOT TO DO:
  - Do NOT use the model's predictions as trading signals directly
  - Do NOT tune parameters based on holdout data
  - Do NOT extract rule thresholds from the model (that was the RF mistake)

Usage:
    # Step 1: build features (run once)
    PYTHONPATH=. .venv/bin/python scripts/ml/xgboost_feature_engineering.py \\
        --dsn "$RC_DB_DSN" --output results/ml/features_365d.parquet

    # Step 2: run discovery
    PYTHONPATH=. .venv/bin/python scripts/ml/xgboost_discovery.py \\
        --features results/ml/features_365d.parquet \\
        --horizon 8 \\
        --train-days 250 \\
        --output results/ml/xgb_discovery_h8.json
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import shap
from xgboost import XGBRegressor


# ── Feature columns ────────────────────────────────────────────────────────────
# Includes ALL features — new theory-first AND existing signal proxies.
# After ranking, we label which features are proxies for confirmed signals.
# Goal: find high-importance features that are NOT proxies.

FEATURE_COLS = [
    # ── Theory-first new mechanisms (what we're hunting for) ──────────────────
    "oi_expanding_3h",       # OI trend — active leverage accumulation
    "rv_compressed_4h",      # Vol compression — coiling before breakout
    "funding_pos_hours",     # Funding persistence — crowded long duration
    "funding_neg_hours",     # Funding persistence — crowded short duration
    "liq_cluster_2h",        # Liq clustering — ongoing cascade
    "hour_sin",              # Intraday seasonality (cyclical)
    "hour_cos",              # Intraday seasonality (cyclical)

    # ── Existing confirmed signal proxies (included for comparison/sanity) ────
    "eth_slope_sign_1h",     # CA-1/CA-2 core
    "btc_slope_sign_1h",     # CA-2 core
    "eth_slope_abs_pct_1h",  # CA family slope magnitude
    "spread_pct",            # CA family spread
    "volume_btc_pct",        # VS family volume gate
    "long_liq_btc_pct",      # LQ-1/LQ-4 cascade signal
    "short_liq_btc_pct",     # LQ-2/LQ-5 squeeze signal
    "total_liq_btc_pct",     # LQ-3/VS-3 combined liq gate

    # ── Other features (could be new or noise) ────────────────────────────────
    "rv48_pct_btc",          # Vol state (VS family proximity)
    "rv48_pct_eth",
    "atr14_pct_btc",
    "oi_btc_pct",            # OI level (H176 territory — probably noisy)
    "funding_btc_pct",       # Instantaneous funding level
    "funding_btc_sign",      # Instantaneous funding direction
    "er20_btc",              # Efficiency ratio — trending vs choppy
    "er20_eth",
    "dist_to_vwap48_z_btc",  # VWAP deviation (★ ranked #2 in first ML run)
    "ret1_btc",              # Most recent 5m bar return
    "ret1_eth",

    # ── Round 2 features — added 2026-03-11 for deeper discovery ─────────────
    "funding_chg_1h",        # Funding rate momentum (accelerating/decelerating)
    "btc_eth_div_1h",        # BTC vs ETH 1h return divergence (rotation signal)
    "oi_velocity",           # OI acceleration (rate of change of OI change)
    "liq_imbalance_dir",     # Long liq / total liq — directional cascade pressure
    "spread_chg_1h",         # Spread widening/narrowing momentum
    "ret_4h_btc",            # 4h BTC return — medium-term momentum context
    "vol_price_div",         # High volume + small price move = absorption

    # ── Round 3 features — added 2026-03-11 ──────────────────────────────────
    "ret_4h_eth",            # 4h ETH return — medium-term momentum
    "eth_slope_4h",          # 4h ETH slope direction
    "btc_slope_4h",          # 4h BTC slope direction
    "btc_eth_corr_2h",       # Rolling 2h BTC-ETH correlation (decoupling signal)
    "bar_dir_run",           # Consecutive same-direction bars (streak momentum)
    "rv_chg_1h",             # Vol of vol: 1h change in RV percentile
]

# Features that are direct proxies for existing confirmed signals.
# If the top-ranked features are all in this set, ML has just rediscovered
# what we already know — not a new finding.
EXISTING_SIGNAL_PROXIES = {
    "eth_slope_sign_1h", "btc_slope_sign_1h", "eth_slope_abs_pct_1h",
    "spread_pct", "volume_btc_pct",
    "long_liq_btc_pct", "short_liq_btc_pct", "total_liq_btc_pct",
}

NEW_MECHANISM_FEATURES = {
    # Round 1 theory-first features
    "oi_expanding_3h", "rv_compressed_4h",
    "funding_pos_hours", "funding_neg_hours",
    "liq_cluster_2h", "hour_sin", "hour_cos",
    # Round 2 features — added 2026-03-11
    "funding_chg_1h", "btc_eth_div_1h", "oi_velocity",
    "liq_imbalance_dir", "spread_chg_1h", "ret_4h_btc", "vol_price_div",
    # Round 3 features — added 2026-03-11
    "ret_4h_eth", "eth_slope_4h", "btc_slope_4h",
    "btc_eth_corr_2h", "bar_dir_run", "rv_chg_1h",
}


def run_discovery(
    x: pd.DataFrame,
    feature_cols: list[str],
    horizon: int,
    train_days: int,
    fold_train_days: int = 60,
    fold_step_days: int = 20,
) -> dict:
    """
    Walk-forward XGBoost + SHAP on training window only.
    Holdout (last 365-train_days days) is never touched.
    Returns aggregated SHAP stats across folds.
    """
    x = x.sort_values("dt").reset_index(drop=True).copy()

    # Forward return target: 8-bar (40-min) BTC return
    x["fwd_r"] = x["close_btc"].shift(-horizon) / x["close_btc"] - 1.0
    x = x.dropna(subset=["fwd_r"])

    # Split: training window vs locked holdout
    cutoff = x["dt"].min() + pd.Timedelta(days=train_days)
    x_train = x[x["dt"] < cutoff].copy()
    x_holdout = x[x["dt"] >= cutoff].copy()

    print(f"\n[xgb] Data split:")
    print(f"  Training : {x_train['dt'].min().date()} → {x_train['dt'].max().date()} "
          f"({len(x_train):,} bars)")
    print(f"  Holdout  : {x_holdout['dt'].min().date()} → "
          f"{x_holdout['dt'].max().date()} ({len(x_holdout):,} bars) ← LOCKED, not used")

    feat_cols = [c for c in feature_cols if c in x_train.columns]
    missing = [c for c in feature_cols if c not in x_train.columns]
    if missing:
        print(f"[xgb] Missing features (skipped): {missing}")
    print(f"[xgb] Using {len(feat_cols)} features")

    # Walk-forward folds on training window only
    fold_results = []
    cursor = x_train["dt"].min()
    train_end_limit = x_train["dt"].max()
    fold_num = 0

    while True:
        fold_train_end = cursor + pd.Timedelta(days=fold_train_days)
        fold_test_end = fold_train_end + pd.Timedelta(days=fold_step_days)

        if fold_test_end > train_end_limit:
            break

        fold_train = x_train[
            (x_train["dt"] >= cursor) & (x_train["dt"] < fold_train_end)
        ]
        fold_test = x_train[
            (x_train["dt"] >= fold_train_end) & (x_train["dt"] < fold_test_end)
        ]

        if len(fold_train) < 500 or len(fold_test) < 100:
            cursor += pd.Timedelta(days=fold_step_days)
            continue

        fold_num += 1
        X_tr = fold_train[feat_cols].fillna(0).values
        y_tr = fold_train["fwd_r"].values
        X_te = fold_test[feat_cols].fillna(0).values

        model = XGBRegressor(
            n_estimators=200,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            verbosity=0,
        )
        model.fit(X_tr, y_tr)

        explainer = shap.TreeExplainer(model)
        shap_vals = explainer.shap_values(X_te)  # shape: (n_test, n_features)

        mean_abs = np.abs(shap_vals).mean(axis=0)
        mean_signed = shap_vals.mean(axis=0)

        fold_results.append({
            "fold": fold_num,
            "train_start": str(cursor.date()),
            "train_end": str(fold_train_end.date()),
            "test_end": str(fold_test_end.date()),
            "n_train": len(fold_train),
            "n_test": len(fold_test),
            "shap_abs": {f: float(mean_abs[i]) for i, f in enumerate(feat_cols)},
            "shap_signed": {f: float(mean_signed[i]) for i, f in enumerate(feat_cols)},
        })

        print(f"  Fold {fold_num:>2}: {cursor.date()} → {fold_test_end.date()}  "
              f"train={len(fold_train):,}  test={len(fold_test):,}")

        cursor += pd.Timedelta(days=fold_step_days)

    if not fold_results:
        raise RuntimeError("No folds completed — check data and date range")

    print(f"\n[xgb] {len(fold_results)} folds completed")

    # Aggregate SHAP across folds
    abs_df = pd.DataFrame([f["shap_abs"] for f in fold_results])
    signed_df = pd.DataFrame([f["shap_signed"] for f in fold_results])

    ranking = pd.DataFrame({
        "mean_abs_shap": abs_df.mean(),
        "std_abs_shap": abs_df.std(),
        "cv": abs_df.std() / (abs_df.mean() + 1e-10),
        "mean_signed_shap": signed_df.mean(),
        "n_folds_positive": (signed_df > 0).sum(),
        "n_folds": len(fold_results),
    }).sort_values("mean_abs_shap", ascending=False)

    ranking["is_new_mechanism"] = ranking.index.isin(NEW_MECHANISM_FEATURES)
    ranking["is_existing_proxy"] = ranking.index.isin(EXISTING_SIGNAL_PROXIES)
    ranking["direction"] = np.where(ranking["mean_signed_shap"] > 0, "BULLISH", "BEARISH")
    ranking["consistent"] = ranking["cv"] < 0.5

    return {
        "feature_ranking": (
            ranking.reset_index()
            .rename(columns={"index": "feature"})
            .to_dict(orient="records")
        ),
        "fold_results": fold_results,
        "n_folds": len(fold_results),
        "horizon_bars": horizon,
        "train_days": train_days,
        "holdout_start": str(cutoff.date()),
    }


def print_summary(result: dict) -> None:
    ranking = pd.DataFrame(result["feature_ranking"])

    print("\n" + "=" * 80)
    print(f"XGBoost Discovery Results")
    print(f"horizon={result['horizon_bars']} bars | "
          f"{result['n_folds']} WF folds | "
          f"holdout locked from {result['holdout_start']}")
    print("=" * 80)
    print(f"{'Rank':<5} {'Feature':<28} {'SHAP':>8} {'±Std':>7} {'CV':>5} "
          f"{'Dir':>8} {'OK':>4} {'Type':<12}")
    print("-" * 80)

    for rank, (_, row) in enumerate(ranking.head(20).iterrows(), 1):
        tag = "NEW ★" if row["is_new_mechanism"] else (
            "proxy" if row["is_existing_proxy"] else "other"
        )
        ok = "✓" if row["consistent"] else "✗"
        print(f"{rank:<5} {row['feature']:<28} {row['mean_abs_shap']:>8.5f} "
              f"{row['std_abs_shap']:>7.5f} {row['cv']:>5.2f} "
              f"{row['direction']:>8} {ok:>4} {tag:<12}")

    print("\n── New mechanism features only ──")
    new = ranking[ranking["is_new_mechanism"]].copy()
    for rank_overall, (_, row) in enumerate(
        ranking[ranking.index.isin(new.index)].iterrows(), 1
    ):
        overall_rank = ranking["feature"].tolist().index(row["feature"]) + 1
        ok = "✓ consistent" if row["consistent"] else "✗ noisy"
        print(f"  #{overall_rank:<3} {row['feature']:<28} "
              f"SHAP={row['mean_abs_shap']:.5f}  "
              f"{row['direction']}  {ok}")

    print("\n── Guide ──")
    print("  NEW ★ + high SHAP + CV<0.5 + economic rationale → write H-number hypothesis")
    print("  proxy at top → ML confirmed existing signal (sanity check, not new finding)")
    print("  CV > 0.5 → noisy across folds → skip")
    print("=" * 80)


def print_multi_horizon_summary(results: list[dict]) -> None:
    """
    Cross-horizon summary: shows each feature's rank and SHAP at every horizon.
    Features that rank consistently high across ALL horizons are the most robust.
    A feature that only appears at h=8 is suspicious; one that appears at h=4,
    h=8, h=24 is genuinely predictive across time scales.
    """
    horizons = [r["horizon_bars"] for r in results]
    all_features = set()
    for r in results:
        for row in r["feature_ranking"]:
            all_features.add(row["feature"])

    # Build per-feature cross-horizon stats
    rows = []
    for feat in sorted(all_features):
        row = {"feature": feat}
        shap_vals = []
        ranks = []
        consistent_count = 0
        for r in results:
            h = r["horizon_bars"]
            ranking = {x["feature"]: x for x in r["feature_ranking"]}
            feat_list = [x["feature"] for x in r["feature_ranking"]]
            if feat in ranking:
                s = ranking[feat]["mean_abs_shap"]
                rank = feat_list.index(feat) + 1
                row[f"shap_h{h}"] = s
                row[f"rank_h{h}"] = rank
                shap_vals.append(s)
                ranks.append(rank)
                if ranking[feat]["consistent"]:
                    consistent_count += 1
            else:
                row[f"shap_h{h}"] = 0.0
                row[f"rank_h{h}"] = 99
        row["mean_shap_all"] = float(np.mean(shap_vals)) if shap_vals else 0.0
        row["mean_rank_all"] = float(np.mean(ranks)) if ranks else 99.0
        row["n_horizons_consistent"] = consistent_count
        row["is_new_mechanism"] = feat in NEW_MECHANISM_FEATURES
        row["is_existing_proxy"] = feat in EXISTING_SIGNAL_PROXIES
        rows.append(row)

    summary = pd.DataFrame(rows).sort_values("mean_shap_all", ascending=False)

    print("\n" + "=" * 100)
    print(f"MULTI-HORIZON Discovery Summary  |  horizons tested: {horizons} bars "
          f"({'min / '.join(str(h*5) for h in horizons)} min)")
    print("Features ranked by mean SHAP across all horizons.")
    print("★ = appears consistently at multiple horizons — strongest candidates for hypothesis.")
    print("=" * 100)

    h_cols = [f"rank_h{h}" for h in horizons]
    header = f"{'Feature':<28} {'AvgSHAP':>9} {'AvgRank':>8}  " + "  ".join(f"r@h{h}" for h in horizons) + "  Consistent  Type"
    print(header)
    print("-" * 100)

    for _, row in summary.head(25).iterrows():
        tag = "NEW ★" if row["is_new_mechanism"] else (
            "proxy" if row["is_existing_proxy"] else "other"
        )
        rank_str = "  ".join(f"{int(row[c]):>5}" for c in h_cols)
        n_cons = int(row["n_horizons_consistent"])
        star = "★" if n_cons >= len(horizons) - 1 else (" " if n_cons > 0 else "✗")
        print(f"{row['feature']:<28} {row['mean_shap_all']:>9.5f} {row['mean_rank_all']:>8.1f}  "
              f"{rank_str}  {star} {n_cons}/{len(horizons)}       {tag}")

    print("\n── Strongest NEW candidates (consistent across horizons) ──")
    strong_new = summary[
        summary["is_new_mechanism"] &
        (summary["n_horizons_consistent"] >= len(horizons) - 1) &
        (summary["mean_rank_all"] <= 15)
    ]
    if strong_new.empty:
        print("  None met criteria (new + consistent at N-1 horizons + avg rank <= 15)")
    else:
        for _, row in strong_new.iterrows():
            rank_str = "  ".join(f"h{h}=#{int(row[f'rank_h{h}'])}" for h in horizons)
            print(f"  {row['feature']:<28}  {rank_str}  → write hypothesis")

    print("=" * 100)


def main():
    parser = argparse.ArgumentParser(description="XGBoost feature discovery run")
    parser.add_argument("--features", default="results/ml/features_365d.parquet",
                        help="Path to features parquet (from xgboost_feature_engineering.py)")
    parser.add_argument("--horizons", type=int, nargs="+", default=[4, 8, 16, 48],
                        help="Forward return horizons in 5m bars (default: 4 8 16 48 = 20min/40min/80min/4h)")
    parser.add_argument("--horizon", type=int, default=None,
                        help="Single horizon (overrides --horizons, for backward compat)")
    parser.add_argument("--train-days", type=int, default=250,
                        help="Training window days. Rest is locked holdout. (default 250)")
    parser.add_argument("--output", default="results/ml/xgb_discovery_multi.json",
                        help="Output JSON path")
    args = parser.parse_args()

    # Backward compat: single --horizon overrides --horizons
    horizons = [args.horizon] if args.horizon is not None else args.horizons

    features_path = Path(args.features)
    if not features_path.exists():
        print(f"ERROR: features file not found: {features_path}", file=sys.stderr)
        print("Run xgboost_feature_engineering.py first.", file=sys.stderr)
        sys.exit(1)

    print(f"[xgb] Loading features from {features_path}...")
    x = pd.read_parquet(features_path)
    x["dt"] = pd.to_datetime(x["dt"], utc=True)
    print(f"[xgb] {len(x):,} bars  ({x['dt'].min().date()} → {x['dt'].max().date()})")

    all_results = []
    for h in horizons:
        print(f"\n{'='*60}")
        print(f"[xgb] Running horizon h={h} ({h*5} min forward return)...")
        result = run_discovery(
            x=x,
            feature_cols=FEATURE_COLS,
            horizon=h,
            train_days=args.train_days,
        )
        print_summary(result)
        all_results.append(result)

    # Multi-horizon combined summary (only if more than one horizon)
    if len(all_results) > 1:
        print_multi_horizon_summary(all_results)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "horizons_tested": horizons,
        "train_days": args.train_days,
        "results_by_horizon": {r["horizon_bars"]: r for r in all_results},
    }
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n[xgb] Full results saved → {out_path}")


if __name__ == "__main__":
    main()
