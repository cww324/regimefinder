# SIGNAL_REGISTRY.md
**Last Updated:** 2026-03-11
**Purpose:** Human-readable registry of confirmed signals. H-numbers remain the canonical pipeline IDs.
Only hypotheses that PASS the full validation gate (gross + bps8, WF 20/20 or near) earn a signal shortcode.

---

## Next Available Shortcodes (authoritative — update when a new shortcode is assigned)

| Family | Last assigned | **Next** |
|--------|--------------|---------|
| CA (Cross-Asset) | CA-5 (H99) | **CA-6** |
| VS (Volatility State) | VS-3 (H180) | **VS-4** |
| LQ (Liquidation) | LQ-6 (H247/H249) | **LQ-7** |
| OV (OI Velocity) | OV-1 (H252/H259) | **OV-2** |
| CD (Correlation Decoupling) | CD-1 (H257/H260) | **CD-2** |
| FR (Funding Regime) | — | **FR-1** |
| MR (Mean Reversion) | — | **MR-1** |
| OI (Open Interest) | blocked (see H176) | **OI-1** (reserved, blocked) |
| MS (Microstructure) | — | **MS-1** |
| ST (Session/Time) | — | **ST-1** |

**Rule:** When a new hypothesis passes and earns a shortcode, update this table first, then add the signal block below.

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
| `LQ` | Liquidation | Forced position closures (cascades + squeezes), Gate.io data |
| `OI` | Open Interest | Leveraged positioning levels, OI-gated slope flips |
| `OV` | OI Velocity | OI acceleration (second derivative) as momentum gate |
| `CD` | Correlation Decoupling | BTC-ETH correlation regime shifts as signal qualifier |

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

**Direction validation (2026-03-11):** H215 (LONG only, 8.2bps WF bps8, 15/19) and H216 (SHORT only, 8.3bps, 15/19) both PASS independently. CA-1 is direction-symmetric — no bull-market bias. Deploy both directions.

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

**Direction validation (2026-03-11):** H217 (LONG only, 31.3bps WF bps8, 17/17) and H218 (SHORT only, 21.8bps, 13/17) both PASS independently. LONG has higher edge but SHORT is independently solid. Deploy both directions.

---

#### VS-3 — VS-2 with Liquidation Confirmation ★ NEW ALL-TIME BEST (2026-02-24)
**What it is:** VS-2 (volume p80 + ETH slope flip, h=12) additionally gated by total liquidations >= p70. All three conditions must align — slope flip, high volume, AND elevated liquidation activity — selecting the highest-conviction momentum entries.

| H-number | Variant | gross_bps | WF gross | WF bps8 | n/day | Label |
|----------|---------|-----------|----------|---------|-------|-------|
| **H180** | Base (vol p80 + liq p70, h=12) | **60.5** | 16/17 | **PASS (15/17, P>0=1.000)** | 0.26 | **VS-3** |
| H187 | 1-bar execution lag | 54.1 | 16/17 | PASS (15/17, 45.1bps mean) | 0.26 | VS-3 replication — execution realistic ✓ |

**Why it works:** Adding the liq confirmation layer filters VS-2 entries to those where forced liquidations are also occurring simultaneously. This selects the highest-conviction momentum events — where price momentum (slope), capital flows (volume), and mechanical deleveraging (liq) all align. The triple-gated signal has the highest gross return per trade in all research history.

**Trade-off:** Lower frequency (0.26/day vs 0.4/day for VS-2). At ~85 trades/year and ~5 trades/fold, WF statistics are still meaningful but fold-level variance is elevated.

**Direction validation (2026-03-11):** H219 (LONG only, 55.8bps WF bps8, 15/16) and H220 (SHORT only, 44.0bps, 11/16) are **INCONCLUSIVE** — artifact classification, not PASS. VS-3 fires ~0.26/day; splitting in half gives n=35/40 per direction, both below the n≥50 threshold. The edge profile looks symmetric and strong, but formal confirmation requires more data. **Deploy both directions; no suppression warranted.**

**Deployment exit note:** H210 (VS-3 + liq-invalidation exit) passes with 49.6bps bps8 WF — essentially matching VS-3 anchor (48.0bps). Liq-drop or slope-reversal exit can be used in live deployment without degrading edge. Not a new shortcode — requires replication first.

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

**Deployment exit note:** H206 (LQ-1 + liq-invalidation exit) passes with 13.1bps bps8 WF, slightly above LQ-1 anchor (11.7bps). Exiting when long_liq_btc_pct drops below p50 is mechanistically correct and doesn't hurt the edge. Not a new shortcode — requires replication first.

---

#### LQ-2 — Short Liquidation Squeeze LONG ★ ANCHOR
**What it is:** When the prior 1h had extreme short-side liquidations (p90 threshold), go LONG for 40 minutes. Forced short covering creates sustained buying pressure.

