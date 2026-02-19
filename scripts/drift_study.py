import argparse
from typing import List, Tuple

import numpy as np
import pandas as pd

from app.config import get_settings
from app.data.db import connect, init_db
from app.db.market_data import load_symbol_candles_with_features_last_days


HORIZONS = [5, 10, 20]
ER_BUCKETS = [-np.inf, 0.25, 0.35, 0.45, 0.60, np.inf]
ER_LABELS = ["<0.25", "0.25-0.35", "0.35-0.45", "0.45-0.60", ">0.60"]
BREAKOUT_NS = [12, 24]
BREAKOUT_BUFFERS = [0.0, 0.5]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Structural drift study on 5m data.")
    parser.add_argument("--days", type=int, default=30, help="Lookback window in days.")
    parser.add_argument(
        "--timeframes",
        type=str,
        default="5m,15m,1h",
        help="Comma-separated timeframes (e.g., 5m,15m,1h).",
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


def _compute_features(df: pd.DataFrame) -> pd.DataFrame:
    data = df.copy()
    data = data.sort_values("ts")
    close = data["close"].astype(float)
    high = data["high"].astype(float)
    low = data["low"].astype(float)
    volume = data["volume"].astype(float)

    data["r1"] = np.log(close / close.shift(1))
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    data["atr14"] = tr.rolling(14).mean()
    n_er = 20
    net = (close - close.shift(n_er)).abs()
    gross = close.diff().abs().rolling(n_er).sum()
    data["er20"] = net / gross.replace(0, np.nan)
    data["rv48"] = data["r1"].rolling(48).std()
    data["volume"] = volume
    return data


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


def main(days: int, timeframes: List[str], save: bool, dsn: str = "") -> None:
    if dsn:
        base = load_symbol_candles_with_features_last_days(
            dsn=dsn, venue_code="coinbase", symbol_code="BTC-USD", timeframe_code="5m", days=days
        )[["ts", "open", "high", "low", "close", "volume", "atr14", "er20", "rv48"]].copy()
        conn = None
    else:
        settings = get_settings()
        conn = connect(settings.db_path)
        init_db(conn)

        cutoff_ts = int(pd.Timestamp.utcnow().timestamp()) - (days * 86400)
        base = pd.read_sql_query(
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

    if base.empty:
        print("no data")
        return

    for tf in timeframes:
        if tf == "5m":
            df = base.copy()
        else:
            df = _resample(base[["ts", "open", "high", "low", "close", "volume"]], tf)
            df = _compute_features(df)

        print(f"=== Timeframe: {tf} ===")
        print("ER drift study (forward returns):")
        er_table = er_drift(df)
        print(er_table.to_string(index=False))
        print()

        print("Breakout-event drift study:")
        br_table = breakout_events(df)
        print(br_table.to_string(index=False))
        print()

        if save:
            import os
            from datetime import datetime, timezone
            os.makedirs("logs", exist_ok=True)
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            er_table.to_csv(f"logs/er_drift_{tf}_{ts}.csv", index=False)
            br_table.to_csv(f"logs/breakout_drift_{tf}_{ts}.csv", index=False)
            with open("logs/summary.log", "a", encoding="utf-8") as f:
                f.write(f"[{ts}] drift_study tf={tf} days={days} rows_er={len(er_table)} rows_br={len(br_table)}\n")

    if conn is not None:
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
    tfs = [t.strip() for t in args.timeframes.split(",") if t.strip()]
    save = args.save
    main(args.days, tfs, save, args.dsn)
