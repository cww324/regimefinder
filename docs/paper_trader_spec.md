# Crypto Paper Trader — Full Build Spec
**Version:** 1.0 | **Date:** 2026-02-27
**Purpose:** Self-contained spec for a fresh coding agent to build the paper trading
application in a new, standalone repo. No dependency on any other codebase.

---

## 1. What This App Is

A live paper trading dashboard that:
1. Consumes real-time BTC/ETH price data via Coinbase WebSocket
2. Fetches hourly liquidation data from Gate.io REST API (no auth required)
3. Evaluates 4 validated trading signals in real time
4. Logs paper trades and P&L to SQLite
5. Displays a live dashboard (React frontend) with price chart, signal status, and trade log

**Paper trading only** — no real money, no exchange orders. Tracks hypothetical entries
and exits at market price to validate that live signal performance matches backtested
expectations. This is the primary purpose: confirming that the backtested edge holds
in live market conditions.

**Deployment:** Runs as a new Docker container on an existing AWS EC2 instance.
SQLite database stored on EBS volume (persists across container restarts).

---

## 2. Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend language | Python 3.11+ |
| Backend framework | FastAPI (async, native WebSocket support) |
| Task scheduler | APScheduler (in-process, for Gate.io polling) |
| Database | SQLite via aiosqlite |
| Frontend framework | React 18 + TypeScript |
| Styling | TailwindCSS |
| Charts | TradingView Lightweight Charts (vanilla JS, used in React via useEffect + ref) |
| HTTP client | httpx (async) |
| Containerization | Docker + Docker Compose |

---

## 3. Architecture Overview

```
EC2 Instance (existing, free tier)
└── Docker container: paper-trader (NEW)
    ├── FastAPI / uvicorn
    │   ├── WebSocket server  →  pushes real-time updates to browser
    │   ├── REST endpoints    →  serve candle history + trade log
    │   └── Static files      →  serves React build (frontend/dist/)
    │
    ├── APScheduler background jobs
    │   ├── Coinbase WS client  →  subscribes BTC-USD + ETH-USD candles (5m)
    │   └── Gate.io poller      →  fetches hourly liq data at :02 past each hour
    │
    ├── Signal engine  →  evaluates 4 signals on each new bar
    ├── Trade manager  →  opens/closes/tracks paper positions in SQLite
    └── SQLite DB      →  mounted from EBS volume at /data/paper_trader.db
```

**Real-time data flow:**
```
Coinbase WS (5m candles)
  → write to SQLite (rolling 30d window)
  → recompute features
  → evaluate signals
  → if signal fires: open paper trade + push WS event to browser

Gate.io REST (1h liq, polled at :02 past each hour)
  → write to SQLite (rolling 30d window)
  → recompute liq features
  → evaluate LQ signals (onset trigger)
  → push updated feature values to browser via WS
```

---

## 4. Project Structure

```
paper-trader/                     ← new standalone repo
├── backend/
│   ├── main.py                   # FastAPI app entry point, startup, WS server
│   ├── db.py                     # SQLite schema + all queries (aiosqlite)
│   ├── features.py               # Feature computation (EMA, slope, rolling pct rank)
│   ├── signals.py                # Signal definitions + evaluation logic
│   ├── trade_manager.py          # Open/close/track paper trades
│   ├── feeds/
│   │   ├── coinbase_ws.py        # Coinbase WebSocket client + REST bootstrap
│   │   └── gateio.py             # Gate.io REST poller + REST bootstrap
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── types.ts              # Shared TypeScript interfaces
│   │   ├── components/
│   │   │   ├── Chart.tsx         # TradingView chart + trade entry/exit markers
│   │   │   ├── SignalPanel.tsx   # Signal status cards (one per signal)
│   │   │   └── TradeLog.tsx      # Open + closed trades table with P&L
│   │   └── hooks/
│   │       └── useWebSocket.ts   # WS connection, auto-reconnect, message dispatch
│   ├── package.json
│   ├── tsconfig.json
│   └── tailwind.config.js
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## 5. Startup Bootstrap (Critical — Do This First)

On every cold start, before opening the Coinbase WebSocket connection, the app must
seed the SQLite rolling window with 30 days of historical data. Without this, the
rolling percentile ranks used by all 4 signals will be meaningless.

**Step 1 — Historical candles (Coinbase REST):**
```
GET https://api.coinbase.com/api/v3/brokerage/market/products/{product_id}/candles
  ?granularity=FIVE_MINUTE
  &start={unix_ts_30_days_ago}
  &end={unix_ts_now}