| H-number | Variant | gross_bps | WF gross | WF bps8 | n/day | Label |
|----------|---------|-----------|----------|---------|-------|-------|
| **H178** | Base (short_liq_btc_pct >= 0.90, h=8) | **16.0** | **18/18** | **PASS (17/18, P>0=1.000)** | 4.44 | **LQ-2** |
| H185 | 1-bar execution lag | 13.7 | 18/18 | BORDERLINE (16/18, 4.7bps mean) | 4.44 | LQ-2 replication — deployable with fill quality awareness |

**Why it works:** Symmetric to LQ-1. Short squeeze buying pressure can propagate through voluntary capitulation and new longs piling on after the forced covering. 17/18 WF bps8 folds positive makes this the most consistent liq signal at cost.

**Deployment exit note:** H208 (LQ-2 + liq-invalidation exit) passes with 7.8bps bps8 WF, slightly above LQ-2 anchor (6.8bps). Exiting when short_liq_btc_pct drops below p50 is safe. Not a new shortcode — requires replication first.

---

#### LQ-3 — Liq-Gated ETH Slope Flip SHORT
**What it is:** ETH slope flips to bearish (CA-1 trigger) AND long liquidations are elevated (>= p70). The liquidation context confirms that the slope change has deleveraging pressure behind it, not just noise.

| H-number | Variant | gross_bps | WF gross | WF bps8 | n/day | Label |
|----------|---------|-----------|----------|---------|-------|-------|
| **H179** | Base (liq p70 gate + slope flip → SHORT, h=8) | **31.0** | **16/17** | **PASS (14/17, P>0=1.000)** | 0.51 | **LQ-3** |
| H186 | 1-bar execution lag | 31.3 | 17/17 | PASS (15/17, 20.9bps mean) | 0.51 | LQ-3 replication — execution realistic ✓ |

**Why it works:** The CA slope flip (CA-1) fires ~4/day. The p70 liq gate selects the subset where forced liquidations are also present — adding a second independent bearish mechanism to the momentum signal.

**Deployment exit note:** H209 (LQ-3 + combo exit) passes with 19.1bps bps8 WF, matching LQ-3 anchor (18.7bps). Both slope-reversal and liq-drop exits can be used. Not a new shortcode — requires replication first.

---

#### LQ-4 — Long Liquidation Cascade SHORT, h=12 ★ NEW (2026-03-11)
**What it is:** LQ-1 with extended 60-minute hold (12 bars) instead of 40-minute (8 bars). Cascade follow-through sustains for longer than previously tested.

| H-number | Variant | gross_bps | WF gross | WF bps8 | n/day | Label |
|----------|---------|-----------|----------|---------|-------|-------|
| **H191** | Base (long_liq_btc_pct >= 0.90, h=12) | **37.7** | **17/17** | **PASS (16/17, 31.0bps mean)** | 4.31 | **LQ-4** |
| H240 | 1-bar execution lag | 33.5 | 17/17 | PASS (16/17, 26.9bps mean) | 4.31 | LQ-4 replication — execution realistic ✓ |

**Why it works:** LQ-1's cascade continues beyond 40 minutes. Extending to 60-minute hold captures the full continuation window — roughly doubles per-trade edge vs LQ-1 (31.0bps vs 13.1bps bps8). Same mechanism, longer capture window.

---

#### LQ-5 — Short Liquidation Squeeze LONG, h=12 ★ NEW (2026-03-11)
**What it is:** LQ-2 with extended 60-minute hold (12 bars). Short squeeze buying pressure sustains beyond 40 minutes.

| H-number | Variant | gross_bps | WF gross | WF bps8 | n/day | Label |
|----------|---------|-----------|----------|---------|-------|-------|
| **H192** | Base (short_liq_btc_pct >= 0.90, h=12) | **29.2** | **17/17** | **PASS (17/17, 21.2bps mean)** | 4.44 | **LQ-5** |
| H241 | 1-bar execution lag | 27.7 | 17/17 | PASS (17/17, 17.3bps mean) | 4.44 | LQ-5 replication — execution realistic ✓ |

**Why it works:** LQ-2's squeeze momentum carries for 60 minutes. 17/17 perfect WF fold consistency on both anchor and lag — most consistent liq signal in the catalog.

---

#### LQ-6 — Liquidation Imbalance SHORT, h=12 ★ NEW (2026-03-11, ML-surfaced)
**What it is:** When short-side liquidations dominate long-side liquidations (liq_imbalance_dir, ML-surfaced feature via XGBoost SHAP), go SHORT for 12 bars (60 minutes). The directional imbalance of forced closures creates sustained directional follow-through beyond the initial event.

**Discovery path:** XGBoost SHAP across 4 horizons (h=4, 8, 16, 48) ranked `liq_imbalance_dir` #4 overall (CV=0.22, consistent 3/4 horizons). Economic interpretation: liq imbalance direction captures which side of the book is being mechanically cleared. Horizon sweep confirmed edge strengthens with hold length — a multi-horizon validated feature.

