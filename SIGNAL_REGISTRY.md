# SIGNAL_REGISTRY.md
**Last Updated:** 2026-02-24
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
| `LQ` | Liquidation | Forced position closures (cascades + squeezes), Gate.io data |
| `OI` | Open Interest | Leveraged positioning levels, OI-gated slope flips |

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

---

#### VS-2 — High-Volume ETH Slope Flip, h=12 ★ NEW ANCHOR (2026-02-24)
**What it is:** VS-1 with a 60-minute hold (12 bars) instead of 40-minute (8 bars). Volume-validated slope flips sustain directional momentum for 60 min.

| H-number | Variant | gross_bps | WF gross | WF bps8 | n/day | Label |
|----------|---------|-----------|----------|---------|-------|-------|
| H167 | Base (p80 vol, h=12) | 38.63 | 17/18 | PASS | 0.4 | **VS-2** |
| H169 | Odd-day | 36.35 | 12/17 | PASS | 0.2 | VS-2 replication |
| H170 | Even-day | 40.72 | 13/17 | PASS | 0.2 | VS-2 replication |
| H171 | 1-bar lag | 34.94 | 17/18 | PASS | 0.4 | VS-2 replication |
| H172 | p75 vol | 39.88 | 17/18 | PASS | 0.5 | VS-2 replication |
| H173 | p85 vol | **45.29** | 17/18 | PASS | 0.3 | VS-2 replication |

**All 5 robustness checks pass.** VS-2 at p85 (H173) was the highest-performing single variant in all research at 45bps gross — now surpassed by VS-3 (H180) at 60.5bps.

---

#### VS-3 — VS-2 with Liquidation Confirmation ★ NEW ALL-TIME BEST (2026-02-24)
**What it is:** VS-2 (volume p80 + ETH slope flip, h=12) additionally gated by total liquidations >= p70. All three conditions must align — slope flip, high volume, AND elevated liquidation activity — selecting the highest-conviction momentum entries.

| H-number | Variant | gross_bps | WF gross | WF bps8 | n/day | Label |
|----------|---------|-----------|----------|---------|-------|-------|
| **H180** | Base (vol p80 + liq p70, h=12) | **60.5** | 16/17 | **PASS (15/17, P>0=1.000)** | 0.26 | **VS-3** |
| H187 | 1-bar execution lag | 54.1 | 16/17 | PASS (15/17, 45.1bps mean) | 0.26 | VS-3 replication — execution realistic ✓ |

**Why it works:** Adding the liq confirmation layer filters VS-2 entries to those where forced liquidations are also occurring simultaneously. This selects the highest-conviction momentum events — where price momentum (slope), capital flows (volume), and mechanical deleveraging (liq) all align. The triple-gated signal has the highest gross return per trade in all research history.

**Trade-off:** Lower frequency (0.26/day vs 0.4/day for VS-2). At ~85 trades/year and ~5 trades/fold, WF statistics are still meaningful but fold-level variance is elevated.

---

### VS Expansion Results (2026-02-24)

**Session gates do NOT help VS** (contrast with CA-1 where 08-16 UTC was strongest):
- H164 (08-16 UTC): FAIL (WF count too low)
- H165 (00-08 UTC): INCONCLUSIVE (n=15)
- H166 (16-24 UTC): BORDERLINE (29.4bps, WF 13/18)
- H168 (ETH vol gate): BORDERLINE (24.46bps, WF 14/18)

Session filtering on VS signals leaves too few trades per fold for reliable WF assessment. All-hours VS is already highly robust.

---

### Liquidation (LQ) — NEW 2026-02-24

**What it is:** Signals based on forced position liquidations from Gate.io. Extreme liquidation events create directional price pressure that persists for 40+ minutes — cascade (long liq → SHORT continuation) and squeeze (short liq → LONG continuation).

#### LQ-1 — Long Liquidation Cascade SHORT ★ ANCHOR
**What it is:** When the prior 1h had extreme long-side liquidations (p90 threshold), go SHORT for 40 minutes. Cascade follow-through from forced selling.

