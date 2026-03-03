# Add CA-1, CA-2, VS-2 to Paper Trader
**Date:** 2026-02-27
**Purpose:** Add three validated signals to the live paper trader.
One new feature required (BTC EMA slope for CA-2). Everything else already exists.

---

## Quick Summary — What Needs to Change

5 files, in this order:

1. **`backend/features.py`** — add `compute_btc_slope_sign()` (same as ETH version, just on BTC candles). Expose `btc_slope_sign` and `btc_slope_sign_prev` in the features dict.
2. **`backend/signals.py`** — replace the fires block wholesale with the updated 7-signal version in this spec.
3. **`backend/db.py`** — update the `INSERT OR IGNORE` seed line to include CA-1, CA-2, VS-2.
4. **`frontend/src/types.ts`** — add new signal names to the union type, add `btc_slope_sign` to `FeatureUpdateEvent`.
5. **`frontend/src/components/SignalPanel.tsx`** — add 3 new signal cards (CA-1, CA-2, VS-2).

CA-2 is the only signal requiring new code beyond copy-paste — the BTC slope feature
is 6 lines, identical to the ETH version but on BTC candles.

---

## Context

The paper trader currently runs 4 signals: LQ-1, LQ-2, LQ-3, VS-3.
This spec adds CA-1, CA-2, and VS-2.

**Features already computed (no changes needed):**
- `eth_slope_sign` — used by LQ-3 and VS-3
- `volume_btc_pct` — used by VS-3

**One new feature needed:**
- `btc_slope_sign` — same calculation as `eth_slope_sign` but on BTC candles (for CA-2)

**Why these 3 and not others:**
- CA-1 = ETH slope flip anchor, ~4/day, fastest live validation feedback
- CA-2 = BTC slope flip, genuinely independent signal (different asset driving it)
- VS-2 = best volume-gated variant (38bps), represents the full VS family
- Skipped CA-3 (identical entries to CA-1, just shorter hold — redundant)
- Skipped VS-1 (identical entries to VS-2, just shorter hold — VS-2 covers it)
- Skipped CA-4 (weakest confirmed signal, identical entries to CA-2)

---

## The 3 New Signals — Exact Rules

### CA-1 — ETH Slope Flip (both directions), h=8

Core anchor signal. ETH 1h EMA20 slope flips → trade in direction of new trend for 40 min.

| Parameter | Value |
|-----------|-------|
| Trigger | `eth_slope_sign` flips (either direction, new value must be non-zero) |
| Direction | LONG if new slope = +1, SHORT if new slope = -1 |
| Hold | 8 bars (40 minutes) |
| Dedup gap | 8 bars |
| Expected frequency | ~4 trades/day |
| Backtested gross (lag-adjusted) | ~26 bps/trade |
| WF validation | 20/20 gross, 20/20 bps8 |

---

### CA-2 — BTC Slope Flip (both directions), h=8

Same logic as CA-1 but driven by BTC's own EMA20 slope, not ETH's.
Independent signal — BTC slope and ETH slope do not always flip at the same time.

| Parameter | Value |
|-----------|-------|
| Trigger | `btc_slope_sign` flips (either direction, new value must be non-zero) |
| Direction | LONG if new BTC slope = +1, SHORT if new BTC slope = -1 |
| Hold | 8 bars (40 minutes) |
| Dedup gap | 8 bars |
| Expected frequency | ~4 trades/day |
| Backtested gross (lag-adjusted) | ~21 bps/trade |
| WF validation | 20/20 gross, 19/20 bps8 |

---

### VS-2 — High-Volume ETH Slope Flip, h=12

CA-1 gated by high BTC volume (top 20%), held for 60 min instead of 40 min.
Volume-confirmed momentum sustains directionally for 60 min.

| Parameter | Value |
|-----------|-------|
| Trigger condition 1 | `eth_slope_sign` flips (either direction) |
| Trigger condition 2 | `volume_btc_pct >= 0.80` at time of flip |
| Direction | LONG if new slope = +1, SHORT if new slope = -1 |
| Hold | 12 bars (60 minutes) |
| Dedup gap | 12 bars |
| Expected frequency | ~0.4 trades/day |
| Backtested gross (lag-adjusted) | ~35 bps/trade |
| WF validation | 17/18 gross, 17/18 bps8 |

