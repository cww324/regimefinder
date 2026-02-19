import argparse
import numpy as np
import pandas as pd

from app.config import get_settings
from app.data.db import connect, init_db
from app.db.market_data import load_symbol_candles_with_features_last_days


HORIZONS = [5, 10, 20]
Z_BUCKETS = [-np.inf, -2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0, np.inf]
Z_LABELS = [
    "<-2.0",
    "-2.0--1.5",
    "-1.5--1.0",
    "-1.0--0.5",
    "-0.5-0.0",
    "0.0-0.5",
    "0.5-1.0",
    "1.0-1.5",
    "1.5-2.0",
    ">2.0",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mean-reversion drift study (VWAP z-score).")
    parser.add_argument("--days", type=int, default=180, help="Lookback window in days.")
    parser.add_argument("--dev-window", type=int, default=48, help="Std window for VWAP deviation.")
    parser.add_argument(
        "--timeframes",
        type=str,
        default="5m,1h,4h",
        help="Comma-separated timeframes (e.g., 5m,1h,4h).",
    )
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


def _resample(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    minutes = 5
    if tf.endswith("m"):
        minutes = int(tf[:-1])
    elif tf.endswith("h"):
        minutes = int(tf[:-1]) * 60
    elif tf.endswith("d"):
        minutes = int(tf[:-1]) * 60 * 24
    rule = f"{minutes}min"
    data = df.copy()
    data["dt"] = pd.to_datetime(data["ts"], unit="s", utc=True)
    data = data.set_index("dt")
    agg = data.resample(rule, label="right", closed="right").agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
    )
    agg = agg.dropna().reset_index()
    agg["ts"] = agg["dt"].astype("int64") // 10**9
    return agg[["ts", "open", "high", "low", "close", "volume"]]


def _compute_vwap(df: pd.DataFrame, window: int) -> pd.Series:
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    vwap_num = (typical * df["volume"]).rolling(window).sum()
    vwap_den = df["volume"].rolling(window).sum()
    return vwap_num / vwap_den.replace(0, np.nan)


def main(days: int, dev_window: int, timeframes: list[str], save: bool, dsn: str = "") -> None:
    if dsn:
        base = load_symbol_candles_with_features_last_days(
            dsn=dsn, venue_code="coinbase", symbol_code="BTC-USD", timeframe_code="5m", days=days
        )[["ts", "open", "high", "low", "close", "volume", "vwap48"]].copy()
    else:
        settings = get_settings()
        conn = connect(settings.db_path)
        init_db(conn)

        cutoff_ts = int(pd.Timestamp.utcnow().timestamp()) - (days * 86400)
        base = pd.read_sql_query(
            """
            SELECT c.ts, c.open, c.high, c.low, c.close, c.volume,
                   f.vwap48
            FROM candles_5m c
            JOIN features_5m f ON f.ts = c.ts
            WHERE c.ts >= ?
            ORDER BY c.ts
            """,
            conn,
            params=(cutoff_ts,),
        )

    if base.empty:
        print("no data")
        return

    for tf in timeframes:
        if tf == "5m":
            df = base.copy()
            df["vwap"] = df["vwap48"]
        else:
            df = _resample(base[["ts", "open", "high", "low", "close", "volume"]], tf)
            df["vwap"] = _compute_vwap(df, 48)

        dev = df["close"] - df["vwap"]
        dev_std = dev.rolling(dev_window).std()
        df["z"] = dev / dev_std.replace(0, np.nan)
        df["z_bucket"] = pd.cut(df["z"], bins=Z_BUCKETS, labels=Z_LABELS, right=False)

        rows = []
        for bucket in Z_LABELS:
            subset = df[df["z_bucket"] == bucket]
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
        print(f"=== Timeframe: {tf} ===")
        print(out.to_string(index=False))
        print()

        if save:
            import os
            from datetime import datetime, timezone
            os.makedirs("logs", exist_ok=True)
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            out.to_csv(f"logs/mr_drift_{tf}_{ts}.csv", index=False)
            with open("logs/summary.log", "a", encoding="utf-8") as f:
                f.write(f"[{ts}] mr_drift tf={tf} days={days} rows={len(out)}\n")


if __name__ == "__main__":
    args = parse_args()
    tfs = [t.strip() for t in args.timeframes.split(",") if t.strip()]
    main(args.days, args.dev_window, tfs, args.save, args.dsn)
