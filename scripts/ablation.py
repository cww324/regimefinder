import argparse
from dataclasses import replace

import pandas as pd

from app.config import get_settings
from app.data.db import connect, init_db
from app.execution.paper import run_trend_level1


COLUMNS = [
    "strategy_name",
    "entry_ts",
    "exit_ts",
    "entry_price",
    "exit_price",
    "breakout_level",
    "er",
    "atr",
    "exit_reason",
    "pnl",
    "pnl_pct",
    "qty",
    "risk_usd",
    "stop_dist",
    "entry_cost",
    "exit_cost",
    "total_cost",
    "equity_before",
    "equity_after",
    "r_multiple",
    "mae_r",
    "mfe_r",
    "bars_to_stop",
    "stop_price_used",
    "exit_price_used",
    "risk_per_unit",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run ablation backtests.")
    parser.add_argument("--days", type=int, default=14, help="Lookback window in days.")
    return parser.parse_args()


def max_loss_streak(pnls):
    streak = 0
    max_streak = 0
    for pnl in pnls:
        if pnl <= 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    return max_streak


def summarize(df: pd.DataFrame, granularity_sec: int):
    if df.empty:
        return {
            "trades": 0,
            "win_rate": 0.0,
            "avg_r": 0.0,
            "total_r": 0.0,
            "max_loss_streak": 0,
            "avg_hold": 0.0,
            "mae_mean": 0.0,
            "mae_median": 0.0,
            "mfe_mean": 0.0,
            "mfe_median": 0.0,
            "stop_rate": 0.0,
            "median_bars_to_stop": 0.0,
            "stop_buckets": "-",
        }

    trades = len(df)
    win_rate = (df["pnl"] > 0).mean()
    avg_r = df["r_multiple"].mean()
    total_r = df["r_multiple"].sum()
    max_ls = max_loss_streak(df["pnl"].tolist())
    avg_hold = (df["exit_ts"] - df["entry_ts"]).mean() / granularity_sec
    mae_mean = df["mae_r"].mean()
    mae_median = df["mae_r"].median()
    mfe_mean = df["mfe_r"].mean()
    mfe_median = df["mfe_r"].median()

    stop_trades = df[df["exit_reason"] == "exit_stop_hit"].copy()
    stop_rate = len(stop_trades) / trades if trades else 0.0
    median_bars_to_stop = stop_trades["bars_to_stop"].median() if not stop_trades.empty else 0.0
    buckets = {
        "1": (stop_trades["bars_to_stop"] == 1).sum(),
        "2-3": stop_trades["bars_to_stop"].between(2, 3).sum(),
        "4-6": stop_trades["bars_to_stop"].between(4, 6).sum(),
        "7-10": stop_trades["bars_to_stop"].between(7, 10).sum(),
        "11-20": stop_trades["bars_to_stop"].between(11, 20).sum(),
        "21+": (stop_trades["bars_to_stop"] >= 21).sum(),
    }
    stop_buckets = ", ".join([f"{k}={v}" for k, v in buckets.items()])

    return {
        "trades": trades,
        "win_rate": win_rate,
        "avg_r": avg_r,
        "total_r": total_r,
        "max_loss_streak": max_ls,
        "avg_hold": avg_hold,
        "mae_mean": mae_mean,
        "mae_median": mae_median,
        "mfe_mean": mfe_mean,
        "mfe_median": mfe_median,
        "stop_rate": stop_rate,
        "median_bars_to_stop": median_bars_to_stop,
        "stop_buckets": stop_buckets,
    }


def run_case(df: pd.DataFrame, settings, label: str):
    trades = run_trend_level1(df, settings)
    if trades:
        out = pd.DataFrame(trades, columns=COLUMNS)
    else:
        out = pd.DataFrame(columns=COLUMNS)
    stats = summarize(out, settings.granularity_sec)
    return label, stats


def main(days: int) -> None:
    settings = get_settings()
    conn = connect(settings.db_path)
    init_db(conn)

    cutoff_ts = int(pd.Timestamp.utcnow().timestamp()) - (days * 86400)
    df = pd.read_sql_query(
        """
        SELECT c.ts, c.open, c.high, c.low, c.close, c.volume,
               f.atr14, f.er20, f.rv48, f.vwap48
        FROM candles_5m c
        JOIN features_5m f ON f.ts = c.ts
        WHERE c.ts >= ?
        ORDER BY c.ts
        """,
        conn,
        params=(cutoff_ts,),
    )

    cases = [
        ("A) baseline", settings),
        (
            "B) buffer+close",
            replace(settings, breakout_atr_buffer=0.5, breakout_requires_close=True),
        ),
        (
            "C) + ER min",
            replace(
                settings,
                breakout_atr_buffer=0.5,
                breakout_requires_close=True,
                entry_er_min=0.45,
            ),
        ),
        (
            "D) + RV skip",
            replace(
                settings,
                breakout_atr_buffer=0.5,
                breakout_requires_close=True,
                entry_er_min=0.45,
                skip_top_decile_rv=True,
            ),
        ),
        (
            "E) + ER band",
            replace(
                settings,
                breakout_atr_buffer=0.5,
                breakout_requires_close=True,
                entry_er_min=0.45,
                skip_top_decile_rv=True,
                er_no_trade_band_low=0.35,
                er_no_trade_band_high=0.45,
            ),
        ),
        (
            "F) + Retest",
            replace(
                settings,
                breakout_atr_buffer=0.5,
                breakout_requires_close=True,
                entry_er_min=0.45,
                skip_top_decile_rv=True,
                er_no_trade_band_low=0.35,
                er_no_trade_band_high=0.45,
                enable_retest=True,
                retest_atr_band=0.2,
                retest_max_bars=6,
            ),
        ),
        (
            "G) + EMA confirm",
            replace(
                settings,
                breakout_atr_buffer=0.5,
                breakout_requires_close=True,
                entry_er_min=0.45,
                skip_top_decile_rv=True,
                er_no_trade_band_low=0.35,
                er_no_trade_band_high=0.45,
                require_ema_confirm=True,
                ema_fast_period=20,
                ema_slow_period=50,
                ema_slope_bars=3,
                ema_slope_min=0.0,
            ),
        ),
    ]

    print(
        "label | trades | win% | avgR | totalR | maxLS | avgHold | MAEmean/med | MFEm/med | stopRate | medBarsToStop | stopBuckets"
    )
    for lbl, cfg in cases:
        label, s = run_case(df, cfg, lbl)
        print(
            f"{label} | {s['trades']} | {s['win_rate']:.2%} | {s['avg_r']:.3f} | {s['total_r']:.3f} | {s['max_loss_streak']} | {s['avg_hold']:.2f} | "
            f"{s['mae_mean']:.3f}/{s['mae_median']:.3f} | {s['mfe_mean']:.3f}/{s['mfe_median']:.3f} | {s['stop_rate']:.2%} | {s['median_bars_to_stop']:.1f} | {s['stop_buckets']}"
        )


if __name__ == "__main__":
    args = parse_args()
    main(args.days)
