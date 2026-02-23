# Findings Simplified
Canonical truth = `results/runs` artifacts; `results/summary.json` and findings are derived.

Last Updated: 2026-02-23
Scope: BTC-USD + ETH-USD, Coinbase, 5m

---
> **DATA ERA NOTE:** Results below H123 were produced on ~180-day datasets (≤2 WF folds in many cases).
> Starting from H124 onward, the canonical dataset is 365 days (~14 WF folds). Results from the 180d
> era carry higher false-positive risk due to insufficient fold count. See `FINDINGS_365D.md` for
> the clean 365d-era results. See `REGIME_FRAMEWORK.md` for H124+ design rules.
---

<!-- === PRE-365D ERA (180d dataset, ≤11 WF folds, higher false-positive risk) === -->

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

- H32: `FAIL` (bps8 n=462, mean=0.00045769968310510514, WF agg=0.0004421428714670377)

- H33: `FAIL` (bps8 n=462, mean=-0.002057699683105106, WF agg=-0.002042142871467038)

- H37: `FAIL` (bps8 n=3747, mean=-0.0006757192310880838, WF agg=-0.0005950443633725123)

- H38: `FAIL` (bps8 n=406, mean=-0.000795139038499537, WF agg=-0.001159263093260172)

- H39: `PASS` (bps8 n=326, mean=0.000608531221681871, WF agg=0.0009142505375646338)

- H40: `FAIL` (bps8 n=7146, mean=-0.0005408389740210429, WF agg=-0.0005009386717780214)

- H41: `FAIL` (bps8 n=1472, mean=-0.0009729836610631007, WF agg=-0.0010013846561422368)

- H42: `FAIL` (bps8 n=2490, mean=-0.0005560967984188211, WF agg=-0.0005371786196449361)

- H43: `FAIL` (bps8 n=2490, mean=-0.0010439032015811792, WF agg=-0.001062821380355064)

- H44: `FAIL` (bps8 n=2449, mean=-0.0006521372701282587, WF agg=-0.0006452543119515767)

- H45: `FAIL` (bps8 n=1286, mean=-0.0009290926943585902, WF agg=-0.0009951618769991227)

- H46: `FAIL` (bps8 n=1795, mean=-0.0006141638905442473, WF agg=-0.000584206482415338)

- H47: `FAIL` (bps8 n=2017, mean=-0.0007603113856433166, WF agg=-0.0007860825099800092)

- H48: `FAIL` (bps8 n=1892, mean=-0.0008356582767705313, WF agg=-0.0007846438361969042)

- H49: `FAIL` (bps8 n=514, mean=-0.0009279892070691534, WF agg=-0.0010249694928039527)

- H50: `FAIL` (bps8 n=1929, mean=-0.0007966581332502239, WF agg=-0.0007762357203084478)

- H51: `FAIL` (bps8 n=372, mean=-0.0006035595521548516, WF agg=-0.0007063938774321842)

- H52: `INCONCLUSIVE` (bps8 n=363, mean=-0.0005117051006692997, WF agg=-4.0703864384104664e-05)

- H53: `FAIL` (bps8 n=612, mean=-0.0007652927313003039, WF agg=-0.0004909237943503551)

- H54: `FAIL` (bps8 n=3884, mean=-0.0008702141746363642, WF agg=-0.0009034568349689908)

- H55: `FAIL` (bps8 n=2012, mean=-0.000781996291616128, WF agg=-0.0008269653048801187)

- H56: `FAIL` (bps8 n=5092, mean=-0.0009707259739250243, WF agg=-0.0010278733088273664)

- H59: `PASS` (bps8 n=334, mean=0.0010149890861475869, WF agg=0.0012866501297545039)

- H60: `PASS` (bps8 n=324, mean=0.0017646081394872518, WF agg=0.0019027564333464171)

- H61: `BORDERLINE` (bps8 n=324, mean=0.0005443140281774565, WF agg=0.0007096416455597401)

