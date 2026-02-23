"""
RF Hypothesis Generator — Stage 2 of ML pipeline
==================================================
Uses XGBoost + SHAP walk-forward to discover which features and feature
combinations predict BTC forward returns. Outputs ranked feature candidates
that can be formalized as explicit rule-based hypotheses.

Key design decisions:
  - Full feature matrix, NO pre-exclusions (CA slope features included)
  - After run: compare top candidates to existing CA-1..CA-5 signals
  - Horizon is configurable — do NOT assume 8 bars
  - RF is never deployed directly; output → hypothesis rule → H-number → pipeline

Walk-forward:
  Train: 90 days  |  Test: 30 days  |  Step: 30 days  → ~9 folds

Usage:
  PYTHONPATH=. .venv/bin/python scripts/ml/rf_hypothesis_generator.py \\
      --dsn "$RC_DB_DSN" \\
      --days 365 \\
      --horizon 12 \\
      --output-json results/ml/rf/rf_candidates_$(date +%Y%m%d)_h12.json

Run multiple horizons to compare:
  --horizon 6   (30 min — mean-reversion candidates)
  --horizon 12  (60 min — default, balanced)
  --horizon 24  (2h — trend/momentum candidates)

Design spec: docs/rf_experiment_plan.md
"""

import argparse
import json
import os
import sys
from datetime import date, timedelta

import numpy as np
import pandas as pd
from xgboost import XGBClassifier
import shap

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from scripts.research_family_runner import load_frame
import app.db.rc as rc


# ── Features to use ───────────────────────────────────────────────────────────
# All features from load_frame() — no pre-exclusions.
# Includes CA slope features intentionally: if RF rediscovers them as top
# predictors, that is independent confirmation they are real.
# After the run, compare candidates to CA-1..CA-5 and flag overlaps.

FEATURE_COLS = [
    # Volatility
    "rv48_pct_btc", "rv48_pct_eth",
    "atr14_pct_btc", "atr14_pct_eth",
    "atr_rv_ratio_pct_btc",
    # Efficiency / trending vs choppy
    "er20_btc", "er20_eth",
    "delta_er", "abs_delta_er_pct",
    # VWAP / mean-reversion
    "vwap_z",
    "dist_to_vwap48_z_btc", "dist_to_vwap48_z_eth",
    "abs_vwap_dist_pct_btc",
    # Bar structure
    "ret1_abs_btc_pct", "ret1_abs_eth_pct",
    "bar_dir_btc", "bar_dir_eth",
    "ret1_btc", "ret1_eth",
    # Cross-asset (CA family — include, not exclude)
    "spread_pct",
    "eth_slope_sign_1h", "btc_slope_sign_1h",
    "eth_slope_abs_pct_1h", "eth_slope_z_1h",
    # Funding
    "funding_btc_pct", "funding_btc_sign", "funding_btc_flip",
    # Session (added below)
    "hour_of_day", "day_of_week", "is_weekend",
]

# Features that belong to existing confirmed signal families.
# Candidates dominated by these get flagged as CA-family, not new discoveries.
CA_FAMILY_FEATURES = {
    "spread_pct", "eth_slope_sign_1h", "btc_slope_sign_1h",
    "eth_slope_abs_pct_1h", "eth_slope_z_1h",
}


# ── Data loading ──────────────────────────────────────────────────────────────

