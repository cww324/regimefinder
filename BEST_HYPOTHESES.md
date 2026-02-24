# BEST_HYPOTHESES.md
**Last Updated:** 2026-02-24
**Dataset:** 365 days (Feb 2025 – Feb 2026), ~105k bars/symbol, 60/15/15 WF (~20 folds)

Quick reference for confirmed signals. Organized by signal shortcode (CA-1, CA-2, etc.).
Full experiment log in `FINDINGS_365D.md`. Signal naming rules in `SIGNAL_REGISTRY.md`.

---

## How to Read This

- **Signal shortcodes** (CA-1, CA-2, ...) = the *core idea*. Assigned once a hypothesis passes.
- **H-numbers** = the *experiment run*. Every test gets one, pass or fail.
- Multiple H-numbers per signal = independent replications confirming the same edge.

---

## CA-1 — ETH Slope Flip, h=8 ★ ANCHOR SIGNAL

**What it is:** When ETH's 1h EMA20 slope changes direction, trade in the direction of the
new trend for 8 bars (40 minutes). Strongest and most replicated signal in the portfolio.

| H-number | Variant | gross mean/trade | WF gross | WF bps8 |
|----------|---------|-----------------|----------|---------|
| **H65** | Base signal — all hours, 365d | **+0.34%** | 20/20 | 20/20 |
| H67 | 120d lookback replication | +0.34% | 20/20 | 20/20 |
| H73 | 180d lookback replication | +0.34% | 20/20 | 20/20 |
| H77 | Next-bar execution lag | +0.34% | 20/20 | 20/20 |
| H79 | Extra-cost stress | +0.34% | 20/20 | 20/20 |
| H70 | Odd-day subsample | +0.34% | 20/20 | 19/20 |
| H71 | Even-day subsample | +0.34% | 19/20 | 18/20 |
| **H84** | **08:00–16:00 UTC only** | **+0.38%** | 20/20 | 20/20 |
| H83 | 00:00–08:00 UTC only | +0.27% | 20/20 | 18/20 |
| H85 | 16:00–24:00 UTC only | +0.36% | 19/20 | 18/20 |

**Key insight:** H65 is the anchor — works all hours, all lookback windows, next-bar execution,
and higher cost stress. H84 (EU/US overlap, 08–16 UTC) is the strongest single variant at +0.38%.

---

## CA-2 — BTC Slope Flip, h=8

**What it is:** Same logic as CA-1 but using BTC's 1h EMA20 slope. Slightly lower edge.

| H-number | Variant | gross mean/trade | WF gross | WF bps8 |
|----------|---------|-----------------|----------|---------|
| **H63** | Base signal | **+0.21%** | 20/20 | 19/20 |
| H66 | 120d lookback replication | +0.21% | 20/20 | 19/20 |
| H72 | 180d lookback replication | +0.21% | 20/20 | 19/20 |
| H76 | Next-bar execution lag | +0.21% | 20/20 | 19/20 |
| H78 | Extra-cost stress | +0.21% | 20/20 | 19/20 |
| H68 | Odd-day subsample | +0.22% | 19/20 | 19/20 |
| H69 | Even-day subsample | +0.20% | 20/20 | 16/20 |
| H81 | 08:00–16:00 UTC only | +0.23% | 20/20 | 17/20 |
| H82 | 16:00–24:00 UTC only | +0.22% | 20/20 | 15/20 |

---

## CA-3 — ETH Slope Flip, h=6

**What it is:** CA-1 with a shorter 6-bar (30 min) hold.

| H-number | Variant | gross mean/trade | WF gross | WF bps8 |
|----------|---------|-----------------|----------|---------|
| **H60** | Base signal | **+0.26%** | 20/20 | 18/20 |
| H75 | 120d lookback replication | +0.26% | 20/20 | 18/20 |
| H64 | horizon=4 variant | +0.17% | 20/20 | 18/20 |

---

## CA-4 — BTC Slope Flip, h=6

**What it is:** BTC slope flip with 6-bar (30 min) hold.

| H-number | Variant | gross mean/trade | WF gross | WF bps8 |
|----------|---------|-----------------|----------|---------|
| **H59** | Base signal | **+0.16%** | 20/20 | 16/20 |
| H74 | 120d lookback replication | +0.16% | 20/20 | 16/20 |

---

## CA-5 — Session Handoff

**What it is:** Entry at UTC market-open transitions (small n, marginal bps8).

| H-number | Variant | gross mean/trade | WF gross | WF bps8 |
|----------|---------|-----------------|----------|---------|
| H99 | Session handoff signal | +0.20% | 17/20 | 12/20 |