**Note:** VS-2 and VS-3 share the same entry trigger when liq is also elevated.
When VS-3 fires, VS-2 will also fire (VS-3 is a subset of VS-2). This is correct
and intentional — they track the same entry but are evaluated independently.

---

## Changes Required

### 1. `backend/features.py` — Add BTC slope sign

Add a `compute_btc_slope_sign()` function mirroring the existing ETH version:

```python
def compute_btc_slope_sign(btc_candles: pd.DataFrame) -> pd.Series:
    """
    btc_candles: DataFrame with columns [ts, close], sorted ascending.
    Returns Series of slope sign (-1, 0, +1) indexed by ts (5m resolution).
    Identical logic to compute_eth_slope_sign() but applied to BTC candles.
    """
    btc = btc_candles.set_index(
        pd.to_datetime(btc_candles['ts'], unit='s', utc=True)
    )['close']

    btc_1h = btc.resample('1h').last().dropna()
    btc_ema20 = btc_1h.ewm(span=20, adjust=False).mean()
    btc_slope = btc_ema20.diff(3)
    btc_slope_sign_1h = np.sign(btc_slope)
    btc_slope_sign_5m = btc_slope_sign_1h.reindex(btc.index, method='ffill')

    return btc_slope_sign_5m
```

Call this alongside the ETH version wherever features are computed (likely in the
main feature computation block that runs on each new 5m bar). The result needs to
be carry-forwarded to 5m bars the same way ETH slope sign is.

Also expose `btc_slope_sign` and `btc_slope_sign_prev` in the features dict passed
to `evaluate_signals()`.

---

### 2. `backend/signals.py` — Add 3 signal rules

Update `evaluate_signals()` to accept and use `btc_slope_sign` and `btc_slope_sign_prev`.

Updated function signature:
```python
def evaluate_signals(
    features: dict,
    current_ts: int,
    is_new_gateio_reading: bool,
    signal_states: dict,
) -> list[SignalFire]:
```

Add `btc_slope` and `btc_slope_prev` extraction alongside the existing feature reads:
```python
slope      = features['eth_slope_sign']
slope_prev = features['eth_slope_sign_prev']
btc_slope      = features['btc_slope_sign']
btc_slope_prev = features['btc_slope_sign_prev']
vol_pct    = features['volume_btc_pct']
ll_pct     = features['long_liq_btc_pct']
sl_pct     = features['short_liq_btc_pct']
tl_pct     = features['total_liq_btc_pct']
```

Full updated fires block (replace existing entirely):

```python
fires = []

# Shared flip conditions
eth_flip        = (slope != slope_prev and slope != 0)
btc_flip        = (btc_slope != btc_slope_prev and btc_slope != 0)
bearish_eth_flip = (slope == -1 and slope_prev != -1)

# CA-1: ETH slope flip → direction of flip, h=8
if eth_flip and not in_dedup('CA-1', 8):
    direction = 'LONG' if slope == 1 else 'SHORT'
    fires.append(SignalFire('CA-1', direction, 8))

# CA-2: BTC slope flip → direction of flip, h=8
if btc_flip and not in_dedup('CA-2', 8):
    direction = 'LONG' if btc_slope == 1 else 'SHORT'
    fires.append(SignalFire('CA-2', direction, 8))

# VS-2: ETH slope flip + high volume, h=12
if eth_flip and vol_pct >= 0.80 and not in_dedup('VS-2', 12):
    direction = 'LONG' if slope == 1 else 'SHORT'
    fires.append(SignalFire('VS-2', direction, 12))

# VS-3: ETH slope flip + high volume + elevated liq, h=12
if eth_flip and vol_pct >= 0.80 and tl_pct >= 0.70 and not in_dedup('VS-3', 12):
    direction = 'LONG' if slope == 1 else 'SHORT'
    fires.append(SignalFire('VS-3', direction, 12))

# LQ-1: extreme long liq → SHORT
if is_new_gateio_reading and ll_pct >= 0.90 and not in_dedup('LQ-1', 8):
    fires.append(SignalFire('LQ-1', 'SHORT', 8))

# LQ-2: extreme short liq → LONG
if is_new_gateio_reading and sl_pct >= 0.90 and not in_dedup('LQ-2', 8):
    fires.append(SignalFire('LQ-2', 'LONG', 8))

# LQ-3: bearish ETH slope flip + elevated long liq → SHORT
if bearish_eth_flip and ll_pct >= 0.70 and not in_dedup('LQ-3', 8):
    fires.append(SignalFire('LQ-3', 'SHORT', 8))

return fires
```