```
- Fetch for both `BTC-USD` and `ETH-USD`
- Coinbase returns max 300 candles per request — paginate to cover 30 days (~8,640 bars)
- No authentication required for market data
- Write all candles to `candles_5m` table

**Step 2 — Historical liquidations (Gate.io REST):**
```
GET https://api.gateio.ws/api/v4/futures/usdt/contract_stats
  ?contract=BTC_USDT&interval=1h&from={unix_ts_30_days_ago}&limit=720
```
- Fetch for both `BTC_USDT` and `ETH_USDT`
- No authentication required
- Write all records to `liquidations_1h` table

**Step 3 — Compute initial features** on the full 30-day dataset.

**Step 4 — Start Coinbase WebSocket** and begin live operation.

The bootstrap takes ~30-60 seconds. After it completes, the app is fully operational
with a properly calibrated 30-day rolling window from the first bar.

---

## 6. The 4 Trading Signals — Exact Rules

These signals were derived from 365 days of backtested data with walk-forward
cross-validation. **Do not change any thresholds.** The rules below are exact.

### Key shared concepts

**Rolling 30-day percentile rank:**
For any raw value (volume, liquidation USD), its percentile rank is computed against
the last 30 days of observed values in the rolling window.
- Window = 30 days × 24h × 12 bars/hour = **8,640 rows** (5m candles)
- `pct_rank = count(past_values <= current_value) / total_values_in_window`
- For hourly liq: same 8,640-bar window applies, but values are carry-forwarded
  across the 12 x 5m bars within each hour (720 unique values)

**Dedup gap:** After a signal fires, do not re-fire that signal for `hold_bars` bars
(= `hold_bars * 300` seconds). Prevents re-entering the same ongoing event.

**Onset trigger (LQ-1 and LQ-2 only):** These signals fire only on the **first 5m bar**
after a new Gate.io hourly reading exceeds the threshold. Subsequent 5m bars in the
same hour do not re-trigger even if the value stays above threshold.

---

### LQ-1 — Long Liquidation Cascade → SHORT

**Theory:** When extreme long-side liquidations occurred in the prior hour (top 10%
historically), the market is in a deleveraging event. Forced selling cascades — one
round of margin calls triggers more stops. Price continuation persists ~40 min.

| Parameter | Value |
|-----------|-------|
| Trigger | `long_liq_btc_pct >= 0.90` on a new hourly Gate.io reading |
| Direction | SHORT |
| Hold | 8 bars (40 minutes) |
| Dedup gap | 8 bars |
| Expected frequency | ~4.3 trades/day |
| Backtested gross return | +20.0 bps/trade |
| Backtested net (after ~8bps cost) | +11.7 bps/trade |

**Entry pseudocode:**
```python
if is_new_gateio_reading and long_liq_btc_pct >= 0.90 and not in_dedup("LQ-1"):
    open_trade(signal="LQ-1", direction="SHORT", hold_bars=8, price=current_btc_close)