## Phase-2 Replication Freeze Update (2026-02-17)
- H59 freeze: `PASS gross / PASS bps8 / PASS bps10` (robust; bps8 and bps10 each 100% positive folds in WF).
- H60 freeze: `PASS gross / PASS bps8 / PASS bps10` (robust).
- H61 freeze (realism variant): `PASS gross / PASS bps8 / BORDERLINE bps10` (10 bps CI crosses 0; bps10 fold support 57.14%).

- H62: `BORDERLINE` (bps8 n=335, mean=0.00033426024334174987, WF agg=0.0005426922388723893)

- H63: `PASS` (bps8 n=335, mean=0.0014379580904312621, WF agg=0.0017501702449459885)

- H64: `PASS` (bps8 n=325, mean=0.0010149075180192581, WF agg=0.0011027892932372364)

- H65: `PASS` (bps8 n=325, mean=0.002259078222285754, WF agg=0.002254674868739397)

- H66: `INCONCLUSIVE` (bps8 n=210, mean=0.001682866287913043, WF agg=0.0015062658827210316)

- H67: `INCONCLUSIVE` (bps8 n=220, mean=0.0022613898043064304, WF agg=0.0009621722484972721)

- H68: `INCONCLUSIVE` (bps8 n=170, mean=0.0015565755365926637, WF agg=0.0015079081630144436)

- H69: `INCONCLUSIVE` (bps8 n=162, mean=0.0013403511705525348, WF agg=0.0018307265769311031)

- H70: `PASS` (bps8 n=163, mean=0.0025294005359594476, WF agg=0.002063329956339998)

- H71: `INCONCLUSIVE` (bps8 n=159, mean=0.0019813068126899153, WF agg=0.001888763804805619)

- H72: `PASS` (bps8 n=332, mean=0.0014510684664164565, WF agg=0.0017604547965901834)

- H73: `PASS` (bps8 n=322, mean=0.002258757983164865, WF agg=0.0023037077715540545)

- H74: `INCONCLUSIVE` (bps8 n=210, mean=0.0012393011349051773, WF agg=0.0010655851371971826)

- H75: `INCONCLUSIVE` (bps8 n=220, mean=0.0019459795260085302, WF agg=0.0004934618278751236)


## Phase-2c Update (2026-02-18)
- H63/H65 robustness replications added as new IDs (H66-H73) plus H59/H60 references (H74-H75); no rule changes.
- Longer-lookback checks (120d vs 180d), odd/even day subsamples, and trade-density/concentration diagnostics logged in FINDINGS_TECHNICAL.md.

- H76: `PASS` (bps8 n=328, mean=0.0015949277557862135, WF agg=0.001888404180074488)

- H76: `PASS` (bps8 n=328, mean=0.0015949277557862135, WF agg=0.001888404180074488)

- H77: `PASS` (bps8 n=324, mean=0.00213298458606954, WF agg=0.0019903163752861028)

- H78: `PASS` (bps8 n=328, mean=0.0014201780443425722, WF agg=0.0017240476861219388)

- H79: `PASS` (bps8 n=324, mean=0.00213298458606954, WF agg=0.0019903163752861028)

- H80: `INCONCLUSIVE` (bps8 n=112, mean=0.0006517901630801529, WF agg=0.0007304200071063339)

- H81: `INCONCLUSIVE` (bps8 n=106, mean=0.0018863729313158602, WF agg=0.0025269968210485565)

- H82: `INCONCLUSIVE` (bps8 n=110, mean=0.001753294268726412, WF agg=0.001999492473436476)

- H83: `INCONCLUSIVE` (bps8 n=116, mean=0.001512895939069123, WF agg=0.0015650959769891444)

- H84: `INCONCLUSIVE` (bps8 n=109, mean=0.002732654466568435, WF agg=0.002319840351523096)

- H85: `INCONCLUSIVE` (bps8 n=99, mean=0.0021993105060459915, WF agg=0.0022020625296173494)

<!-- DERIVED_STATUS_START -->

