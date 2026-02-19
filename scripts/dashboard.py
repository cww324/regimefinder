import argparse
from datetime import datetime, timezone

import pandas as pd
from rich.console import Console
from rich.table import Table

from app.config import get_settings
from app.data.db import connect, init_db
from app.db import rc
from app.strategy.trend import trend_regime


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Trading dashboard.")
    parser.add_argument("--days", type=int, default=30, help="Lookback window in days.")
    parser.add_argument("--last-trades", type=int, default=10, help="Number of last trades to show.")
    parser.add_argument(
        "--strategy-name",
        default="",
        help="Optional strategy_name filter (e.g., h2s_vol_expert_l0_h10).",
    )
    parser.add_argument("--dsn", type=str, default="", help="Optional Postgres DSN for rc schema")
    return parser.parse_args()


def ts_to_iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def max_drawdown(equity):
    peak = equity[0]
    max_dd = 0.0
    for x in equity:
        peak = max(peak, x)
        dd = peak - x
        max_dd = max(max_dd, dd)
    return max_dd


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


def main(days: int, last_trades: int, strategy_name: str, dsn: str = "") -> None:
    settings = get_settings()
    cutoff_ts = int(datetime.now(timezone.utc).timestamp()) - (days * 86400)
    console = Console()

    if dsn:
        cutoff_dt = datetime.fromtimestamp(cutoff_ts, tz=timezone.utc)
        where = "WHERE p.closed_at IS NOT NULL AND p.opened_at >= %s"
        params: list[object] = [cutoff_dt]
        if strategy_name:
            where += " AND h.hypothesis_id = %s"
            params.append(strategy_name)
        with rc.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT
                        p.position_id AS id,
                        EXTRACT(EPOCH FROM p.opened_at)::bigint AS entry_ts,
                        EXTRACT(EPOCH FROM p.closed_at)::bigint AS exit_ts,
                        p.avg_entry_price AS entry_price,
                        p.avg_exit_price AS exit_price,
                        'closed' AS exit_reason,
                        COALESCE(p.realized_pnl, 0) AS pnl,
                        NULL::double precision AS pnl_pct,
                        p.qty,
                        p.max_adverse_excursion AS mae_r,
                        p.max_favorable_excursion AS mfe_r,
                        NULL::double precision AS er,
                        NULL::double precision AS atr,
                        h.hypothesis_id AS strategy_name
                    FROM rc.paper_positions p
                    JOIN rc.hypotheses h ON h.hypothesis_pk = p.hypothesis_pk
                    {where}
                    ORDER BY p.closed_at
                    """,
                    tuple(params),
                )
                rows = cur.fetchall()
        cols = [
            "id",
            "entry_ts",
            "exit_ts",
            "entry_price",
            "exit_price",
            "exit_reason",
            "pnl",
            "pnl_pct",
            "qty",
            "mae_r",
            "mfe_r",
            "er",
            "atr",
            "strategy_name",
        ]
        trades = pd.DataFrame(rows, columns=cols)
    else:
        conn = connect(settings.db_path)
        init_db(conn)
        if strategy_name:
            trades = pd.read_sql_query(
                """
                SELECT * FROM paper_trades
                WHERE exit_ts >= ? AND strategy_name = ?
                ORDER BY exit_ts
                """,
                conn,
                params=(cutoff_ts, strategy_name),
            )
        else:
            trades = pd.read_sql_query(
                """
                SELECT * FROM paper_trades
                WHERE exit_ts >= ?
                ORDER BY exit_ts
                """,
                conn,
                params=(cutoff_ts,),
            )


    if trades.empty:
        console.print("no trades found")
        return

    # Use stored sizing fields when available
    if "risk_usd" in trades.columns and trades["risk_usd"].notna().any():
        trades["r"] = trades["pnl"] / trades["risk_usd"].replace(0, pd.NA)
    elif "atr" in trades.columns and trades["atr"].notna().any():
        stop_dist = trades["atr"] * 1.2
        trades["r"] = trades["pnl"] / stop_dist.replace(0, pd.NA)
    else:
        trades["r"] = pd.NA

    wins = trades["pnl"] > 0
    losses = trades["pnl"] <= 0
    win_rate = wins.mean()
    avg_r = trades["r"].mean()
    avg_win_r = trades.loc[wins, "r"].mean()
    avg_loss_r = trades.loc[losses, "r"].mean()
    expectancy = avg_r
    profit_factor = trades.loc[wins, "pnl"].sum() / abs(trades.loc[losses, "pnl"].sum()) if losses.any() else float("inf")

    equity = trades["pnl"].cumsum().tolist()
    dd = max_drawdown(equity)
    loss_streak = max_loss_streak(trades["pnl"].tolist())
    ending_equity = settings.initial_equity + trades["pnl"].sum()
    mae_mean = trades["mae_r"].mean() if "mae_r" in trades.columns else None
    mae_median = trades["mae_r"].median() if "mae_r" in trades.columns else None
    mfe_mean = trades["mfe_r"].mean() if "mfe_r" in trades.columns else None
    mfe_median = trades["mfe_r"].median() if "mfe_r" in trades.columns else None

    # Summary table
    summary = Table(title="Summary")
    summary.add_column("trades")
    summary.add_column("win rate")
    summary.add_column("avg R")
    summary.add_column("avg win R")
    summary.add_column("avg loss R")
    summary.add_column("expectancy")
    summary.add_column("profit factor")
    summary.add_row(
        str(len(trades)),
        f"{win_rate:.2%}",
        f"{avg_r:.3f}",
        f"{avg_win_r:.3f}" if pd.notna(avg_win_r) else "n/a",
        f"{avg_loss_r:.3f}" if pd.notna(avg_loss_r) else "n/a",
        f"{expectancy:.3f}",
        f"{profit_factor:.3f}" if profit_factor != float("inf") else "inf",
    )
    console.print(summary)

    console.print(f"max drawdown (pnl units): {dd:.2f}")
    console.print(f"max loss streak: {loss_streak}")
    console.print(
        f"bankroll: start={settings.initial_equity:.2f} end={ending_equity:.2f}"
    )
    if mae_mean is not None:
        console.print(
            f"MAE_R mean/median: {mae_mean:.3f} / {mae_median:.3f} | "
            f"MFE_R mean/median: {mfe_mean:.3f} / {mfe_median:.3f}"
        )

    # Exit reason breakdown
    by_reason = trades.groupby("exit_reason")["pnl"].agg(["count", "sum", "mean"]).reset_index()
    t_reason = Table(title="Exit Reason Breakdown")
    for col in ["exit_reason", "count", "sum", "mean"]:
        t_reason.add_column(col)
    for _, row in by_reason.iterrows():
        t_reason.add_row(
            str(row["exit_reason"]),
            str(int(row["count"])),
            f"{row['sum']:.2f}",
            f"{row['mean']:.2f}",
        )
    console.print(t_reason)

    # Regime performance table (using ER at entry)
    trades["entry_regime"] = trades["er"].apply(lambda x: trend_regime(float(x)))
    if "er" in trades.columns and trades["er"].notna().any():
        by_regime = trades.groupby("entry_regime").apply(
            lambda df: pd.Series(
                {
                    "count": len(df),
                    "win_rate": (df["pnl"] > 0).mean(),
                    "avg_r": df["r"].mean(),
                }
            )
        ).reset_index()

        t_regime = Table(title="Regime Performance")
        for col in ["entry_regime", "count", "win_rate", "avg_r"]:
            t_regime.add_column(col)
        for _, row in by_regime.iterrows():
            t_regime.add_row(
                str(row["entry_regime"]),
                str(int(row["count"])),
                f"{row['win_rate']:.2%}",
                f"{row['avg_r']:.3f}" if pd.notna(row["avg_r"]) else "n/a",
            )
        console.print(t_regime)

    # Last trades table
    last = trades.sort_values("exit_ts").tail(last_trades)
    t_last = Table(title=f"Last {len(last)} Trades")
    for col in [
        "entry_ts",
        "exit_ts",
        "hold_bars",
        "pnl",
        "r",
        "risk_$",
        "stop_dist",
        "pos_size",
        "cost_$",
        "er",
        "atr",
        "exit_reason",
    ]:
        t_last.add_column(col)

    prior_pnl = trades.loc[trades["exit_ts"] < last["entry_ts"].min(), "pnl"].sum()
    equity = settings.initial_equity + prior_pnl
    for _, row in last.iterrows():
        hold_bars = int((row["exit_ts"] - row["entry_ts"]) / settings.granularity_sec)
        stop_dist_val = float(row["stop_dist"]) if pd.notna(row.get("stop_dist")) else float(row["atr"]) * 1.2
        risk_usd = float(row["risk_usd"]) if pd.notna(row.get("risk_usd")) else abs(equity * settings.risk_pct)
        pos_size = float(row["qty"]) if pd.notna(row.get("qty")) else (risk_usd / stop_dist_val if stop_dist_val > 0 else 0.0)
        if pd.notna(row.get("total_cost")):
            cost_usd = float(row["total_cost"])
        else:
            cost_bps = settings.half_spread_bps + settings.slippage_bps
            cost_usd = (row["entry_price"] + row["exit_price"]) * (cost_bps / 10000.0) * pos_size
        t_last.add_row(
            ts_to_iso(int(row["entry_ts"])) + " UTC",
            ts_to_iso(int(row["exit_ts"])) + " UTC",
            str(hold_bars),
            f"{row['pnl']:.2f}",
            f"{row['r']:.3f}",
            f"{risk_usd:.2f}",
            f"{stop_dist_val:.2f}",
            f"{pos_size:.4f}",
            f"{cost_usd:.2f}",
            f"{row['er']:.3f}" if pd.notna(row.get("er")) else "n/a",
            f"{row['atr']:.2f}" if pd.notna(row.get("atr")) else "n/a",
            str(row["exit_reason"]),
        )
        equity += float(row["pnl"])
    console.print(t_last)

    avg_hold = trades["exit_ts"].sub(trades["entry_ts"]).div(settings.granularity_sec).mean()
    console.print(f"avg hold bars: {avg_hold:.2f}")

    # Stop-exit stats
    if "bars_to_stop" in trades.columns:
        stop_trades = trades[trades["exit_reason"] == "exit_stop_hit"].copy()
        if not stop_trades.empty:
            stop_rate = len(stop_trades) / len(trades)
            median_bars_to_stop = stop_trades["bars_to_stop"].median()
            buckets = {
                "1": (stop_trades["bars_to_stop"] == 1).sum(),
                "2-3": stop_trades["bars_to_stop"].between(2, 3).sum(),
                "4-6": stop_trades["bars_to_stop"].between(4, 6).sum(),
                "7-10": stop_trades["bars_to_stop"].between(7, 10).sum(),
                "11-20": stop_trades["bars_to_stop"].between(11, 20).sum(),
                "21+": (stop_trades["bars_to_stop"] >= 21).sum(),
            }
            console.print(
                f"stop-exit rate: {stop_rate:.2%} | median bars_to_stop: {median_bars_to_stop:.1f}"
            )
            console.print(
                "bars_to_stop histogram: "
                + ", ".join([f"{k}={v}" for k, v in buckets.items()])
            )


if __name__ == "__main__":
    args = parse_args()
    main(args.days, args.last_trades, args.strategy_name, args.dsn)