| H-number | Variant | gross_bps | WF gross | WF bps8 | n/day | Label |
|----------|---------|-----------|----------|---------|-------|-------|
| H247 | Base signal (h=12) | ~30bps | 17/17 | **PASS (17/17, 27.4bps mean)** | — | **LQ-6** |
| H249 | 1-bar execution lag (h=12) | ~26bps | 17/17 | **PASS (17/17, 22.8bps mean)** | — | LQ-6 replication ✓ |

**Horizon sweep (H243–H248):**
- h=4 (H246): 3.8bps, 12/17 folds — weak, cost-constrained
- h=8 (H243): 9.8bps, 16/17 folds — PASS but baseline
- **h=12 (H247): 27.4bps, 17/17 folds — ANCHOR ★** — momentum sustains to 60 min
- h=24 (H248): 30.6bps, 17/17 folds — PASS (longer hold, similar edge, less capital efficient)

Edge strengthens monotonically from h=4 to h=24 — not an artifact of a specific hold length. Both LONG and SHORT direction tested; SHORT direction is the cleaner signal. 1-bar lag confirmed (H249).

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

### OI Velocity (OV) — NEW 2026-03-11, ML-surfaced

#### OV-1 — OI Acceleration Gate on CA-1, h=24 ★ NEW (2026-03-11)
**What it is:** CA-1 signal (ETH slope flip) gated by OI acceleration — OI must be growing faster in the current 1h window than the prior 1h window. When the slope flip is accompanied by accelerating OI growth (new money entering), the directional momentum is more sustained.

**Discovery path:** XGBoost SHAP ranked `oi_velocity` #10 overall (CV=0.33), consistent 4/4 horizons — the only feature consistent at every tested horizon. Economic mechanism: OI acceleration means new leveraged positions are opening, not just existing positions flipping. This represents fresh directional commitment.

| H-number | Variant | gross_bps | WF gross | WF bps8 | n/day | Label |
|----------|---------|-----------|----------|---------|-------|-------|
| H252 | Base (CA-1 + OI accel, h=24) | ~20bps | 17/19 | **PASS (17/19, 18.4bps mean)** | — | **OV-1** |
| H259 | 1-bar execution lag (h=24) | ~17bps | 17/19 | **PASS (17/19, 15.8bps mean)** | — | OV-1 replication ✓ |

**Horizon sweep (H250–H252):**
- h=8 (H250): 8.8bps, 15/19 folds — PASS but weak
- h=12 (H251): 16.8bps, 16/19 folds — PASS
- **h=24 (H252): 18.4bps, 17/19 folds — ANCHOR ★** — edge peaks at 2h hold

Edge improves monotonically with hold length. OI acceleration predicts sustained 2h+ follow-through, not 40-minute moves. 1-bar lag confirmed (H259).

---

### Correlation Decoupling (CD) — NEW 2026-03-11, ML-surfaced

#### CD-1 — BTC-ETH Correlation Decoupling + ETH Flip, h=12 ★ NEW (2026-03-11)
**What it is:** ETH slope flip (CA-1 trigger) gated by BTC-ETH 2h rolling correlation being in its bottom quintile (historically low correlation). When BTC and ETH decouple, ETH slope flips reflect idiosyncratic ETH momentum rather than just BTC following. These are higher-conviction ETH directional moves.

**Discovery path:** XGBoost SHAP ranked `btc_eth_corr_2h` #3 overall (CV=0.35), consistent 3/4 horizons. Economic mechanism: normal BTC-ETH correlation is ~0.8+. Decoupling below p20 signals ETH is trading on its own fundamentals. A slope flip in this context captures ETH-specific momentum that isn't explained by BTC.

| H-number | Variant | gross_bps | WF gross | WF bps8 | n/day | Label |
|----------|---------|-----------|----------|---------|-------|-------|
| H257 | Base (corr < p20 + ETH flip, h=12) | ~15bps | 15/18 | **PASS (15/18, 14.1bps mean)** | — | **CD-1** |
| H260 | 1-bar execution lag (h=12) | ~16bps | 15/18 | **PASS (15/18, 15.2bps mean)** | — | CD-1 replication ✓ |

**Horizon sweep (H256–H258):**
- h=8 (H256): 6.4bps, 10/18 folds — BORDERLINE
- **h=12 (H257): 14.1bps, 15/18 folds — ANCHOR ★** — sweet spot for ETH idiosyncratic momentum
- h=24 (H258): 17.6bps, 11/18 folds — PASS but fold support drops

h=12 is the optimal hold — fold support stronger than h=24, edge substantially better than h=8. 1-bar lag confirmed (H260).

---

### Other Families (No Confirmed Signals Yet)

| Family | H-numbers tested | Outcome | Notes |
|--------|-----------------|---------|-------|
| MR (Mean Reversion) | H15, H18, H22-H26, H235-H236 | FAIL | VWAP MR dead at 5m — BTC trends through extensions |

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
