# HMM Regime Discovery Plan
**Created:** 2026-02-23
**Purpose:** Design spec for `scripts/hmm_regime_discovery.py`.
Read this before building the script.

---

## Goal

Use a Hidden Markov Model to discover persistent market regimes from 1h bar data.
Output: a regime label (0, 1, 2) for every bar in the dataset, stored in Postgres
and usable as a Layer 1 feature in all subsequent RF and hypothesis work.

**HMM is never deployed as a trading signal directly.**
HMM output → regime labels → features for RF → explicit hypothesis rules → pipeline.

---

## Why 1h Bars, Not 5m

- 5m HMM finds intraday session effects (active vs quiet hours) — not useful as regime
- 1h HMM finds multi-day trending/ranging/volatile states — the actual regime structure
- 365 days × 24 bars/day = ~8,760 1h bars — sufficient for stable HMM estimation
- 1h regime labels get mapped back to 5m bars for use in trading signals

---

## Why HMM, Not K-Means

K-means treats each bar independently — it doesn't know that regimes persist.
A trending regime doesn't flip to ranging in a single bar.

HMM explicitly models state transitions:
- "Given we're in state 1, there's an 85% chance we stay in state 1 next hour"
- This produces smooth, persistent regime labels that match how markets actually behave
- K-means is useful for a first visual pass but HMM is the right tool here

---

## Features (Input to HMM)

All must be computed at 1h granularity (aggregate from 5m or compute directly):

| Feature | Description | Why |
|---------|-------------|-----|
| `rv_1h` | Rolling std of 1h log-returns (12-period) | Captures volatility level |
| `er20_1h` | Efficiency ratio over 20 1h bars | Trending vs choppy |
| `atr_pct_1h` | ATR percentile at 1h | Range size relative to history |
| `funding_pct_1h` | Funding rate percentile (BTC, hourly) | Crowding / sentiment state |

Start with these 4. Do not add more until initial results are reviewed — more features
increase the risk of HMM finding spurious states.

---

## Model Configuration

```python
from hmmlearn import hmm

model = hmm.GaussianHMM(
    n_components=3,       # 3 states: expect low-vol/ranging, trending, high-vol/shock
    covariance_type="full",
    n_iter=100,
    random_state=42,
)
```

**Why 3 states?**
Start with 3. Inspect the results — if 2 states look identical or 1 state has < 5% of bars,
reduce to 2. Do not automatically use more states to get a better fit score — that is overfitting.

---

## Walk-Forward Setup

HMM must be trained walk-forward. Never fit on the full dataset and label it — that is lookahead.

```
Total: 365 days of 1h bars (~8,760 bars)
Train:  90 days (2,160 bars)
Label:  next 30 days (720 bars)
Step:   30 days
→ ~9 label windows

For each window:
  1. Fit HMM on train window
  2. Decode (predict) states for test window only
  3. Store state labels for test bars
  4. Advance window by 30 days
```

The first 90 days will not have labels (no training data before them).
That is acceptable — treat them as unlabeled and exclude from hypothesis testing.

---

## Labeling the States

After fitting, the state numbers (0, 1, 2) are arbitrary — HMM doesn't know which
is "trending" and which is "volatile." Label them by examining statistics in each state:

```python
# After walk-forward labeling, compute per-state summary:
for state in [0, 1, 2]:
    mask = (labels == state)
    print(f"State {state}:")
    print(f"  % of bars:    {mask.mean():.1%}")
    print(f"  mean rv_1h:   {df.loc[mask, 'rv_1h'].mean():.4f}")
    print(f"  mean er20_1h: {df.loc[mask, 'er20_1h'].mean():.3f}")
    print(f"  mean |ret|:   {df.loc[mask, 'ret_1h'].abs().mean():.4f}")
    print(f"  mean funding: {df.loc[mask, 'funding_pct_1h'].mean():.3f}")
```

Then assign human labels:
- Highest RV + low ER → `VOLATILE` (shock/liquidation regime)
- Moderate RV + high ER → `TRENDING` (directional move regime)
- Lowest RV + low ER → `RANGING` (quiet/mean-reverting regime)

These labels map to the regime taxonomy in `REGIME_FRAMEWORK.md`.

---

## Output

### 1. Postgres table: `rc.regime_labels`

