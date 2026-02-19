import argparse

import pandas as pd

from app.config import get_settings
from app.data.db import connect
from app.db.market_data import load_symbol_candles_with_features_last_days


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sanity report for candles/features.")
    parser.add_argument("--dsn", type=str, default="", help="Optional Postgres DSN for rc schema")
    parser.add_argument("--days", type=int, default=30, help="Lookback days when using rc schema")
    return parser.parse_args()


def main(dsn: str = "", days: int = 30) -> None:
    if dsn:
        joined = load_symbol_candles_with_features_last_days(
            dsn=dsn,
            venue_code="coinbase",
            symbol_code="BTC-USD",
            timeframe_code="5m",
            days=days,
        ).tail(500)
        candles = joined[["ts", "open", "high", "low", "close", "volume"]].copy()
        features = joined[["ts", "atr14", "er20", "rv48", "vwap48"]].copy()
    else:
        settings = get_settings()
        conn = connect(settings.db_path)

        candles = pd.read_sql_query(
            "SELECT ts, open, high, low, close, volume FROM candles_5m ORDER BY ts DESC LIMIT 500",
            conn,
        )
        features = pd.read_sql_query(
            "SELECT ts, atr14, er20, rv48, vwap48 FROM features_5m ORDER BY ts DESC LIMIT 500",
            conn,
        )
        joined = candles.merge(features, on="ts", how="left")

    if candles.empty:
        print("no candles found")
        return

    print(f"candles: rows={len(candles)} range={candles['ts'].min()}..{candles['ts'].max()}")
    if features.empty:
        print("no features found")
        return

    if not dsn:
        joined = candles.merge(features, on="ts", how="left")
    missing = joined["atr14"].isna().sum()
    print(f"features: rows={len(features)} missing_in_join={missing}")

    for col in ["atr14", "er20", "rv48", "vwap48"]:
        series = joined[col].dropna()
        if series.empty:
            print(f"{col}: no values")
            continue
        print(
            f"{col}: min={series.min():.6f} max={series.max():.6f} mean={series.mean():.6f}"
        )

    # quick plausibility checks
    latest = joined.dropna().head(1)
    if not latest.empty:
        atr = latest["atr14"].iloc[0]
        er = latest["er20"].iloc[0]
        rv = latest["rv48"].iloc[0]
        vwap = latest["vwap48"].iloc[0]
        close = latest["close"].iloc[0]
        flags = []
        if not (0 <= er <= 1):
            flags.append("er_out_of_bounds")
        if atr <= 0 or rv <= 0:
            flags.append("atr_or_rv_nonpositive")
        if vwap <= 0 or close <= 0:
            flags.append("vwap_or_close_nonpositive")
        print(f"latest_flags: {','.join(flags) if flags else 'ok'}")


if __name__ == "__main__":
    args = parse_args()
    main(args.dsn, args.days)
