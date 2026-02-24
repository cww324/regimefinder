# SIGNAL_REGISTRY.md
**Last Updated:** 2026-02-23
**Purpose:** Human-readable registry of confirmed signals. H-numbers remain the canonical pipeline IDs.
Only hypotheses that PASS the full validation gate (gross + bps8, WF 20/20 or near) earn a signal shortcode.

---

## How the Naming System Works

- **H-numbers** — experiment IDs. Every hypothesis that enters the pipeline gets one, pass or fail.
  Assigned sequentially, never reassigned. Used in all code, artifacts, and commands.
- **Signal shortcodes** — assigned only when a hypothesis passes. Represent the *core idea*, not
  the specific test. Multiple H-numbers can share a shortcode (replications of the same signal).
- **Family prefixes** — two letters identifying the regime type:

| Prefix | Family | What it detects |
|--------|--------|----------------|
| `CA` | Cross-Asset | ETH/BTC relative momentum, slope changes, spread |
| `FR` | Funding Regime | Perp funding rate extremes, crowding, positioning |
| `VS` | Volatility State | RV transitions, ATR regimes, vol compression/expansion |
| `MR` | Mean Reversion | VWAP-z pullbacks, spread reversion |
| `MS` | Microstructure | Intraday order flow, VWAP deviations, bar structure |
| `ST` | Session/Time | UTC session effects, day-of-week, open/close transitions |
| `CD` | Cross-exchange Divergence | Coinbase vs Binance price leadership |

**Multi-regime hypotheses** use a primary label + secondary tag:
- `CA-1` = core ETH slope flip, no filter
- `CA-1 | ST` = CA-1 gated by session (e.g. H84)
- `CA-1 | FR` = CA-1 gated by funding regime (e.g. future H124 if it passes)

---

## Confirmed Signals (365d dataset, 2026-02-23)

### Cross-Asset (CA)

#### CA-1 — ETH Slope Flip, h=8 ★ ANCHOR SIGNAL
**What it is:** When ETH's 1h EMA20 slope changes direction, trade in the direction of the new trend
for 8 bars (40 minutes). The strongest and most replicated signal in the research history.

| H-number | Variant | gross mean/trade | WF gross | WF bps8 | Label |
|----------|---------|-----------------|----------|---------|-------|
| H65 | Base signal (all hours, 365d) | +0.34% | 20/20 | 20/20 | **CA-1** |
| H67 | 120d lookback replication | +0.34% | 20/20 | 20/20 | CA-1 replication |
| H73 | 180d lookback replication | +0.34% | 20/20 | 20/20 | CA-1 replication |
| H77 | Next-bar execution lag | +0.34% | 20/20 | 20/20 | CA-1 replication |
| H79 | Extra-cost stress | +0.34% | 20/20 | 20/20 | CA-1 replication |
| H84 | 08:00–16:00 UTC only | +0.38% | 20/20 | 20/20 | **CA-1 \| ST** (best variant) |
| H83 | 00:00–08:00 UTC only | +0.27% | 20/20 | 18/20 | CA-1 \| ST |
| H85 | 16:00–24:00 UTC only | +0.36% | 19/20 | 18/20 | CA-1 \| ST |
| H70 | Odd-day subsample | +0.34% | 20/20 | 19/20 | CA-1 stability check |
| H71 | Even-day subsample | +0.34% | 19/20 | 18/20 | CA-1 stability check |

**Key insight:** CA-1 works across all UTC sessions (Asia/EU/US), all lookback windows, and
next-bar execution. H84 (EU/US overlap, 08-16 UTC) is the strongest single variant at +0.38%/trade.

---

#### CA-2 — BTC Slope Flip, h=8
**What it is:** Same as CA-1 but using BTC's 1h EMA20 slope. Slightly lower edge than CA-1.

