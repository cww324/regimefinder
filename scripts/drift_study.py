import argparse
from typing import List, Tuple

import numpy as np
import pandas as pd

from app.config import get_settings
from app.data.db import connect, init_db


HORIZONS = [5, 10, 20]
ER_BUCKETS = [-np.inf, 0.25, 0.35, 0.45, 0.60, np.inf]
ER_LABELS = ["<0.25", "0.25-0.35", "0.35-0.45", "0.45-0.60", ">0.60"]
BREAKOUT_NS = [12, 24]
BREAKOUT_BUFFERS = [0.0, 0.5]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Structural drift study on 5m data.")
    parser.add_argument("--days", type=int, default=30, help="Lookback window in days.")
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


def er_drift(df: pd.DataFrame) -> pd.DataFrame:
    out_rows = []
    df = df.copy()
    df["er_bucket"] = pd.cut(df["er20"], bins=ER_BUCKETS, labels=ER_LABELS, right=False)
    for bucket in ER_LABELS:
        subset = df[df["er_bucket"] == bucket]
        for h in HORIZONS:
            stats = summarize_returns(forward_returns(subset["close"], h))
            out_rows.append(
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
    return pd.DataFrame(out_rows)


def breakout_events(df: pd.DataFrame) -> pd.DataFrame:
    out_rows = []
    data = df.copy()
    for n in BREAKOUT_NS:
        rolling_high = data["high"].shift(1).rolling(n).max()
        for buf in BREAKOUT_BUFFERS:
            threshold = rolling_high + (data["atr14"] * buf)
            event = data["close"] > threshold
            for h in HORIZONS:
                stats = summarize_returns(forward_returns(data.loc[event, "close"], h))
                out_rows.append(
                    {
                        "N": n,
                        "buffer_atr": buf,
                        "h": h,
                        "n": stats["n"],
                        "mean": stats["mean"],
                        "median": stats["median"],
                        "hit_rate": stats["hit"],
                        "std": stats["std"],
                        "sharpe_like": stats["sharpe"],
                    }
                )
    return pd.DataFrame(out_rows)


def stop_exit_r_stats(df_trades: pd.DataFrame) -> pd.DataFrame:
    stop_trades = df_trades[df_trades["exit_reason"] == "exit_stop_hit"].copy()
    if stop_trades.empty:
        return pd.DataFrame([{"n": 0, "mean_r": 0.0, "median_r": 0.0}])
    return pd.DataFrame(
        [
            {
                "n": len(stop_trades),
                "mean_r": stop_trades["r_multiple"].mean(),
                "median_r": stop_trades["r_multiple"].median(),
            }
        ]
    )


def main(days: int) -> None:
    settings = get_settings()
    conn = connect(settings.db_path)
    init_db(conn)

    cutoff_ts = int(pd.Timestamp.utcnow().timestamp()) - (days * 86400)
    df = pd.read_sql_query(
        """
        SELECT c.ts, c.open, c.high, c.low, c.close, c.volume,
               f.atr14, f.er20, f.rv48
        FROM candles_5m c
        JOIN features_5m f ON f.ts = c.ts
        WHERE c.ts >= ?
        ORDER BY c.ts
        """,
        conn,
        params=(cutoff_ts,),
    )

    if df.empty:
        print("no data")
        return

    print("ER drift study (forward returns):")
    er_table = er_drift(df)
    print(er_table.to_string(index=False))
    print()

    print("Breakout-event drift study:")
    br_table = breakout_events(df)
    print(br_table.to_string(index=False))
    print()

    trades = pd.read_sql_query(
        """
        SELECT exit_reason, r_multiple
        FROM paper_trades
        WHERE exit_ts >= ?
        ORDER BY exit_ts
        """,
        conn,
        params=(cutoff_ts,),
    )
    print("Stop-exit R stats (given current fill model):")
    print(stop_exit_r_stats(trades).to_string(index=False))


if __name__ == "__main__":
    args = parse_args()
    main(args.days)