def load_features(days: int, horizon: int, dsn: str) -> pd.DataFrame:
    """
    Load feature frame via existing load_frame(), add session features
    and forward return target. Returns clean DataFrame.
    """
    print(f"[RF] Loading feature frame ({days}d, horizon={horizon})...")
    x = load_frame(days=days, dsn=dsn)

    # Session features
    x["hour_of_day"] = x["dt"].dt.hour
    x["day_of_week"] = x["dt"].dt.dayofweek
    x["is_weekend"]  = (x["day_of_week"] >= 5).astype(int)

    # Forward return target
    x["fwd_r_h"] = x["close_btc"].shift(-horizon) / x["close_btc"] - 1.0
    x["target"]  = np.sign(x["fwd_r_h"]).astype(int)

    # Drop flat bars and NaN targets
    x = x[x["target"] != 0].copy()

    # Keep only columns we need
    keep = ["dt", "ts", "fwd_r_h", "target"] + [
        c for c in FEATURE_COLS if c in x.columns
    ]
    x = x[keep].dropna(subset=[c for c in FEATURE_COLS if c in x.columns])

    print(f"[RF] Feature frame: {len(x):,} bars  "
          f"({x['dt'].min().date()} → {x['dt'].max().date()})")
    missing = [c for c in FEATURE_COLS if c not in x.columns]
    if missing:
        print(f"[RF] Warning: missing features (skipped): {missing}")

    return x.reset_index(drop=True)


# ── Walk-forward RF ───────────────────────────────────────────────────────────

def run_walkforward_rf(
    x: pd.DataFrame,
    train_days: int,
    step_days: int,
    n_estimators: int,
    max_depth: int,
) -> list[dict]:
    """
    Walk-forward XGBoost + SHAP.

    For each fold:
      1. Train XGBClassifier on train window
      2. Compute SHAP values on test window
      3. Record per-feature mean |SHAP| and direction

    Returns list of fold result dicts.
    """
    feat_cols = [c for c in FEATURE_COLS if c in x.columns]
    x = x.sort_values("dt").reset_index(drop=True)
    x["dt_date"] = x["dt"].dt.date

    fold_results = []
    fold_num = 0

    dates = sorted(x["dt_date"].unique())
    train_delta = timedelta(days=train_days)
    step_delta  = timedelta(days=step_days)

    start_date = dates[0]
    cursor = start_date + train_delta

    while cursor <= dates[-1]:
        train_end  = cursor
        test_start = cursor
        test_end   = cursor + step_delta

        train_mask = (x["dt"].dt.date >= start_date) & (x["dt"].dt.date < train_end)
        test_mask  = (x["dt"].dt.date >= test_start) & (x["dt"].dt.date < test_end)

        X_train = x.loc[train_mask, feat_cols]
        y_train = x.loc[train_mask, "target"]
        X_test  = x.loc[test_mask,  feat_cols]

        if len(X_train) < 500 or len(X_test) < 100:
            cursor += step_delta
            continue

        # Map target: -1 → 0, 1 → 1  (XGBoost needs 0/1)
        y_train_bin = (y_train == 1).astype(int)

        model = XGBClassifier(
            n_estimators=n_estimators,
            max_depth=max_depth,
            min_child_weight=100,   # prevents tiny leaf nodes
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            eval_metric="logloss",
            random_state=42,
            verbosity=0,
        )
        model.fit(X_train, y_train_bin)

        # SHAP on a sample of test bars (fast)
        shap_sample = X_test.sample(min(500, len(X_test)), random_state=42)
        explainer   = shap.TreeExplainer(model)
        shap_vals   = explainer.shap_values(shap_sample)  # shape: (n, features)

        # Per-feature: mean |SHAP| (importance) and mean signed SHAP (direction)
        mean_abs_shap = np.abs(shap_vals).mean(axis=0)
        mean_shap     = shap_vals.mean(axis=0)

        # Feature importance ranking for this fold
        importance_rank = np.argsort(mean_abs_shap)[::-1]
        top_features = [
            {
                "feature":       feat_cols[i],
                "rank":          int(r + 1),
                "mean_abs_shap": float(mean_abs_shap[i]),
                "mean_shap":     float(mean_shap[i]),
                "direction":     "positive" if mean_shap[i] > 0 else "negative",
            }
            for r, i in enumerate(importance_rank[:15])  # top-15 per fold
        ]

        fold_num += 1
        print(f"  fold {fold_num:2d}: train_end={train_end}  "
              f"train_n={len(X_train):,}  test_n={len(X_test):,}  "
              f"top_feature={feat_cols[importance_rank[0]]}")

        fold_results.append({
            "fold":         fold_num,
            "train_end":    str(train_end),
            "test_start":   str(test_start),
            "test_end":     str(test_end),
            "train_n":      int(len(X_train)),
            "test_n":       int(len(X_test)),
            "top_features": top_features,
        })

        cursor += step_delta

    return fold_results