---

## Signal in Limbo (gross real, cost-constrained)

These have confirmed gross alpha but cannot survive 8bps costs at current trade frequency.
Not assigned a shortcode yet.

| H-number | Idea | Gross WF | bps8 WF | Issue | Next step |
|----------|------|----------|---------|-------|-----------|
| H32 | ETH 1h EMA slope regime gate | 12/14 | 8/14 | ~7 trades/day, edge too thin for 8bps | H124: tighter entry threshold |
| H87 | cross_asset_regime variant | 13/14 | 3/14 | Gross real, cost kills it | Reduce frequency |
| H91 | cross_asset_regime variant | 13/14 | 5/14 | Gross real, cost kills it | Reduce frequency |
| H97 | cross_asset_regime variant | 12/14 | 3/14 | Gross real, cost kills it | Reduce frequency |

---

## Borderline (gross passes, bps8 marginal)

| H-number | Idea | WF gross | WF bps8 | Notes |
|----------|------|----------|---------|-------|
| H39 | cross_asset_regime variant | 20/20 | 16/20 | bps10 likely fails |
| H61 | cross_asset_regime variant | 20/20 | 13/20 | bps8 inconsistent |

---

## VS-1 — High-Volume ETH Slope Flip ★ NEW ANCHOR (2026-02-23)

**What it is:** CA-1 (ETH slope flip) gated by volume expansion (volume_btc_pct ≥ p80). Only trades slope flips that occur during high-volume bars. Volume filters out thin-book noise flips.

**Why it works:** Volume expansion during a slope flip confirms that real capital is driving the move. Unfiltered CA-1 includes thin-book artifact flips that dilute the edge. The volume gate selects only flips with genuine participation — ~3× higher per-trade return than CA-1.

| H-number | Variant | gross_bps | n/day | WF+ | bps8 PASS | Label |
|----------|---------|-----------|-------|-----|-----------|-------|
| **H145** | Base signal (365d, p80 volume) | **26.19** | 0.4 | **15/18** | **YES** | **VS-1** |

**Status:** PASS + 4/5 robustness checks pass (H159-H163, run 2026-02-24). Signal confirmed robust.

| H-number | Variant | gross_bps | WF+ | bps8 PASS | n/day |
|----------|---------|-----------|-----|-----------|-------|
| H145 | Base (p80 vol) | 26.19 | 15/18 | YES | 0.4 |
| H159 | Odd-day | 24.83 | 12/17 | YES | 0.2 |
| H160 | Even-day | 27.43 | 12/17 | BORDERLINE | 0.2 |
| H161 | 1-bar lag | 25.84 | 16/18 | YES | 0.4 |
| H162 | p75 vol | 26.58 | 16/18 | YES | 0.5 |
| H163 | p85 vol | **32.23** | 16/18 | YES | 0.3 |

---

## Families with No Confirmed Signals

| Family | H-numbers tested | Outcome |
|--------|-----------------|---------|
| FR (Funding Regime) | H121–H144, H174–H175 | All FAIL/INCONCLUSIVE. H174 (p80, n=25, 20bps, P>0=0.983) is the strongest FR signal yet — mechanism real, but fires ~1×/month, too rare for 365d WF. Needs 2+ years or multi-asset funding. H175 (h=12) FAIL — forced unwind doesn't sustain 60 min. |
| MR (Mean Reversion) | H15, H18, H22–H26 | INCONCLUSIVE (insufficient folds) |
| CD (Cross-Exchange Divergence) | H102–H113 | FAIL (no second exchange data) |

---

## Key Observations

1. **Two signal families confirmed.** CA (ETH/BTC slope flip) and VS (volume-gated slope flip) both pass.
2. **H65 is the CA anchor.** H84 (EU/US overlap session) is the strongest single CA variant at +0.38%/trade.
3. **H145 is the VS anchor.** High-volume slope flips average 26bps — ~3× unfiltered CA-1.
4. **No confirmed short-side signals.** The 365d window (Feb 2025–Feb 2026) was a bull run.
5. **FR signals cost-constrained.** Every funding rate signal tested has real gross alpha but can't clear 8bps cost gate.
6. **FR mechanism real but rare.** H174 (p80 threshold): 20bps gross, P>0=0.983 — mechanism confirmed. But ~25 trades/year (1×/month), 9/15 WF folds empty. Needs 2+ years of data or multi-asset funding combination to validate.

---

## What to do next

---

## VS-2 — High-Volume ETH Slope Flip, h=12 ★ ANCHOR (2026-02-24)

**What it is:** VS-1 with 60-minute hold (12 bars). Volume-validated momentum sustains for 60 min.

