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
- H16 final: FAIL (no gross edge on kickoff). No refinement.
- H17 baseline kickoff (no tuning): PASS for magnitude relation (`ETH top-decile shocks -> BTC abs move +69.65% vs base`), non-directional signal.
- H17 note: may serve as a volatility conditioning layer for directional hypotheses (e.g., H15) in future combination testing; no combination performed at this stage.
- H18 baseline (no tuning): H15 + frozen H17 volatility-conditioning module shows higher mean (`0.001218` vs `0.000578`) on smaller sample (`57` vs `225`); provisional only.
- H18 WF 60/15/15 (no tuning):
  - gross: PASS (`5/7` positive folds, aggregated mean `+0.001640`)
  - 8 bps RT: PASS (`5/7`, `+0.000840`)
  - 10 bps RT: BORDERLINE PASS (`5/7`, `+0.000640`)
- H18 frozen: no tuning allowed (same freeze discipline as H15); definition locked as H15 gated by H17 module.
- H18 status: CURRENT BEST DIRECTIONAL CANDIDATE (frozen rules).
- H19 baseline kickoff (no tuning): PARTIAL PROMISE (`combined n=5256`, `P(cont>0)=52.83%`, `mean_cont=+0.000598`; stronger on short-tail bucket).
- H19 locked: `PASS gross`, `FAIL at 8 bps`; rules frozen.
- H20 baseline kickoff (no tuning, no friction; lock context H15/H18/H19 frozen): FAIL/WEAK.
  - Test: `H20 = H18 frozen` gated by `H19 long-tail (spread_pct>=0.90)`.
  - Result: `n=8`, win `50.00%`, mean `+0.001006` vs H18 `n=57`, mean `+0.001218` (delta `-0.000212`).
  - Decision: keep as baseline log only; no tuning.
- H20 final classification update: `FAIL` (no uplift vs H18); rules frozen.
- H21 baseline kickoff (no tuning, no friction; frozen context carried): FAIL.
  - Test: `H21 = H18 frozen` gated by `H19 short-tail (spread_pct<0.10)`.
  - Result: `n=0`, mean `0.000000` vs H18 mean `+0.001218` (delta `-0.001218`).
  - Decision: baseline logged only; no tuning.
- H22 baseline kickoff (no tuning, no friction; frozen context carried): PARTIAL PROMISE.
  - Test: `H22 = H18 frozen` gated by `H19 neutral (0.10<=spread_pct<0.90)`.
  - Result: `n=28`, win `78.57%`, mean `+0.002184` vs H18 `n=57`, mean `+0.001218` (delta `+0.000966`).
  - Decision: promising baseline signal; keep rules frozen and validate with WF+friction before any advancement call.
- H22 classification locked: `PASS gross`, `PASS at 8 bps`, `PASS at 10 bps`; rules frozen (no tuning).
- H23 baseline kickoff (no tuning, no friction; frozen context carried): PARTIAL PROMISE.
  - Test: `H23 = H15 frozen` gated by `H19 neutral (0.10<=spread_pct<0.90)`.
  - Result: `n=87`, win `79.31%`, mean `+0.001566` vs H15 `n=225`, mean `+0.000578` (delta `+0.000988`).
  - Decision: promising baseline signal; keep rules frozen and validate with WF+friction before any advancement call.
- H23 classification locked: `PASS gross`, `PASS at 8 bps`, `BORDERLINE PASS at 10 bps`; rules frozen (no tuning).
- H24 baseline kickoff (no tuning, no friction; frozen context carried): FAIL.
  - Test: `H24 = H15 frozen` gated by `H19 long-tail (spread_pct>=0.90)`.
  - Result: `n=16`, win `43.75%`, mean `-0.000994` vs H15 `n=225`, mean `+0.000578` (delta `-0.001572`).
  - Decision: baseline logged only; no tuning.
- H24 final classification update: `FAIL` (no uplift; negative mean); rules frozen.
- H25 baseline kickoff (no tuning, no friction; frozen context carried): INCONCLUSIVE (sample too small).
  - Test: `H25 = H15 frozen` gated by `H19 short-tail (spread_pct<0.10)`.
  - Result: `n=1`, win `100.00%`, mean `+0.003239` vs H15 mean `+0.000578` (delta `+0.002661`).
  - Decision: baseline logged only; no tuning.