## Derived Status (Artifact-Backed)
- H100: `FAIL` (artifact: `results/runs/20260219T060657Z_H100.json`)
- H101: `FAIL` (artifact: `results/runs/20260219T210243Z_H101.json`)
- H102: `INCONCLUSIVE` (artifact: `results/runs/20260219T211115Z_H102.json`)
- H103: `FAIL` (artifact: `results/runs/20260219T211942Z_H103.json`)
- H104: `FAIL` (artifact: `results/runs/20260219T212809Z_H104.json`)
- H105: `FAIL` (artifact: `results/runs/20260219T213637Z_H105.json`)
- H106: `FAIL` (artifact: `results/runs/20260219T214503Z_H106.json`)
- H107: `FAIL` (artifact: `results/runs/20260219T215330Z_H107.json`)
- H108: `FAIL` (artifact: `results/runs/20260219T220202Z_H108.json`)
- H109: `INCONCLUSIVE` (artifact: `results/runs/20260219T221028Z_H109.json`)
- H110: `INCONCLUSIVE` (artifact: `results/runs/20260219T221847Z_H110.json`)

## Funding Regime Family — First Run (2026-02-22)
Data source: Hyperliquid public API (1h funding, 365 days). Infrastructure committed:
`db/schema.sql` (3 new tables), `scripts/backfill_derivatives.py`, `app/db/derivatives.py`,
`load_frame()` wired with `merge_asof`. 17,520 hourly funding records loaded (BTC + ETH).

- H121: `FAIL` — extreme funding long fade. 365d rerun: 70 trades, gross mean=+0.00032, P>0=0.771, but WF only 3/11 folds positive. Signal is inconsistent — extreme funding crowding does not reliably predict short-term mean reversion at 5m/6-bar horizon. (180d: `results/runs/20260222T203728Z_H121.json`; 365d: `results/runs/20260222T205008Z_H121.json`)
- H122: `FAIL` — funding sign flip momentum does not predict returns. Gross mean=-0.00038, P>0=0.08 (negative before costs). All modes FAIL. (artifact: `results/runs/20260222T203731Z_H122.json`)
- H123: `FAIL` — H32 filtered by non-extreme funding (gate: funding_btc_pct < 0.85). **365-day rerun (2026-02-22):** Gross n=2006, mean=+0.00065, CI=[+0.00048,+0.00083], P>0=1.000. WF gross: 12/14 folds positive, mean=+0.00068, P>0=1.000. Signal has real gross alpha. FAIL due to cost: inherits H32's ~7 trades/day cadence — 8bps round-trip cost (+0.080%) exceeds gross edge (+0.065%) by 23%. bps8 mean=-0.00015, WF 4/14 folds positive. Diagnosis: funding filter improves quality but not enough to overcome cost drag at high frequency. **Next step: H124 — use funding filter with much tighter spread threshold to reduce to 1-2 trades/day.** (180d artifact: `results/runs/20260222T203735Z_H123.json`; 365d artifact: `results/runs/20260222T204904Z_H123.json`)

<!-- === 365D ERA START (2026-02-23 — 365d dataset, ~14 WF folds, regime framework rules apply) === -->
<!-- All H124+ results belong in FINDINGS_365D.md first, then summarized here. -->

## 365d Rerun — Summary (2026-02-23)
Full results in `FINDINGS_365D.md`. Key reclassifications on 365d data:

**CONFIRMED PASS (365d, WF 20/20):** H59, H60, H63, H64, H65 — strongest survivors. H65 perfect 20/20 at both gross and bps8.

**DOWNGRADED — FAIL on 365d (were PASS on 180d):**
- H32: Gross real (WF 12/14, P>0=1.000) but bps8 cost-constrained (mean≈0, WF 8/14). Signal exists, trade frequency too high for 8bps edge. Paper trading status: UNDER REVIEW.
- H33: Complete collapse on 365d (gross WF 2/14, P>0=0.000). Short-side only worked in narrow 180d window. FROZEN as FAIL.

**DOWNGRADED — BORDERLINE (were PASS):** H39 (WF 20/20 gross but bps8 WF 16/20).