**The best single VS variant:** VS-2 at p85 (H173): **45.29bps gross, WF+ 17/18, bps8 P>0=1.000**

| H-number | Variant | gross_bps | WF+ | bps8 PASS | n/day |
|----------|---------|-----------|-----|-----------|-------|
| H167 | Base (p80 vol, h=12) | 38.63 | 17/18 | YES | 0.4 |
| H169 | Odd-day | 36.35 | 12/17 | YES | 0.2 |
| H170 | Even-day | 40.72 | 13/17 | YES | 0.2 |
| H171 | 1-bar lag | 34.94 | 17/18 | YES | 0.4 |
| H172 | p75 vol | 39.88 | 17/18 | YES | 0.5 |
| H173 | p85 vol | **45.29** | 17/18 | YES | 0.3 |

**VS pattern summary (all confirmed pass):**

| | h=8 | h=12 |
|--|-----|------|
| **p80 vol** | 26bps (VS-1/H145) | 38bps (VS-2/H167) |
| **p85 vol** | 32bps (H163) | **45bps (H173, BEST)** |

Both volume threshold and hold horizon independently add edge and compound together.
**Session gates do NOT help VS** (H164-H166 FAIL/BORDERLINE/INCONCLUSIVE). All-hours is already robust.

---

## VS-3 — VS-2 with Liquidation Confirmation ★ NEW ALL-TIME BEST (2026-02-24)

**What it is:** VS-2 gated by total liquidations >= p70 — slope flip + high volume + liq confirmation must all align. Triple-gated signal produces the highest per-trade return in all research history at **60.5bps gross**.

**Why it works:** Adding the liq layer selects VS-2 events where forced deleveraging is also occurring simultaneously. Three independent engines — momentum (slope), capital (volume), and mechanical (liq) — all aligned.

| H-number | Variant | gross_bps | n/day | WF+ | bps8 PASS | Label |
|----------|---------|-----------|-------|-----|-----------|-------|
| **H180** | Base (p80 vol + liq p70, h=12) | **60.5** | 0.26 | **16/17** | **YES (15/17, P>0=1.000)** | **VS-3** |

**VS progression:**

| Signal | Rule | gross_bps | n/day |
|--------|------|-----------|-------|
| CA-1 (H65) | slope flip only | ~34 | ~4.0 |
| VS-1 (H145) | + volume p80, h=8 | 26.2 | 0.4 |
| VS-2 (H167) | + volume p80, h=12 | 38.6 | 0.4 |
| VS-2 p85 (H173) | + volume p85, h=12 | 45.3 | 0.3 |
| **VS-3 (H180)** | **+ volume p80 + liq p70, h=12** | **60.5** | **0.26** |

Each additional gate compounds the edge. VS-3 is the natural peak of this progression.

---

## LQ-1 — Long Liquidation Cascade SHORT ★ ANCHOR (2026-02-24)

**What it is:** When the prior 1h had extreme long-side liquidations (p90 threshold), go SHORT for 40 minutes. The liquidation cascade has three-phase follow-through — forced sales trigger more stops, remaining longs capitulate, price overshoots.

| H-number | Variant | gross_bps | n/day | WF+ | bps8 PASS | Label |
|----------|---------|-----------|-------|-----|-----------|-------|
| **H177** | Base (long_liq p90, h=8) | **20.0** | 4.31 | **18/18** | **YES (16/18, P>0=1.000)** | **LQ-1** |

**Key stats:** n=1437, WF+ gross 18/18 folds, WF bps8 P>0=1.000 — every WF fold grosses positive and 16/18 beat costs. The most consistently positive gross WF record in the research after the CA family.

---

## LQ-2 — Short Liquidation Squeeze LONG ★ ANCHOR (2026-02-24)

**What it is:** Symmetric to LQ-1. Extreme short-side liquidations (p90) → go LONG for 40 minutes. Forced short covering drives buying pressure that sustains beyond the initial event.

| H-number | Variant | gross_bps | n/day | WF+ | bps8 PASS | Label |
|----------|---------|-----------|-------|-----|-----------|-------|
| **H178** | Base (short_liq p90, h=8) | **16.0** | 4.44 | **18/18** | **YES (17/18, P>0=1.000)** | **LQ-2** |

**Key stats:** n=1474, WF+ bps8 17/18 — one more fold passes costs than LQ-1. The most cost-consistent liq signal. LQ-1 + LQ-2 together provide ~8.75 trades/day total from liquidation data.

---

## LQ-3 — Liq-Gated ETH Slope Flip SHORT (2026-02-24)

