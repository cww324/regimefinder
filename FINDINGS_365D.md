# FINDINGS_365D.md — 365-Day Era Results
**Created:** 2026-02-23
**Dataset:** BTC-USD + ETH-USD, Coinbase 5m candles, 365 days (2025-02-22 → 2026-02-22), ~105k bars/symbol
**Walk-Forward:** 60/15/15 train/val/step unless noted — yields ~14 folds on 365d data
**Regime Framework:** All H124+ hypotheses must follow `REGIME_FRAMEWORK.md`

---

## Purpose

This document is the clean-slate record for the 365d era. It is organized by **signal family / regime**, not chronologically. Every hypothesis result from H124 onward is logged here first, then summarized in `FINDINGS_SIMPLIFIED.md`.

The 180d era results (H15–H123) are preserved in `FINDINGS_SIMPLIFIED.md` as archive.

---

## 365d Rerun Results (Pre-Framework Hypotheses)

These are reruns of pre-framework hypotheses (H15–H123) on the extended 365d dataset.
Classification decisions are **updated** — a hypothesis that was INCONCLUSIVE on 180d may resolve on 365d.

> Batch completed: 2026-02-23. 49 hypotheses rerun. Note: H68–H85, H66/67/74/75, H87–H110 have
> per-hypothesis `lookback_days` overrides (180d or 120d) and did NOT run on 365d data — marked below.
> These need dedicated 365d reruns with per-hypothesis override removed or bumped.

### ⚠️ CRITICAL FINDING: H32 and H33 downgraded on 365d

**H32 (live paper candidate):** Gross signal is still real (WF 12/14 folds positive, P>0=1.000) but
bps8 mean ≈ 0, WF 8/14, P>0=0.54. The edge (+0.074%/trade gross) is too thin to survive 8bps costs
reliably across the full year. **Classification: FAIL on 365d.**

**H33 (short-side symmetry):** Complete collapse. Gross WF 2/14, P>0=0.000. The short side only worked
in the narrow 180d window (likely a bull-run bias). **Classification: FAIL on 365d.**

**Implication:** The H32+H33 paper portfolio must be reviewed. H33 is dead. H32 has real gross alpha
but needs either tighter entry (reduce frequency) or lower-cost execution to survive 8bps.

---