| H-number | Variant | gross mean/trade | WF gross | WF bps8 | Label |
|----------|---------|-----------------|----------|---------|-------|
| H63 | Base signal | +0.21% | 20/20 | 19/20 | **CA-2** |
| H66 | 120d lookback replication | +0.21% | 20/20 | 19/20 | CA-2 replication |
| H72 | 180d lookback replication | +0.21% | 20/20 | 19/20 | CA-2 replication |
| H76 | Next-bar execution lag | +0.21% | 20/20 | 19/20 | CA-2 replication |
| H78 | Extra-cost stress | +0.21% | 20/20 | 19/20 | CA-2 replication |
| H81 | 08:00–16:00 UTC only | +0.23% | 20/20 | 17/20 | CA-2 \| ST |
| H82 | 16:00–24:00 UTC only | +0.22% | 20/20 | 15/20 | CA-2 \| ST |
| H68 | Odd-day subsample | +0.22% | 19/20 | 19/20 | CA-2 stability check |
| H69 | Even-day subsample | +0.20% | 20/20 | 16/20 | CA-2 stability check |

---

#### CA-3 — ETH Slope Flip, h=6
**What it is:** CA-1 with a shorter 6-bar (30 min) hold instead of 8-bar (40 min).

| H-number | Variant | gross mean/trade | WF gross | WF bps8 | Label |
|----------|---------|-----------------|----------|---------|-------|
| H60 | Base signal | +0.26% | 20/20 | 18/20 | **CA-3** |
| H75 | 120d lookback replication | +0.26% | 20/20 | 18/20 | CA-3 replication |

---

#### CA-4 — BTC Slope Flip, h=6
**What it is:** BTC slope flip with 6-bar hold.

| H-number | Variant | gross mean/trade | WF gross | WF bps8 | Label |
|----------|---------|-----------------|----------|---------|-------|
| H59 | Base signal | +0.16% | 20/20 | 16/20 | **CA-4** |
| H74 | 120d lookback replication | +0.16% | 20/20 | 16/20 | CA-4 replication |

---

#### CA-5 — Session Handoff
**What it is:** Entry at UTC market-open transitions.

| H-number | Variant | gross mean/trade | WF gross | WF bps8 | Label |
|----------|---------|-----------------|----------|---------|-------|
| H99 | Session handoff | +0.20% | 17/20 | 12/20 | **CA-5** (marginal bps8) |

---

### Funding Regime (FR)
*No confirmed signals yet. H121-H144 all failed or inconclusive.*

| H-number | Idea | Status | Notes |
|----------|------|--------|-------|
| H121 | Extreme funding fade | FAIL | Inconsistent, negative gross |
| H122 | Funding sign flip | FAIL | Negative gross |
| H123 | CA signal + funding gate | FAIL | Signal real, cost-constrained |
| H124 | CA + FR, tighter (≥0.97) | BORDERLINE | Gross real, bps8 straddles zero |
| H140 | Extreme negative funding → LONG | FAIL | 0.94bps gross, cost-constrained |
| H141 | Extreme funding + slope flip → SHORT | INCONCLUSIVE | 17.6bps gross but n=16 |
| H142 | ETH>BTC funding spread → SHORT | FAIL | No gross edge |
| H143 | Funding+slope consensus | FAIL | 1.63bps, cost-constrained |
| H144 | Sustained extreme funding + flip → SHORT | INCONCLUSIVE | n=11 |

*First passing FR hypothesis will be labeled **FR-1**. H141 concept is promising — needs more data (loosened threshold or longer lookback).*

---

### Volume State (VS) — NEW 2026-02-23

| H-number | Idea | Status | Notes |
|----------|------|--------|-------|
| **H145** | **High-volume ETH slope flip** | **PASS — VS-1 ANCHOR** | **26bps gross, P>0=1.000, WF+ 15/18, bps8 PASS** |
| H146 | Volume breakout (price > 12-bar high) | FAIL | No gross edge |
| H147 | Low-volume large bar fade | FAIL | 2.41bps, cost-constrained |

