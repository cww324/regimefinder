"""
Backfill Gate.io perpetual futures open interest and liquidation data into Postgres rc schema.

Fetches from Gate.io's public REST API (no API key required, US-accessible):
  - Open interest snapshots (1h resolution)
  - Liquidation volumes by side — long_liq_usd and short_liq_usd (1h windows)

Gate.io is used because Binance geo-blocks US and Hyperliquid has no historical OI/liq API.
Gate.io data goes back to ~Oct 2023, fully covering the Feb 2025 - Feb 2026 research window.

Data stored in:
  rc.open_interest  — oi_contracts (raw Gate.io contract count), oi_usd (USD notional)
  rc.liquidations   — long_liq_usd, short_liq_usd (USD, 1h window)

Usage:
    PYTHONPATH=. .venv/bin/python scripts/backfill_oi_liq_gate.py \\
        --dsn "$RC_DB_DSN" \\
        --days 365

API docs: https://www.gate.io/docs/developers/apiv4/en/#get-futures-stats
"""

import argparse
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg
import requests

GATE_BASE_URL = "https://api.gateio.ws/api/v4"
GATE_CONTRACT_STATS_PATH = "/futures/usdt/contract_stats"

# Gate.io contract name → (rc symbol_code, base_asset, quote_asset)
SYMBOL_MAP: dict[str, tuple[str, str, str]] = {
    "BTC_USDT": ("BTC", "BTC", "USDT"),
    "ETH_USDT": ("ETH", "ETH", "USDT"),
}

VENUE_CODE = "gate_futures"
VENUE_NAME = "Gate.io Perpetual Futures"
VENUE_METADATA = '{"type": "perp_futures", "data_use": "research_signals_only", "auth_required": false, "oi_cadence": "1h", "liq_cadence": "1h"}'

MAX_RECORDS_PER_REQUEST = 2000
DEFAULT_SLEEP_S = 0.3


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Backfill Gate.io OI and liquidation data into Postgres rc schema."
    )
    p.add_argument("--dsn", required=True, help="Postgres DSN")
    p.add_argument("--days", type=int, default=365, help="Lookback window in days (default: 365)")
    p.add_argument(
        "--symbols",
        default="BTC_USDT,ETH_USDT",
        help="Comma-separated Gate.io contract names (default: BTC_USDT,ETH_USDT)",
    )
    p.add_argument("--sleep", type=float, default=DEFAULT_SLEEP_S, help="Sleep between API calls (s)")
    p.add_argument("--trigger", default="manual", help="ingest_runs.trigger_type label")
    return p.parse_args()


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def gate_get(path: str, params: dict[str, Any], sleep_s: float) -> Any:
    """GET from Gate.io API. Raises on non-200."""
    url = GATE_BASE_URL + path
    resp = requests.get(url, params=params, timeout=15, headers={"Accept": "application/json"})
    resp.raise_for_status()
    time.sleep(sleep_s)
    return resp.json()


def fetch_contract_stats(
    contract: str,
    start_ts: int,
    end_ts: int,
    sleep_s: float,
) -> list[dict[str, Any]]:
    """
    Fetch all hourly contract_stats for a contract between start_ts and end_ts (unix seconds).
    Paginates by advancing `from` to last record time + 3600 after each batch.
    Returns list sorted ascending by time.
    """
    records: list[dict[str, Any]] = []
    cursor = start_ts

    while cursor < end_ts:
        batch = gate_get(
            GATE_CONTRACT_STATS_PATH,
            {
                "contract": contract,
                "from": cursor,
                "interval": "1h",
                "limit": MAX_RECORDS_PER_REQUEST,
            },
            sleep_s,
        )
        if not batch:
            break

        for item in batch:
            if item["time"] > end_ts:
                return records
            records.append(item)

        if len(batch) < MAX_RECORDS_PER_REQUEST:
            break

        # Advance by 1h past last record to avoid re-fetching it
        cursor = batch[-1]["time"] + 3600

    return records