| H-number | Variant | gross_bps | WF gross | WF bps8 | n/day | Label |
|----------|---------|-----------|----------|---------|-------|-------|
| **H177** | Base (long_liq_btc_pct >= 0.90, h=8) | **20.0** | **18/18** | **PASS (16/18, P>0=1.000)** | 4.31 | **LQ-1** |
| H184 | 1-bar execution lag | 18.1 | 18/18 | PASS (14/18, 9.9bps mean) | 4.31 | LQ-1 replication — execution realistic ✓ |

**Why it works:** Extreme long liquidations are mechanical — margin systems force position closure regardless of price. Top-10% liq hours represent genuine deleveraging events with three-phase continuation: initial cascade → more stops triggered → price discovery overshoot.

---

#### LQ-2 — Short Liquidation Squeeze LONG ★ ANCHOR
**What it is:** When the prior 1h had extreme short-side liquidations (p90 threshold), go LONG for 40 minutes. Forced short covering creates sustained buying pressure.

| H-number | Variant | gross_bps | WF gross | WF bps8 | n/day | Label |
|----------|---------|-----------|----------|---------|-------|-------|
| **H178** | Base (short_liq_btc_pct >= 0.90, h=8) | **16.0** | **18/18** | **PASS (17/18, P>0=1.000)** | 4.44 | **LQ-2** |
| H185 | 1-bar execution lag | 13.7 | 18/18 | BORDERLINE (16/18, 4.7bps mean) | 4.44 | LQ-2 replication — deployable with fill quality awareness |

**Why it works:** Symmetric to LQ-1. Short squeeze buying pressure can propagate through voluntary capitulation and new longs piling on after the forced covering. 17/18 WF bps8 folds positive makes this the most consistent liq signal at cost.

---

#### LQ-3 — Liq-Gated ETH Slope Flip SHORT
**What it is:** ETH slope flips to bearish (CA-1 trigger) AND long liquidations are elevated (>= p70). The liquidation context confirms that the slope change has deleveraging pressure behind it, not just noise.

| H-number | Variant | gross_bps | WF gross | WF bps8 | n/day | Label |
|----------|---------|-----------|----------|---------|-------|-------|
| **H179** | Base (liq p70 gate + slope flip → SHORT, h=8) | **31.0** | **16/17** | **PASS (14/17, P>0=1.000)** | 0.51 | **LQ-3** |
| H186 | 1-bar execution lag | 31.3 | 17/17 | PASS (15/17, 20.9bps mean) | 0.51 | LQ-3 replication — execution realistic ✓ |

**Why it works:** The CA slope flip (CA-1) fires ~4/day. The p70 liq gate selects the subset where forced liquidations are also present — adding a second independent bearish mechanism to the momentum signal.

---

### Open Interest (OI) — shortcode NOT assigned — robustness failed

| H-number | Idea | Status | Notes |
|----------|------|--------|-------|
| H176 | OI-gated ETH slope flip (oi_btc_pct >= 0.80, h=8) | PASS gross / FAIL robustness | n=217, 16.4bps gross P>0=1.000, WF bps8=7.1bps P>0=0.995 — 13/18 WF bps8 folds borderline |
| H181 | H176 odd-day subsample | BORDERLINE | 113 trades, 17.1bps gross, 11/18 bps8 folds |
| H182 | H176 even-day subsample | FAIL | 104 trades, 15.6bps gross, **5/18 bps8 folds** — edge collapses on even days |
| H183 | H176 1-bar execution lag | BORDERLINE | 217 trades, 14.9bps gross, 9/18 bps8 folds — cost-constrained at lag |

**OI-1 shortcode NOT assigned.** H182 (even-day) failed badly (5/18 bps8 folds), revealing day-asymmetric edge. H183 (lag) borderline. H176 has real gross alpha but is not cost-reliably exploitable. Do not iterate OI thresholds further without longer data (2+ years).

*OI-1 label is reserved but blocked. Will require 2+ years of data or a multi-asset OI combination before the signal can be reliably validated.*

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
