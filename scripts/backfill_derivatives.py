"""
Backfill Hyperliquid perpetual futures funding rate data into Postgres rc schema.

Fetches from Hyperliquid's public API (no API key required):
  - Funding rates (1h settlements)

Hyperliquid is used instead of Bybit because Bybit geo-blocks US IPs.
Hyperliquid provides ~12 months of hourly funding history for BTC and ETH.

Usage:
    PYTHONPATH=. .venv/bin/python scripts/backfill_derivatives.py \\
        --dsn "$RC_DB_DSN" \\
        --days 365

API docs: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint
"""

import argparse
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg
import requests

HL_BASE_URL = "https://api.hyperliquid.xyz"
HL_INFO_ENDPOINT = "/info"

# Hyperliquid coin name → rc.symbols symbol_code mapping
# Hyperliquid uses short coin names ("BTC", "ETH") as-is.
SYMBOL_MAP: dict[str, str] = {
    "BTC": "BTC",
    "ETH": "ETH",
}

MAX_RECORDS_PER_REQUEST = 500
DEFAULT_SLEEP_S = 0.2


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Backfill Hyperliquid funding rates into Postgres rc schema."
    )
    p.add_argument("--dsn", required=True, help="Postgres DSN (e.g. postgresql://user:pass@host/db)")
    p.add_argument("--days", type=int, default=365, help="Lookback window in days (default: 365)")
    p.add_argument(
        "--symbols",
        default="BTC,ETH",
        help="Comma-separated Hyperliquid coin names (default: BTC,ETH)",
    )
    p.add_argument("--venue", default="hyperliquid", help="Venue code in rc.venues (default: hyperliquid)")
    p.add_argument("--sleep", type=float, default=DEFAULT_SLEEP_S, help="Sleep between API calls (s)")
    p.add_argument("--trigger", default="manual", help="ingest_runs.trigger_type label")
    return p.parse_args()


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def ms_to_dt(ms: int) -> datetime:
    return datetime.fromtimestamp(int(ms) / 1000.0, tz=timezone.utc).replace(microsecond=0)


def dt_to_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def hl_post(payload: dict[str, Any], sleep_s: float) -> Any:
    """POST to Hyperliquid /info endpoint. Raises on non-200."""
    url = HL_BASE_URL + HL_INFO_ENDPOINT
    resp = requests.post(url, json=payload, timeout=15)
    resp.raise_for_status()
    time.sleep(sleep_s)
    return resp.json()


def fetch_funding_history(
    coin: str,
    start_ms: int,
    end_ms: int,
    sleep_s: float,
) -> list[dict[str, Any]]:
    """
    Fetch all hourly funding rate settlements for a coin between start_ms and end_ms.
    Hyperliquid returns records oldest-first, up to 500 per request.
    Paginates by advancing startTime to max(time)+1 of each batch.
    Returns list sorted ascending by timestamp.
    """
    records: list[dict[str, Any]] = []
    cursor_start_ms = start_ms

    while True:
        payload = {
            "type": "fundingHistory",
            "coin": coin,
            "startTime": cursor_start_ms,
        }
        batch = hl_post(payload, sleep_s)
        if not batch:
            break

        for item in batch:
            ts_ms = int(item["time"])
            if ts_ms > end_ms:
                return records
            records.append({
                "ts_ms": ts_ms,
                "funding_rate": float(item["fundingRate"]),
            })

        if len(batch) < MAX_RECORDS_PER_REQUEST:
            break

        # Advance cursor to just after the last record in this batch
        cursor_start_ms = max(int(r["time"]) for r in batch) + 1

    return records


def resolve_venue_and_symbols(
    conn: psycopg.Connection,
    venue_code: str,
    coins: list[str],
) -> tuple[int, dict[str, int]]:
    """
    Look up venue_id and symbol_ids from rc schema.
    Returns (venue_id, {coin: symbol_id}).
    Raises if venue or any symbol is not found — run db-seed first.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT venue_id FROM rc.venues WHERE venue_code = %s", (venue_code,))
        row = cur.fetchone()
        if not row:
            raise RuntimeError(
                f"Venue '{venue_code}' not found in rc.venues. Run: make db-seed"
            )
        venue_id = int(row[0])

        symbol_ids: dict[str, int] = {}
        for coin in coins:
            symbol_code = SYMBOL_MAP[coin]
            cur.execute(
                "SELECT symbol_id FROM rc.symbols WHERE venue_id = %s AND symbol_code = %s",
                (venue_id, symbol_code),
            )
            row = cur.fetchone()
            if not row:
                raise RuntimeError(
                    f"Symbol '{symbol_code}' not found in rc.symbols for venue '{venue_code}'. "
                    f"Run: make db-seed"
                )
            symbol_ids[coin] = int(row[0])

    return venue_id, symbol_ids


def create_ingest_run(conn: psycopg.Connection, venue_id: int, trigger: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO rc.ingest_runs
                (venue_id, source_name, trigger_type, started_at, status, symbols_count,
                 rows_inserted, rows_upserted, rows_rejected)
            VALUES (%s, 'hyperliquid_funding_backfill', %s, %s, 'running', 0, 0, 0, 0)
            RETURNING ingest_run_id
            """,
            (venue_id, trigger, utc_now()),
        )
        run_id = int(cur.fetchone()[0])
    conn.commit()
    return run_id