```

---

### LQ-2 — Short Liquidation Squeeze → LONG

**Theory:** Symmetric to LQ-1. Extreme short liquidations = forced short covering.
Buying pressure from short squeezes propagates ~40 min after the liq window.

| Parameter | Value |
|-----------|-------|
| Trigger | `short_liq_btc_pct >= 0.90` on a new hourly Gate.io reading |
| Direction | LONG |
| Hold | 8 bars (40 minutes) |
| Dedup gap | 8 bars |
| Expected frequency | ~4.4 trades/day |
| Backtested gross return | +16.0 bps/trade |
| Backtested net (after ~8bps cost) | +6.8 bps/trade |

---

### LQ-3 — Liq-Gated ETH Slope Flip → SHORT

**Theory:** The ETH momentum signal fires ~4x/day. The p70 liq gate selects only
the subset where long liquidations are also elevated — the slope flip has real
deleveraging pressure behind it, not just noise. SHORT only.

| Parameter | Value |
|-----------|-------|
| Trigger condition 1 | `eth_slope_sign` flips from `+1` to `-1` (new bearish flip) |
| Trigger condition 2 | `long_liq_btc_pct >= 0.70` at time of flip |
| Direction | SHORT only |
| Hold | 8 bars (40 minutes) |
| Dedup gap | 8 bars |
| Expected frequency | ~0.5 trades/day |
| Backtested gross return | +31.0 bps/trade |
| Backtested net (after ~8bps cost) | +18.7 bps/trade |

---

### VS-3 — Volume + Slope Flip + Liq Gate → direction of flip (BEST SIGNAL)

**Theory:** ETH momentum slope flip, gated by high BTC volume (top 20%) AND elevated
total liquidations (p70+). Three independent mechanisms aligning simultaneously:
momentum (slope), capital flows (volume), mechanical deleveraging (liq).
Highest per-trade edge of all 4 signals.

| Parameter | Value |
|-----------|-------|
| Trigger condition 1 | `eth_slope_sign` flips (either direction) |
| Trigger condition 2 | `volume_btc_pct >= 0.80` at time of flip |
| Trigger condition 3 | `total_liq_btc_pct >= 0.70` at time of flip |
| Direction | LONG if slope flips to +1, SHORT if slope flips to -1 |
| Hold | 12 bars (60 minutes) |
| Dedup gap | 12 bars |
| Expected frequency | ~0.26 trades/day (~8/month) |
| Backtested gross return | +60.5 bps/trade |
| Backtested net (after ~8bps cost) | +48.0 bps/trade |

---

## 7. Feature Computation (features.py)

All features computed in Python from SQLite data. Only pandas + numpy needed.

### `eth_slope_sign` — ETH 1h EMA20 slope direction

```python
def compute_eth_slope_sign(eth_candles: pd.DataFrame) -> pd.Series:
    """
    eth_candles: DataFrame with columns [ts, close], sorted ascending.
    Returns Series of slope sign (-1, 0, +1) indexed by ts (5m resolution).
    """
    eth = eth_candles.set_index(
        pd.to_datetime(eth_candles['ts'], unit='s', utc=True)
    )['close']

    # Resample to 1h (last 5m close in each hour)
    eth_1h = eth.resample('1h').last().dropna()

    # EMA with span=20 on 1h series
    eth_ema20 = eth_1h.ewm(span=20, adjust=False).mean()

    # 3-period difference on 1h series (= 3h momentum)
    eth_slope = eth_ema20.diff(3)

    # Sign: -1, 0, or +1
    eth_slope_sign_1h = np.sign(eth_slope)

    # Carry-forward to 5m resolution via backward fill
    eth_slope_sign_5m = eth_slope_sign_1h.reindex(eth.index, method='ffill')

    return eth_slope_sign_5m
