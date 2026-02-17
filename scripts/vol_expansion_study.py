import argparse
import numpy as np
import pandas as pd

from app.config import get_settings
from app.data.db import connect, init_db


HORIZONS = [5, 10, 20]
EVENTS = [
    ("rv_low_10", 0.10),
    ("rv_low_20", 0.20),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Volatility expansion drift study.")
    parser.add_argument("--days", type=int, default=180, help="Lookback window in days.")
    parser.add_argument("--window", type=int, default=2000, help="Rolling window for percentile.")
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


def main(days: int, window: int, save: bool) -> None:
    settings = get_settings()
    conn = connect(settings.db_path)
    init_db(conn)

    cutoff_ts = int(pd.Timestamp.utcnow().timestamp()) - (days * 86400)
    df = pd.read_sql_query(
        """
        SELECT c.ts, c.close, f.rv48
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

    rv = df["rv48"]
    rv_pct = rv.rolling(window).apply(lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False)
    df["rv_pct"] = rv_pct
    df["rv_rising"] = df["rv48"] > df["rv48"].shift(1)

    rows = []
    for label, pct in EVENTS:
        low = df["rv_pct"] <= pct
        for rising in [False, True]:
            mask = low & (df["rv_rising"] if rising else True)
            tag = f"{label}_rising" if rising else label
            for h in HORIZONS:
                stats = summarize_returns(forward_returns(df.loc[mask, "close"], h))
                rows.append(
                    {
                        "event": tag,
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
        out.to_csv(f"logs/vol_expansion_{ts}.csv", index=False)
        with open("logs/summary.log", "a", encoding="utf-8") as f:
            f.write(f"[{ts}] vol_expansion days={days} rows={len(out)} window={window}\n")


if __name__ == "__main__":
    args = parse_args()
    main(args.days, args.window, args.save)