- H25 final classification update: `INCONCLUSIVE` (n too small); rules frozen.
- H26 baseline kickoff (no tuning, no friction; frozen context carried): PARTIAL PROMISE.
  - Test: `H26 = H15 frozen` gated by `H19 mid (0.25<=spread_pct<0.75)`.
  - Result: `n=54`, win `87.04%`, mean `+0.001754` vs H15 `n=225`, mean `+0.000578` (delta `+0.001176`).
  - Decision: promising baseline signal; keep rules frozen and validate with WF+friction before any advancement call.
- H26 classification locked: `PASS gross`, `PASS at 8 bps`, `PASS at 10 bps`; rules frozen (no tuning).
- H27 baseline (liquidity shock continuation; no tuning): FAIL.
  - Rule: `range>1.8x med20` AND `volume>1.8x med20`, follow shock-bar direction for `h=6`.
  - Result: gross `n=1838`, mean `-0.000013`; 8 bps mean `-0.000813`; 10 bps mean `-0.001013`.
  - Classification locked: `FAIL gross`, `FAIL at 8 bps`, `FAIL at 10 bps`; rules frozen.
- H27 final classification update: `FAIL`; rules frozen.
- H28 baseline (liquidity sweep reversal; no tuning): FAIL.
  - Rule: break prior 12-bar high/low, then close back inside within 2 bars; fade failed break; `h=6`.
  - Result: gross `n=4635`, mean `+0.000006`; 8 bps mean `-0.000794`; 10 bps mean `-0.000994`.
  - Classification locked: `FAIL gross`, `FAIL at 8 bps`, `FAIL at 10 bps`; rules frozen.
- H29 baseline (H19 neutral-entry state transition; no tuning): FAIL.
  - Rule: on entry into H19 neutral from non-neutral, measure BTC `h=6` forward return.
  - Result: gross `n=3740`, mean `-0.000026`; 8 bps mean `-0.000826`; 10 bps mean `-0.001026`.
  - Classification locked: `FAIL gross`, `FAIL at 8 bps`, `FAIL at 10 bps`; rules frozen.
- H30 baseline (ETH/BTC 1h sign-divergence continuation; no tuning): FAIL.
  - Rule: if ETH 1h sign != BTC 1h sign, trade BTC in ETH sign direction for `h=6`.
  - Result: gross `n=1580`, mean `-0.000519`; 8 bps mean `-0.001319`; 10 bps mean `-0.001519`.
  - Classification locked: `FAIL gross`, `FAIL at 8 bps`, `FAIL at 10 bps`; rules frozen.
- H31 conditional distribution (stats-only, no trading logic/no tuning): logged.
  - Conditioning: `(ETH 1h EMA20 slope sign) x (H19 regime)`.
  - Key means: `neg x short_tail -0.001077`, `neg x long_tail +0.000507`, `pos x short_tail +0.000518`, `pos x neutral +0.000074`, `pos x long_tail +0.000181`.
  - Overall unconditional BTC `h=6` mean: `-0.000053`.
- H32 baseline (ETH 1h slope direction only in H19 short_tail; no tuning): PASS.
  - Rule: trade BTC in ETH 1h EMA20 slope-sign direction when `spread_pct<0.10`; `h=6`.
  - Result: gross `n=462`, mean `+0.001258`; 8 bps mean `+0.000458`; 10 bps mean `+0.000258`.
  - Classification locked: `PASS gross`, `PASS at 8 bps`, `PASS at 10 bps`; rules frozen.
- H32 interpretation lock (frozen): `PASS gross`, `BORDERLINE at 8 bps` (CI slightly crosses 0), `FAIL/NOT-ROBUST at 10 bps`.
- Next step locked to replication only: extend >180d and rerun same fixed H32 tests, or run same fixed H32 on ETH-USD 5m if available.
- Guardrail: no new thresholds, no new slicing, no stacking.
- H32 replication data-extension attempt: BLOCKED (Coinbase DNS failure), so replication used max local history with frozen rules.
- H32 replication A (BTC primary, max local history):
  - Baseline means: gross `+0.001258`, 8 bps `+0.000458`, 10 bps `+0.000258` (`n=462`).
  - WF+bootstrap interpretation lock: `PASS gross`, `BORDERLINE at 8 bps`, `FAIL/NOT-ROBUST at 10 bps`.
  - Rule state: frozen (no changes).