def complete_ingest_run(
    conn: psycopg.Connection,
    run_id: int,
    status: str,
    symbols_count: int,
    rows_inserted: int,
    rows_upserted: int,
    rows_rejected: int,
    error_message: str | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE rc.ingest_runs
            SET completed_at   = %s,
                status         = %s,
                symbols_count  = %s,
                rows_inserted  = %s,
                rows_upserted  = %s,
                rows_rejected  = %s,
                error_message  = %s
            WHERE ingest_run_id = %s
            """,
            (
                utc_now(), status, symbols_count,
                rows_inserted, rows_upserted, rows_rejected,
                error_message, run_id,
            ),
        )
    conn.commit()


def upsert_funding_rates(
    conn: psycopg.Connection,
    symbol_id: int,
    venue_id: int,
    ingest_run_id: int,
    records: list[dict[str, Any]],
) -> tuple[int, int]:
    """Upsert funding rate records. Returns (inserted, upserted)."""
    if not records:
        return 0, 0

    inserted = 0
    upserted = 0

    with conn.cursor() as cur:
        for rec in records:
            ts_dt = ms_to_dt(rec["ts_ms"])
            cur.execute(
                """
                INSERT INTO rc.funding_rates
                    (symbol_id, venue_id, ts, funding_rate, ingest_run_id)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (symbol_id, venue_id, ts) DO UPDATE
                    SET funding_rate   = EXCLUDED.funding_rate,
                        ingest_run_id  = EXCLUDED.ingest_run_id
                RETURNING (xmax = 0) AS was_inserted
                """,
                (symbol_id, venue_id, ts_dt, rec["funding_rate"], ingest_run_id),
            )
            row = cur.fetchone()
            if row and row[0]:
                inserted += 1
            else:
                upserted += 1

    conn.commit()
    return inserted, upserted


def main() -> None:
    args = parse_args()
    coins = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    unknown = [c for c in coins if c not in SYMBOL_MAP]
    if unknown:
        raise SystemExit(f"Unknown coins: {unknown}. Supported: {list(SYMBOL_MAP)}")

    now = utc_now()
    start_dt = datetime.fromtimestamp(now.timestamp() - args.days * 86400, tz=timezone.utc)
    start_ms = dt_to_ms(start_dt)
    end_ms = dt_to_ms(now)

    print(f"Backfill window: {start_dt.isoformat()} → {now.isoformat()} ({args.days} days)")
    print(f"Coins: {coins}  Venue: {args.venue}")

    with psycopg.connect(args.dsn) as conn:
        venue_id, symbol_ids = resolve_venue_and_symbols(conn, args.venue, coins)
        ingest_run_id = create_ingest_run(conn, venue_id, args.trigger)
        print(f"ingest_run_id={ingest_run_id}")

        total_inserted = 0
        total_upserted = 0
        total_rejected = 0
        symbols_done = 0

        try:
            for coin in coins:
                symbol_id = symbol_ids[coin]
                print(f"\n--- {coin} (symbol_id={symbol_id}) ---")

                print(f"  Fetching funding rate history...")
                funding_records = fetch_funding_history(coin, start_ms, end_ms, args.sleep)
                print(f"  Got {len(funding_records)} hourly settlements")
                ins, ups = upsert_funding_rates(conn, symbol_id, venue_id, ingest_run_id, funding_records)
                print(f"  Funding: inserted={ins} upserted={ups}")
                total_inserted += ins
                total_upserted += ups

                symbols_done += 1

            complete_ingest_run(
                conn, ingest_run_id, "success",
                symbols_count=symbols_done,
                rows_inserted=total_inserted,
                rows_upserted=total_upserted,
                rows_rejected=total_rejected,
            )
            print(f"\nDone. inserted={total_inserted} upserted={total_upserted}")

        except Exception as exc:
            complete_ingest_run(
                conn, ingest_run_id, "failed",
                symbols_count=symbols_done,
                rows_inserted=total_inserted,
                rows_upserted=total_upserted,
                rows_rejected=total_rejected,
                error_message=str(exc),
            )
            raise


if __name__ == "__main__":
    main()
