# RF Experiment Plan
**Created:** 2026-02-23
**Purpose:** Implementation groundwork for Random Forest + SHAP hypothesis discovery.
Read this before building `scripts/rf_hypothesis_generator.py`.

---

## Goal

Use RF/XGBoost walk-forward to discover which features and feature combinations predict
8-bar forward returns in our 365d dataset — then formalize discoveries as explicit rule-based
hypotheses (new H-numbers) and run through the standard validation pipeline.

**RF is never deployed directly. RF output → hypothesis rule → H-number → pipeline.**

---

## The Core Problem RF Solves

H86–H113 were designed by hand — we guessed combinations, tested them, mostly failed.
That's slow and biased toward ideas we already had. RF on the full feature matrix will:
1. Rank which of our ~80 features actually carry predictive power
2. Surface feature interactions (AND conditions) we haven't thought to test
3. Point toward regime families we haven't explored yet

---

## Critical Design Decision: What to Include in the Feature Matrix

**The risk:** If we include `eth_slope_sign_1h` and `btc_slope_sign_1h` (our CA signal features),
RF will almost certainly rediscover CA-1 as the top predictor — it already passes with 20/20 WF
folds, so it dominates the target. We'd spend compute confirming what we already know.

**Three options — pick one before building the script:**

### Option A: Exclude slope features (recommended for new-regime discovery)
Drop `eth_slope_sign_1h`, `btc_slope_sign_1h`, `eth_slope_stable_*`, `eth_above_ema20_1h`
from the feature matrix entirely. Force RF to find predictive power elsewhere.
- **Pro:** Guaranteed to find non-CA signals
- **Con:** May miss CA-enhancement signals (e.g. "CA-1 only when RV is low")

### Option B: Include everything, filter output by correlation with CA-1
Run RF with all features. After extracting candidates, compute pairwise correlation of each
candidate signal's trade sequence with CA-1. Only formalize candidates where correlation < 0.3.
- **Pro:** Finds both new signals AND CA enhancements in one run
- **Con:** More post-processing work

### Option C: Residual prediction (most rigorous)
Regress CA-1 signal out of forward returns, run RF on the residual. Whatever RF finds is
definitionally orthogonal to CA-1.
- **Pro:** Guaranteed independence from existing edge
- **Con:** More complex implementation

**Recommendation:** Run Option A first (1-2 hours), see what comes up. If nothing interesting
emerges, try Option B. Option C is the right next step if we want to explicitly build a
portfolio layer on top of CA-1.

---

## Feature Matrix

All features already exist in `load_frame()` in `scripts/research_family_runner.py`.
The RF script reuses the same frame. See full column list below.

### Include by default (Option A):

**Volatility / regime:**
- `rv48_pct_btc`, `rv48_pct_eth` — realized vol percentile
- `atr14_pct_btc`, `atr14_pct_eth` — ATR percentile
- `atr_rv_ratio_pct_btc` — ATR/RV ratio (trending vs choppy indicator)
- `er20_btc`, `er20_eth` — efficiency ratio
- `delta_er`, `abs_delta_er_pct` — BTC/ETH divergence in efficiency

**VWAP / mean-reversion:**
- `vwap_z` — BTC distance to 24h VWAP, z-scored
- `dist_to_vwap48_z_btc`, `dist_to_vwap48_z_eth`
- `abs_vwap_dist_pct_btc`

**Bar structure:**
- `ret1_abs_btc_pct`, `ret1_abs_eth_pct` — bar size percentile
- `bar_dir_btc`, `bar_dir_eth` — direction of current bar
- `ret1_btc`, `ret1_eth` — 1-bar returns

**Cross-asset:**
- `spread_pct` — ETH-BTC 6h return spread percentile

**Funding (conditional on --dsn):**
- `funding_btc_pct` — funding rate percentile
- `funding_btc_sign` — funding direction
- `funding_btc_flip` — funding sign changed

**Session (need to add to load_frame — simple):**
- `hour_of_day` = `dt.hour`
- `day_of_week` = `dt.dayofweek`
- `is_weekend` = `(day_of_week >= 5).astype(int)`

### Exclude (Option A — CA signal features):
- `eth_slope_sign_1h`, `btc_slope_sign_1h`
- `eth_slope_stable_2_1h`, `eth_slope_abs_1h`
- `eth_slope_abs_pct_1h`, `eth_slope_z_1h`
- `eth_above_ema20_1h`

---

## Target Variable

```python
# 8-bar forward return (match our best CA signals)
x["fwd_r_h8"] = x["close_btc"].shift(-8) / x["close_btc"] - 1.0

# Binary classification target
x["target"] = np.sign(x["fwd_r_h8"])  # 1 = up, -1 = down, 0 = flat
x = x[x["target"] != 0]  # drop flat bars
```

---

## Walk-Forward Setup

```
Total: 365 days
Train:  90 days
Test:   30 days
Step:   30 days
→ ~9 test folds

For each fold:
  1. Fit model on train window (no lookahead)
  2. Extract feature importances (built-in)
  3. Compute SHAP values on test window
  4. Record top features, direction, magnitude per fold
  5. Check: is this feature positive/negative in this fold?
```

Only report features that appear in top-10 importance in **5+ of 9 folds** — single-fold
patterns are noise.