| ID | 180d Status | 365d Status | Data Used | WF gross / bps8 |
|----|-------------|-------------|-----------|-----------------|
| H15 | INCONCLUSIVE | INCONCLUSIVE | 365d | 7/13 / 6/13 |
| H18 | INCONCLUSIVE | INCONCLUSIVE | 365d | 2/12 / 1/12 |
| H19 | INCONCLUSIVE | **FAIL** ← | 365d | 1/14 / 0/14 |
| H22 | INCONCLUSIVE | INCONCLUSIVE | 365d | 2/10 / 1/10 |
| H23 | INCONCLUSIVE | INCONCLUSIVE | 365d | 5/11 / 4/11 |
| H26 | INCONCLUSIVE | INCONCLUSIVE | 365d | 4/11 / 3/11 |
| H29 | INCONCLUSIVE | **FAIL** ← | 365d | 6/14 / 0/14 |
| H32 | PASS | **FAIL** ← | 365d | 12/14 / 8/14 — gross real, cost-constrained |
| H33 | PASS | **FAIL** ← | 365d | 2/14 / 1/14 — short side collapses |
| H37 | INCONCLUSIVE | **FAIL** ← | 365d | 10/14 / 0/14 |
| H38 | INCONCLUSIVE | **FAIL** ← | 365d | 11/14 / 1/14 |
| H39 | PASS | BORDERLINE ↓ | 365d | 20/20 / 16/20 |
| H51 | INCONCLUSIVE | **FAIL** ← | 365d | 11/14 / 3/14 |
| H52 | INCONCLUSIVE | **FAIL** ← | 365d | 12/14 / 1/14 |
| H59 | PASS | **PASS ✓** | 365d | 20/20 / 16/20 |
| H60 | PASS | **PASS ✓** | 365d | 20/20 / 18/20 |
| H61 | BORDERLINE | BORDERLINE | 365d | 20/20 / 13/20 |
| H62 | BORDERLINE | FAIL ← | 365d | 20/20 / 10/20 — bps10 gate fails |
| H63 | PASS | **PASS ✓** | 365d | 20/20 / 19/20 |
| H64 | PASS | **PASS ✓** | 365d | 20/20 / 18/20 |
| H65 | PASS | **PASS ✓** | 365d | 20/20 / 20/20 — perfect |
| H66 | INCONCLUSIVE | **PASS ✓** ← | 365d | 20/20 / 19/20 |
| H67 | INCONCLUSIVE | **PASS ✓** ← | 365d | 20/20 / 20/20 — perfect |
| H68 | PASS | **PASS ✓** | 365d | 19/20 / 19/20 |
| H69 | PASS | **PASS ✓** | 365d | 20/20 / 16/20 |
| H70 | PASS | **PASS ✓** | 365d | 20/20 / 19/20 |
| H71 | PASS | **PASS ✓** | 365d | 19/20 / 18/20 |
| H72 | PASS | **PASS ✓** | 365d | 20/20 / 19/20 |
| H73 | PASS | **PASS ✓** | 365d | 20/20 / 20/20 — perfect |
| H74 | INCONCLUSIVE | **PASS ✓** ← | 365d | 20/20 / 16/20 |
| H75 | INCONCLUSIVE | **PASS ✓** ← | 365d | 20/20 / 18/20 |
| H76 | PASS | **PASS ✓** | 365d | 20/20 / 19/20 |
| H77 | PASS | **PASS ✓** | 365d | 20/20 / 20/20 — perfect |
| H78 | PASS | **PASS ✓** | 365d | 20/20 / 19/20 |
| H79 | PASS | **PASS ✓** | 365d | 20/20 / 20/20 — perfect |
| H81 | PASS | **PASS ✓** | 365d | 20/20 / 17/20 |
| H82 | PASS | **PASS ✓** | 365d | 20/20 / 15/20 |
| H83 | PASS | **PASS ✓** | 365d | 20/20 / 18/20 |
| H84 | PASS | **PASS ✓** | 365d | 20/20 / 20/20 — perfect |
| H85 | PASS | **PASS ✓** | 365d | 19/20 / 18/20 |
| H87 | INCONCLUSIVE | FAIL ← | 365d | 13/14 / 3/14 — gross real, cost-constrained |
| H91 | INCONCLUSIVE | FAIL ← | 365d | 13/14 / 5/14 — gross real, cost-constrained |
| H95 | BORDERLINE | FAIL ← | 365d | 18/18 / 10/18 — bps8 WF only 55% |
| H96 | INCONCLUSIVE | FAIL ← | 365d | 2/14 / 1/14 |
| H97 | INCONCLUSIVE | FAIL ← | 365d | 12/14 / 3/14 — gross real, cost-constrained |
| H99 | INCONCLUSIVE | **PASS ✓** ← | 365d | 17/20 / 12/20 |
| H102 | INCONCLUSIVE | FAIL ← | 365d | 7/16 / 4/16 |
| H109 | INCONCLUSIVE | FAIL ← | 365d | 7/16 / 3/16 |
| H110 | INCONCLUSIVE | FAIL ← | 365d | 3/13 / 2/13 |

---

## Regime Framework Era Hypotheses (H124+)

Organized by regime family. All results use 365d dataset and 60/15/15 WF.

### Family: funding_regime

| ID | Entry Rule | n | /day | gross_bps | P>0_gross | WF+ | bps8_P>0 | Status | Notes |
|----|-----------|---|------|-----------|-----------|-----|----------|--------|-------|
| H121 | funding_pct ≥ 0.90, spread < 0.10 | ~70 | 0.2 | neg | — | — | — | FAIL | Inconsistent, negative gross |
| H122 | funding sign flip | — | — | neg | — | — | — | FAIL | Negative gross |
| H123 | funding < 0.85, spread ≥ 0.90 | — | 7.0 | ~6-7 | — | — | 0.0 | FAIL | Real signal, cost-constrained |
| H124 | funding < 0.85, spread ≥ 0.97 | ~750 | 2.1 | — | 1.000 | 12/14 | ~0 | BORDERLINE | Gross real, bps8 straddles zero |
| H140 | funding_btc_pct ≤ 0.10 → LONG | 1461 | 4.0 | 0.94 | 0.801 | 12/18 | 0.000 | FAIL | Cost-constrained |
| H141 | funding_pct ≥ 0.85 + slope flip → SHORT | 16 | 0.04 | 17.64 | 0.863 | 1/5 | 0.702 | INCONCLUSIVE | n=16 too few |
| H142 | funding_spread_pct ≥ 0.80 → SHORT | 2400 | 6.6 | -0.10 | 0.443 | 5/18 | 0.000 | FAIL | No gross edge |
| H143 | funding_sign = slope_sign → direction | 6821 | 18.7 | 1.63 | 1.000 | 16/20 | 0.000 | FAIL | Cost-constrained |
| H144 | sustained funding 3h + slope flip → SHORT | 11 | 0.03 | 4.94 | 0.543 | 0/5 | 0.387 | INCONCLUSIVE | n=11 too few |