```

**Flip detection:** On each new 5m bar, compare `eth_slope_sign[current]` to
`eth_slope_sign[previous]`. A flip occurred when they differ and the new value
is non-zero. Since slope only updates at the top of each hour, flips will only
ever be detected on the first 5m bar of a new hour.

### `volume_btc_pct` — BTC volume percentile rank

```python
# Rolling 30-day pct rank of raw BTC 5m volume
volume_btc_pct = btc_candles['volume'].rolling(8640).rank(pct=True)
```

### Liquidation features — from Gate.io data

Gate.io provides raw USD values per hour window:
- `long_liq_usd` — USD value of long positions liquidated that hour
- `short_liq_usd` — USD value of short positions liquidated that hour

```python
# After carry-forwarding hourly values onto 5m frame:
long_liq_btc_pct  = long_liq_usd_series.rolling(8640).rank(pct=True)
short_liq_btc_pct = short_liq_usd_series.rolling(8640).rank(pct=True)
total_liq_btc_pct = (long_liq_usd + short_liq_usd).rolling(8640).rank(pct=True)
```

---

## 8. Data Sources

### 8a. Coinbase Advanced Trade API — Authentication

Both the REST candles endpoint and the WebSocket connection require authentication
via the Coinbase Advanced Trade API. Use the API key and secret from your `.env`.

Coinbase Advanced Trade uses **JWT authentication**. For each REST request, generate
a JWT signed with your API secret and include it as a Bearer token. For the WebSocket,
send a signed subscribe message.

The easiest approach is to use the official Coinbase Python SDK which handles JWT
signing automatically:
```
pip install coinbase-advanced-py
```

Or handle JWT manually — Coinbase's auth docs:
https://docs.cdp.coinbase.com/advanced-trade/docs/sdk-authentication

**Environment variables needed:**
```
COINBASE_API_KEY=your_api_key_name       # format: "organizations/.../apiKeys/..."
COINBASE_API_SECRET=your_api_secret      # EC private key (-----BEGIN EC PRIVATE KEY-----)
```

---

### 8b. Coinbase WebSocket — 5m Candles (live)

**URL:** `wss://advanced-trade-ws.coinbase.com`

**Subscribe message** (must include JWT signature):
```json
{
  "type": "subscribe",
  "product_ids": ["BTC-USD", "ETH-USD"],
  "channel": "candles",
  "api_key": "your_api_key_name",
  "timestamp": "1706745600",
  "signature": "your_jwt_signature"
}
```

**Incoming candle event:**
```json
{
  "channel": "candles",
  "events": [{
    "type": "candle",
    "candles": [{
      "start": "1706745600",
      "open": "42000.00",
      "high": "42100.00",
      "low": "41900.00",
      "close": "42050.00",
      "volume": "123.45",
      "product_id": "BTC-USD"
    }]
  }]
}
```

- `start` is bar open time in Unix seconds. Bar is closed when `now >= start + 300`.
- Treat a bar as final only when the next bar's `start` arrives.
- Handle disconnects with exponential backoff reconnect (1s, 2s, 4s... max 30s).

**Historical bootstrap (REST):**
```
GET https://api.coinbase.com/api/v3/brokerage/products/{product_id}/candles
  ?granularity=FIVE_MINUTE&start={unix_30d_ago}&end={unix_now}
```
Requires Bearer JWT token in `Authorization` header. Returns max 300 candles per
request — paginate to cover 30 days (~8,640 bars). Fetch for both `BTC-USD` and
`ETH-USD`.

### 8b. Gate.io REST — Hourly Liquidations

**No authentication required.**

**URL:** `https://api.gateio.ws/api/v4/futures/usdt/contract_stats`

**Query params:**
| Param | Value |
|-------|-------|
| `contract` | `BTC_USDT` or `ETH_USDT` |
| `interval` | `1h` |
| `from` | Unix timestamp |
| `limit` | Number of hourly records |

**Response:**
```json
[{ "time": 1706745600, "long_liq_usd": "1234567.89", "short_liq_usd": "987654.32" }]
```

**Live polling:** APScheduler job runs every hour at **:02 past the hour**.
Fetch last 2 records to ensure no gaps. Set `is_new_gateio_reading = True` on
the first 5m bar after a successful poll — pass this flag to signal evaluation.

---

## 9. SQLite Schema (db.py)

