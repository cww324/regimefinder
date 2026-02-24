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

INTERACTION MODE (--interactions):
  Also extracts multi-feature hypothesis rules by:
    1. Computing pairwise SHAP interaction values for top-8 features per fold
    2. Running quadrant analysis (f1_high/low × f2_high/low) on test-set forward returns
    3. Finding pairs where a specific quadrant has consistent direction across 3+ folds
  This is the principled way to get multi-feature rules: the RF identifies which
  pairs interact, quadrant analysis gives the directional edge, fold consistency
  ensures it's not noise.
  Adds ~30-60 sec per run. Recommended: use with --regime for cleaner signals.

Design spec: docs/rf_experiment_plan.md
"""

import argparse
import json
import os
import sys
from collections import defaultdict
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

def load_regime_labels(dsn: str) -> pd.DataFrame:
    """Load HMM regime labels from rc.regime_labels. Returns df with [dt, regime]."""
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
        raise RuntimeError("No regime labels found in rc.regime_labels. Run HMM script first.")
    labels = pd.DataFrame(rows, columns=["dt", "regime"])
    labels["dt"] = pd.to_datetime(labels["dt"], utc=True)
    return labels


def load_features(days: int, horizon: int, dsn: str, regime: str | None = None) -> pd.DataFrame:
    """
    Load feature frame via existing load_frame(), add session features
    and forward return target. If regime is set, filters to only bars
    with that HMM regime label — RF then discovers signals within that regime.
    """
    regime_tag = f", regime={regime}" if regime else ""
    print(f"[RF] Loading feature frame ({days}d, horizon={horizon}{regime_tag})...")
    x = load_frame(days=days, dsn=dsn)

    # Session features
    x["hour_of_day"] = x["dt"].dt.hour
    x["day_of_week"] = x["dt"].dt.dayofweek
    x["is_weekend"]  = (x["day_of_week"] >= 5).astype(int)

    # Forward return target
    x["fwd_r_h"] = x["close_btc"].shift(-horizon) / x["close_btc"] - 1.0

    # Regime filter — join HMM labels and filter BEFORE dropping NaN targets
    # so the forward return is still computed on the full series (no leakage)
    if regime and dsn:
        labels = load_regime_labels(dsn)
        x = x.sort_values("dt").reset_index(drop=True)
        x = pd.merge_asof(
            x,
            labels.sort_values("dt"),
            on="dt",
            direction="backward",
        )
        n_before = len(x)
        x = x[x["regime"] == regime].copy()
        print(f"[RF] Regime filter '{regime}': {len(x):,} / {n_before:,} bars "
              f"({len(x)/n_before*100:.0f}%)")

    # Explicitly drop NaN targets before sign/cast (last `horizon` bars will be NaN)
    x = x.dropna(subset=["fwd_r_h"]).copy()
    x["target"] = np.sign(x["fwd_r_h"]).astype(int)

    # Drop flat bars (target == 0)
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
    compute_interactions: bool = False,
) -> tuple[list[dict], list[dict]]:
    """
    Walk-forward XGBoost + SHAP.

    For each fold:
      1. Train XGBClassifier on train window
      2. Compute SHAP values on test window
      3. Record per-feature mean |SHAP| and direction
      4. If compute_interactions=True: also compute pairwise SHAP interaction
         values for top-8 features and run quadrant analysis on test forward returns

    Returns (fold_results, pair_fold_results).
    pair_fold_results is empty if compute_interactions=False.
    """
    feat_cols = [c for c in FEATURE_COLS if c in x.columns]
    x = x.sort_values("dt").reset_index(drop=True)
    x["dt_date"] = x["dt"].dt.date

    fold_results      = []
    pair_fold_results = []
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

        X_train      = x.loc[train_mask, feat_cols]
        y_train      = x.loc[train_mask, "target"]
        X_test       = x.loc[test_mask,  feat_cols]
        y_test_fwd_r = x.loc[test_mask,  "fwd_r_h"]

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

        # ── Interaction analysis ───────────────────────────────────────────
        if compute_interactions:
            top8_idx   = importance_rank[:8]
            top8_feats = [feat_cols[i] for i in top8_idx]

            # Compute SHAP interaction values on a small sample (fast)
            inter_sample_n = min(200, len(shap_sample))
            inter_sample   = shap_sample.iloc[:inter_sample_n]

            try:
                # interaction_values shape: (n_samples, n_feat_total, n_feat_total)
                # Off-diagonal [i,j,k] (j≠k) = interaction effect between features j and k
                inter_vals = explainer.shap_interaction_values(inter_sample)
                # Mean absolute interaction across samples → (n_feat, n_feat)
                mean_inter_full = np.abs(inter_vals).mean(axis=0)

                # Extract top interacting pairs within the top-8 features
                inter_pairs = []
                for a, fi in enumerate(top8_idx):
                    for b, fj in enumerate(top8_idx):
                        if fi >= fj:
                            continue
                        inter_pairs.append((
                            feat_cols[fi],
                            feat_cols[fj],
                            float(mean_inter_full[fi, fj]),
                        ))
                inter_pairs.sort(key=lambda p: -p[2])
                # Analyze ALL pairs within top-8 (C(8,2)=28 pairs), not just top-3.
                # SHAP interaction score used for ranking only — not for filtering.
                # This ensures the same pair is analyzed across all folds so
                # aggregate_pair_rules() can find consistent multi-fold patterns.

                # Quadrant analysis for all top-8 pairs on test data forward returns
                pair_rules = _quadrant_analysis(
                    X_train, X_test, y_test_fwd_r, inter_pairs
                )
                pair_fold_results.append({
                    "fold":       fold_num,
                    "pair_rules": pair_rules,
                })
                top1 = inter_pairs[0]
                print(f"         interactions: top pair=({top1[0]},{top1[1]}) "
                      f"score={top1[2]:.5f}  "
                      f"quadrant_rules={len(pair_rules)}")

            except Exception as e:
                print(f"  [WARN] Interaction analysis failed fold {fold_num}: {e}",
                      file=sys.stderr)

        cursor += step_delta

    return fold_results, pair_fold_results


def _quadrant_analysis(
    X_train: pd.DataFrame,
    X_test:  pd.DataFrame,
    y_test_fwd_r: pd.Series,
    pairs: list[tuple],
    hi_q: float = 0.70,
    lo_q: float = 0.30,
    min_n:  int = 30,
) -> list[dict]:
    """
    For each feature pair (f1, f2, inter_score): compute mean forward return
    in each of the 4 quadrants (f1_hi/lo × f2_hi/lo).

    Thresholds are computed from TRAINING data only — no lookahead.
    Only quadrants with n >= min_n on the test window are recorded.

    Returns list of {f1, dir1, f2, dir2, n, mean_fwd_r, direction, inter_score}.
    """
    rules = []
    for f1, f2, inter_score in pairs:
        if f1 not in X_train.columns or f2 not in X_train.columns:
            continue

        # Thresholds from training data
        t1_hi = float(X_train[f1].quantile(hi_q))
        t1_lo = float(X_train[f1].quantile(lo_q))
        t2_hi = float(X_train[f2].quantile(hi_q))
        t2_lo = float(X_train[f2].quantile(lo_q))

        for dir1, mask1 in [
            ("high", X_test[f1] > t1_hi),
            ("low",  X_test[f1] < t1_lo),
        ]:
            for dir2, mask2 in [
                ("high", X_test[f2] > t2_hi),
                ("low",  X_test[f2] < t2_lo),
            ]:
                combined = mask1 & mask2
                n = int(combined.sum())
                if n < min_n:
                    continue
                mean_r = float(y_test_fwd_r.loc[combined].mean())
                rules.append({
                    "f1":          f1,
                    "dir1":        dir1,
                    "f2":          f2,
                    "dir2":        dir2,
                    "n":           n,
                    "mean_fwd_r":  round(mean_r * 100, 4),  # in %
                    "direction":   "long" if mean_r > 0 else "short",
                    "inter_score": round(inter_score, 6),
                })

    return rules


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


def aggregate_pair_rules(
    pair_fold_results: list[dict],
    min_folds: int = 3,
    min_direction_pct: float = 0.67,
) -> list[dict]:
    """
    Aggregate quadrant results across folds to find stable multi-feature rules.

    A rule (f1, dir1, f2, dir2) is stable if:
      - It appears in at least min_folds test windows
      - At least min_direction_pct of those folds agree on direction (long/short)

    Note: features are sorted alphabetically to deduplicate (f1 ≤ f2).

    Returns list of stable rules sorted by fold_count desc, then direction
    consistency desc, then |mean_fwd_r| desc.
    """
    rule_data: dict[tuple, list] = defaultdict(list)

    for fold_data in pair_fold_results:
        seen_in_fold: set[tuple] = set()
        for rule in fold_data["pair_rules"]:
            # Canonical key: features sorted alphabetically
            if rule["f1"] <= rule["f2"]:
                key = (rule["f1"], rule["dir1"], rule["f2"], rule["dir2"])
            else:
                key = (rule["f2"], rule["dir2"], rule["f1"], rule["dir1"])

            if key in seen_in_fold:
                continue  # Don't double-count same rule within a fold
            seen_in_fold.add(key)

            rule_data[key].append({
                "fold":        fold_data["fold"],
                "mean_fwd_r":  rule["mean_fwd_r"],
                "n":           rule["n"],
                "direction":   rule["direction"],
                "inter_score": rule["inter_score"],
            })

    stable_rules = []
    for key, fold_list in rule_data.items():
        if len(fold_list) < min_folds:
            continue

        n_long  = sum(1 for f in fold_list if f["direction"] == "long")
        n_short = sum(1 for f in fold_list if f["direction"] == "short")
        n_total = len(fold_list)

        if n_long / n_total >= min_direction_pct:
            consensus_dir    = "long"
            pct_consistent   = round(n_long / n_total, 2)
        elif n_short / n_total >= min_direction_pct:
            consensus_dir    = "short"
            pct_consistent   = round(n_short / n_total, 2)
        else:
            continue  # Direction unstable across folds — skip

        mean_r     = float(np.mean([f["mean_fwd_r"]  for f in fold_list]))
        mean_n     = int(  np.mean([f["n"]           for f in fold_list]))
        mean_inter = float(np.mean([f["inter_score"] for f in fold_list]))

        f1, dir1, f2, dir2 = key
        dir1_str = ">70th pct" if dir1 == "high" else "<30th pct"
        dir2_str = ">70th pct" if dir2 == "high" else "<30th pct"
        is_ca = f1 in CA_FAMILY_FEATURES or f2 in CA_FAMILY_FEATURES

        stable_rules.append({
            "f1":               f1,
            "dir1":             dir1,
            "f2":               f2,
            "dir2":             dir2,
            "direction":        consensus_dir,
            "fold_count":       n_total,
            "total_folds":      len(pair_fold_results),
            "pct_consistent":   pct_consistent,
            "mean_fwd_r_pct":   round(mean_r, 4),
            "mean_n_per_fold":  mean_n,
            "mean_inter_score": round(mean_inter, 6),
            "ca_family":        is_ca,
            "suggested_rule":   (
                f"Enter {consensus_dir} BTC when {f1} {dir1_str} "
                f"AND {f2} {dir2_str}"
            ),
            "note": (
                "CA-family feature involved — may overlap existing signal."
                if is_ca else
                "Both features non-CA — potential new discovery."
            ),
        })

    stable_rules.sort(key=lambda r: (
        -r["fold_count"],
        -r["pct_consistent"],
        -abs(r["mean_fwd_r_pct"]),
    ))
    return stable_rules


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


def suggest_pair_hypotheses(
    stable_rules: list[dict],
    next_h_id: int,
    regime: str | None = None,
) -> list[dict]:
    """
    For top non-CA pair rules that appear in 4+ folds with high direction
    consistency, suggest multi-feature hypotheses.

    These are stronger candidates than single-feature rules: the RF identified
    the pair interaction, and quadrant analysis confirmed the directional edge
    out-of-sample across multiple folds.
    """
    suggestions = []
    h_id = next_h_id

    # Require 4+ folds AND 70%+ consistency for multi-feature suggestions
    eligible = [
        r for r in stable_rules
        if r["fold_count"] >= 4 and r["pct_consistent"] >= 0.70
    ]

    for rule in eligible[:8]:  # max 8 multi-feature suggestions
        regime_gate = f", gated by regime={regime}" if regime else ""
        f1, dir1 = rule["f1"], rule["dir1"]
        f2, dir2 = rule["f2"], rule["dir2"]

        dir1_str = ">70th pct" if dir1 == "high" else "<30th pct"
        dir2_str = ">70th pct" if dir2 == "high" else "<30th pct"

        family = _guess_family_pair(f1, f2)

        suggestions.append({
            "suggested_h_id":   f"H{h_id}",
            "feature_1":        f1,
            "feature_1_dir":    dir1,
            "feature_2":        f2,
            "feature_2_dir":    dir2,
            "direction":        rule["direction"],
            "fold_count":       rule["fold_count"],
            "pct_consistent":   rule["pct_consistent"],
            "mean_fwd_r_pct":   rule["mean_fwd_r_pct"],
            "mean_inter_score": rule["mean_inter_score"],
            "suggested_rule":   (
                f"Enter {rule['direction']} BTC when {f1} {dir1_str} "
                f"AND {f2} {dir2_str}{regime_gate}"
            ),
            "suggested_family": family,
            "ca_family":        rule["ca_family"],
            "status":           "CANDIDATE — review before adding to hypotheses.yaml",
            "warning": (
                "Pre-commit to both thresholds BEFORE looking at in-sample performance. "
                "Use 70th/30th pct as defined here. Do not optimize."
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


def _guess_family_pair(f1: str, f2: str) -> str:
    """Guess family for a two-feature rule — prefer the more specific family."""
    f1_fam = _guess_family(f1)
    f2_fam = _guess_family(f2)
    if f1_fam == f2_fam:
        return f1_fam
    if "cross_asset_regime" in (f1_fam, f2_fam):
        return "cross_asset_regime"
    # Mixed families → composite
    return f"composite_{f1_fam}_{f2_fam}"


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="RF Hypothesis Generator")
    parser.add_argument("--dsn",          required=True)
    parser.add_argument("--days",         type=int, default=365)
    parser.add_argument("--horizon",      type=int, default=12,
                        help="Forward return horizon in bars (6=30min, 12=60min, 24=2h)")
    parser.add_argument("--regime",       type=str, default=None,
                        choices=["TRENDING", "RANGING", "VOLATILE"],
                        help="Filter to only bars with this HMM regime label before running RF. "
                             "Discovers signals that work within that specific regime.")
    parser.add_argument("--interactions", action="store_true", default=False,
                        help="Enable SHAP pairwise interaction analysis + quadrant rule extraction. "
                             "Adds ~30-60 sec per run. Produces multi-feature hypothesis candidates.")
    parser.add_argument("--train-days",   type=int, default=90)
    parser.add_argument("--step-days",    type=int, default=30)
    parser.add_argument("--min-folds",    type=int, default=3,
                        help="Min folds in top-10 to report a feature as candidate "
                             "(default 3 for regime runs — fewer bars per fold)")
    parser.add_argument("--min-pair-folds", type=int, default=3,
                        help="Min folds a pair rule must appear in to be reported (default 3)")
    parser.add_argument("--n-estimators", type=int, default=300)
    parser.add_argument("--max-depth",    type=int, default=4)
    parser.add_argument("--next-h-id",   type=int, default=134,
                        help="Next available hypothesis ID for suggestions")
    parser.add_argument("--output-json",  default="results/ml/rf/rf_candidates.json")
    args = parser.parse_args()

    run_date = date.today()
    config = {
        "days":         args.days,
        "horizon":      args.horizon,
        "regime":       args.regime,
        "interactions": args.interactions,
        "train_days":   args.train_days,
        "step_days":    args.step_days,
        "min_folds":    args.min_folds,
        "min_pair_folds": args.min_pair_folds,
    }

    # Load features (regime-filtered if --regime set)
    x = load_features(days=args.days, horizon=args.horizon, dsn=args.dsn,
                      regime=args.regime)

    # Walk-forward RF
    regime_tag = f", regime={args.regime}" if args.regime else " (full dataset)"
    inter_tag  = " + interaction analysis" if args.interactions else ""
    print(f"\n[RF] Running walk-forward XGBoost "
          f"(train={args.train_days}d, step={args.step_days}d, "
          f"horizon={args.horizon} bars = {args.horizon * 5}min"
          f"{regime_tag}{inter_tag})...")

    fold_results, pair_fold_results = run_walkforward_rf(
        x,
        train_days=args.train_days,
        step_days=args.step_days,
        n_estimators=args.n_estimators,
        max_depth=args.max_depth,
        compute_interactions=args.interactions,
    )
    print(f"\n[RF] Completed {len(fold_results)} folds.")

    # Aggregate single-feature candidates
    candidates = aggregate_folds(fold_results, min_folds=args.min_folds)
    print(f"\n[RF] Top candidates (present in {args.min_folds}+ folds):")
    for c in candidates:
        tag = " [CA-FAMILY]" if c["ca_family"] else " [NEW]"
        print(f"  {c['feature']:35s}  folds={c['consistent_folds']}/{len(fold_results)}"
              f"  shap={c['mean_abs_shap']:.5f}  dir={c['direction']}{tag}")

    # Aggregate pair rules (only if interaction analysis was run)
    stable_pair_rules = []
    pair_suggestions  = []
    if pair_fold_results:
        stable_pair_rules = aggregate_pair_rules(
            pair_fold_results, min_folds=args.min_pair_folds
        )
        print(f"\n[RF] Stable pair rules ({args.min_pair_folds}+ folds, 67%+ direction consistency):")
        if stable_pair_rules:
            for r in stable_pair_rules[:10]:
                ca_tag = " [CA]" if r["ca_family"] else " [NEW]"
                print(f"  {r['f1']:25s} {r['dir1']:4s} × {r['f2']:25s} {r['dir2']:4s}"
                      f"  → {r['direction']:5s}  "
                      f"folds={r['fold_count']}/{r['total_folds']}  "
                      f"consistency={r['pct_consistent']:.0%}  "
                      f"mean_r={r['mean_fwd_r_pct']:+.3f}%{ca_tag}")
        else:
            print("  (none — try lowering --min-pair-folds)")

        pair_suggestions = suggest_pair_hypotheses(
            stable_pair_rules,
            next_h_id=args.next_h_id,
            regime=args.regime,
        )

    # Regime-conditional breakdown for non-CA single-feature candidates
    print(f"\n[RF] Running regime-conditional breakdown...")
    regime_data = regime_breakdown(x, candidates, dsn=args.dsn,
                                   horizon=args.horizon, run_date=run_date)

    # Single-feature hypothesis suggestions
    # Start H-IDs after any pair suggestions
    single_next_id = args.next_h_id + len(pair_suggestions)
    single_suggestions = suggest_hypotheses(candidates, regime_data,
                                            next_h_id=single_next_id)

    # Build and write output
    output = {
        "run_date":      str(run_date),
        "config":        config,
        "n_folds":       len(fold_results),
        "n_candidates":  len(candidates),
        # Single-feature analysis (existing)
        "top_candidates":          candidates,
        "regime_breakdown":        regime_data,
        "hypothesis_suggestions":  single_suggestions,
        # Multi-feature pair analysis (new)
        "pair_rules_stable":       stable_pair_rules,
        "pair_hypothesis_suggestions": pair_suggestions,
        "pair_fold_detail":        pair_fold_results if pair_fold_results else [],
        # Raw fold data
        "folds": fold_results,
        "notes": [
            f"Horizon={args.horizon} bars ({args.horizon * 5} min). "
            "Re-run with --horizon 6 and --horizon 24 for MR and trend candidates.",
            "CA-family candidates likely rediscover existing signals. Focus on [NEW] candidates.",
            "Pre-commit to threshold before running any suggestion through the pipeline.",
            "Run suggestions through standard WF+bootstrap gates — do not trust RF in-sample performance.",
            (
                "MULTI-FEATURE RULES: pair_rules_stable contains 2-feature conjunctions where RF "
                "found SHAP interaction between the pair AND quadrant analysis on test forward returns "
                "shows consistent directional edge across folds. These are stronger candidates than "
                "single-feature rules (H125-H133 lesson). Still validate with full WF+bootstrap."
                if pair_fold_results else
                "Run with --interactions to also extract multi-feature pair rules."
            ),
        ],
    }

    os.makedirs(os.path.dirname(args.output_json), exist_ok=True)
    with open(args.output_json, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n[RF] Output written to {args.output_json}")

    # Print summary of suggestions
    if pair_suggestions:
        print(f"\n[RF] Multi-feature pair hypothesis suggestions:")
        for s in pair_suggestions:
            ca_tag = " [CA-overlap]" if s["ca_family"] else ""
            print(f"  {s['suggested_h_id']}: {s['suggested_rule']}")
            print(f"         family={s['suggested_family']}  "
                  f"folds={s['fold_count']}  "
                  f"consistency={s['pct_consistent']:.0%}  "
                  f"mean_r={s['mean_fwd_r_pct']:+.3f}%{ca_tag}")

    if single_suggestions:
        print(f"\n[RF] Single-feature hypothesis suggestions:")
        for s in single_suggestions:
            print(f"  {s['suggested_h_id']}: {s['suggested_rule']}")
            print(f"         family={s['suggested_family']}  folds={s['consistent_folds']}")

    print("\n[RF] Done.")
    print("Next steps:")
    print("  1. Review pair_rules_stable in output JSON — these are the multi-feature candidates")
    print("  2. Pair rules with 4+ folds and 80%+ consistency are highest priority")
    print("  3. Pre-commit to both thresholds (70th/30th pct) before pipeline run")
    print("  4. Add selected rules to hypotheses.yaml with next H-number")
    print("  5. Run through standard WF+bootstrap pipeline for final validation")
    print(f"  6. Run with --regime TRENDING / RANGING / VOLATILE for regime-specific rules")


if __name__ == "__main__":
    main()
