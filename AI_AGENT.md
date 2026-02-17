# AI_AGENT.md (compact handoff)
## Regime Crypto Bot — Current Operating Brief

Last Updated: 2026-02-17 UTC

## 1) Mission
- Build a truthful, no-leakage crypto trading system.
- Validate hypotheses on historical data first, then forward paper only after strict OOS gates.
- Current instrument/timeframe: BTC-USD spot, Coinbase, 5m candles.

## 2) Current Dataset Constraint
- Available working dataset: ~180 days (about 51k 5m bars).
- Date range in findings: 2025-08-20 to 2026-02-16 (UTC).
- Implication: enough for early filtering, not enough for strong statistical confidence on subtle edges.

## 3) Tech Stack (Current)
- Language/runtime: Python 3.x in `.venv`
- Core data libs: `pandas`, `numpy`
- API/http/env: `requests`, `python-dotenv`, `PyJWT`, `cryptography`
- Console/reporting: `rich`
- Data store: SQLite (`data/market.sqlite`)
- Exchange/data source: Coinbase Advanced API (BTC-USD, 5m candles)
- Strategy/research entry points: `scripts/*.py`, `scripts/experts/*.py`
- Exact dependency list/versions: `requirements.txt`

## 4) Canonical Files (Use These in Order)
1. `FINDINGS_SIMPLIFIED.md` (quick truth: what was run, pass/fail/partial, next queue)
2. `FINDINGS.md` (human summary log)
3. `FINDINGS_TECHNICAL.md` (full commands + outputs + tables)
4. `AI_AGENT.md` (this file; operational handoff)

## 5) Locked Research Protocol
- One hypothesis per execution where applicable.
- No lookahead leakage.
- No random splits; use holdout/walkforward only.
- Keep findings append-only.
- Always include friction in serious OOS decisions.
- Small, principled parameter changes only.

## 6) What Has Been Tested
- Initial hypothesis set (1–13) has been run.
- See `FINDINGS_SIMPLIFIED.md` for simple statuses.
- Core result on current 180d sample: no robust directional edge confirmed.

### 6.1 Hypothesis Status Snapshot (Quick)
1. Trend/breakout drift: failed
2. VWAP-z mean reversion drift: failed
3. RV regime directional drift: failed
4. Time-of-day/day-of-week drift: failed
5. Daily prior-return drift: failed
6. Vol compression -> expansion: partial (vol signal, not direction)
7. Shock continuation/reversion: weak/inconsistent
8. Shock asymmetry: partial promise (spawned H2S/H2S-VOL branch)
9. Return autocorrelation: no directional edge
10. Vol persistence after large moves: yes for risk/vol forecasting
11. Range dynamics: partial (vol relation, not direction)
12. MTF EMA alignment: failed
13. Volume spike effects: failed

## 7) H2/H2S/H2S-VOL Decision
- Status: archived as watchlist (not deployable now).
- Why:
  - OOS friction-on results unstable across splits.
  - Bootstrap CIs for mean return mostly overlap zero.
  - No tested config passed acceptance gate.
- Reopen only if:
  - larger sample (target >1 year), and ideally replication on multiple assets.
  - same acceptance gate passes without relaxed standards.

## 8) Active Track Now
- Track: H14 Strategy Ablation (non-H2 branch).
- Latest read:
  - trend ablation variants remained negative.
  - MR1 variant still negative.
- Interpretation:
  - currently no viable strategy from tested ablations on 180d sample.

## 9) Acceptance Gate (Deployability Candidate)
Use this gate before promoting any strategy to forward paper deployment:
- Friction on: `fee_bps=2`, `slippage_bps=2` per side.
- OOS trade count threshold: >= 100 per evaluated horizon.
- Mean return 95% bootstrap CI lower bound > 0.
- `P(mean_return > 0)` >= 0.70.
- Sharpe-like > 0 and not single-fold dependent.
- Stability across multiple walkforward geometries.

If a strategy fails this gate, it stays research-only.

## 10) Important Scripts
- Hypothesis studies:
  - `scripts/hypothesis_studies.py`
- H2 expert branch:
  - `scripts/experts/h2s_vol_expert.py`
  - `scripts/h2s_vol_uncertainty.py`
- Ablation track:
  - `scripts/ablation.py`
- Reporting/dashboard:
  - `scripts/dashboard.py`

### 10.1 Data/Feature Pipeline Scripts
- `scripts/backfill_5m.py` (historical fetch/backfill)
- `scripts/ingest_5m.py` and `scripts/run_ingest_loop.py` (ongoing ingest)
- `scripts/compute_features.py` (feature materialization)
- `scripts/sanity_report.py` and `scripts/summary_report.py` (health summaries)