```sql
-- 5m candles — rolling 30d window (~8,640 rows per symbol)
CREATE TABLE IF NOT EXISTS candles_5m (
    ts      INTEGER NOT NULL,
    symbol  TEXT NOT NULL,      -- 'BTC-USD' or 'ETH-USD'
    open    REAL NOT NULL,
    high    REAL NOT NULL,
    low     REAL NOT NULL,
    close   REAL NOT NULL,
    volume  REAL NOT NULL,
    PRIMARY KEY (ts, symbol)
);

-- Hourly liquidations — rolling 30d window (~720 rows per symbol)
CREATE TABLE IF NOT EXISTS liquidations_1h (
    ts            INTEGER NOT NULL,
    symbol        TEXT NOT NULL,  -- 'BTC' or 'ETH'
    long_liq_usd  REAL NOT NULL DEFAULT 0.0,
    short_liq_usd REAL NOT NULL DEFAULT 0.0,
    PRIMARY KEY (ts, symbol)
);

-- Paper trades log
CREATE TABLE IF NOT EXISTS paper_trades (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    signal       TEXT NOT NULL,   -- 'LQ-1', 'LQ-2', 'LQ-3', 'VS-3'
    direction    TEXT NOT NULL,   -- 'LONG' or 'SHORT'
    entry_ts     INTEGER NOT NULL,
    entry_price  REAL NOT NULL,   -- BTC-USD close at entry bar
    exit_ts      INTEGER,         -- NULL while open
    exit_price   REAL,            -- NULL while open
    hold_bars    INTEGER NOT NULL,
    gross_bps    REAL,            -- NULL while open
                                  -- = (exit_price/entry_price - 1) * 10000 * direction_sign
                                  -- direction_sign: +1 for LONG, -1 for SHORT
    status       TEXT NOT NULL DEFAULT 'OPEN'  -- 'OPEN' or 'CLOSED'
);

-- Per-signal dedup state
CREATE TABLE IF NOT EXISTS signal_state (
    signal         TEXT PRIMARY KEY,  -- 'LQ-1', 'LQ-2', 'LQ-3', 'VS-3'
    last_fire_ts   INTEGER,
    last_fire_dir  TEXT,
    open_trade_id  INTEGER  -- FK to paper_trades.id, NULL if no open trade
);

-- Seed on first start:
INSERT OR IGNORE INTO signal_state (signal)
VALUES ('LQ-1'), ('LQ-2'), ('LQ-3'), ('VS-3');
```

**Rolling window maintenance:** After every insert, prune old rows:
```sql
DELETE FROM candles_5m    WHERE ts < strftime('%s','now') - 2592000;
DELETE FROM liquidations_1h WHERE ts < strftime('%s','now') - 2592000;
```

---

## 10. Signal Engine (signals.py)

```python
from dataclasses import dataclass

@dataclass
class SignalFire:
    signal: str      # 'LQ-1', 'LQ-2', 'LQ-3', 'VS-3'
    direction: str   # 'LONG' or 'SHORT'
    hold_bars: int


def evaluate_signals(
    features: dict,
    current_ts: int,
    is_new_gateio_reading: bool,
    signal_states: dict,
) -> list[SignalFire]:

    def in_dedup(signal, hold_bars):
        last = signal_states[signal]['last_fire_ts']
        if last is None:
            return False
        return (current_ts - last) < (hold_bars * 300)

    slope      = features['eth_slope_sign']         # current: -1, 0, or +1
    slope_prev = features['eth_slope_sign_prev']    # previous bar
    vol_pct    = features['volume_btc_pct']
    ll_pct     = features['long_liq_btc_pct']
    sl_pct     = features['short_liq_btc_pct']
    tl_pct     = features['total_liq_btc_pct']

    fires = []

    # LQ-1: extreme long liq → SHORT
    if is_new_gateio_reading and ll_pct >= 0.90 and not in_dedup('LQ-1', 8):
        fires.append(SignalFire('LQ-1', 'SHORT', 8))

    # LQ-2: extreme short liq → LONG
    if is_new_gateio_reading and sl_pct >= 0.90 and not in_dedup('LQ-2', 8):
        fires.append(SignalFire('LQ-2', 'LONG', 8))

    # LQ-3: bearish slope flip + elevated long liq → SHORT
    bearish_flip = (slope == -1 and slope_prev != -1)
    if bearish_flip and ll_pct >= 0.70 and not in_dedup('LQ-3', 8):
        fires.append(SignalFire('LQ-3', 'SHORT', 8))

    # VS-3: any slope flip + high volume + elevated total liq → direction of flip
    any_flip = (slope != slope_prev and slope != 0)
    if any_flip and vol_pct >= 0.80 and tl_pct >= 0.70 and not in_dedup('VS-3', 12):
        direction = 'LONG' if slope == 1 else 'SHORT'
        fires.append(SignalFire('VS-3', direction, 12))

    return fires
```