**365d RERUN COMPLETE (all hypotheses):** Full results in `FINDINGS_365D.md`.

365d PASS set (confirmed robust, WF 20/20 or near): H59, H60, H63, H64, H65, H66, H67, H68, H69, H70, H71, H72, H73, H74, H75, H76, H77, H78, H79, H81, H82, H83, H84, H85, H99.
Notable perfects (20/20 gross AND bps8): H65, H67, H73, H77, H79, H84.

- H15: `INCONCLUSIVE` (artifact: `results/runs/20260219T035146Z_H15.json`)
- H18: `INCONCLUSIVE` (artifact: `results/runs/20260219T035159Z_H18.json`)
- H19: `INCONCLUSIVE` (artifact: `results/runs/20260219T035211Z_H19.json`)
- H22: `INCONCLUSIVE` (artifact: `results/runs/20260219T042009Z_H22.json`)
- H23: `INCONCLUSIVE` (artifact: `results/runs/20260219T042025Z_H23.json`)
- H26: `INCONCLUSIVE` (artifact: `results/runs/20260219T042041Z_H26.json`)
- H27: `FAIL` (artifact: `results/runs/20260219T040716Z_H27.json`)
- H28: `FAIL` (artifact: `results/runs/20260219T040727Z_H28.json`)
- H29: `INCONCLUSIVE` (artifact: `results/runs/20260219T040739Z_H29.json`)
- H30: `FAIL` (artifact: `results/runs/20260219T040752Z_H30.json`)
- H32: `INCONCLUSIVE` (artifact: `results/runs/20260217T171153Z_H32.json`)
- H33: `INCONCLUSIVE` (artifact: `results/runs/20260217T172009Z_H33.json`)
- H37: `INCONCLUSIVE` (artifact: `results/runs/20260217T174740Z_H37.json`)
- H38: `INCONCLUSIVE` (artifact: `results/runs/20260217T174744Z_H38.json`)
- H39: `PASS` (artifact: `results/runs/20260217T174748Z_H39.json`)
- H40: `FAIL` (artifact: `results/runs/20260217T174752Z_H40.json`)
- H41: `FAIL` (artifact: `results/runs/20260217T174756Z_H41.json`)
- H42: `FAIL` (artifact: `results/runs/20260217T180330Z_H42.json`)
- H43: `FAIL` (artifact: `results/runs/20260217T180334Z_H43.json`)
- H44: `FAIL` (artifact: `results/runs/20260217T180338Z_H44.json`)
- H45: `FAIL` (artifact: `results/runs/20260217T180342Z_H45.json`)
- H46: `FAIL` (artifact: `results/runs/20260217T180346Z_H46.json`)
- H47: `FAIL` (artifact: `results/runs/20260217T180351Z_H47.json`)
- H48: `FAIL` (artifact: `results/runs/20260217T180355Z_H48.json`)
- H49: `FAIL` (artifact: `results/runs/20260217T180359Z_H49.json`)
- H50: `FAIL` (artifact: `results/runs/20260217T180402Z_H50.json`)
- H51: `INCONCLUSIVE` (artifact: `results/runs/20260217T180406Z_H51.json`)
- H52: `INCONCLUSIVE` (artifact: `results/runs/20260217T180410Z_H52.json`)
- H53: `FAIL` (artifact: `results/runs/20260217T180414Z_H53.json`)
- H54: `FAIL` (artifact: `results/runs/20260217T180418Z_H54.json`)
- H55: `FAIL` (artifact: `results/runs/20260217T180422Z_H55.json`)
- H56: `FAIL` (artifact: `results/runs/20260217T180426Z_H56.json`)
- H59: `PASS` (artifact: `results/runs/20260217T181139Z_H59.json`)
- H60: `PASS` (artifact: `results/runs/20260217T181143Z_H60.json`)
- H61: `BORDERLINE` (artifact: `results/runs/20260217T181147Z_H61.json`)
- H62: `BORDERLINE` (artifact: `results/runs/20260217T181610Z_H62.json`)
- H63: `PASS` (artifact: `results/runs/20260217T181614Z_H63.json`)
- H64: `PASS` (artifact: `results/runs/20260217T181618Z_H64.json`)
- H65: `PASS` (artifact: `results/runs/20260217T181622Z_H65.json`)
- H66: `INCONCLUSIVE` (artifact: `results/runs/20260218T074308Z_H66.json`)
- H67: `INCONCLUSIVE` (artifact: `results/runs/20260218T074311Z_H67.json`)
- H68: `PASS` (artifact: `results/runs/20260218T074315Z_H68.json`)
- H69: `PASS` (artifact: `results/runs/20260218T074319Z_H69.json`)
- H70: `PASS` (artifact: `results/runs/20260218T074323Z_H70.json`)
- H71: `PASS` (artifact: `results/runs/20260218T074327Z_H71.json`)
- H72: `PASS` (artifact: `results/runs/20260218T074331Z_H72.json`)
- H73: `PASS` (artifact: `results/runs/20260218T074334Z_H73.json`)
- H74: `INCONCLUSIVE` (artifact: `results/runs/20260218T074337Z_H74.json`)
- H75: `INCONCLUSIVE` (artifact: `results/runs/20260218T074340Z_H75.json`)
- H76: `PASS` (artifact: `results/runs/20260219T045701Z_H76.json`)
- H77: `PASS` (artifact: `results/runs/20260219T045712Z_H77.json`)
- H78: `PASS` (artifact: `results/runs/20260219T045750Z_H78.json`)
- H79: `PASS` (artifact: `results/runs/20260219T045725Z_H79.json`)
- H80: `FAIL` (artifact: `results/runs/20260218T211339Z_H80.json`)
- H81: `PASS` (artifact: `results/runs/20260219T045737Z_H81.json`)
- H82: `PASS` (artifact: `results/runs/20260219T045802Z_H82.json`)
- H83: `PASS` (artifact: `results/runs/20260218T211351Z_H83.json`)
- H84: `PASS` (artifact: `results/runs/20260218T211355Z_H84.json`)
- H85: `PASS` (artifact: `results/runs/20260218T211400Z_H85.json`)
- H86: `FAIL` (artifact: `results/runs/20260219T045029Z_H86.json`)
- H87: `INCONCLUSIVE` (artifact: `results/runs/20260219T045043Z_H87.json`)
- H88: `FAIL` (artifact: `results/runs/20260219T045056Z_H88.json`)
- H89: `FAIL` (artifact: `results/runs/20260219T045108Z_H89.json`)
- H90: `FAIL` (artifact: `results/runs/20260219T045120Z_H90.json`)
- H91: `INCONCLUSIVE` (artifact: `results/runs/20260219T053232Z_H91.json`)
- H92: `FAIL` (artifact: `results/runs/20260219T053545Z_H92.json`)
- H93: `FAIL` (artifact: `results/runs/20260219T053907Z_H93.json`)
- H94: `FAIL` (artifact: `results/runs/20260219T054257Z_H94.json`)
- H95: `BORDERLINE` (artifact: `results/runs/20260219T054650Z_H95.json`)
- H96: `INCONCLUSIVE` (artifact: `results/runs/20260219T055032Z_H96.json`)
- H97: `INCONCLUSIVE` (artifact: `results/runs/20260219T055459Z_H97.json`)
- H98: `FAIL` (artifact: `results/runs/20260219T055836Z_H98.json`)
- H99: `INCONCLUSIVE` (artifact: `results/runs/20260219T060220Z_H99.json`)

<!-- DERIVED_STATUS_END -->


## Portfolio-Construction Rerun (2026-02-20)
- P01-P04 combined 180d bps8 rerun: `BLOCKED_HEAT` (artifact: `results/paper/20260220T065602Z_P01_P04_combined_180d.json`; audit: `results/audit/audit_20260220T081857Z_portfolio_construction_p01_p04_combined_180d_rerun.json`; continuation: `BLOCKED`).
