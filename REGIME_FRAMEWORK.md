# REGIME_FRAMEWORK.md
**Created:** 2026-02-23
**Status:** Active governance document — all H124+ hypotheses must conform to this framework.

---

## Overview

Every hypothesis must now be designed as a **regime-aware system**, not a single flat signal. The prior era (H15–H123) conflated regime detection and entry signal into a single condition — this caused high fire rates, cost erosion, and poor fold consistency. The new architecture separates concerns cleanly.

---

## 1. Three-Layer Architecture

Every H124+ hypothesis must specify which layer(s) it occupies:

```
Layer 1: REGIME CLASSIFIER
  - Identifies the current market state
  - Fires infrequently (hours to days per regime)
  - Example: ETH 1h slope direction, funding percentile, HMM state, RV regime
  - Should have high confidence and low noise

         ↓ (only pass signal if regime matches)

Layer 2: STRATEGY ROUTER
  - Selects which strategy to deploy in the detected regime
  - Can include: direction bias (long-only, short-only, neutral), holding horizon, max position size
  - Example: "In long-regime, only take long entries. In neutral, skip."

         ↓ (strategy activated, now wait for entry condition)

Layer 3: ENTRY FILTER
  - Precise timing trigger within the active regime
  - Example: VWAP-z pullback to -0.5, spread percentile exceeds 0.90, bar direction confirmation
  - Should fire 1-3 times per day, not 7+ times

         → TRADE
```

**Why this matters for H123:** H123 failed because it used `funding_btc_pct < 0.85` as a Layer 1 regime gate but used the spread percentile condition (≥0.90) as the only Layer 3 filter — which fires ~7×/day. H124 fixes this by tightening the Layer 3 filter to ≥0.97, targeting 1-2 trades/day.

---

## 2. Regime Taxonomy

These are the recognized market regimes for this system. Each hypothesis should be tagged with the regime(s) it applies to.

| Regime ID | Name | Approximate Conditions | Typical Duration |
|-----------|------|------------------------|------------------|
| `TREND_UP` | Trending up | ETH 1h slope > 0, RV moderate, spread high pct | Hours to days |
| `TREND_DOWN` | Trending down | ETH 1h slope < 0, RV moderate, spread low pct | Hours to days |
| `MEAN_REVERT` | Mean-reverting / chop | ER20 < 0.3, RV low, VWAP-z oscillating | Hours to days |
| `VOLATILE` | High-volatility shock | RV > 90th pct, ATR spike, large bars | Minutes to hours |
| `CALM` | Low-volatility quiet | RV < 20th pct, narrow ranges, low volume | Hours to days |
| `CROWD_LONG` | Crowded long | funding_btc_pct ≥ 0.90, OI rising | Hours to 1-2 days |
| `CROWD_SHORT` | Crowded short | funding_btc_pct ≤ 0.10, OI rising | Hours to 1-2 days |
| `SESSION_EU` | EU session active | 08:00–12:00 UTC | 4h window |
| `SESSION_US` | US session active | 13:00–21:00 UTC | 8h window |
| `SESSION_ASIA` | Asia session active | 00:00–08:00 UTC (weaker historically) | 8h window |

Tag every hypothesis in `hypotheses.yaml` under `regime_tags: [REGIME_ID, ...]`.

---

## 3. Rules for H124+ Hypothesis Design

### 3.1 Mandatory Three-Layer Specification
Every new hypothesis must explicitly specify:
- **Layer 1 condition**: What regime gate determines we are in a tradeable state?
- **Layer 2 constraint**: What direction/horizon/sizing applies in this regime?
- **Layer 3 filter**: What precise entry condition triggers a trade within the active regime?

If you cannot articulate all three layers, the hypothesis is not yet specified well enough.