---

### 3. `backend/db.py` — Seed 3 new signal_state rows

Find the existing seed insert:
```sql
INSERT OR IGNORE INTO signal_state (signal)
VALUES ('LQ-1'), ('LQ-2'), ('LQ-3'), ('VS-3');
```

Replace with:
```sql
INSERT OR IGNORE INTO signal_state (signal)
VALUES ('CA-1'), ('CA-2'), ('VS-2'), ('VS-3'), ('LQ-1'), ('LQ-2'), ('LQ-3');
```

`INSERT OR IGNORE` means existing live rows are untouched — safe to run on the live DB.

Also update any hardcoded signal name lists elsewhere in `db.py` (e.g. initial
inserts, queries filtering by signal name) to include `CA-1`, `CA-2`, `VS-2`.

---

### 4. Frontend — `types.ts`

Update the signal union type:

```typescript
// Before:
signal: 'LQ-1' | 'LQ-2' | 'LQ-3' | 'VS-3'

// After:
signal: 'CA-1' | 'CA-2' | 'VS-2' | 'VS-3' | 'LQ-1' | 'LQ-2' | 'LQ-3'
```

Also update `FeatureUpdateEvent` to include `btc_slope_sign` so the frontend
can display it in the CA-2 card:

```typescript
export type FeatureUpdateEvent = {
  type: 'feature_update'
  eth_slope_sign: number       // -1, 0, or 1
  btc_slope_sign: number       // -1, 0, or 1  ← NEW
  volume_btc_pct: number
  long_liq_btc_pct: number
  short_liq_btc_pct: number
  total_liq_btc_pct: number
}
```

---

### 5. Frontend — `SignalPanel.tsx`

Add 3 new signal cards following the existing pattern.

**CA-1 card:**
- Name: `CA-1`
- Description: `ETH slope flip — trade direction of new trend`
- Feature display: `eth_slope_sign` current value (show as BULLISH / BEARISH / FLAT)
- Expected: ~4 fires/day — should be the most active card

**CA-2 card:**
- Name: `CA-2`
- Description: `BTC slope flip — trade direction of new BTC trend`
- Feature display: `btc_slope_sign` current value (BULLISH / BEARISH / FLAT)
- Expected: ~4 fires/day

**VS-2 card:**
- Name: `VS-2`
- Description: `High-volume ETH slope flip, 60 min hold`
- Feature display: `eth_slope_sign` + `volume_btc_pct` progress bar
- Expected: ~0.4 fires/day (~3/week)
- Note: fires at the same time as VS-3 when liq is also elevated

---

## Deployment

1. Build and test locally first:
   - Unit test `compute_btc_slope_sign()` — verify slope sign flips at sensible times
   - Unit test new signal rules with hardcoded feature values that should/shouldn't trigger
2. `docker compose build && docker compose up -d`
3. The `INSERT OR IGNORE` safely adds 3 rows to the live SQLite DB
4. Verify CA-1 fires within a few hours of startup (expect ~4/day)

---

## Expected Live Behavior After Deployment

| Signal | Expected fires | Notes |
|--------|---------------|-------|
| CA-1 | ~4/day | Most active signal — fast live validation feedback |
| CA-2 | ~4/day | Fires independently of CA-1; BTC and ETH slopes don't always flip together |
| VS-2 | ~3/week | Fires alongside VS-3 when liq is also elevated |
| VS-3 | ~2/week | Already live — now VS-2 also fires on these same events |
| LQ-1 | ~4/day | Already live, unchanged |
| LQ-2 | ~4/day | Already live, unchanged |
| LQ-3 | ~3/week | Already live, unchanged |

**What to watch:** If CA-1 is silent for more than 12 hours, check slope flip
detection — it fires frequently enough that silence = bug. CA-2 should behave
similarly. VS-2 and VS-3 co-firing is expected and correct.
