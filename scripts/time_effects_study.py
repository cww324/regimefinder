import argparse
import numpy as np
import pandas as pd

from app.config import get_settings
from app.data.db import connect, init_db
from app.db.market_data import load_symbol_candles_last_days


HORIZONS = [5, 10, 20]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Time-of-day / day-of-week drift study.")
    parser.add_argument("--days", type=int, default=180, help="Lookback window in days.")
    parser.add_argument("--save", action="store_true", help="Save outputs to logs/")
    parser.add_argument("--dsn", type=str, default="", help="Optional Postgres DSN for rc schema")
    return parser.parse_args()


def forward_returns(close: pd.Series, h: int) -> pd.Series:
    return close.shift(-h) / close - 1.0


def summarize_returns(returns: pd.Series) -> dict:
    returns = returns.dropna()
    if returns.empty:
        return {"mean": 0.0, "median": 0.0, "hit": 0.0, "std": 0.0, "sharpe": 0.0, "n": 0}
    mean = returns.mean()
    std = returns.std(ddof=0)
    return {
        "mean": mean,
        "median": returns.median(),
        "hit": (returns > 0).mean(),
        "std": std,
        "sharpe": (mean / std) if std > 0 else 0.0,
        "n": len(returns),
    }


def main(days: int, save: bool, dsn: str = "") -> None:
    if dsn:
        df = load_symbol_candles_last_days(
            dsn=dsn, venue_code="coinbase", symbol_code="BTC-USD", timeframe_code="5m", days=days
        )[["ts", "close"]].copy()
    else:
        settings = get_settings()
        conn = connect(settings.db_path)
        init_db(conn)

        cutoff_ts = int(pd.Timestamp.utcnow().timestamp()) - (days * 86400)
        df = pd.read_sql_query(
            """
            SELECT ts, close
            FROM candles_5m
            WHERE ts >= ?
            ORDER BY ts
            """,
            conn,
            params=(cutoff_ts,),
        )

    if df.empty:
        print("no data")
        return

    df["dt"] = pd.to_datetime(df["ts"], unit="s", utc=True)
    df["hour"] = df["dt"].dt.hour
    df["dow"] = df["dt"].dt.dayofweek  # Mon=0

    rows_hour = []
    for hour in range(24):
        subset = df[df["hour"] == hour]
        for h in HORIZONS:
            stats = summarize_returns(forward_returns(subset["close"], h))
            rows_hour.append(
                {
                    "hour": hour,
                    "h": h,
                    "n": stats["n"],
                    "mean": stats["mean"],
                    "median": stats["median"],
                    "hit_rate": stats["hit"],
                    "std": stats["std"],
                    "sharpe_like": stats["sharpe"],
                }
            )

    rows_dow = []
    for dow in range(7):
        subset = df[df["dow"] == dow]
        for h in HORIZONS:
            stats = summarize_returns(forward_returns(subset["close"], h))
            rows_dow.append(
                {
                    "dow": dow,
                    "h": h,
                    "n": stats["n"],
                    "mean": stats["mean"],
                    "median": stats["median"],
                    "hit_rate": stats["hit"],
                    "std": stats["std"],
                    "sharpe_like": stats["sharpe"],
                }
            )

    out_hour = pd.DataFrame(rows_hour)
    out_dow = pd.DataFrame(rows_dow)
    print("=== Hour-of-day drift ===")
    print(out_hour.to_string(index=False))
    print()
    print("=== Day-of-week drift (Mon=0) ===")
    print(out_dow.to_string(index=False))

    if save:
        import os
        from datetime import datetime, timezone

        os.makedirs("logs", exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out_hour.to_csv(f"logs/time_drift_hour_{ts}.csv", index=False)
        out_dow.to_csv(f"logs/time_drift_dow_{ts}.csv", index=False)
        with open("logs/summary.log", "a", encoding="utf-8") as f:
            f.write(f"[{ts}] time_effects days={days} rows_hour={len(out_hour)} rows_dow={len(out_dow)}\n")


if __name__ == "__main__":
    args = parse_args()
    main(args.days, args.save, args.dsn)