### 3.2 Trade Frequency Budget
Based on cost structure (8bps round-trip, ~0.065% average gross edge per trade at H32-class hypotheses):
- **Max frequency: 2 trades/day** on the 8bps cost gate
- **Preferred: 0.5–1.5 trades/day** — enough to accumulate edge, few enough for each trade to breathe
- If a hypothesis fires >3 trades/day at gross stage, it will likely fail the 8bps gate → redesign Layer 3

### 3.3 Cost Gate Pre-Check
Before writing code, estimate trade frequency at Layer 3:
- Count how often the Layer 3 condition would have fired in a 30-day representative window
- Divide total expected gross edge by number of trades
- Check: (gross edge per trade) > 0.12% to pass 8bps round-trip?
- If not: tighten Layer 3 threshold before testing

### 3.4 Regime-Specific Signal Direction
- A hypothesis should only trade **one direction in one regime**
- If a signal works long in TREND_UP and short in CROWD_LONG, those are two separate hypotheses
- No "trade both sides" within a single hypothesis — keeps rules frozen and testable

### 3.5 No Post-Hoc Feature Additions
- Features must be declared before the first test run
- No adding new gates after seeing the gross result
- If Layer 1 needs to change, declare a new hypothesis ID

---

## 4. RF/ML Integration Guidelines

Random Forest and other ML tools are **hypothesis generators**, not deployed models.

### Two-Stage ML Pipeline (Canonical Approach)

```
Stage 1: HMM REGIME DISCOVERY (unsupervised)
  - Aggregate 5m bars to 1h
  - Fit GaussianHMM(n_components=3) on: rv_1h, er20_1h, atr_pct_1h, funding_pct_1h
  - Walk-forward: train 90d, label next 30d, repeat
  - Output: regime label (0/1/2) for every 1h bar → map back to 5m bars
  - Label states by examining mean RV + return direction in each state
  - See: docs/hmm_regime_plan.md

         ↓ (regime labels become features for Stage 2)

Stage 2: RF SIGNAL DISCOVERY (supervised)
  - Full feature matrix — no pre-exclusions (do NOT exclude CA slope features)
  - Include HMM regime label as a feature
  - Target: sign(fwd_r at h=horizon) — horizon NOT fixed, see rule below
  - Walk-forward RF: train 90d, extract SHAP on 30d test, repeat
  - After run: compare top candidates to existing signals (CA-1 through CA-5)
    → if candidate maps to existing signal family, skip it
    → if genuinely new territory, formalize as hypothesis
  - See: docs/rf_experiment_plan.md
```

### Horizon Pre-Commit Rule (Critical — prevents 8-bar mining)

**Do NOT fix horizon=8 for all hypotheses.** The 8-bar assumption came from CA-1 and has been applied to every subsequent hypothesis — this is a form of data mining on the horizon parameter.

**Pre-commit rule:** Before running any hypothesis, declare the horizon based on the hypothesis type:
- Mean-reversion signal → horizon = 4–6 bars (20–30 min)
- Trend-following / momentum signal → horizon = 16–24 bars (80–120 min)
- Cross-asset divergence signal → horizon = 8–12 bars (40–60 min)

Choose the horizon that matches the economic logic of the signal. Write it in the hypothesis spec before looking at any results. Do not test multiple horizons and pick the best one — that is in-sample tuning.

### Never Deploy RF Output Directly
- RF importance/SHAP output → propose hypothesis rule → validate with WF+bootstrap
- The RF's WF test performance does NOT substitute for the hypothesis gate protocol
- SHAP tells you *what* to test, not *whether* it will survive OOS

### HMM Regime Detection
When using Hidden Markov Model for Layer 1 regime:
- Aggregate 5m → 1h bars before fitting (do NOT run HMM on raw 5m bars)
- 1h granularity finds multi-day macro regimes; 5m finds only intraday session effects
- Fit `hmmlearn.GaussianHMM(n_components=3)` on: rv_1h, er20_1h, atr_pct_1h, funding_pct_1h
- Train window: 90 days, predict current state
- Label states *after* fitting by examining mean RV in each state (low/med/high)
- Use decoded state label as Layer 1 regime gate
- Must be retrained walk-forward — never fit on OOS period
- 365d data limitation: all regimes discovered are bull-market variants (Feb 2025 – Feb 2026 was net positive). Any strategy built on these labels is bull-market biased until tested on older data.