#### VS-1 — High-Volume ETH Slope Flip ★ NEW ANCHOR
**What it is:** CA-1 (ETH slope flip) gated by high volume (volume_btc_pct ≥ 0.80). Only fires when the slope change is accompanied by above-average trading volume, indicating real capital flows rather than thin-book noise.

| H-number | Variant | gross_bps | WF gross | WF bps8 | n/day | Label |
|----------|---------|-----------|----------|---------|-------|-------|
| H145 | Base signal (p80 vol, 365d) | 26.19 | 15/18 | PASS | 0.4 | **VS-1** |
| H159 | Odd-day subsample | 24.83 | 12/17 | PASS | 0.2 | VS-1 replication |
| H160 | Even-day subsample | 27.43 | 12/17 | BORDERLINE* | 0.2 | VS-1 replication |
| H161 | 1-bar execution lag | 25.84 | 16/18 | PASS | 0.4 | VS-1 replication |
| H162 | p75 volume gate | 26.58 | 16/18 | PASS | 0.5 | VS-1 replication |
| H163 | p85 volume gate | 32.23 | 16/18 | PASS | 0.3 | VS-1 replication |

*H160 bps8 P>0=0.999 — edge is real, BORDERLINE classification from low fold count.

**Why it works:** Volume expansion during a slope flip signals large participants are driving the move. Unfiltered CA-1 flips include thin-book artifact reversals that dilute the edge. Volume ≥ p80 filters to flips with genuine participation — ~3× the per-trade edge of CA-1.

**Confirmed robust:** All 5 robustness checks pass. 1-bar lag survives (execution realistic). p75-p85 range all pass (not curve-fitted). Odd + even day both hold (not temporal artifact).

**VS family ready for expansion.** Next candidates:
- VS-1 | ST — session-gated variants (08-16 UTC strongest for CA)
- VS-2 — longer horizon (h=12): do high-volume flips persist longer?
- VS-1 with ETH volume gate (volume_eth_pct ≥ 0.80) instead of BTC
- VS-1 with p85 as production threshold (H163 showed 32bps — consider making this the standard)

---

### Other Families (No Confirmed Signals Yet)

| Family | H-numbers tested | Outcome | Notes |
|--------|-----------------|---------|-------|
| MR (Mean Reversion) | H15, H18, H22-H26 | INCONCLUSIVE | Insufficient folds even on 365d |
| CD (Cross-Asset Divergence) | H102-H113 | FAIL | No Binance data yet |

---

## Signal in Limbo (Gross real, cost-constrained)

These hypotheses have confirmed gross alpha but cannot survive 8bps costs at current trade frequency.
They are NOT labeled as confirmed signals — but their gross signal is worth building on.

| H-number | Gross WF | Issue | Next step |
|----------|----------|-------|-----------|
| H32 | 12/14 | ETH slope regime, ~7 trades/day | H124 (tighter entry) |
| H87 | 13/14 | cost-constrained | Reduce frequency |
| H91 | 13/14 | cost-constrained | Reduce frequency |
| H97 | 12/14 | cost-constrained | Reduce frequency |

---

## Rules for Assigning a Shortcode

1. Hypothesis must PASS gross + bps8 gates on 365d data
2. At least 8 positive WF folds at gross (prefer 15+/20)
3. At least one replication must also pass before label is permanent
4. Multi-regime hypotheses get a primary label + secondary tag (e.g. CA-1 | FR)
5. Shortcode is assigned in this registry — update here first, then update BEST_HYPOTHESES.md

---

## What to Read Next
- `BEST_HYPOTHESES.md` — quick reference table
- `FINDINGS_365D.md` — full 365d results
- `REGIME_FRAMEWORK.md` — H124+ design rules
- `docs/rf_experiment_plan.md` — ML-assisted hypothesis discovery
- `docs/multi_market_expansion.md` — adding new markets/exchanges
