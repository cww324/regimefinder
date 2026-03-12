# Paper Trader Signal Specifications
**Last Updated:** 2026-03-12
**Research repo:** regime-crypto
**All signals validated:** 365-day BTC/ETH dataset, walk-forward cross-validation, 1-bar execution lag confirmed

---

## Portfolio Change Summary

| Signal | Action | Reason |
|--------|--------|--------|
| CA-1 | ✅ Keep | Core signal, firing well |
| CA-2 | ✅ Keep | Core signal, firing well |
| VS-2 | ❌ Remove | VS-3 covers the best VS events at 61bps vs 39bps; redundant |
| VS-3 | ✅ Keep | Best VS signal |
| LQ-1 | ✅ Keep | Core signal — **but fire rate bug suspected** (see note below) |
| LQ-2 | ❌ Replace with LQ-5 | LQ-5 is same mechanism, h=12 instead of h=8, 21bps vs 16bps |
| LQ-3 | ✅ Keep | Low frequency (~0.5/day) but distinct mechanism |
| LQ-4 | ➕ Add | LQ-1 same mechanism, longer hold — 31bps vs LQ-1's ~12bps net |
| LQ-5 | ➕ Add (replaces LQ-2) | Short liq squeeze LONG, h=12 |
| LQ-6 | ➕ Add | New ML-surfaced mechanism: liq directional imbalance |
| OV-1 | ➕ Add | New ML-surfaced mechanism: OI acceleration gate |
| CD-1 | ➕ Add | New ML-surfaced mechanism: BTC-ETH correlation decoupling |

**⚠️ LQ-1 fire rate note:** Research expectation is ~4.3 trades/day. Paper trader shows ~0.1/day over 10 days — almost certainly a bug. The most likely cause: `long_liq_btc_pct` is a **rolling percentile** computed over a long lookback window (365 days = ~105,000 5-minute bars). If the paper trader computes this percentile over a short rolling window (e.g. 1 day), the p90 threshold resets constantly and almost never stays triggered. Fix: ensure the rolling window for all `*_pct` columns is at least 20 days (5,760 5m bars). The same bug would affect LQ-2, LQ-3 if they also haven't fired.

---

## Data Requirements

All signals require:
- **BTC-USD 5-minute OHLCV candles** (Coinbase or equivalent)
- **ETH-USD 5-minute OHLCV candles**

Additional per signal:

| Signal | Additional data |
|--------|----------------|
| LQ-1, LQ-4 | Gate.io liquidations (1h): `long_liq_usd_btc` |
| LQ-2, LQ-5 | Gate.io liquidations (1h): `short_liq_usd_btc` |
| LQ-3 | Gate.io liquidations (1h): `long_liq_usd_btc` + ETH 1h EMA20 slope |
| LQ-6 | Gate.io liquidations (1h): `long_liq_usd_btc`, `short_liq_usd_btc` |
| VS-3 | Gate.io liquidations (1h): `total_liq_usd_btc` + BTC volume |
| OV-1 | Gate.io open interest (1h): `oi_contracts_btc` + ETH 1h EMA20 slope |
| CD-1 | ETH-USD 5m candles only (correlation computed from price returns) |

---

## Shared Computed Features

These are computed once and reused across multiple signals.

### ETH 1h EMA20 Slope Sign
```
# Resample ETH 5m closes to 1h
eth_1h_close = eth_5m_close.resample('1h').last()

# EMA20 on 1h bars
eth_ema20_1h = eth_1h_close.ewm(span=20, adjust=False).mean()

# Slope = 3-bar difference of EMA
eth_slope_1h = eth_ema20_1h.diff(3)

# Sign: +1 (positive slope), -1 (negative slope), 0 (flat)
eth_slope_sign_1h = sign(eth_slope_1h)

# Flip = sign changed AND is non-zero
eth_slope_flip = (eth_slope_sign_1h != eth_slope_sign_1h.shift(1)) AND (eth_slope_sign_1h != 0)
```
Then forward-fill this 1h signal onto the 5m frame (each 5m bar carries the last 1h slope sign).