## 11) Resume Commands (Most Useful)
### 11.1 H2S-VOL (archived track; rerun only when needed)
- Friction-on walkforward matrix example:
  - `.venv/bin/python -m scripts.experts.h2s_vol_expert --days 180 --window 2000 --variant B --horizons 10,20 --split-mode walkforward --train-days 60 --test-days 15 --step-days 15 --fee_bps 2 --slippage_bps 2 --equity-csv-prefix logs/h2s_vol_expert_vb_wf_60_15_15_fee2_slip2`
- Uncertainty example:
  - `.venv/bin/python -m scripts.h2s_vol_uncertainty --label wf_60_15_15_base --horizons 10,20 --train-days 60 --test-days 15 --step-days 15 --rv-pct-min 0.70 --rv-pct-max 0.90 --shock-atr-min 1.50 --shock-atr-max 2.50 --fee_bps 2 --slippage_bps 2 --bootstrap-iters 3000`

### 11.2 Active H14 ablation
- `.venv/bin/python -m scripts.ablation --days 180`

### 11.3 Core Drift Studies (reference reruns)
- Trend/breakout drift:
  - `.venv/bin/python -m scripts.drift_study --days 180 --timeframes 5m,15m,1h,4h,1d`
- Mean-reversion drift:
  - `.venv/bin/python -m scripts.mr_drift_study --days 180 --timeframes 5m,1h,4h --dev-window 48`
- RV drift:
  - `.venv/bin/python -m scripts.rv_drift_study --days 180 --window 2000`
- Time effects:
  - `.venv/bin/python -m scripts.time_effects_study --days 180`
- Daily drift:
  - `.venv/bin/python -m scripts.daily_drift_study --days 720`

## 12) Update Rules (Keep Organization Clean)
When you run anything meaningful:
1. Add one short line in `FINDINGS_SIMPLIFIED.md` (status update).
2. Append concise summary block to `FINDINGS.md`.
3. Append command + output tables to `FINDINGS_TECHNICAL.md`.
4. Update this file only if session state changes (active track, acceptance gate, resume commands).

Do not rewrite old findings blocks; append new dated entries.

### 12.1 Logging Style Rules
- Use explicit UTC timestamps in new findings blocks.
- Include exact command strings used.
- Include whether friction was on/off.
- For OOS conclusions, always include split geometry (`train/test/step`).
- If results are negative, still log them fully (no silent drops).

## 13) Practical Next Queue
1. Continue H14 with controlled ablation (small parameter deltas, no broad search).
2. If possible, expand data horizon beyond 180d and rerun acceptance gate.
3. Replicate key tests on ETH-USD to check portability.
4. Only reopen H2 after #2/#3 conditions are met.

### 13.1 Stop/Continue Logic
- Continue current branch only if evidence quality increases (more data, tighter CI, stable folds).
- Pause branch when repeated friction-on OOS runs stay CI-overlap-zero.
- Escalate to new branch when prior branch is archived or saturated.

## 14) Guardrails
- No overfitting from tiny windows.
- No parameter hunt without a clear hypothesis.
- No deployment claims from single split or CI-overlapping-zero results.
- Prefer robust, boring truth over attractive but fragile backtests.

## 15) Quick Session Start Checklist
At start of any new AI session:
1. Read `FINDINGS_SIMPLIFIED.md`.
2. Read latest sections at bottom of `FINDINGS.md` and `FINDINGS_TECHNICAL.md`.
3. Confirm active track (currently H14).
4. Run one focused test.
5. Log all three findings files.

## 16) Known Limitations Right Now
- Sample length is short for robust market-regime generalization.
- Current universe is mostly BTC-USD only; weak cross-asset validation.
- 5m bars can be noisy; small edges are fragile under fees/slippage.
- Some hypothesis runners are H1/H2-family specific and not full generic frameworks.

## 17) Preferred Next Data Upgrade
- Expand beyond 180d history (target >= 1 year first).
- Add ETH-USD mirror dataset and run same core drift + gating pipeline.
- Keep same acceptance gate to prevent post-hoc standard changes.

## 18) Session Preflight (Quick)
Run these before new research runs:
1. `.venv/bin/python -V`
2. `.venv/bin/python -m scripts.health`
3. Verify data coverage quickly (latest findings range in `FINDINGS_SIMPLIFIED.md`).
4. Use one focused command from Section 11 and log all outputs in findings files.

---
Archive note: previous full playbook version saved at `archive/AI_AGENT_full_2026-02-17.md`.
