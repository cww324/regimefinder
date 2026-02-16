import argparse

import pandas as pd

from app.config import get_settings
from app.data.db import connect, init_db
from app.features.compute import compute_features, to_feature_rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compute features from candles_5m.")
    parser.add_argument(
        "--since-ts",
        type=int,
        default=0,
        help="Only compute features for candles with ts >= since-ts.",
    )
    return parser.parse_args()


def main(since_ts: int) -> None:
    settings = get_settings()
    conn = connect(settings.db_path)
    init_db(conn)

    if since_ts:
        df = pd.read_sql_query(
            "SELECT ts, open, high, low, close, volume FROM candles_5m WHERE ts >= ? ORDER BY ts",
            conn,
            params=(since_ts,),
        )
    else:
        df = pd.read_sql_query(
            "SELECT ts, open, high, low, close, volume FROM candles_5m ORDER BY ts",
            conn,
        )

    features = compute_features(df)
    rows = to_feature_rows(features)

    conn.executemany(
        "INSERT OR REPLACE INTO features_5m (ts, atr14, er20, rv48, vwap48) VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()


if __name__ == "__main__":
    args = parse_args()
    main(args.since_ts)
