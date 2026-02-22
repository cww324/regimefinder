# Research Roadmap
**Created:** 2026-02-22
**Status:** Active guidance document — update as hypotheses are tested and findings evolve.

---

## 1. Current State Assessment

### What Works
- H32 / H33 (ETH 1h slope direction in short-tail ETH-BTC relative momentum regime): PASS gross/8bps, marginal at 10bps. Frozen and in paper trading.
- H32+H33 portfolio: PASS gross/8/10bps. Current best deployable candidate.
- Research protocol (no-tuning, WF+bootstrap, freeze discipline) is sound and should be preserved.

### Root Problems
1. **Data window is 180 days — far too short.** This is the single biggest issue. All edge detection, all regime modeling, and all validation is on one market slice. Target: minimum 2 years, ideally 3+.
2. **Feature space monoculture.** H15–H113 are nearly all variations of: VWAP-z, ETH 1h EMA slope sign, ETH-BTC spread percentile, RV/ATR percentile. Genuine diversification of signal *families* has not yet happened.
3. **No risk-adjusted gating.** Mean return is the primary gate. Two hypotheses with identical mean but 5x different volatility are treated the same.
4. **Multiple testing problem.** 100+ hypotheses tested with no false discovery correction. At 5% significance, ~5 false positives are expected by chance alone.

---

## 2. Data Extension Priorities (Do First)

### 2a. Extend OHLCV History — Target 12 Months, Not 2 Years

**Important nuance:** Crypto markets change structurally on a 6–18 month cycle. Going back 2+ years risks pooling incompatible regimes:
- 2022 (FTX/Terra collapse) has entirely different microstructure than 2025
- Pre- vs post-BTC ETF approval (Jan 2024) represent different participant bases and flow dynamics
- Signals that "worked" in crisis regimes often fail in normal regimes and vice versa

**Target: 12 months of recent history** (not 2 years)
- Long enough: supports 4–5 walk-forward folds at 30-day test windows (vs. current 7 folds at 15-day — much better statistical power)
- Short enough: stays within 1–2 identifiable recent market regimes
- Captures at least one full volatility cycle

**Action:** Run `scripts/backfill_5m.py` with `--days 365`. Re-run all frozen hypotheses (H32, H33, H32+H33 portfolio) with 12 months of data and 90/30/30 WF splits.

**Regime-aware validation:**
After extending to 12 months, segment the window into 2–3 regimes using change point detection (PELT on rolling RV). Validate that frozen hypotheses work within each sub-regime, not just across the pooled average. A hypothesis that only works in one regime is fragile.

**Gate:** If H32/H33 hold positive means in at least 2 of 3 identified sub-regimes, confidence increases significantly. If they only work in one sub-regime, they are regime-dependent and should be treated as BORDERLINE.

### 2b. Add New Data Sources
Priority order for new data feeds:

| Source | Signal Families Unlocked | Priority |
|--------|--------------------------|----------|
| Perp funding rates (BTC + ETH) | Carry/funding signals, sentiment proxy | HIGH |
| Open Interest (OI) | Position crowding, squeeze risk, momentum confirmation | HIGH |
| Binance 5m candles (BTC + ETH) | Cross-exchange arbitrage, execution quality comparison | MEDIUM |
| On-chain: exchange netflow | Whale accumulation/distribution regimes | MEDIUM |
| On-chain: SOPR, MVRV | Macro regime (holder profit/loss state) | LOWER |
| Options: IV term structure | Realized vs implied vol premium, tail risk regimes | LOWER |

---

## 3. New Signal Families to Explore (H114+)

### 3a. Funding Rate Signals (Highest Priority)
Perpetual futures funding rates are one of the strongest regime signals in crypto. When funding is extremely positive, longs are paying shorts — market is crowded long. Historically, extreme positive funding precedes mean-reversion downward.

**Hypotheses to formalize:**
- `H114`: Trade BTC in direction opposite to extreme funding (|funding| > 90th percentile), gated by RV < 75th pct
- `H115`: Funding sign flip (positive→negative) as momentum trigger in direction of flip
- `H116`: Funding + OI divergence (funding rising, OI falling = forced unwind signal)
- `H117`: Basis (futures premium/discount) as regime gate for existing H32 entry

### 3b. Open Interest Signals
- `H118`: OI increasing + price increasing = momentum confirmation (long BTC)
- `H119`: OI increasing + price decreasing = short squeeze setup (fade direction)
- `H120`: OI spike (>90th pct) followed by price reversal within 3 bars

### 3c. Cross-Exchange Divergence
- `H121`: Coinbase premium vs Binance as directional signal (when Coinbase leads)
- `H122`: Volume-weighted price divergence across venues as mean-reversion trigger

### 3d. Improved Regime Detection (Replace Simple Percentile-Rank)
The current H19 "regime" (rolling percentile of ETH-BTC spread) is a relative momentum condition, not a true regime model. Upgrade path:

**Short-term (next 30 days):**
- Test HMM with 2–3 states on RV + return sign features. States should correspond to: trending/volatile, ranging/quiet, shock/recovery.
- Use the HMM state as a gate for existing signal families (does H32 work better in certain HMM states?)

**Medium-term:**
- Build a proper regime classifier using: RV percentile, ER20, funding rate level, OI trend, BTC dominance. Train on rolling window, classify current bar, use classification as a filter.