```sql
CREATE TABLE IF NOT EXISTS rc.regime_labels (
    symbol      TEXT NOT NULL,
    ts          TIMESTAMPTZ NOT NULL,
    timeframe   TEXT NOT NULL DEFAULT '1h',
    state_id    SMALLINT NOT NULL,     -- raw HMM state (0, 1, 2)
    regime_name TEXT NOT NULL,         -- human label: TRENDING / RANGING / VOLATILE
    model_train_end TIMESTAMPTZ,       -- when was the model trained up to
    PRIMARY KEY (symbol, ts, timeframe)
);
```

### 2. JSON summary: `results/hmm/hmm_regimes_YYYYMMDD.json`

```json
{
  "run_date": "2026-02-24",
  "config": {"days": 365, "n_states": 3, "timeframe": "1h", "train_days": 90},
  "n_labeled_bars": 6500,
  "state_summary": [
    {"state": 0, "label": "RANGING",  "pct_bars": 0.42, "mean_rv": 0.0008, "mean_er": 0.21},
    {"state": 1, "label": "TRENDING", "pct_bars": 0.45, "mean_rv": 0.0015, "mean_er": 0.61},
    {"state": 2, "label": "VOLATILE", "pct_bars": 0.13, "mean_rv": 0.0041, "mean_er": 0.29}
  ],
  "transition_matrix": [[0.85, 0.12, 0.03], [0.10, 0.84, 0.06], [0.15, 0.20, 0.65]]
}
```

---

## Script Outline: `scripts/hmm_regime_discovery.py`

```python
"""
HMM Regime Discovery
Usage:
  PYTHONPATH=. .venv/bin/python scripts/hmm_regime_discovery.py \
    --dsn "$RC_DB_DSN" \
    --days 365 \
    --symbol BTC-USD \
    --n-states 3 \
    --train-days 90 \
    --step-days 30 \
    --output-json results/hmm/hmm_regimes_$(date +%Y%m%d).json
"""

# Steps:
# 1. Load 5m candles from rc.candles → aggregate to 1h bars
# 2. Load 1h funding rates from rc.funding_rates → merge on timestamp
# 3. Compute features: rv_1h, er20_1h, atr_pct_1h, funding_pct_1h
# 4. Walk-forward HMM:
#    for each 30-day step:
#        train = bars[step - 90d : step]
#        test  = bars[step : step + 30d]
#        fit GaussianHMM on train
#        decode states for test → store labels
# 5. Assign human labels to states (TRENDING/RANGING/VOLATILE)
#    based on mean rv and er in each state
# 6. Map 1h labels back to 5m bars (forward-fill within each 1h period)
# 7. Write to rc.regime_labels (upsert)
# 8. Write JSON summary
```

---

## What Happens After HMM

1. Review the JSON summary — do the 3 states make intuitive sense?
2. Plot regime labels over time (optional but useful for sanity check)
3. Check: does CA-1 (existing top signal) perform differently across states?
   - If CA-1 works in TRENDING but fails in RANGING → confirms regime-dependence
   - This tells you the regime labels are meaningful
4. Pass regime label as a feature into the RF signal discovery script
5. RF will then find: "signal X works in regime TRENDING but not RANGING"
   → that becomes a regime-gated hypothesis

---

## Known Limitation: Bull-Market Bias

The 365d window (Feb 2025 – Feb 2026) was a net-positive bull period.
HMM will find states that are all variations of bullish conditions:
- TRENDING = trending up most of the time
- VOLATILE = brief corrections within a bull run
- RANGING = consolidation before next leg up

The model has not seen a sustained bear market. Any strategies built on these
regime labels should be considered **bull-market valid only** until tested
on a data window that includes 2022–2023 conditions.

---

## Checklist Before Running

- [ ] `hmmlearn>=0.3` installed in .venv
- [ ] Postgres running: `docker start rc-postgres`
- [ ] Features current: `compute_features.py --days 365` run recently
- [ ] Funding rates current: `make backfill-derivatives`
- [ ] `results/hmm/` directory created
- [ ] `rc.regime_labels` table added to schema.sql and applied

---

## Links
- `REGIME_FRAMEWORK.md` — three-layer architecture, regime taxonomy
- `docs/rf_experiment_plan.md` — RF signal discovery (runs after HMM)
- `VALIDATION_IMPROVEMENTS.md` — validation gaps to address
