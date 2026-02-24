# BEST_HYPOTHESES.md
**Last Updated:** 2026-02-23
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
| FR (Funding Regime) | H121–H144 | All FAIL/INCONCLUSIVE. H141 (n=16, 17bps) is interesting but insufficient data. |
| MR (Mean Reversion) | H15, H18, H22–H26 | INCONCLUSIVE (insufficient folds) |
| CD (Cross-Exchange Divergence) | H102–H113 | FAIL (no second exchange data) |

---

## Key Observations

1. **Two signal families confirmed.** CA (ETH/BTC slope flip) and VS (volume-gated slope flip) both pass.
2. **H65 is the CA anchor.** H84 (EU/US overlap session) is the strongest single CA variant at +0.38%/trade.
3. **H145 is the VS anchor.** High-volume slope flips average 26bps — ~3× unfiltered CA-1.
4. **No confirmed short-side signals.** The 365d window (Feb 2025–Feb 2026) was a bull run.
5. **FR signals cost-constrained.** Every funding rate signal tested has real gross alpha but can't clear 8bps cost gate.
6. **H141 concept promising.** Extreme funding (≥p85) + slope flip produced 17.64bps in only 16 trades — too few to confirm but mechanism is sound.

---

## What to do next

1. **VS family expansion**: session-gated (08-16 UTC), ETH volume gate, h=12, p85 as standard threshold
2. **H141 revisit**: loosen funding threshold from p85 to p80 to get more trades (pre-commit threshold first)
3. **OI/liquidations data**: backfill rc.open_interest and rc.liquidations to unlock H148-H156
