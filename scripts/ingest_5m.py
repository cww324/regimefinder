import argparse
import time
from typing import List, Optional

from app.config import get_settings
from app.data.coinbase_client import fetch_candles
from app.data.db import connect, init_db

MAX_CANDLES_PER_REQ = 350


def align_to_granularity(ts: int, granularity: int) -> int:
    return (ts // granularity) * granularity


def get_last_candle_ts(conn) -> int:
    row = conn.execute("SELECT MAX(ts) AS max_ts FROM candles_5m").fetchone()
    return int(row["max_ts"] or 0)


def get_first_candle_ts(conn) -> int:
    row = conn.execute("SELECT MIN(ts) AS min_ts FROM candles_5m").fetchone()
    return int(row["min_ts"] or 0)


def expected_timestamps(start_ts: int, end_ts: int, step: int) -> List[int]:
    if end_ts < start_ts:
        return []
    return list(range(start_ts, end_ts + 1, step))


def insert_candles(conn, candles: List[dict]) -> int:
    before = conn.execute("SELECT COUNT(*) AS c FROM candles_5m").fetchone()["c"]
    conn.executemany(
        "INSERT OR IGNORE INTO candles_5m (ts, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?)",
        [(c["ts"], c["open"], c["high"], c["low"], c["close"], c["volume"]) for c in candles],
    )
    conn.commit()
    after = conn.execute("SELECT COUNT(*) AS c FROM candles_5m").fetchone()["c"]
    return after - before


def log_data_quality(conn, ts: int, bar_count_ok: bool, data_gap: bool, source_lag_seconds: int, notes: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO data_quality_5m (ts, bar_count_ok, data_gap, source_lag_seconds, notes) VALUES (?, ?, ?, ?, ?)",
        (ts, int(bar_count_ok), int(data_gap), int(source_lag_seconds), notes),
    )
    conn.commit()


def fetch_candles_chunked(settings, start_ts: int, end_ts: int) -> List[dict]:
    candles: List[dict] = []
    step = settings.granularity_sec
    chunk_span = step * (MAX_CANDLES_PER_REQ - 1)
    cur = start_ts
    while cur <= end_ts:
        chunk_end = min(cur + chunk_span, end_ts)
        candles.extend(fetch_candles(settings, cur, chunk_end))
        cur = chunk_end + step
    return candles


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest 5m candles into SQLite.")
    parser.add_argument(
        "--lookback-bars",
        type=int,
        default=200,
        help="Number of 5m bars to backfill when DB is empty.",
    )
    parser.add_argument(
        "--backfill-bars",
        type=int,
        default=0,
        help="Backfill N 5m bars ending at the current last closed bar (even if DB has data).",
    )
    parser.add_argument(
        "--backfill-older-bars",
        type=int,
        default=0,
        help="Backfill N 5m bars ending at the current earliest stored bar.",
    )
    return parser.parse_args()


def main(lookback_bars: Optional[int] = None, backfill_bars: int = 0, backfill_older_bars: int = 0) -> None:
    settings = get_settings()
    conn = connect(settings.db_path)
    init_db(conn)

    now = int(time.time())
    safe_now = now - settings.safety_lag_sec
    last_closed = align_to_granularity(safe_now, settings.granularity_sec)

    last_ts = get_last_candle_ts(conn)
    first_ts = get_first_candle_ts(conn)

    if backfill_older_bars and backfill_older_bars > 0 and first_ts:
        start_ts = first_ts - (settings.granularity_sec * int(backfill_older_bars))
        last_closed = first_ts - settings.granularity_sec
    elif backfill_bars and backfill_bars > 0:
        start_ts = last_closed - (settings.granularity_sec * int(backfill_bars))
    elif last_ts:
        start_ts = last_ts + settings.granularity_sec
    else:
        bars = int(lookback_bars or 200)
        start_ts = last_closed - (settings.granularity_sec * bars)

    if start_ts > last_closed:
        log_data_quality(conn, last_closed, True, False, now - last_closed, "no_new_bars")
        return

    candles = fetch_candles_chunked(settings, start_ts, last_closed)
    if not candles:
        log_data_quality(conn, last_closed, False, True, now - last_closed, "no_candles_returned")
        return

    inserted = insert_candles(conn, candles)

    expected = expected_timestamps(start_ts, last_closed, settings.granularity_sec)
    received = {c["ts"] for c in candles}
    missing = [ts for ts in expected if ts not in received]

    bar_count_ok = len(expected) == len(candles) == len(received)
    data_gap = len(missing) > 0

    notes = f"inserted={inserted},received={len(candles)},missing={len(missing)}"
    log_data_quality(conn, last_closed, bar_count_ok, data_gap, now - last_closed, notes)


if __name__ == "__main__":
    args = parse_args()
    main(args.lookback_bars, args.backfill_bars, args.backfill_older_bars)