### Isolation Forest for Anomaly Gating
- Anomaly score > 0.7 → unusual bar → skip entry (Layer 3 veto)
- Fit on rolling 60-day window of (VWAP-z, spread_pct, RV, ATR)
- Reduces exposure to flash crashes and liquidity gaps

---

## 5. Hypothesis Metadata Fields (H124+)

Add these fields to every H124+ entry in `hypotheses.yaml`:

```yaml
H124:
  family: funding_regime
  data_era: 365d                        # which data window this was designed/tested on
  regime_tags: [CROWD_LONG, TREND_UP]   # which regimes this hypothesis targets
  signal_layer:
    L1: "funding_btc_pct >= 0.97 (extreme crowd long)"
    L2: "long-only; horizon=6"
    L3: "spread_pct >= 0.97 AND bar direction up"
  cost_profile:
    target_trades_per_day: 1.0          # design target
    gross_edge_per_trade_pct: ~0.08     # estimated minimum needed
  validation_era: 365d
  status: pending
```

---

## 6. H124 Specification (Next Hypothesis)

**Problem solved:** H123 had genuine signal (gross P>0=1.000, WF 12/14 folds positive) but fired ~7 trades/day, exhausting the 8bps edge budget.

**Fix:** Tighten Layer 3 filter from ≥0.90 to ≥0.97 (top 3% of spread distribution).

| Layer | H123 (failed) | H124 (proposed) |
|-------|---------------|-----------------|
| L1 | `funding_btc_pct < 0.85` | `funding_btc_pct < 0.85` (same) |
| L2 | long-only, horizon=6 | long-only, horizon=6 (same) |
| L3 | `spread_pct >= 0.90` | `spread_pct >= 0.97` (tighter) |
| Expected frequency | ~7 trades/day | ~1–2 trades/day |
| Required gross edge | 0.112% (8bps×1.4) | 0.112% |
| Estimated gross edge | 0.065% | 0.13–0.20% (top 3% events are stronger) |

**Family:** `funding_regime`
**Signal logic:**
```python
# L1: funding regime gate
funding_ok = funding_btc_pct < 0.85  # not crowded long

# L3: precise entry
entry = (spread_pct >= 0.97) & (bar_direction > 0)

# Combined
signal = dedup_idx(funding_ok & entry, gap=horizon)
```

---

## 7. Regime Framework Era Checklist

Before classifying any H124+ hypothesis as PASS:

- [ ] Three-layer architecture documented
- [ ] Trade frequency target stated and within budget (≤2/day)
- [ ] Estimated gross edge per trade > 0.12% (8bps headroom)
- [ ] Regime tags assigned
- [ ] Walk-forward folds ≥ 8 (365d dataset)
- [ ] Bootstrap CI excludes zero at 80th percentile
- [ ] No Layer 3 adjustments made after seeing gross result
- [ ] `data_era: 365d` set in hypothesis metadata
- [ ] Result appended to `FINDINGS_365D.md` (not just FINDINGS_SIMPLIFIED.md)

---

## 8. Links

- `RESEARCH_ROADMAP.md` — signal family priorities, ML experiment design
- `VALIDATION_IMPROVEMENTS.md` — pending protocol upgrades (FDR, permutation, Sharpe gate)
- `PERFORMANCE_OPTIMIZATION.md` — pipeline speed optimizations
- `AI_AGENT.md` — operating brief and locked hypothesis state
- `FINDINGS_SIMPLIFIED.md` — complete hypothesis history (all eras)
- `FINDINGS_365D.md` — 365d era results (clean slate, organized by regime/family)