---

## 11. Trade Lifecycle (trade_manager.py)

1. Signal fires → `open_trade()`: insert row to `paper_trades` (status='OPEN'),
   update `signal_state.open_trade_id` and `last_fire_ts`
2. On each new 5m bar → check all open trades for expiry:
   `if (current_ts - entry_ts) >= hold_bars * 300: close_trade()`
3. `close_trade()`:
   - `direction_sign = +1 if LONG else -1`
   - `gross_bps = (exit_price / entry_price - 1) * 10000 * direction_sign`
   - Update row: status='CLOSED', exit_ts, exit_price, gross_bps
   - Clear `signal_state.open_trade_id`
   - Push `trade_close` WebSocket event to all connected clients
4. Multiple signals open simultaneously is fine — each is independent.
   One open trade per signal at a time (enforced via `signal_state.open_trade_id`).

---

## 12. FastAPI Endpoints (main.py)

```
# WebSocket — real-time push to browser
WS  /ws

# REST — initial page load data
GET /api/candles?symbol=BTC-USD&limit=576   → last 48h of candles (JSON)
GET /api/trades?status=all&limit=100        → recent paper trades (JSON)
GET /api/signals                            → current signal state + latest features

# Serve React build
GET /*  →  frontend/dist/index.html + assets
```

### WebSocket event types (server → browser)

Define these in `frontend/src/types.ts`:

```typescript
export type CandleEvent = {
  type: 'candle'
  symbol: 'BTC-USD' | 'ETH-USD'
  ts: number
  open: number; high: number; low: number; close: number; volume: number
}

export type FeatureUpdateEvent = {
  type: 'feature_update'
  eth_slope_sign: number       // -1, 0, or 1
  volume_btc_pct: number       // 0.0–1.0
  long_liq_btc_pct: number
  short_liq_btc_pct: number
  total_liq_btc_pct: number
}

export type SignalFireEvent = {
  type: 'signal_fire'
  signal: 'LQ-1' | 'LQ-2' | 'LQ-3' | 'VS-3'
  direction: 'LONG' | 'SHORT'
  entry_price: number
  ts: number
}

export type TradeCloseEvent = {
  type: 'trade_close'
  signal: string
  direction: 'LONG' | 'SHORT'
  entry_price: number
  exit_price: number
  gross_bps: number
  ts: number
}

export type WSEvent = CandleEvent | FeatureUpdateEvent | SignalFireEvent | TradeCloseEvent
```

---

## 13. React Frontend

### `useWebSocket.ts`
- Connect to `ws://{host}/ws` on mount
- Auto-reconnect with exponential backoff on disconnect (1s, 2s, 4s... max 30s)
- Parse incoming JSON as `WSEvent`, dispatch to component state via callbacks or context

### `Chart.tsx` — TradingView Lightweight Charts
- `npm install lightweight-charts`
- Mount via `useEffect` + `useRef` (vanilla JS library, not a React component):
  ```typescript
  const chartRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const chart = createChart(chartRef.current!, { ... })
    const series = chart.addCandlestickSeries()
    // fetch initial candles from GET /api/candles, call series.setData()
    // on new CandleEvent from WS: series.update(candle)
    // on SignalFireEvent: series.setMarkers([...markers, newMarker])
  }, [])
  ```