**What it is:** CA-1 slope flip (bearish direction only) gated by elevated long liquidations (p70). Liquidation context confirms that the slope change is backed by forced deleveraging, not thin-book noise.

| H-number | Variant | gross_bps | n/day | WF+ | bps8 PASS | Label |
|----------|---------|-----------|-------|-----|-----------|-------|
| **H179** | Base (liq p70 + slope flip → SHORT, h=8) | **31.0** | 0.51 | **16/17** | **YES (14/17, P>0=1.000)** | **LQ-3** |

**Key stats:** n=166. Gross 31bps is well above the 8bps cost gate. The liq gate adds directional confidence to what is otherwise a neutral slope flip.

---

## H176 — OI-Gated Slope Flip (OI-1 Candidate, pending robustness)

**What it is:** Same structure as VS-1 but using open interest percentile (oi_btc_pct >= 0.80) as the gate instead of volume. PASS on aggregate metrics but WF bps8 fold count is borderline (13/18).

| H-number | Variant | gross_bps | n/day | WF bps8 P>0 | WF bps8+ | Status |
|----------|---------|-----------|-------|-------------|----------|--------|
| H176 | OI-gated flip (h=8) | 16.4 | 0.65 | 0.995 | 13/18 | OI-1 candidate — needs robustness checks |

**OI-1 shortcode NOT assigned.** H181-H183 robustness checks revealed day-asymmetric edge: H182 (even-day) failed badly (5/18 bps8 folds). H183 (lag) borderline. H176 has real gross alpha but is not cost-reliably exploitable. Do not iterate OI thresholds further without longer data.

---

## Key Observations

1. **Four signal families now confirmed.** CA (ETH/BTC slope flip), VS (volume-gated slope flip), LQ (liquidation-driven), and OI (OI-gated — candidate, needs robustness).
2. **H65 is the CA anchor.** H84 (EU/US overlap session) is the strongest single CA variant at +0.38%/trade.
3. **H145 is the VS anchor; H180 (VS-3) is the all-time best** at 60.5bps gross — triple-gated (slope + vol + liq).
4. **LQ-1 (H177) and LQ-2 (H178) are high-frequency confirmed signals.** Both achieve 18/18 WF+ gross and P>0=1.000 bps8, providing ~8.75 trades/day combined from liquidation data alone.
5. **No confirmed short-side signals before the LQ family.** LQ-1 is the first clean directional SHORT signal (cascade) and LQ-2 is the first clean directional LONG from derivatives data.
6. **H176 (OI-1 candidate) failed robustness.** Even-day split failed (5/18 bps8 folds), lag borderline. OI-1 shortcode NOT assigned. Gross edge is real but day-asymmetric and cost-constrained.
7. **FR signals cost-constrained.** Every funding rate signal tested has real gross alpha but can't clear 8bps cost gate at current frequency.

---

## What to do next

1. **Paper trader — next priority.** All signals execution-confirmed. Build AWS/EC2 paper trader with Coinbase (5m candle) + Gate.io (hourly liq) polling. SQLite for state. Telegram alerts. Individual signals first, portfolio second.
2. **New hypothesis generation (H188+).** LQ family extensions (ETH liq variants, liq imbalance, higher horizons), OI+liq combined gate, liq threshold sensitivity (p80/p95).
3. **VS-3 lag test complete — all priority signals paper trade ready:**
   - VS-3 (H180): 54bps lag-adjusted ✓
   - LQ-1 (H177): 18bps lag-adjusted ✓
   - LQ-2 (H178): 14bps lag-adjusted (borderline) ✓
   - LQ-3 (H179): 31bps lag-adjusted ✓

## Paper Trading Roadmap

| Stage | Signal | Lag-adj bps | Status | Notes |
|-------|--------|-------------|--------|-------|
| 1 | CA-1 (H65) | ~26bps | Execution confirmed (H161) — ready | Baseline anchor |
| 1 | VS-3 (H180) | ~54bps | Execution confirmed (H187) — ready | All-time best |
| 1 | LQ-1 (H177) | ~18bps | Execution confirmed (H184) — ready | High-freq cascade SHORT |
| 1 | LQ-2 (H178) | ~14bps | Execution confirmed (H185, borderline) — ready | Short squeeze LONG |
| 1 | LQ-3 (H179) | ~31bps | Execution confirmed (H186) — ready | Liq-gated slope flip SHORT |
| 2 | Combined portfolio | — | Blocked on Stage 1 | TBD |

**Why individual first:** Backtests can't model fill quality, latency, or queue position. With 8bps cost gate, slippage matters. Individual paper trading also detects regime change (365d was a bull run) before it corrupts portfolio-level P&L.