# ── Aggregate across folds ────────────────────────────────────────────────────

def aggregate_folds(fold_results: list[dict], min_folds: int = 5) -> list[dict]:
    """
    Aggregate feature importance across folds.
    A feature is a candidate if it appears in top-10 in min_folds+ folds.
    """
    feat_cols = FEATURE_COLS
    n_folds   = len(fold_results)

    # Count how many folds each feature appears in top-10
    top10_counts  = {f: 0 for f in feat_cols}
    shap_sums     = {f: 0.0 for f in feat_cols}
    direction_sum = {f: 0.0 for f in feat_cols}

    for fold in fold_results:
        top10 = {e["feature"] for e in fold["top_features"][:10]}
        for e in fold["top_features"]:
            feat = e["feature"]
            if feat in top10_counts:
                top10_counts[feat]  += (1 if feat in top10 else 0)
                shap_sums[feat]     += e["mean_abs_shap"]
                direction_sum[feat] += e["mean_shap"]

    candidates = []
    for feat in feat_cols:
        if top10_counts[feat] >= min_folds:
            direction = "positive" if direction_sum[feat] > 0 else "negative"
            is_ca_family = feat in CA_FAMILY_FEATURES
            candidates.append({
                "feature":          feat,
                "consistent_folds": top10_counts[feat],
                "total_folds":      n_folds,
                "mean_abs_shap":    round(shap_sums[feat] / n_folds, 6),
                "direction":        direction,
                "ca_family":        is_ca_family,
                "note": (
                    "CA-family feature — likely rediscovering existing signal. "
                    "Skip unless combining with non-CA features."
                    if is_ca_family else
                    "Non-CA feature — potential new signal family."
                ),
            })

    # Sort by consistent_folds desc, then mean_abs_shap desc
    candidates.sort(key=lambda c: (-c["consistent_folds"], -c["mean_abs_shap"]))
    return candidates


# ── Regime-conditional breakdown ──────────────────────────────────────────────