- Trade markers:
  - LONG entry: `{ shape: 'arrowUp', color: 'green', position: 'belowBar' }`
  - SHORT entry: `{ shape: 'arrowDown', color: 'red', position: 'aboveBar' }`
  - Trade close: `{ shape: 'circle', color: 'gray', position: 'inBar' }`

### `SignalPanel.tsx`
Four cards, one per signal (LQ-1, LQ-2, LQ-3, VS-3). Each shows:
- Signal name + one-line description
- Relevant feature values as progress bars (e.g. `long_liq_btc_pct` for LQ-1)
- Last fired timestamp (or "Never")
- Status badge: **ACTIVE** (trade open) / **WATCHING** / **COOLING DOWN** (in dedup)

Update in real-time from `FeatureUpdateEvent` and `SignalFireEvent`.

### `TradeLog.tsx`
Table with two tabs: **Open Trades** | **Closed Trades**

Columns: Signal | Direction | Entry Time | Entry Price | Exit Price | Duration | Gross (bps)
- Gross bps: green text if positive, red if negative
- Closed trades: most recent first
- Show rolling stats below the table: total trades, win rate, mean bps

---

## 14. Docker Setup

### Dockerfile
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY frontend/dist/ ./frontend/dist/

EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### docker-compose.yml
```yaml
version: "3.9"

services:
  paper-trader:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - /data/paper-trader:/data    # EBS volume mounted on EC2 at /data/paper-trader
    environment:
      - DB_PATH=/data/paper_trader.db
    restart: unless-stopped
```

### .env.example
```
DB_PATH=/data/paper_trader.db
COINBASE_API_KEY=organizations/.../apiKeys/...
COINBASE_API_SECRET=-----BEGIN EC PRIVATE KEY-----\n...\n-----END EC PRIVATE KEY-----
```

Gate.io contract_stats is a public unauthenticated endpoint — no key needed.
Coinbase requires authentication for both the REST candles endpoint and WebSocket.

---

## 15. requirements.txt (backend)

```
fastapi>=0.111.0
uvicorn[standard]>=0.30.0
aiosqlite>=0.20.0
apscheduler>=3.10.0
websockets>=12.0
httpx>=0.27.0
pandas>=2.0.0
numpy>=1.26.0
python-dotenv>=1.0.0
```

---

## 16. Build Order

Build and test each piece before moving on:

1. **`db.py`** — Schema creation, insert/query helpers. Test with a small script.
2. **`feeds/gateio.py`** — Fetch + print one page of historical liq. Verify field names.
3. **`feeds/coinbase_ws.py`** — Connect, receive a few candle events, print them.
   Test reconnect behavior.
4. **`features.py`** — Compute on static data. Verify slope signs flip at sensible
   times, pct ranks are in [0.0, 1.0].
5. **`signals.py`** — Unit test all 4 rules with hardcoded feature values that should
   and shouldn't trigger each signal.
6. **`trade_manager.py`** — Open, hold, and close a paper trade end-to-end in SQLite.
7. **`main.py`** — Wire bootstrap + WS feed + signal engine + trade manager together.
   Verify candles flow all the way through and WS events reach a browser tab.
8. **Frontend** — Build components one at a time: Chart → SignalPanel → TradeLog.
   Connect `useWebSocket` last.
9. **Dockerfile + docker-compose** — Build image, run locally, verify. Then deploy
   to EC2 as a new container alongside the existing one.

---

## 17. What Success Looks Like

Over 4–8 weeks of paper trading, the app is working correctly when:
- LQ-1 and LQ-2 fire **~4–5x/day each**
- LQ-3 fires **~3–5x/week**
- VS-3 fires **~1–2x/week**
- Mean gross returns per trade land near backtested values:
  - LQ-1: 15–25 bps/trade
  - LQ-2: 10–20 bps/trade
  - LQ-3: 25–35 bps/trade
  - VS-3: 45–65 bps/trade

If returns consistently match these ranges, the backtested edge is confirmed live
and the signals are candidates for real capital deployment. If they diverge
significantly, investigate feature computation first (percentile ranks are the
most likely source of bugs).
