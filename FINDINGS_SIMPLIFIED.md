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