---

## Sub-Period Anti-Bias Check

The 365d window was a crypto bull run. RF will find signals that worked in trending/bullish
conditions. After identifying a candidate:

```
Split 365d into 4 quarters (Q1/Q2/Q3/Q4 2025)
For each quarter, measure candidate signal mean return
If positive in 3+ quarters → reasonably robust
If positive in only 1-2 quarters → regime-specific, label accordingly
```

---

## Model Parameters

```python
# Preferred: XGBoost (better than sklearn RF on tabular data)
from xgboost import XGBClassifier

model = XGBClassifier(
    n_estimators=300,
    max_depth=4,
    min_child_weight=100,  # prevents tiny leaf nodes, reduces overfit
    learning_rate=0.05,
    subsample=0.8,
    colsample_bytree=0.8,
    use_label_encoder=False,
    eval_metric="logloss",
    random_state=42
)
```

```python
# SHAP
import shap
explainer = shap.TreeExplainer(model)
shap_values = explainer.shap_values(X_test)
# shap_values shape: (n_bars, n_features)
# positive = feature pushes prediction toward "up"
```

---

## Libraries Needed

Check `requirements.txt` — add if missing:
```
xgboost>=2.0
shap>=0.43
scikit-learn>=1.3   # for train/test split utilities
```

---

## Script Outline: `scripts/rf_hypothesis_generator.py`

```python
"""
RF Walk-Forward Hypothesis Generator
Usage:
  PYTHONPATH=. .venv/bin/python scripts/rf_hypothesis_generator.py \
    --dsn "$RC_DB_DSN" \
    --days 365 \
    --horizon 8 \
    --train-days 90 \
    --test-days 30 \
    --output-json results/rf/rf_candidates_$(date +%Y%m%d).json \
    --exclude-ca   # Option A: exclude slope features
"""

# Steps:
# 1. load_frame() → full feature DataFrame
# 2. Add session features (hour_of_day, day_of_week, is_weekend)
# 3. Add fwd_r_h8 target, drop NaN tail
# 4. Optionally drop CA features (--exclude-ca flag)
# 5. Walk-forward loop:
#    for train_end in date_range(start + 90d, end, step=30d):
#        train = frame[train_end-90d : train_end]
#        test  = frame[train_end     : train_end+30d]
#        model.fit(X_train, y_train)
#        shap_values = explainer(X_test)
#        record fold results
# 6. Aggregate: features in top-10 in 5+ folds → candidates
# 7. For each candidate: measure quarterly breakdown
# 8. Output JSON with candidates + suggested hypothesis rules
```

---

## Reading the Output → Hypothesis Candidates

After running, look for:

**Single-feature patterns:**
> `rv48_pct_btc` in top-5 in 7/9 folds, positive SHAP when `rv48_pct_btc > 0.80`
→ "Enter long when BTC vol is in top 20%" → new VS family hypothesis

**Two-feature interactions:**
> `funding_btc_pct < 0.20` AND `vwap_z < -0.5` → consistent positive SHAP
→ "Buy VWAP dip when funding is not crowded" → new MR|FR hypothesis

**Session interactions:**
> `hour_of_day in [8,9,10,11]` with strong positive SHAP on multiple features
→ EU open window has unique predictive structure → refine ST hypotheses

**Formalization rule:** Describe the candidate in plain English → assign next H-number →
add to `hypotheses.yaml` with `signal_group` tag → run through pipeline.

---

## Output Format

```json
{
  "run_date": "2026-02-24",
  "config": {"days": 365, "horizon": 8, "train_days": 90, "exclude_ca": true},
  "n_folds": 9,
  "top_features": [
    {"feature": "rv48_pct_btc", "consistent_folds": 7, "mean_abs_shap": 0.021, "direction": "high RV → positive"},
    {"feature": "funding_btc_pct", "consistent_folds": 6, "mean_abs_shap": 0.018, "direction": "low funding → positive"}
  ],
  "hypothesis_candidates": [
    {
      "description": "Buy BTC when realized vol breaks above 80th percentile (volatility breakout)",
      "rule": "rv48_pct_btc > 0.80 AND bar_dir_btc > 0",
      "suggested_family": "VS",
      "consistent_folds": 7,
      "quarterly_positive": [true, true, false, true]
    }
  ]
}
```

---

## Checklist Before Running

- [ ] `xgboost` and `shap` in requirements.txt and installed in .venv
- [ ] Postgres running: `docker start rc-postgres`
- [ ] Features current: `compute_features.py --days 365` run recently
- [ ] Funding rates current: `make backfill-derivatives`
- [ ] `results/rf/` directory created
- [ ] Decision made on Option A vs B vs C (exclude slope or not)
- [ ] Session features added to load_frame() or handled in script

---

## What Happens After RF

1. Read output JSON — pick top 3-5 candidates that appear in 5+ folds
2. Check quarterly breakdown — prefer candidates positive in 3+ quarters
3. Write each as an explicit rule in plain English
4. Add to `hypotheses.yaml` as new H-numbers (H125, H126...)
5. Tag with `signal_group` based on predicted family (VS, FR, MR...)
6. Run through standard batch pipeline
7. If PASS → assign shortcode in `SIGNAL_REGISTRY.md`
