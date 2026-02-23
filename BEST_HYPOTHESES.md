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

## Families with No Confirmed Signals

| Family | H-numbers tested | Outcome |
|--------|-----------------|---------|
| FR (Funding Regime) | H121–H124 | H121–H123 FAIL; H124 pending |
| VS (Volatility State) | H101–H110 | All FAIL (tested on 180d, worth 365d revisit) |
| MR (Mean Reversion) | H15, H18, H22–H26 | INCONCLUSIVE (insufficient folds) |
| CD (Cross-Exchange Divergence) | H102–H113 | FAIL (no second exchange data) |

---

## Key Observations

1. **One signal family dominates.** All 25 confirmed PASSes are `cross_asset_regime` — ETH/BTC slope flip trades.
2. **H65 is the anchor.** H84 has the highest per-trade return (+0.38%) but is session-restricted. H65 runs all hours and survives every replication test.
3. **Replication is unusually solid.** CA-1 has 9 independent replications. CA-2 has 8. This level of robustness is rare.
4. **No confirmed short-side signals.** All 25 PASSes are long-biased. The 365d window (Feb 2025–Feb 2026) was a bull run.
5. **Next regime: RF discovery.** Use `docs/rf_experiment_plan.md` to systematically explore non-CA signal families.

---

## What to do next

- Run **H124**: CA+FR with tighter spread threshold (≥0.97) — target 1-2 trades/day
- Run **RF experiment**: `docs/rf_experiment_plan.md` — let XGBoost find what we haven't tested
- Consider **portfolio construction** combining H65 (all-hours) + H84 (session-filtered)
- See `docs/multi_market_expansion.md` to add SOL-USD or a second exchange
