# Data Contract (Phase 2)

Status: frozen for current ingestion rollout.

## Scope
- Canonical timeframe: `5m` only.
- Source: Coinbase Advanced Trade candles API.
- All timestamps stored in UTC and aligned to 5-minute boundaries.

## Keys and Idempotency
- Canonical uniqueness key for candles in `rc.candles`: `(symbol_id, timeframe_id, ts)`.
- Venue identity is carried by `symbol_id -> rc.symbols.venue_id`.
- Duplicate handling: `INSERT ... ON CONFLICT (symbol_id, timeframe_id, ts) DO UPDATE`.

## Candle Data Rules
- Do not fabricate candles.
- Persist only what Coinbase returns.
- Missing intervals are allowed and represent source truth for that request window.

## Ingestion Lineage
- Every backfill run must create a row in `rc.ingest_runs` with status `running` at start.
- On completion, update that row to `success` or `failed` with:
  - row counts (`rows_inserted`, `rows_upserted`, `rows_rejected`)
  - time bounds and metadata
  - optional checksum

## Current Symbol Set
- `BTC-USD`
- `ETH-USD`

Additional symbols are added via `rc.symbols` seed/migration only.
