# Findings Simplified

Last Updated: 2026-02-17
Scope: BTC-USD, Coinbase, 5m, ~180 days

## Completed Tests (Simple Status)
1. Trend / Breakout drift: FAIL (no positive edge)
2. Mean-reversion VWAP-z: FAIL (no positive edge)
3. Volatility regime drift: FAIL (no positive edge)
4. Time effects (hour/day): FAIL (no positive edge)
5. Daily drift by prior day return: FAIL (no clear edge)
6. Vol compression -> expansion: PARTIAL (predicts bigger moves, not direction)
7. Large shock continuation/reversion: WEAK (small/inconsistent)
8. Shock asymmetry (pos vs neg): PARTIAL PROMISE (led to H2S/H2S-VOL)
9. Return autocorrelation: NO EDGE (returns near zero autocorr)
10. Vol persistence after large moves: YES (for volatility/risk only)
11. Range dynamics: PARTIAL (volatility relation, not direction)
12. Multi-timeframe EMA alignment: FAIL (no directional edge)
13. Volume spike effects: FAIL (no directional edge)

## H2 / H2S / H2S-VOL Status
- Current decision: ARCHIVED (watchlist, not deployable yet)
- Why: with friction + OOS walkforward + bootstrap CI, results are unstable and mostly overlap zero.
- Reopen only if: larger dataset (target >1 year, ideally multi-asset) and same acceptance gates pass.

## New Track Started
- H14: Strategy ablation (non-H2)
- Initial result: still negative across tested variants (trend variants and MR1 both negative).

## What We Are Running Next
1. Continue H14 ablation in a controlled way (small changes only, same logging format).
2. Add more history if possible (move beyond 180 days) and re-run the same gates.
3. Run the same key tests on ETH-USD for replication check.

## Simple Bottom Line
- On current 180-day BTC 5m data, no robust directional edge is confirmed.
- Some volatility/risk structure is real, but direction signals are not stable enough yet.

## H14 Latest Update (2026-02-17)
- Focused test run: MR2 with stricter entry (`VWAP z<=-2.0`, from `-1.5`).
- Result: still FAIL for directional edge (`1494` trades, `10.58%` win, `avgR -2.550`).
- Interpretation: stricter MR entry reduced overtrading but did not fix negative expectancy.
- H14 focused MR3 (`z<=-2.0`, `max_hold=6`): still FAIL (`1547` trades, `8.27%` win, `avgR -2.524`); shorter hold reduced stop-rate but did not fix expectancy.

## H15 Latest Update (2026-02-17)
- New hypothesis started: cross-asset confirmation (BTC entries gated by ETH confirmation).
- Blocked today: ETH ingest unavailable in environment (`api.coinbase.com` DNS/network failure).
- Focused offline proxy run (BTC-only 1h confirmation) showed promise:
  - Raw MR2 (`z<=-2.0`): `n=1272`, mean net return `-0.000419`.
  - With 1h confirmation: `n=170`, mean net return `+0.000952`.
- Status: H15 provisional PROMISE in proxy form; needs full validation and real ETH confirmation once data access is restored.
- H15 real test (BTC MR2 + ETH 1h confirmation): PARTIAL PROMISE (`n=225`, win `55.56%`, mean net `+0.000178`) vs raw BTC MR2 mean `-0.000419`; needs walkforward/bootstrap validation.
- H15 walkforward+bootstrap (60/15/15, real ETH confirm): STRONG PARTIAL PASS (`n=117`, mean `+0.000813`, CI `[+0.000246,+0.001328]`, `P(mean>0)=0.998`), while raw MR2 stays negative.
- H15 robustness:
  - 90/30/30: ETH-confirmed stays positive (`n=80`, mean `+0.000984`, CI `[+0.000318,+0.001672]`).
  - 120/30/30: ETH-confirmed still positive mean (`n=49`, mean `+0.000647`) but CI crosses zero.
- Current call: H15 is the best active lead but still research-only (trade-count/stability gate not fully satisfied across geometries).
- H15 log locked: `PASS gross`, `PASS at 8 bps`, `BORDERLINE PASS at 10 bps`; rules frozen (no tuning).
- H16 kickoff (ETH shock lead-lag -> BTC h=6, no tuning, no friction): FAIL/WEAK (`P(cont>0)=47.53%`, `mean_cont=-0.000026`).
