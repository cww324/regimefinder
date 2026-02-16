import time
from datetime import datetime, timezone

from app.config import get_settings
from app.data.db import connect, init_db
from scripts.ingest_5m import main as ingest_main
from scripts.compute_features import main as compute_main
from scripts.run_paper_forward import main as forward_main


def sleep_until_next_bar(granularity_sec: int, safety_lag_sec: int) -> None:
    now = time.time()
    next_bar = ((int(now) // granularity_sec) + 1) * granularity_sec
    wake_at = next_bar + safety_lag_sec
    sleep_for = max(1, wake_at - now)
    time.sleep(sleep_for)


def latest_ts(conn) -> int:
    row = conn.execute("SELECT MAX(ts) AS max_ts FROM candles_5m").fetchone()
    return int(row["max_ts"] or 0)


def main() -> None:
    settings = get_settings()
    conn = connect(settings.db_path)
    init_db(conn)

    while True:
        started = datetime.now(timezone.utc).isoformat()
        last_ts = latest_ts(conn)

        ingest_main()
        compute_main(last_ts if last_ts else 0)
        forward_main()

        ended = datetime.now(timezone.utc).isoformat()
        print(f"loop: start={started} end={ended} last_ts={last_ts}")

        sleep_until_next_bar(settings.granularity_sec, settings.safety_lag_sec)


if __name__ == "__main__":
    main()