### 3e. Microstructure / Intraday Session Effects
The 08:00–16:00 UTC window (London/New York overlap) has been identified as the strongest. Formalize:
- `H123`: Full-session specialist — only trade during 08:00–16:00 UTC, use H32 entry logic
- `H124`: Session transition — enter at session open (08:00 UTC) if ETH slope is positive and spread is in short-tail
- `H125`: Weekend vs weekday regime gate (crypto has different dynamics on weekends)

---

## 4. ML-Assisted Hypothesis Generation

### 4a. Using Random Forest for Idea Discovery

Random Forest is a strong tool for *discovering* which feature combinations carry predictive signal. Use it as a hypothesis generator, not as a deployed model.

**Correct workflow:**
```
Step 1: Build feature matrix from existing computed features
        (VWAP-z, spread_pct, ETH slope, RV, ER20, ATR, bar direction, etc.)
        - All features must be point-in-time at bar t (no lookahead)

Step 2: Target variable = sign(fwd_r at h=6 bars)
        - Binary: 1 if positive, 0 if negative (or -1/0/1 with neutral band)

Step 3: Walk-forward RF training
        - Train on rolling 90-day window
        - Extract SHAP values on next 30-day test window
        - Repeat across full history

Step 4: Identify top feature interactions from SHAP
        - Look for: "Feature A > threshold AND Feature B in range X → consistent direction"
        - These become new hypothesis candidates

Step 5: Formalize as explicit rule-based hypotheses in hypotheses.yaml
        - Do NOT deploy the RF model directly
        - Translate the discovered interaction into a fixed rule, then run through
          the existing gate pipeline (gross/bps8/bps10, WF, bootstrap)
```

**What RF is good for:**
- Feature importance ranking (tells you which of your 40+ features actually matter)
- Interaction discovery (finds the "AND" conditions you're manually building in H86-H113)
- Non-linear threshold discovery (RF finds where splits add information, SHAP explains why)

**What RF is NOT for:**
- Direct signal generation for live trading
- Bypassing the WF+bootstrap gate protocol
- Testing on the same data you trained on

**Other ML tools to use alongside RF:**
- **SHAP** (SHapley Additive exPlanations): Makes RF/XGBoost interpretable. Gives you "this feature pushed the prediction +0.03 in this bar" — directly translatable to hypothesis rules.
- **XGBoost/LightGBM**: Better than vanilla RF for tabular data. Use for feature importance, same workflow as RF.
- **Isolation Forest**: Anomaly detection — identifies "unusual" bars that may correspond to regime transitions worth investigating.
- **Hidden Markov Model (HMM)**: For proper regime detection. Use `hmmlearn` library. 2–3 hidden states on (RV, |return|) is a good starting point.
- **K-Means / UMAP**: Cluster feature vectors to discover natural market states without specifying regimes manually.

### 4b. Recommended First ML Experiment
Before building a full RF pipeline, run this simple experiment:

1. Compute feature matrix at each 5m bar: `[spread_pct, eth_slope_sign_1h, vwap_z, rv48_pct, er20, atr14_pct, hour_of_day, day_of_week]`
2. Target: `sign(close.shift(-6) / close - 1)` — direction of 6-bar forward return
3. Fit RF with `n_estimators=200, max_depth=5, min_samples_leaf=100` on first 120 days
4. Predict on next 60 days. Record feature importances and top SHAP interactions.
5. Look for high-importance feature pairs → candidate for next hypothesis

This will take ~30 minutes to build and will give you a feature importance ranking plus interaction candidates that can feed directly into H114+ definition.

---

## 5. Decision Tree: What to Do Next

```
Priority 1 (Do immediately):
  → Extend data to 2+ years
  → Re-run H32, H33, H32+H33 portfolio on extended data
  → If they hold: confidence +, proceed to paper track
  → If they fail: go back to signal research

Priority 2 (Parallel with Priority 1):
  → Add funding rate data source
  → Build H114 (funding extremes) and H115 (funding flip)
  → Run through existing gate pipeline

Priority 3 (After data extension):
  → Run ML experiment (RF feature importance)
  → Formalize top 3-5 interactions as new hypotheses (H116+)
  → Add HMM regime detection as alternative to H19 regime

Priority 4 (Validation infrastructure):
  → Add multiple testing correction (BH-FDR) to classify_mode()
  → Add permutation test to research_family_runner.py
  → Add Sharpe ratio gate alongside mean return gate
  → Fix trade independence gap (use 2x horizon minimum)
  → Add hold-out OOS block (final 30 days, never used in any training)
```

---

## 6. Things NOT to Do (Guardrails)

- Do not tune H32/H33 parameters to fit extended data — they are frozen. Re-run with fixed rules only.
- Do not use RF/ML model output directly as a live trading signal without passing through WF+bootstrap gates.
- Do not test more H variants on 180-day data — additional testing on the same short window adds noise, not signal.
- Do not add new features to `load_frame()` without profiling the runtime impact first (see PERFORMANCE_OPTIMIZATION.md).
- Do not stack signals post-hoc — each new combination must be declared as a new hypothesis ID before testing.

---

## 7. Links to Related Documents
- `VALIDATION_IMPROVEMENTS.md` — how to strengthen the testing protocol
- `PERFORMANCE_OPTIMIZATION.md` — how to speed up the research pipeline
- `AI_AGENT.md` — current operating brief and locked hypothesis state
- `FINDINGS_SIMPLIFIED.md` — canonical decision log for all hypothesis outcomes
