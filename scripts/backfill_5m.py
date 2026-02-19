import argparse
import time
from datetime import datetime, timezone
from typing import Any

from app.config import get_settings
from app.data.coinbase_client import fetch_candles
from app.db import rc

MAX_CANDLES_PER_REQ = 350


def align_to_granularity(ts: int, granularity: int) -> int:
    return (ts // granularity) * granularity


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Backfill Coinbase 5m candles into Postgres rc schema.")
    p.add_argument("--dsn", required=True, help="Postgres DSN")
    p.add_argument("--days", type=int, default=180, help="Lookback days")
    p.add_argument("--symbols", default="BTC-USD,ETH-USD", help="Comma-separated Coinbase symbols")
    p.add_argument("--venue", default="coinbase", help="Venue code in rc.venues")
    p.add_argument("--timeframe", default="5m", choices=["5m"], help="Frozen timeframe for phase 2")
    p.add_argument("--sleep", type=float, default=0.15, help="Sleep between API chunks")
    p.add_argument("--trigger", default="manual", help="ingest_runs.trigger_type")
    return p.parse_args()


def chunk_ranges(start_ts: int, end_ts: int, granularity: int):
    span = granularity * (MAX_CANDLES_PER_REQ - 1)
    cur = start_ts
    while cur <= end_ts:
        e = min(end_ts, cur + span)
        yield cur, e
        cur = e + granularity


def to_dt(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc).replace(microsecond=0)


def ingest_symbol(
    conn,
    settings,
    symbol: rc.SymbolRef,
    timeframe_id: int,
    start_ts: int,
    end_ts: int,
    ingest_run_id: int,
    sleep_s: float,
) -> dict[str, Any]:
    inserted = 0
    upserted = 0
    rejected = 0
    min_ts = None
    max_ts = None

    for c_start, c_end in chunk_ranges(start_ts, end_ts, settings.granularity_sec):
        candles = fetch_candles(settings, c_start, c_end, product_id=symbol.symbol_code)

        cleaned: list[dict[str, Any]] = []
        for c in candles:
            ts = int(c["ts"])
            if ts % settings.granularity_sec != 0:
                rejected += 1
                continue
            if ts < c_start or ts > c_end:
                rejected += 1
                continue
            if c["open"] <= 0 or c["high"] <= 0 or c["low"] <= 0 or c["close"] <= 0:
                rejected += 1
                continue
            cleaned.append(
                {
                    "ts": ts,
                    "ts_dt": to_dt(ts),
                    "open": float(c["open"]),
                    "high": float(c["high"]),
                    "low": float(c["low"]),
                    "close": float(c["close"]),
                    "volume": float(c["volume"]),
                }
            )

        ts_dts = [c["ts_dt"] for c in cleaned]
        existing = rc.fetch_existing_ts(conn, symbol.symbol_id, timeframe_id, ts_dts)
        rc.upsert_candles(conn, symbol.symbol_id, timeframe_id, cleaned, ingest_run_id)

        batch_existing = len(existing)
        batch_total = len(cleaned)
        inserted += max(0, batch_total - batch_existing)
        upserted += batch_existing

        if cleaned:
            b_min = min(c["ts"] for c in cleaned)
            b_max = max(c["ts"] for c in cleaned)
            min_ts = b_min if min_ts is None else min(min_ts, b_min)
            max_ts = b_max if max_ts is None else max(max_ts, b_max)

        time.sleep(sleep_s)

    return {
        "symbol": symbol.symbol_code,
        "inserted": inserted,
        "upserted": upserted,
        "rejected": rejected,
        "min_ts": min_ts,
        "max_ts": max_ts,
    }


def main() -> None:
    args = parse_args()
    settings = get_settings()

    if settings.granularity_sec != 300:
        raise SystemExit("CANDLE_GRANULARITY_SEC must be 300 for phase-2 frozen contract.")

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    if not symbols:
        raise SystemExit("No symbols specified.")

    now = int(time.time())
    last_closed = align_to_granularity(now - settings.safety_lag_sec, settings.granularity_sec)
    start_ts = align_to_granularity(last_closed - (args.days * 86400), settings.granularity_sec)

    with rc.connect(args.dsn) as conn:
        venue_id = rc.get_venue_id(conn, args.venue)
        timeframe_id = rc.get_timeframe_id(conn, args.timeframe)
        symbol_refs = rc.get_symbols(conn, venue_id, symbols)

        run_meta = {
            "symbols": symbols,
            "timeframe": args.timeframe,
            "days": args.days,
            "start_ts": to_dt(start_ts).isoformat(),
            "end_ts": to_dt(last_closed).isoformat(),
            "granularity_sec": settings.granularity_sec,
        }
        ingest_run_id = rc.create_ingest_run(
            conn,
            venue_id=venue_id,
            source_name="coinbase_backfill_5m",
            trigger_type=args.trigger,
            metadata=run_meta,
        )

        totals = {"inserted": 0, "upserted": 0, "rejected": 0}
        per_symbol = []

        try:
            for symbol in symbol_refs:
                stats = ingest_symbol(
                    conn,
                    settings=settings,
                    symbol=symbol,
                    timeframe_id=timeframe_id,
                    start_ts=start_ts,
                    end_ts=last_closed,
                    ingest_run_id=ingest_run_id,
                    sleep_s=args.sleep,
                )
                per_symbol.append(stats)
                totals["inserted"] += stats["inserted"]
                totals["upserted"] += stats["upserted"]
                totals["rejected"] += stats["rejected"]

            rc.complete_ingest_run(
                conn,
                ingest_run_id=ingest_run_id,
                status="success",
                symbols_count=len(symbol_refs),
                rows_inserted=totals["inserted"],
                rows_upserted=totals["upserted"],
                rows_rejected=totals["rejected"],
                error_message=None,
                metadata={"per_symbol": per_symbol},
            )

            print(f"ingest_run_id={ingest_run_id}")
            for s in per_symbol:
                print(
                    f"symbol={s['symbol']} inserted={s['inserted']} upserted={s['upserted']} "
                    f"rejected={s['rejected']} min_ts={s['min_ts']} max_ts={s['max_ts']}"
                )
            print(
                f"totals inserted={totals['inserted']} upserted={totals['upserted']} rejected={totals['rejected']}"
            )

        except Exception as err:
            rc.complete_ingest_run(
                conn,
                ingest_run_id=ingest_run_id,
                status="failed",
                symbols_count=len(symbol_refs),
                rows_inserted=totals["inserted"],
                rows_upserted=totals["upserted"],
                rows_rejected=totals["rejected"],
                error_message=str(err),
                metadata={"per_symbol": per_symbol},
            )
            raise


if __name__ == "__main__":
    main()