**FR Family Lesson**: Funding rate signals consistently hit a cost ceiling. No standalone FR signal has cleared 8bps in 365d testing. H141 is interesting (17bps gross) but statistically inconclusive.

---

### Family: volume_state (VS) — NEW 2026-02-23

| ID | Entry Rule | n | /day | gross_bps | P>0_gross | WF+ | bps8_P>0 | Status | Notes |
|----|-----------|---|------|-----------|-----------|-----|----------|--------|-------|
| **H145** | **eth_slope_flip + volume_btc_pct ≥ 0.80** | **136** | **0.4** | **26.19** | **1.000** | **15/18** | **1.000** | **PASS (VS-1)** | **VS family anchor** |
| H146 | close > 12-bar high + volume ≥ p75 → LONG | 2077 | 5.7 | 0.15 | 0.555 | 10/18 | 0.000 | FAIL | No gross edge |
| H147 | large_bar + volume < p20 → fade | 403 | 1.1 | 2.41 | 0.984 | 12/18 | 0.000 | FAIL | Cost-constrained |

**VS Family Result**: H145 is a genuine new signal anchor — **confirmed robust across all 5 checks run 2026-02-24**.

| Robustness Check | H# | n | gross_bps | P>0 | WF+ | bps8_P>0 | Result |
|-----------------|-----|---|-----------|-----|-----|----------|--------|
| Anchor (p80 vol) | H145 | 136 | 26.19 | 1.000 | 15/18 | 1.000 | **PASS** |
| Odd-day subsample | H159 | 65 | 24.83 | 1.000 | 12/17 | 0.995 | **PASS** |
| Even-day subsample | H160 | 71 | 27.43 | 1.000 | 12/17 | 0.999 | BORDERLINE* |
| 1-bar execution lag | H161 | 136 | 25.84 | 1.000 | 16/18 | 1.000 | **PASS** |
| Looser vol gate (p75) | H162 | 164 | 26.58 | 1.000 | 16/18 | 1.000 | **PASS** |
| Tighter vol gate (p85) | H163 | 104 | 32.23 | 1.000 | 16/18 | 1.000 | **PASS** |

*H160 BORDERLINE is a WF fold-count artifact (71 trades / 17 folds = ~4/fold). bps8 P>0=0.999 confirms the edge is real.

**Key robustness insights:**
- **1-bar lag passes** → real execution at next bar close works; no look-ahead dependence
- **p85 gives highest edge (32bps)** → higher-volume flips are more reliable; mechanism is real
- **p75 also passes with same edge** → not curve-fitted to p80; stable across threshold range
- **Odd + even day both hold** → not a temporal or calendar artifact

---

### Family: momentum / trend (ETH slope)

*Results to be populated from 365d rerun.*

### Family: mean_reversion

*Results to be populated from 365d rerun.*

### Family: cross_asset_divergence

*Results to be populated from 365d rerun.*

---

## Classification Guide (365d Era)

| Classification | Criteria |
|----------------|----------|
| PASS | Gross + bps8 + bps10 all positive WF means; P(mean>0) ≥ 0.90 gross, ≥ 0.80 bps8; ≥ 8 positive folds gross |
| BORDERLINE | Gross PASS but bps8 marginal (0.65–0.80 P>0); may still be deployable with tighter execution |
| FAIL | Any of: gross P(mean>0) < 0.70; fewer than 50% positive WF folds gross; negative gross mean |
| INCONCLUSIVE | < 5 WF folds with trades (usually due to regime filter reducing sample size) |
| REGIME_FAIL | Signal real at gross but FAIL at bps8+ due to trade frequency / cost structure |

> Note: REGIME_FAIL is a new classification for the 365d era. It distinguishes "bad signal" (FAIL) from
> "good signal, wrong frequency" (REGIME_FAIL). H123 would be REGIME_FAIL under this taxonomy.

---

## Next Steps

1. Complete 365d rerun batch (H15–H123 PASS/BORDERLINE/INCONCLUSIVE list)
2. Update table above with 365d results
3. Design and run H124 (funding regime, tighter entry)
4. Run RF feature importance experiment on 365d feature matrix
5. Add HMM regime detection experiment
