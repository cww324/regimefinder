import argparse
from datetime import datetime, timezone

from app.config import get_settings
from app.data.db import connect, init_db
from app.execution.forward import load_last_processed_ts


def ts_to_iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts else "n/a"


def lag_status(seconds: int) -> str:
    if seconds <= 60:
        return "green"
    if seconds <= 180:
        return "yellow"
    return "red"


def main() -> None:
    settings = get_settings()
    conn = connect(settings.db_path)
    init_db(conn)

    last_candle = conn.execute("SELECT MAX(ts) AS ts FROM candles_5m").fetchone()["ts"] or 0
    last_quality = conn.execute(
        "SELECT * FROM data_quality_5m ORDER BY ts DESC LIMIT 1"
    ).fetchone()

    last_processed_ts = load_last_processed_ts(conn)

    print(f"last_candle_ts: {last_candle} ({ts_to_iso(last_candle)})")
    print(f"forward_last_processed_ts: {last_processed_ts} ({ts_to_iso(last_processed_ts)})")
    now = int(datetime.now(timezone.utc).timestamp())
    next_candle_ts = ((now // settings.granularity_sec) + 1) * settings.granularity_sec
    print(f"expected_next_candle_ts: {next_candle_ts} ({ts_to_iso(next_candle_ts)})")

    if last_quality:
        lag = int(last_quality["source_lag_seconds"])
        print(
            "data_quality: ts={ts} bar_count_ok={b} data_gap={g} source_lag_seconds={lag} lag_status={status} notes={n}".format(
                ts=last_quality["ts"],
                b=last_quality["bar_count_ok"],
                g=last_quality["data_gap"],
                lag=lag,
                status=lag_status(lag),
                n=last_quality["notes"],
            )
        )
    else:
        print("data_quality: n/a")


if __name__ == "__main__":
    main()
