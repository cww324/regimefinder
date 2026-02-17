import argparse
import time
from datetime import datetime, timezone

from app.config import get_settings
from app.data.db import connect, init_db
from scripts.ingest_5m import main as ingest_main


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill 5m candles in chunks.")
    parser.add_argument("--days", type=int, default=30, help="Days to backfill.")
    parser.add_argument("--chunk-bars", type=int, default=300, help="Bars per chunk (<=350 recommended).")
    parser.add_argument("--sleep", type=float, default=0.25, help="Sleep seconds between chunks.")
    parser.add_argument("--log-file", type=str, default="logs/backfill.log", help="Log file path.")
    return parser.parse_args()


def get_first_ts(conn) -> int:
    row = conn.execute("SELECT MIN(ts) AS min_ts FROM candles_5m").fetchone()
    return int(row["min_ts"] or 0)


def align(ts: int, granularity: int) -> int:
    return (ts // granularity) * granularity


def log(msg: str, log_file: str) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    line = f"[{ts}] {msg}"
    print(line)
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def main(days: int, chunk_bars: int, sleep_s: float, log_file: str) -> None:
    settings = get_settings()
    conn = connect(settings.db_path)
    init_db(conn)

    # ensure log dir exists
    log_dir = log_file.rsplit("/", 1)[0] if "/" in log_file else "."
    if log_dir != ".":
        import os
        os.makedirs(log_dir, exist_ok=True)

    now = int(time.time())
    target_ts = align(now - (days * 86400), settings.granularity_sec)
    total_bars = int((align(now, settings.granularity_sec) - target_ts) / settings.granularity_sec)
    start_time = time.time()

    while True:
        first_ts = get_first_ts(conn)
        if first_ts == 0:
            # Empty DB: seed with a chunk ending at last closed
            ingest_main(lookback_bars=min(chunk_bars, days * 288), backfill_bars=0, backfill_older_bars=0)
            log("seeded initial chunk", log_file)
            time.sleep(sleep_s)
            continue

        if first_ts <= target_ts:
            log("backfill complete", log_file)
            break

        remaining_bars = int((first_ts - target_ts) / settings.granularity_sec)
        bars = min(chunk_bars, remaining_bars)
        done_bars = total_bars - remaining_bars
        elapsed = time.time() - start_time
        rate = done_bars / elapsed if elapsed > 0 else 0
        eta = (remaining_bars / rate) if rate > 0 else 0
        log(
            f"backfill chunk: bars={bars} remaining_bars={remaining_bars} done_bars={done_bars} "
            f"rate={rate:.2f} bars/s eta={eta/60:.1f} min",
            log_file,
        )
        ingest_main(lookback_bars=0, backfill_bars=0, backfill_older_bars=bars)
        time.sleep(sleep_s)


if __name__ == "__main__":
    args = parse_args()
    main(args.days, args.chunk_bars, args.sleep, args.log_file)