### BTC 1h EMA20 Slope Sign (CA-2 only)
Same as above but using BTC 1h closes:
```
btc_ema20_1h = btc_1h_close.ewm(span=20, adjust=False).mean()
btc_slope_1h = btc_ema20_1h.diff(3)
btc_slope_sign_1h = sign(btc_slope_1h)
btc_slope_flip = (btc_slope_sign_1h != btc_slope_sign_1h.shift(1)) AND (btc_slope_sign_1h != 0)
```

### Liquidation Percentile Columns
```
# Rolling percentile rank over 20-day window (5,760 5m bars)
# Source: Gate.io liquidations, 1h resolution, forward-filled to 5m frame
ROLLING_WINDOW = 5760  # 20 days × 24h × 12 bars/h

long_liq_btc_pct  = long_liq_usd_btc.rolling(ROLLING_WINDOW).rank(pct=True)
short_liq_btc_pct = short_liq_usd_btc.rolling(ROLLING_WINDOW).rank(pct=True)
total_liq_btc_pct = total_liq_usd_btc.rolling(ROLLING_WINDOW).rank(pct=True)
```
**Critical:** The p90 threshold means "top 10% of the rolling 20-day distribution." If window is too short, the threshold adapts and fires too rarely or too often.

### BTC Volume Percentile (VS-3 only)
```
volume_btc_pct = btc_5m_volume.rolling(ROLLING_WINDOW).rank(pct=True)
```

---

## Signal Specifications

---

### CA-1 — ETH Slope Flip (EXISTING, KEEP)
**H-numbers:** H65 (anchor), H77 (lag replication)
**bps8 WF:** ~26bps | **n/day:** ~4.0 | **Direction:** Both LONG and SHORT

**Entry:**
```
TRIGGER: eth_slope_flip == True  (ETH 1h EMA20 slope changes direction)
DIRECTION: +1 (LONG) if new slope is positive, -1 (SHORT) if new slope is negative
EXECUTION: Enter at open of the bar AFTER signal fires (1-bar lag)
HOLD: 8 bars (40 minutes)
NO additional filters
```
**Exit:** Fixed hold — exit at close of bar 8 after entry. No early exits.

---

### CA-2 — BTC Slope Flip (EXISTING, KEEP)
**H-numbers:** H63 (anchor), H76 (lag replication)
**bps8 WF:** ~13bps | **n/day:** ~4.0 | **Direction:** Both LONG and SHORT

**Entry:**
```
TRIGGER: btc_slope_flip == True  (BTC 1h EMA20 slope changes direction)
DIRECTION: +1 (LONG) if new slope is positive, -1 (SHORT) if new slope is negative
EXECUTION: Enter at open of the bar AFTER signal fires (1-bar lag)
HOLD: 8 bars (40 minutes)
NO additional filters
```
**Exit:** Fixed hold — exit at close of bar 8 after entry.

---

### VS-3 — Volume + Liquidation Gated ETH Flip (EXISTING, KEEP)
**H-numbers:** H180 (anchor), H187 (lag replication)
**bps8 WF:** ~48bps (lag) | **n/day:** ~0.26 | **Direction:** Both

**Entry:**
```
CONDITION 1: eth_slope_flip == True
CONDITION 2: volume_btc_pct >= 0.80  (BTC volume in top 20% at time of flip)
CONDITION 3: total_liq_btc_pct >= 0.70  (total liquidations in top 30%)
ALL THREE must be true simultaneously.
DIRECTION: follows ETH slope flip direction
EXECUTION: Enter at open of bar AFTER signal fires (1-bar lag)
HOLD: 12 bars (60 minutes)
```
**Exit:** Fixed hold. Thesis-invalidation exit is also valid: exit early if `total_liq_btc_pct` drops below 0.50 OR ETH slope reverses mid-hold (optional, does not hurt edge).

