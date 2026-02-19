import argparse

from app.features.compute import compute_features, to_feature_rows
from app.db.market_data import load_symbol_ohlcv_last_days, upsert_feature_rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compute features from rc.candles into rc.features.")
    parser.add_argument("--dsn", required=True, help="Postgres DSN")
    parser.add_argument("--venue", default="coinbase")
    parser.add_argument("--symbol", default="BTC-USD")
    parser.add_argument("--timeframe", default="5m", choices=["5m"])
    parser.add_argument("--days", type=int, default=365, help="Load this many days from rc.candles")
    parser.add_argument("--feature-version", default="v1")
    parser.add_argument(
        "--since-ts",
        type=int,
        default=0,
        help="Only keep rows with ts >= since-ts before writing features.",
    )
    return parser.parse_args()


def main(dsn: str, venue: str, symbol: str, timeframe: str, days: int, feature_version: str, since_ts: int) -> None:
    df = load_symbol_ohlcv_last_days(
        dsn=dsn,
        venue_code=venue,
        symbol_code=symbol,
        timeframe_code=timeframe,
        days=days,
    )
    if since_ts:
        df = df[df["ts"] >= int(since_ts)].copy()

    features = compute_features(df)
    rows = to_feature_rows(features)
    writes = upsert_feature_rows(
        dsn=dsn,
        venue_code=venue,
        symbol_code=symbol,
        timeframe_code=timeframe,
        rows=rows,
        feature_version=feature_version,
    )
    print(f"symbol={symbol} rows_in={len(df)} feature_rows={len(rows)} writes={writes}")


if __name__ == "__main__":
    args = parse_args()
    main(
        dsn=args.dsn,
        venue=args.venue,
        symbol=args.symbol,
        timeframe=args.timeframe,
        days=args.days,
        feature_version=args.feature_version,
        since_ts=args.since_ts,
    )