def ensure_venue_and_symbols(
    conn: psycopg.Connection,
    contracts: list[str],
) -> tuple[int, dict[str, int]]:
    """
    Upsert gate_futures venue and requested symbols. Returns (venue_id, {contract: symbol_id}).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO rc.venues (venue_code, venue_name, metadata)
            VALUES (%s, %s, %s::jsonb)
            ON CONFLICT (venue_code) DO UPDATE
                SET venue_name = EXCLUDED.venue_name,
                    metadata   = EXCLUDED.metadata
            RETURNING venue_id
            """,
            (VENUE_CODE, VENUE_NAME, VENUE_METADATA),
        )
        venue_id = int(cur.fetchone()[0])
    conn.commit()

    symbol_ids: dict[str, int] = {}
    for contract in contracts:
        symbol_code, base_asset, quote_asset = SYMBOL_MAP[contract]
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO rc.symbols (venue_id, symbol_code, base_asset, quote_asset, status, metadata)
                VALUES (%s, %s, %s, %s, 'active', '{"instrument_type": "perpetual_future", "margin_asset": "USDT"}'::jsonb)
                ON CONFLICT (venue_id, symbol_code) DO UPDATE
                    SET base_asset = EXCLUDED.base_asset,
                        quote_asset = EXCLUDED.quote_asset,
                        status = EXCLUDED.status
                RETURNING symbol_id
                """,
                (venue_id, symbol_code, base_asset, quote_asset),
            )
            symbol_ids[contract] = int(cur.fetchone()[0])
    conn.commit()

    return venue_id, symbol_ids


def create_ingest_run(conn: psycopg.Connection, venue_id: int, trigger: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO rc.ingest_runs
                (venue_id, source_name, trigger_type, started_at, status,
                 symbols_count, rows_inserted, rows_upserted, rows_rejected)
            VALUES (%s, 'gate_oi_liq_backfill', %s, %s, 'running', 0, 0, 0, 0)
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


def upsert_open_interest(
    conn: psycopg.Connection,
    symbol_id: int,
    venue_id: int,
    ingest_run_id: int,
    records: list[dict[str, Any]],
) -> tuple[int, int]:
    """Upsert OI records. Returns (inserted, upserted)."""
    if not records:
        return 0, 0
    inserted = upserted = 0
    with conn.cursor() as cur:
        for rec in records:
            ts_dt = datetime.fromtimestamp(rec["time"], tz=timezone.utc)
            oi_contracts = rec.get("open_interest")
            oi_usd = rec.get("open_interest_usd")
            cur.execute(
                """
                INSERT INTO rc.open_interest
                    (symbol_id, venue_id, ts, oi_contracts, oi_usd, ingest_run_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (symbol_id, venue_id, ts) DO UPDATE
                    SET oi_contracts   = EXCLUDED.oi_contracts,
                        oi_usd         = EXCLUDED.oi_usd,
                        ingest_run_id  = EXCLUDED.ingest_run_id
                RETURNING (xmax = 0) AS was_inserted
                """,
                (symbol_id, venue_id, ts_dt, oi_contracts, oi_usd, ingest_run_id),
            )
            if cur.fetchone()[0]:
                inserted += 1
            else:
                upserted += 1
    conn.commit()
    return inserted, upserted


def upsert_liquidations(
    conn: psycopg.Connection,
    symbol_id: int,
    venue_id: int,
    ingest_run_id: int,
    records: list[dict[str, Any]],
) -> tuple[int, int]:
    """Upsert liquidation records (1h window). Returns (inserted, upserted)."""
    if not records:
        return 0, 0
    inserted = upserted = 0
    with conn.cursor() as cur:
        for rec in records:
            ts_dt = datetime.fromtimestamp(rec["time"], tz=timezone.utc)
            long_liq = rec.get("long_liq_usd", 0) or 0
            short_liq = rec.get("short_liq_usd", 0) or 0
            cur.execute(
                """
                INSERT INTO rc.liquidations
                    (symbol_id, venue_id, ts, window_minutes, long_liq_usd, short_liq_usd, ingest_run_id)
                VALUES (%s, %s, %s, 60, %s, %s, %s)
                ON CONFLICT (symbol_id, venue_id, ts, window_minutes) DO UPDATE
                    SET long_liq_usd   = EXCLUDED.long_liq_usd,
                        short_liq_usd  = EXCLUDED.short_liq_usd,
                        ingest_run_id  = EXCLUDED.ingest_run_id
                RETURNING (xmax = 0) AS was_inserted
                """,
                (symbol_id, venue_id, ts_dt, long_liq, short_liq, ingest_run_id),
            )
            if cur.fetchone()[0]:
                inserted += 1
            else:
                upserted += 1
    conn.commit()
    return inserted, upserted


def main() -> None:
    args = parse_args()
    contracts = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    unknown = [c for c in contracts if c not in SYMBOL_MAP]
    if unknown:
        raise SystemExit(f"Unknown contracts: {unknown}. Supported: {list(SYMBOL_MAP)}")

    now = utc_now()
    start_dt = now - timedelta(days=args.days)
    start_ts = int(start_dt.timestamp())
    end_ts = int(now.timestamp())

    print(f"Backfill window: {start_dt.isoformat()} → {now.isoformat()} ({args.days} days)")
    print(f"Contracts: {contracts}  Venue: {VENUE_CODE}")

    with psycopg.connect(args.dsn) as conn:
        venue_id, symbol_ids = ensure_venue_and_symbols(conn, contracts)
        print(f"venue_id={venue_id}  symbol_ids={symbol_ids}")

        ingest_run_id = create_ingest_run(conn, venue_id, args.trigger)
        print(f"ingest_run_id={ingest_run_id}")

        total_oi_ins = total_oi_ups = 0
        total_liq_ins = total_liq_ups = 0
        symbols_done = 0

        try:
            for contract in contracts:
                symbol_id = symbol_ids[contract]
                print(f"\n--- {contract} (symbol_id={symbol_id}) ---")

                print(f"  Fetching contract_stats (1h, {args.days}d)...")
                records = fetch_contract_stats(contract, start_ts, end_ts, args.sleep)
                print(f"  Got {len(records)} hourly records")

                oi_ins, oi_ups = upsert_open_interest(conn, symbol_id, venue_id, ingest_run_id, records)
                print(f"  OI:  inserted={oi_ins} upserted={oi_ups}")

                liq_ins, liq_ups = upsert_liquidations(conn, symbol_id, venue_id, ingest_run_id, records)
                print(f"  Liq: inserted={liq_ins} upserted={liq_ups}")

                total_oi_ins += oi_ins
                total_oi_ups += oi_ups
                total_liq_ins += liq_ins
                total_liq_ups += liq_ups
                symbols_done += 1

            total_inserted = total_oi_ins + total_liq_ins
            total_upserted = total_oi_ups + total_liq_ups
            complete_ingest_run(
                conn, ingest_run_id, "success",
                symbols_count=symbols_done,
                rows_inserted=total_inserted,
                rows_upserted=total_upserted,
                rows_rejected=0,
            )
            print(f"\nDone.")
            print(f"  OI:  inserted={total_oi_ins} upserted={total_oi_ups}")
            print(f"  Liq: inserted={total_liq_ins} upserted={total_liq_ups}")

        except Exception as exc:
            complete_ingest_run(
                conn, ingest_run_id, "failed",
                symbols_count=symbols_done,
                rows_inserted=total_oi_ins + total_liq_ins,
                rows_upserted=total_oi_ups + total_liq_ups,
                rows_rejected=0,
                error_message=str(exc),
            )
            raise


if __name__ == "__main__":
    main()