def regime_breakdown(
    x: pd.DataFrame,
    candidates: list[dict],
    dsn: str,
    horizon: int,
    run_date: date,
) -> list[dict]:
    """
    For each top-5 non-CA candidate: compute mean forward return
    broken down by HMM regime label. Shows whether the signal is
    regime-dependent.
    """
    if not dsn:
        return []

    # Load HMM labels from DB
    try:
        with rc.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT ts, regime_name
                    FROM rc.regime_labels
                    WHERE symbol = 'BTC-USD' AND timeframe = '1h'
                    ORDER BY ts
                """)
                rows = cur.fetchall()
        if not rows:
            return []
        labels = pd.DataFrame(rows, columns=["ts", "regime_name"])
        labels["ts"] = pd.to_datetime(labels["ts"], utc=True)
        labels = labels.set_index("ts")
    except Exception as e:
        print(f"[RF] Could not load regime labels: {e}", file=sys.stderr)
        return []

    # Merge labels onto feature frame (forward-fill 1h label onto 5m bars)
    x2 = x.copy()
    x2 = x2.set_index("dt").sort_index()
    x2["regime"] = pd.merge_asof(
        x2[[]].reset_index(),
        labels.reset_index().rename(columns={"ts": "dt"}),
        on="dt",
        direction="backward",
    ).set_index("dt")["regime_name"]

    results = []
    non_ca_top5 = [c for c in candidates if not c["ca_family"]][:5]

    for cand in non_ca_top5:
        feat = cand["feature"]
        if feat not in x2.columns:
            continue

        # Simple threshold: feature in top 30% (for "high" condition)
        # This is exploratory only — not a hypothesis threshold
        threshold = float(x2[feat].quantile(0.70))
        direction = cand["direction"]
        if direction == "positive":
            mask = x2[feat] > threshold
        else:
            mask = x2[feat] < x2[feat].quantile(0.30)

        regime_stats = {}
        for regime in ["RANGING", "TRENDING", "VOLATILE"]:
            regime_mask = mask & (x2["regime"] == regime)
            n = int(regime_mask.sum())
            if n < 20:
                regime_stats[regime] = {"n": n, "mean_fwd_r": None}
                continue
            mean_r = float(x2.loc[regime_mask, "fwd_r_h"].mean())
            regime_stats[regime] = {
                "n":          n,
                "mean_fwd_r": round(mean_r * 100, 4),  # in %
            }

        results.append({
            "feature":      feat,
            "direction":    direction,
            "threshold_p70": round(threshold, 6),
            "regime_stats": regime_stats,
            "interpretation": _interpret_regime_stats(regime_stats),
        })

    return results


def _interpret_regime_stats(stats: dict) -> str:
    positive = [r for r, v in stats.items()
                if v["mean_fwd_r"] is not None and v["mean_fwd_r"] > 0]
    if len(positive) == 3:
        return "Works across all regimes — robust candidate"
    elif len(positive) == 2:
        return f"Works in {' and '.join(positive)} — regime-conditional"
    elif len(positive) == 1:
        return f"Only works in {positive[0]} regime — fragile, label accordingly"
    else:
        return "No positive regime — signal may be noise"


# ── Hypothesis candidate suggestions ─────────────────────────────────────────

def suggest_hypotheses(
    candidates: list[dict],
    regime_data: list[dict],
    next_h_id: int,
) -> list[dict]:
    """
    For each non-CA candidate that appears in 6+ folds, suggest a hypothesis rule.
    Returns suggested H-number assignments (starting from next_h_id).
    The user and AI review these before adding to hypotheses.yaml.
    """
    suggestions = []
    h_id = next_h_id

    non_ca = [c for c in candidates if not c["ca_family"] and c["consistent_folds"] >= 6]
    regime_map = {r["feature"]: r for r in regime_data}

    for cand in non_ca[:5]:  # max 5 suggestions
        feat = cand["feature"]
        direction_word = "above 70th pct" if cand["direction"] == "positive" else "below 30th pct"
        regime_info = regime_map.get(feat, {})
        best_regime = None
        if regime_info:
            stats = regime_info.get("regime_stats", {})
            best = max(
                ((r, v["mean_fwd_r"]) for r, v in stats.items()
                 if v["mean_fwd_r"] is not None),
                key=lambda x: x[1],
                default=(None, None),
            )
            best_regime = best[0]

        suggestions.append({
            "suggested_h_id": f"H{h_id}",
            "feature":         feat,
            "direction":       cand["direction"],
            "consistent_folds": cand["consistent_folds"],
            "suggested_rule":  (
                f"Enter long BTC when {feat} is {direction_word}"
                + (f", gated by regime={best_regime}" if best_regime else "")
            ),
            "suggested_family": _guess_family(feat),
            "best_regime":     best_regime,
            "status":          "CANDIDATE — review before adding to hypotheses.yaml",
            "warning": (
                "Pre-commit to threshold BEFORE looking at in-sample performance. "
                "Use 70th/30th pct as starting point, do not optimize."
            ),
        })
        h_id += 1

    return suggestions


def _guess_family(feature: str) -> str:
    if "rv" in feature or "atr" in feature:
        return "volatility_state"
    if "funding" in feature:
        return "funding_regime"
    if "vwap" in feature or "dist" in feature:
        return "mean_reversion"
    if "er20" in feature or "delta_er" in feature:
        return "efficiency"
    if "hour" in feature or "day" in feature or "weekend" in feature:
        return "session"
    if "spread" in feature or "slope" in feature:
        return "cross_asset_regime"
    return "unknown"


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="RF Hypothesis Generator")
    parser.add_argument("--dsn",          required=True)
    parser.add_argument("--days",         type=int, default=365)
    parser.add_argument("--horizon",      type=int, default=12,
                        help="Forward return horizon in bars (6=30min, 12=60min, 24=2h)")
    parser.add_argument("--train-days",   type=int, default=90)
    parser.add_argument("--step-days",    type=int, default=30)
    parser.add_argument("--min-folds",    type=int, default=5,
                        help="Min folds in top-10 to report a feature as candidate")
    parser.add_argument("--n-estimators", type=int, default=300)
    parser.add_argument("--max-depth",    type=int, default=4)
    parser.add_argument("--next-h-id",   type=int, default=125,
                        help="Next available hypothesis ID for suggestions")
    parser.add_argument("--output-json",  default="results/ml/rf/rf_candidates.json")
    args = parser.parse_args()

    run_date = date.today()
    config = {
        "days":       args.days,
        "horizon":    args.horizon,
        "train_days": args.train_days,
        "step_days":  args.step_days,
        "min_folds":  args.min_folds,
    }

    # Load features
    x = load_features(days=args.days, horizon=args.horizon, dsn=args.dsn)

    # Walk-forward RF
    print(f"\n[RF] Running walk-forward XGBoost "
          f"(train={args.train_days}d, step={args.step_days}d, "
          f"horizon={args.horizon} bars = {args.horizon * 5}min)...")
    fold_results = run_walkforward_rf(
        x,
        train_days=args.train_days,
        step_days=args.step_days,
        n_estimators=args.n_estimators,
        max_depth=args.max_depth,
    )
    print(f"\n[RF] Completed {len(fold_results)} folds.")

    # Aggregate candidates
    candidates = aggregate_folds(fold_results, min_folds=args.min_folds)
    print(f"\n[RF] Top candidates (present in {args.min_folds}+ folds):")
    for c in candidates:
        tag = " [CA-FAMILY]" if c["ca_family"] else " [NEW]"
        print(f"  {c['feature']:35s}  folds={c['consistent_folds']}/{len(fold_results)}"
              f"  shap={c['mean_abs_shap']:.5f}  dir={c['direction']}{tag}")

    # Regime-conditional breakdown for non-CA candidates
    print(f"\n[RF] Running regime-conditional breakdown...")
    regime_data = regime_breakdown(x, candidates, dsn=args.dsn,
                                   horizon=args.horizon, run_date=run_date)

    # Hypothesis suggestions
    suggestions = suggest_hypotheses(candidates, regime_data, next_h_id=args.next_h_id)

    # Build and write output
    output = {
        "run_date":      str(run_date),
        "config":        config,
        "n_folds":       len(fold_results),
        "n_candidates":  len(candidates),
        "top_candidates": candidates,
        "regime_breakdown": regime_data,
        "hypothesis_suggestions": suggestions,
        "folds": fold_results,
        "notes": [
            f"Horizon={args.horizon} bars ({args.horizon * 5} min). "
            "Re-run with --horizon 6 and --horizon 24 for MR and trend candidates.",
            "CA-family candidates likely rediscover existing signals. Focus on [NEW] candidates.",
            "Pre-commit to threshold before running any suggestion through the pipeline.",
            "Run suggestions through standard WF+bootstrap gates — do not trust RF in-sample performance.",
        ],
    }

    os.makedirs(os.path.dirname(args.output_json), exist_ok=True)
    with open(args.output_json, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n[RF] Output written to {args.output_json}")

    if suggestions:
        print(f"\n[RF] Suggested hypotheses to review:")
        for s in suggestions:
            print(f"  {s['suggested_h_id']}: {s['suggested_rule']}")
            print(f"         family={s['suggested_family']}  folds={s['consistent_folds']}")

    print("\n[RF] Done.")
    print("Next steps:")
    print("  1. Review output JSON with your human eyes")
    print("  2. Compare [CA-FAMILY] candidates to existing signals — are they truly the same?")
    print("  3. For [NEW] candidates: write explicit rule in plain English")
    print("  4. Add to hypotheses.yaml with next H-number, run through standard pipeline")
    print(f"  5. Re-run with --horizon 6 and --horizon 24 for other time horizons")


if __name__ == "__main__":
    main()
