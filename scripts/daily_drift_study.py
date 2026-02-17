import argparse
import numpy as np
import pandas as pd

from app.config import get_settings
from app.data.db import connect, init_db


HORIZONS = [1, 3, 5]
RET_BINS = [-np.inf, -0.05, -0.02, -0.01, 0.0, 0.01, 0.02, 0.05, np.inf]
RET_LABELS = ["<-5%", "-5--2%", "-2--1%", "-1-0%", "0-1%", "1-2%", "2-5%", ">5%"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Daily drift study by prior return bucket.")
    parser.add_argument("--days", type=int, default=720, help="Lookback window in days.")
    parser.add_argument("--save", action="store_true", help="Save outputs to logs/")
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


def main(days: int, save: bool) -> None:
    settings = get_settings()
    conn = connect(settings.db_path)
    init_db(conn)

    cutoff_ts = int(pd.Timestamp.utcnow().timestamp()) - (days * 86400)
    df = pd.read_sql_query(
        """
        SELECT ts, open, high, low, close, volume
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
    df = df.set_index("dt")
    daily = df.resample("1D", label="right", closed="right").agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
    ).dropna().reset_index()
    daily["ret1"] = daily["close"].pct_change()
    daily["ret_bucket"] = pd.cut(daily["ret1"], bins=RET_BINS, labels=RET_LABELS, right=False)

    rows = []
    for bucket in RET_LABELS:
        subset = daily[daily["ret_bucket"] == bucket]
        for h in HORIZONS:
            stats = summarize_returns(forward_returns(subset["close"], h))
            rows.append(
                {
                    "bucket": bucket,
                    "h": h,
                    "n": stats["n"],
                    "mean": stats["mean"],
                    "median": stats["median"],
                    "hit_rate": stats["hit"],
                    "std": stats["std"],
                    "sharpe_like": stats["sharpe"],
                }
            )

    out = pd.DataFrame(rows)
    print(out.to_string(index=False))

    if save:
        import os
        from datetime import datetime, timezone

        os.makedirs("logs", exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out.to_csv(f"logs/daily_drift_{ts}.csv", index=False)
        with open("logs/summary.log", "a", encoding="utf-8") as f:
            f.write(f"[{ts}] daily_drift days={days} rows={len(out)}\n")


if __name__ == "__main__":
    args = parse_args()
    main(args.days, args.save)
