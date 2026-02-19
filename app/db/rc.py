from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

try:
    import psycopg
except Exception as err:  # pragma: no cover
    raise RuntimeError("psycopg is required for rc Postgres access") from err


@dataclass
class SymbolRef:
    symbol_id: int
    symbol_code: str


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect(dsn: str):
    return psycopg.connect(dsn)


def get_venue_id(conn, venue_code: str) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT venue_id FROM rc.venues WHERE venue_code = %s", (venue_code,))
        row = cur.fetchone()
    if not row:
        raise ValueError(f"Unknown venue_code: {venue_code}")
    return int(row[0])


def get_timeframe_id(conn, timeframe_code: str) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT timeframe_id FROM rc.timeframes WHERE timeframe_code = %s", (timeframe_code,))
        row = cur.fetchone()
    if not row:
        raise ValueError(f"Unknown timeframe_code: {timeframe_code}")
    return int(row[0])


def get_symbols(conn, venue_id: int, symbol_codes: list[str]) -> list[SymbolRef]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT symbol_id, symbol_code
            FROM rc.symbols
            WHERE venue_id = %s AND symbol_code = ANY(%s)
            ORDER BY symbol_code
            """,
            (venue_id, symbol_codes),
        )
        rows = cur.fetchall()
    refs = [SymbolRef(symbol_id=int(r[0]), symbol_code=str(r[1])) for r in rows]
    have = {r.symbol_code for r in refs}
    missing = sorted(set(symbol_codes) - have)
    if missing:
        raise ValueError(f"Missing symbols in rc.symbols: {missing}")
    return refs


def create_ingest_run(conn, venue_id: int, source_name: str, trigger_type: str, metadata: dict[str, Any]) -> int:
    started_at = utc_now_iso()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO rc.ingest_runs (
                venue_id, source_name, trigger_type, started_at, status, metadata
            )
            VALUES (%s, %s, %s, %s, 'running', %s::jsonb)
            RETURNING ingest_run_id
            """,
            (venue_id, source_name, trigger_type, started_at, __import__("json").dumps(metadata, sort_keys=True)),
        )
        row = cur.fetchone()
    conn.commit()
    return int(row[0])


def complete_ingest_run(
    conn,
    ingest_run_id: int,
    status: str,
    symbols_count: int,
    rows_inserted: int,
    rows_upserted: int,
    rows_rejected: int,
    error_message: str | None,
    metadata: dict[str, Any],
) -> None:
    completed_at = utc_now_iso()
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE rc.ingest_runs
            SET
                completed_at = %s,
                status = %s,
                symbols_count = %s,
                rows_inserted = %s,
                rows_upserted = %s,
                rows_rejected = %s,
                error_message = %s,
                metadata = metadata || %s::jsonb
            WHERE ingest_run_id = %s
            """,
            (
                completed_at,
                status,
                symbols_count,
                rows_inserted,
                rows_upserted,
                rows_rejected,
                error_message,
                __import__("json").dumps(metadata, sort_keys=True),
                ingest_run_id,
            ),
        )
    conn.commit()


def fetch_existing_ts(conn, symbol_id: int, timeframe_id: int, ts_list: list[datetime]) -> set[datetime]:
    if not ts_list:
        return set()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ts
            FROM rc.candles
            WHERE symbol_id = %s AND timeframe_id = %s AND ts = ANY(%s)
            """,
            (symbol_id, timeframe_id, ts_list),
        )
        rows = cur.fetchall()
    return {r[0] for r in rows}


def upsert_candles(conn, symbol_id: int, timeframe_id: int, candles: list[dict[str, Any]], ingest_run_id: int) -> None:
    if not candles:
        return
    rows = [
        (
            symbol_id,
            timeframe_id,
            c["ts_dt"],
            c["open"],
            c["high"],
            c["low"],
            c["close"],
            c["volume"],
            None,
            None,
            ingest_run_id,
        )
        for c in candles
    ]
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO rc.candles (
                symbol_id, timeframe_id, ts, open, high, low, close, volume, vwap, trade_count, ingest_run_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (symbol_id, timeframe_id, ts)
            DO UPDATE SET
                open = EXCLUDED.open,
                high = EXCLUDED.high,
                low = EXCLUDED.low,
                close = EXCLUDED.close,
                volume = EXCLUDED.volume,
                vwap = EXCLUDED.vwap,
                trade_count = EXCLUDED.trade_count,
                ingest_run_id = EXCLUDED.ingest_run_id
            """,
            rows,
        )
    conn.commit()