**Note:** Low frequency (~1-2 trades/week). Do not be alarmed if it doesn't fire for several days.

---

### LQ-1 — Long Liquidation Cascade SHORT (EXISTING, KEEP)
**H-numbers:** H177 (anchor), H184 (lag replication)
**bps8 WF:** ~10bps (lag) | **n/day:** ~4.3 | **Direction:** SHORT only

**Entry:**
```
CONDITION: long_liq_btc_pct >= 0.90  (long-side liq in top 10% of 20-day rolling window)
TRIGGER: onset — first bar where condition becomes True after being False
DIRECTION: -1 (SHORT always)
EXECUTION: Enter at open of bar AFTER trigger fires (1-bar lag)
HOLD: 8 bars (40 minutes)
```
**Exit:** Fixed hold. Optional thesis-invalidation exit: if `long_liq_btc_pct` drops below 0.50 mid-hold, exit early (does not hurt edge).

**⚠️ If not firing:** Check rolling window size for `long_liq_btc_pct`. Must be >= 5,760 bars (20 days). With a shorter window the p90 threshold resets too quickly.

---

### LQ-3 — Liquidation-Gated ETH Slope Flip SHORT (EXISTING, KEEP)
**H-numbers:** H179 (anchor), H186 (lag replication)
**bps8 WF:** ~21bps (lag) | **n/day:** ~0.5 | **Direction:** SHORT only

**Entry:**
```
CONDITION 1: eth_slope_flip == True AND new slope direction is -1 (flip to bearish only)
CONDITION 2: long_liq_btc_pct >= 0.70  (long-side liq in top 30%)
BOTH must be true simultaneously.
DIRECTION: -1 (SHORT always)
EXECUTION: Enter at open of bar AFTER signal fires (1-bar lag)
HOLD: 8 bars (40 minutes)
```
**Exit:** Fixed hold. Optional: exit if ETH slope flips bullish mid-hold OR `long_liq_btc_pct` drops below 0.50.

---

### LQ-4 — Long Liquidation Cascade SHORT, h=12 (NEW — ADD)
**H-numbers:** H191 (anchor), H240 (lag replication)
**bps8 WF:** 26.9bps (lag) | **n/day:** ~4.3 | **Direction:** SHORT only

**Entry:** Identical to LQ-1 entry:
```
CONDITION: long_liq_btc_pct >= 0.90
TRIGGER: onset (first bar condition becomes True after being False)
DIRECTION: -1 (SHORT always)
EXECUTION: Enter at open of bar AFTER trigger (1-bar lag)
HOLD: 12 bars (60 minutes)  ← only difference from LQ-1
```
**Exit:** Fixed hold at 12 bars. Optional: exit early if `long_liq_btc_pct` drops below 0.50.

**Note:** Same entry as LQ-1 but significantly better edge (26.9bps vs ~10bps) due to longer hold capturing full cascade duration. LQ-1 and LQ-4 will fire at the same time — they are independent paper positions testing different hold lengths.

---

### LQ-5 — Short Liquidation Squeeze LONG, h=12 (NEW — replaces LQ-2)
**H-numbers:** H192 (anchor), H241 (lag replication)
**bps8 WF:** 17.3bps (lag) | **n/day:** ~4.4 | **Direction:** LONG only

**Entry:**
```
CONDITION: short_liq_btc_pct >= 0.90  (short-side liq in top 10% of 20-day rolling window)
TRIGGER: onset (first bar condition becomes True after being False)
DIRECTION: +1 (LONG always)
EXECUTION: Enter at open of bar AFTER trigger (1-bar lag)
HOLD: 12 bars (60 minutes)
```
**Exit:** Fixed hold. Optional: exit early if `short_liq_btc_pct` drops below 0.50.

**Note:** Symmetric complement to LQ-4 (short squeeze buying pressure vs long cascade selling pressure). 17/17 WF folds positive — most consistent signal in the catalog.