- H32 replication B (ETH primary, same frozen rule form):
  - Baseline means: gross `+0.002235`, 8 bps `+0.001435`, 10 bps `+0.001235` (`n=462`).
  - WF+bootstrap interpretation lock: `PASS gross`, `PASS at 8 bps`, `PASS at 10 bps`.
  - Rule state: frozen (no changes).
- H33 classification locked: `PASS gross`, `PASS at 8 bps`, `PASS at 10 bps`; rules frozen (no tuning).
- Symmetry confirmation: H33 reverse-logic test confirms H32 cross-asset short-tail directional structure under same fixed protocol.
- H32+H33 concurrent portfolio eval (frozen, no tuning): PASS.
  - Combined baseline (50/50 sleeves): gross mean `+0.001709`, 8 bps `+0.000909`, 10 bps `+0.000709`; max DD `-3.997% / -7.588% / -8.747%`.
  - WF+bootstrap (60/15/15):
    - gross CI `[+0.001095,+0.002353]`, `P(mean>0)=1.000`
    - 8 bps CI `[+0.000286,+0.001558]`, `P(mean>0)=0.997`
    - 10 bps CI `[+0.000097,+0.001359]`, `P(mean>0)=0.987`
  - Per-trade return correlation (H32 vs H33 when both active): `+0.811961`.
  - Note: intersection/either/concurrent variants are identical here because both frozen signals are active on the same event timestamps in this sample.
  - Classification locked: `PASS gross`, `PASS at 8 bps`, `PASS at 10 bps`; rules frozen.
- H34 (short_tail + top-30% |ETH 1h slope|, BTC traded; no tuning):
  - Baseline means: gross `+0.001375` (`n=320`), 8 bps `+0.000575`, 10 bps `+0.000375`.
  - WF+bootstrap interpretation lock: `PASS gross`, `BORDERLINE at 8 bps`, `FAIL/NOT-ROBUST at 10 bps`.
  - Rules frozen; no tuning.
- H35 short-tail decile map (stats-only): logged.
  - In H19 short_tail, BTC `h=6` conditional mean by |ETH slope| decile is mostly non-positive; strongest negative pocket at decile 10 (`-0.002688`), weak near-zero pockets at deciles 3/9.
  - Mapping only, no trading logic, no new thresholds.
- H35 signed-slope decile map (stats-only): logged.
  - Within H19 short_tail, most negative bucket is strongest negative slope decile (`bin 1`, mean `-0.002691`), while upper signed deciles (`9-10`) turn positive (`+0.000363`, `+0.000621`).
  - Mapping only, no trading logic changes.
- H36 (short_tail + bottom signed-slope decile, BTC short; no tuning):
  - Baseline means: gross `+0.001310` (`n=206`), 8 bps `+0.000510`, 10 bps `+0.000310`.
  - WF+bootstrap interpretation lock: `PASS gross`, `BORDERLINE at 8 bps`, `FAIL/NOT-ROBUST at 10 bps`.
  - Rules frozen.
- H32 horizon swap (no tuning beyond h):
  - `h=4`: gross PASS; fails robustness at 8/10 bps (CI crosses 0, weak fold support).
  - `h=8`: gross PASS; BORDERLINE at 8 bps; FAIL/NOT-ROBUST at 10 bps.
  - Both horizon variants frozen.
- H32 execution realism check (frozen h=6, next-bar-close entry):
  - Means changed slightly: gross `+0.001258 -> +0.001242`, 8 bps `+0.000458 -> +0.000442`, 10 bps `+0.000258 -> +0.000242`.
  - Win-rates decreased: gross `60.17% -> 56.93%`, 8 bps `50.87% -> 48.05%`, 10 bps `47.84% -> 45.67%`.
  - H32 remains frozen; no rule changes.
