import argparse
from datetime import datetime, timezone

from app.config import get_settings
from app.data.db import connect, init_db
from app.execution.forward import load_last_processed_ts
from app.db import rc


def ts_to_iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts else "n/a"


def lag_status(seconds: int) -> str:
    if seconds <= 60:
        return "green"
    if seconds <= 180:
        return "yellow"
    return "red"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Health check for market data ingestion.")
    parser.add_argument("--dsn", type=str, default="", help="Optional Postgres DSN for rc schema")
    return parser.parse_args()


def main(dsn: str = "") -> None:
    settings = get_settings()

    if dsn:
        with rc.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT EXTRACT(EPOCH FROM MAX(c.ts))::bigint
                    FROM rc.candles c
                    JOIN rc.symbols s ON s.symbol_id = c.symbol_id
                    JOIN rc.venues v ON v.venue_id = s.venue_id
                    JOIN rc.timeframes tf ON tf.timeframe_id = c.timeframe_id
                    WHERE v.venue_code = 'coinbase'
                      AND s.symbol_code = 'BTC-USD'
                      AND tf.timeframe_code = '5m'
                    """
                )
                row = cur.fetchone()
                last_candle = int(row[0] or 0)
                cur.execute(
                    """
                    SELECT ingest_run_id, status, started_at, completed_at, rows_inserted, rows_upserted, rows_rejected, error_message
                    FROM rc.ingest_runs
                    ORDER BY ingest_run_id DESC
                    LIMIT 1
                    """
                )
                last_ingest = cur.fetchone()
        last_processed_ts = 0
    else:
        conn = connect(settings.db_path)
        init_db(conn)
        last_candle = conn.execute("SELECT MAX(ts) AS ts FROM candles_5m").fetchone()["ts"] or 0
        last_quality = conn.execute("SELECT * FROM data_quality_5m ORDER BY ts DESC LIMIT 1").fetchone()
        last_processed_ts = load_last_processed_ts(conn)
        last_ingest = None

    print(f"last_candle_ts: {last_candle} ({ts_to_iso(last_candle)})")
    print(f"forward_last_processed_ts: {last_processed_ts} ({ts_to_iso(last_processed_ts)})")
    now = int(datetime.now(timezone.utc).timestamp())
    next_candle_ts = ((now // settings.granularity_sec) + 1) * settings.granularity_sec
    print(f"expected_next_candle_ts: {next_candle_ts} ({ts_to_iso(next_candle_ts)})")

    if dsn:
        if last_ingest:
            rid, status, started_at, completed_at, rows_ins, rows_up, rows_rej, err = last_ingest
            print(
                "ingest_run: id={rid} status={status} started_at={started_at} completed_at={completed_at} "
                "rows_inserted={rows_ins} rows_upserted={rows_up} rows_rejected={rows_rej} error={err}".format(
                    rid=rid,
                    status=status,
                    started_at=started_at,
                    completed_at=completed_at,
                    rows_ins=rows_ins,
                    rows_up=rows_up,
                    rows_rej=rows_rej,
                    err=err,
                )
            )
        else:
            print("ingest_run: n/a")
    else:
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
    args = parse_args()
    main(args.dsn)