---

### LQ-6 — Liquidation Imbalance Direction SHORT, h=12 (NEW — ADD)
**H-numbers:** H247 (anchor), H249 (lag replication)
**bps8 WF:** 22.8bps (lag) | **n/day:** TBD | **Direction:** SHORT only

**Entry:**
```python
# Step 1: Compute directional imbalance ratio
# long_liq_usd_btc and short_liq_usd_btc are raw USD liquidation amounts (Gate.io, 1h)
total_liq = long_liq_usd_btc + short_liq_usd_btc
liq_imbalance_dir = (long_liq_usd_btc / total_liq.replace(0, NaN)).fillna(0.5) - 0.5
# Result ranges: -0.5 (all short liq = bullish squeeze) to +0.5 (all long liq = bearish cascade)

# Step 2: Rolling p80 threshold (20-day window on 5m frame = 5760 bars)
threshold = liq_imbalance_dir.rolling(5760, min_periods=100).quantile(0.80)

# Step 3: Onset trigger
above = liq_imbalance_dir >= threshold
onset = above AND NOT above.shift(1)  # first bar crossing threshold

DIRECTION: -1 (SHORT always)
EXECUTION: Enter at open of bar AFTER onset (1-bar lag)
HOLD: 12 bars (60 minutes)
```
**Why different from LQ-1/LQ-4:** LQ-1/LQ-4 trigger on *absolute level* of long liquidations being extreme. LQ-6 triggers on the *directional imbalance* — when long liq is unusually dominant as a share of total liq activity. Can fire even when absolute liq levels aren't extreme, as long as the directional skew is historically unusual.

---

### OV-1 — OI Velocity Gate on ETH Flip, h=24 (NEW — ADD)
**H-numbers:** H252 (anchor), H259 (lag replication)
**bps8 WF:** 15.8bps (lag) | **n/day:** TBD | **Direction:** Both LONG and SHORT

**Entry:**
```python
# Step 1: ETH slope flip (same as CA-1)
eth_slope_flip = ...  # see Shared Computed Features above

# Step 2: OI acceleration gate
# oi_contracts_btc = BTC perpetual open interest in contracts (Gate.io, 1h, forward-filled to 5m)
oi_chg_now  = oi_contracts_btc - oi_contracts_btc.shift(12)   # 1h change (12 5m bars)
oi_chg_prev = oi_contracts_btc.shift(12) - oi_contracts_btc.shift(24)  # prior 1h change
oi_accelerating = oi_chg_now > oi_chg_prev  # OI growing faster than previous hour

# Step 3: Combined trigger
signal = eth_slope_flip AND oi_accelerating

DIRECTION: follows ETH slope flip (+1 LONG if flip upward, -1 SHORT if flip downward)
EXECUTION: Enter at open of bar AFTER signal (1-bar lag)
HOLD: 24 bars (120 minutes / 2 hours)
```
**Why it works:** A CA-1 slope flip where OI is also accelerating means new leveraged positions are being opened alongside the momentum shift — fresh capital commitment, not just existing positions repositioning. Edge peaks at h=24 (2h hold); much weaker at h=8 (40min).

---

### CD-1 — BTC-ETH Correlation Decoupling + ETH Flip, h=12 (NEW — ADD)
**H-numbers:** H257 (anchor), H260 (lag replication)
**bps8 WF:** 15.2bps (lag) | **n/day:** TBD | **Direction:** Both LONG and SHORT

**Entry:**
```python
# Step 1: ETH slope flip (same as CA-1)
eth_slope_flip = ...

# Step 2: Rolling 2h BTC-ETH return correlation
# ret1_btc = btc_5m_close.pct_change()
# ret1_eth = eth_5m_close.pct_change()
corr_2h = ret1_btc.rolling(24).corr(ret1_eth)  # 24 5m bars = 2h rolling correlation
# Fill NaN with 0 for early bars

# Step 3: Rolling p20 threshold (1-year lookback on 5m frame)
LOOKBACK = 5760 * 18  # ~18 months worth, or use full available history, min 5760
corr_p20 = corr_2h.rolling(LOOKBACK, min_periods=5760).quantile(0.20)
# p20 = bottom quintile of historical correlation

# Step 4: Decoupling gate
decoupled = corr_2h < corr_p20  # correlation is unusually low

# Step 5: Combined trigger
signal = eth_slope_flip AND decoupled

DIRECTION: follows ETH slope flip (+1 LONG if flip upward, -1 SHORT if flip downward)
EXECUTION: Enter at open of bar AFTER signal (1-bar lag)
HOLD: 12 bars (60 minutes)
```
**Why it works:** BTC-ETH correlation is normally ~0.8+. When it drops below p20 (typically below ~0.5-0.6), ETH is trading on its own dynamics rather than following BTC mechanically. An ETH slope flip during decoupling is a higher-conviction idiosyncratic move — not just BTC-driven noise. h=12 is the sweet spot (stronger fold support than h=24).

---

## Full Target Portfolio

| # | Signal | Status | Direction | Hold | bps8 WF (lag) | n/day | Key mechanism |
|---|--------|--------|-----------|------|--------------|-------|---------------|
| 1 | CA-1 | Existing | Both | 40 min | ~26bps | ~4.0 | ETH 1h EMA20 slope flip |
| 2 | CA-2 | Existing | Both | 40 min | ~13bps | ~4.0 | BTC 1h EMA20 slope flip |
| 3 | VS-3 | Existing | Both | 60 min | ~45bps | ~0.26 | ETH flip + vol p80 + liq p70 triple gate |
| 4 | LQ-1 | Existing | SHORT | 40 min | ~10bps | ~4.3 | Long liq extreme onset (fix fire rate bug) |
| 5 | LQ-3 | Existing | SHORT | 40 min | ~21bps | ~0.5 | Long liq p70 gate on bearish ETH flip |
| 6 | LQ-4 | **ADD** | SHORT | 60 min | 26.9bps | ~4.3 | Long liq extreme onset, longer hold |
| 7 | LQ-5 | **ADD** (replaces LQ-2) | LONG | 60 min | 17.3bps | ~4.4 | Short liq extreme onset, longer hold |
| 8 | LQ-6 | **ADD** | SHORT | 60 min | 22.8bps | TBD | Liq directional imbalance > p80 |
| 9 | OV-1 | **ADD** | Both | 120 min | 15.8bps | TBD | ETH flip + OI acceleration |
| 10 | CD-1 | **ADD** | Both | 60 min | 15.2bps | TBD | ETH flip + BTC-ETH correlation < p20 |

**Remove:** VS-2, LQ-2

---

## Implementation Notes

1. **All signals use 1-bar execution lag.** Enter at the open of the bar *after* the signal fires. Do not enter at the signal bar's close.

2. **All holds are fixed.** Do not use price-based stops, take-profits, or trailing stops. Research confirmed these reduce performance for slope-flip signals by ~50%. Exception: thesis-invalidation exits (liq drops, slope reversal mid-hold) are safe for LQ signals but not required.

3. **Percentile thresholds use rolling windows, not fixed values.** The threshold for `long_liq_btc_pct >= 0.90` means "current value is in the top 10% of the last 20 days of data." This adapts over time. Window must be at least 20 days (5,760 5m bars) or the threshold becomes unstable.

4. **No deduplication needed across signals.** Each signal is independent. If CA-1 and OV-1 fire at the same bar, both open separate positions.

5. **Low-frequency signals (VS-3, LQ-3, CD-1, OV-1) may not fire for days.** Expected behavior — do not interpret silence as a bug unless it persists beyond 2-3 weeks.

6. **All bps8 figures are net of 8bps round-trip cost.** Validate against actual exchange fees. If fees are higher (e.g. 10bps), re-check CA-1/CA-2 viability.
