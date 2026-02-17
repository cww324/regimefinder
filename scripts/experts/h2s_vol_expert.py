import argparse
from datetime import datetime, timezone

import pandas as pd

from app.data.db import connect, init_db


DEFAULT_HORIZONS = [5, 10, 20]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="H2S-VOL expert paper backtest (Level 0, no stops).")
    parser.add_argument("--days", type=int, default=180, help="Lookback window in days.")
    parser.add_argument("--window", type=int, default=2000, help="Rolling window for RV percentile.")
    parser.add_argument(
        "--split-mode",
        choices=["none", "holdout", "walkforward"],
        default="holdout",
        help="Data split mode.",
    )
    parser.add_argument("--holdout-days", type=int, default=60, help="Holdout OOS length in days.")
    parser.add_argument(
        "--is-days",
        type=int,
        default=0,
        help="Optional fixed IS length in days (IS immediately precedes OOS).",
    )
    parser.add_argument("--train-days", type=int, default=120, help="Walkforward train window length in days.")
    parser.add_argument("--test-days", type=int, default=30, help="Walkforward test window length in days.")
    parser.add_argument(
        "--step-days",
        type=int,
        default=0,
        help="Walkforward step in days (default: test-days).",
    )
    parser.add_argument(
        "--horizons",
        default="5,10,20",
        help="Comma-separated horizons in bars (e.g., 10,20).",
    )
    parser.add_argument(
        "--variant",
        choices=["A", "B"],
        default="A",
        help="Direction mapping variant: A=neg->short,pos->short; B=neg->short,pos->long.",
    )
    parser.add_argument("--rv-pct-min", type=float, default=0.70, help="Minimum RV percentile filter (inclusive).")
    parser.add_argument("--rv-pct-max", type=float, default=0.90, help="Maximum RV percentile filter (exclusive).")
    parser.add_argument("--shock-atr-min", type=float, default=1.5, help="Minimum |r1|/ATR-return shock filter (inclusive).")
    parser.add_argument("--shock-atr-max", type=float, default=2.5, help="Maximum |r1|/ATR-return shock filter (exclusive).")
    parser.add_argument("--fee_bps", type=float, default=0.0, help="Fee in bps per side (entry and exit).")
    parser.add_argument("--slippage_bps", type=float, default=0.0, help="Slippage in bps per side (entry and exit).")
    parser.add_argument(
        "--save-equity-csv",
        default="",
        help="Optional path to save full equity curve rows as CSV.",
    )
    parser.add_argument(
        "--equity-csv-prefix",
        default="",
        help="Prefix for split/fold equity CSV outputs.",
    )
    parser.add_argument(
        "--print-equity",
        action="store_true",
        help="Print full equity curve rows to stdout.",
    )
    parser.add_argument(
        "--write-paper-trades",
        action="store_true",
        help="Write trades into paper_trades for dashboard viewing (only split-mode=none).",
    )
    parser.add_argument(
        "--strategy-prefix",
        default="h2s_vol_expert_l0",
        help="Strategy prefix used when writing to paper_trades (horizon suffix is appended).",
    )
    parser.add_argument(
        "--reset-strategy",
        action="store_true",
        help="Delete existing trades for this strategy prefix before insert.",
    )
    return parser.parse_args()


def parse_horizons(value: str) -> list[int]:
    parts = [x.strip() for x in value.split(",") if x.strip()]
    horizons = sorted({int(x) for x in parts})
    if not horizons:
        return DEFAULT_HORIZONS.copy()
    return horizons


def load_data(days: int) -> pd.DataFrame:
    conn = connect("data/market.sqlite")
    init_db(conn)

    cutoff_ts = int(pd.Timestamp.now("UTC").timestamp()) - (days * 86400)
    df = pd.read_sql_query(
        """
        SELECT c.ts, c.open, c.close, f.atr14, f.rv48
        FROM candles_5m c
        JOIN features_5m f ON f.ts = c.ts
        WHERE c.ts >= ?
        ORDER BY c.ts
        """,
        conn,
        params=(cutoff_ts,),
    )
    if df.empty:
        raise SystemExit("no data")
    return df


def map_side(shock_r1: float, variant: str) -> str:
    if shock_r1 < 0:
        return "short"
    if variant == "A":
        return "short"
    return "long"


def prepare_features(df: pd.DataFrame, window: int) -> pd.DataFrame:
    data = df.copy().reset_index(drop=True)
    data["r1"] = data["close"].pct_change()
    data["atr_r"] = data["atr14"] / data["close"]
    data["shock_atr"] = data["r1"].abs() / data["atr_r"]
    data["rv_pct"] = data["rv48"].rolling(window).apply(lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False)
    return data


def build_trades(
    df: pd.DataFrame,
    window: int,
    variant: str,
    horizons: list[int],
    rv_pct_min: float,
    rv_pct_max: float,
    shock_atr_min: float,
    shock_atr_max: float,
    fee_bps: float,
    slippage_bps: float,
) -> pd.DataFrame:
    data = prepare_features(df, window)

    signal_mask = (
        (data["rv_pct"] >= rv_pct_min)
        & (data["rv_pct"] < rv_pct_max)
        & (data["shock_atr"] >= shock_atr_min)
        & (data["shock_atr"] < shock_atr_max)
        & (data["r1"] != 0)
    )
    signal_idx = data.index[signal_mask]

    rows = []
    for h in horizons:
        for idx in signal_idx:
            entry_idx = idx + 1
            exit_idx = idx + 1 + h
            if exit_idx >= len(data):
                continue

            shock_r1 = float(data.at[idx, "r1"])
            side = map_side(shock_r1, variant)
            entry_open = float(data.at[entry_idx, "open"])
            exit_open = float(data.at[exit_idx, "open"])
            if entry_open <= 0 or exit_open <= 0:
                continue

            if side == "long":
                gross_ret = (exit_open / entry_open) - 1.0
            else:
                gross_ret = (entry_open / exit_open) - 1.0

            # Apply friction per side (entry + exit).
            total_cost = 2.0 * ((fee_bps + slippage_bps) / 10000.0)
            ret = gross_ret - total_cost

            rows.append(
                {
                    "h": h,
                    "signal_ts": int(data.at[idx, "ts"]),
                    "entry_ts": int(data.at[entry_idx, "ts"]),
                    "exit_ts": int(data.at[exit_idx, "ts"]),
                    "side": side,
                    "ret": ret,
                    "entry_open": entry_open,
                    "exit_open": exit_open,
                    "atr": float(data.at[idx, "atr14"]) if pd.notna(data.at[idx, "atr14"]) else 0.0,
                }
            )

    return pd.DataFrame(rows)


def summarize_trades(trades_df: pd.DataFrame, horizons: list[int]) -> tuple[pd.DataFrame, pd.DataFrame]:
    summary_rows = []
    equity_rows = []

    for h in horizons:
        subset = trades_df[trades_df["h"] == h].copy() if not trades_df.empty else pd.DataFrame()
        if subset.empty:
            summary_rows.append(
                {
                    "h": h,
                    "trades": 0,
                    "win_rate": 0.0,
                    "mean_return": 0.0,
                    "median_return": 0.0,
                    "std_return": 0.0,
                    "sharpe_like": 0.0,
                    "final_equity_r": 1.0,
                }
            )
            continue

        subset = subset.sort_values("exit_ts").reset_index(drop=True)
        subset["win"] = subset["ret"] > 0
        subset["equity_r"] = 1.0 + subset["ret"].cumsum()
        subset["trade_id"] = range(1, len(subset) + 1)
        subset["exit_utc"] = pd.to_datetime(subset["exit_ts"], unit="s", utc=True).dt.strftime("%Y-%m-%d %H:%M")

        mean_ret = float(subset["ret"].mean())
        std_ret = float(subset["ret"].std(ddof=0))
        sharpe_like = 0.0 if std_ret == 0 else mean_ret / std_ret

        summary_rows.append(
            {
                "h": h,
                "trades": int(len(subset)),
                "win_rate": float(subset["win"].mean()),
                "mean_return": mean_ret,
                "median_return": float(subset["ret"].median()),
                "std_return": std_ret,
                "sharpe_like": sharpe_like,
                "final_equity_r": float(subset["equity_r"].iloc[-1]),
            }
        )
        equity_rows.append(subset[["h", "trade_id", "exit_utc", "equity_r"]].copy())

    summary_df = pd.DataFrame(summary_rows)
    equity_df = pd.concat(equity_rows, ignore_index=True) if equity_rows else pd.DataFrame(columns=["h", "trade_id", "exit_utc", "equity_r"])
    return summary_df, equity_df


def save_equity_by_horizon(equity_df: pd.DataFrame, prefix: str, tag: str) -> None:
    if equity_df.empty or not prefix:
        return
    for h in sorted(equity_df["h"].unique()):
        out_path = f"{prefix}_{tag}_h{int(h)}.csv"
        equity_df[equity_df["h"] == h].to_csv(out_path, index=False)
        print(f"Saved equity CSV: {out_path}")


def write_paper_trades(trades_df: pd.DataFrame, strategy_prefix: str, reset_strategy: bool) -> None:
    if trades_df.empty:
        return

    conn = connect("data/market.sqlite")
    init_db(conn)

    if reset_strategy:
        conn.execute("DELETE FROM paper_trades WHERE strategy_name LIKE ?", (f"{strategy_prefix}_h%",))
        conn.commit()

    rows = []
    for _, t in trades_df.iterrows():
        strategy_name = f"{strategy_prefix}_h{int(t['h'])}"
        rows.append(
            (
                int(t["entry_ts"]),
                int(t["exit_ts"]),
                float(t["entry_open"]),
                float(t["exit_open"]),
                None,
                0.0,
                float(t["atr"]),
                f"horizon_exit_{int(t['h'])}",
                float(t["ret"]),
                float(t["ret"]),
                strategy_name,
                1.0,
                1.0,
                1.0,
                0.0,
                0.0,
                0.0,
                None,
                None,
                float(t["ret"]),
                None,
                None,
                None,
                None,
                float(t["exit_open"]),
                1.0,
            )
        )

    conn.executemany(
        """
        INSERT OR REPLACE INTO paper_trades (
            entry_ts, exit_ts, entry_price, exit_price, breakout_level, er, atr, exit_reason, pnl, pnl_pct,
            strategy_name, qty, risk_usd, stop_dist, entry_cost, exit_cost, total_cost, equity_before, equity_after,
            r_multiple, mae_r, mfe_r, bars_to_stop, stop_price_used, exit_price_used, risk_per_unit
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()


def run_holdout(
    df: pd.DataFrame,
    window: int,
    variant: str,
    horizons: list[int],
    rv_pct_min: float,
    rv_pct_max: float,
    shock_atr_min: float,
    shock_atr_max: float,
    holdout_days: int,
    is_days: int,
    fee_bps: float,
    slippage_bps: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if holdout_days <= 0:
        raise SystemExit("holdout-days must be > 0")

    end_ts = int(df["ts"].max()) + 1
    oos_start = end_ts - (holdout_days * 86400)

    if is_days > 0:
        is_start = oos_start - (is_days * 86400)
    else:
        is_start = int(df["ts"].min())

    is_df = df[(df["ts"] >= is_start) & (df["ts"] < oos_start)].copy()
    oos_df = df[df["ts"] >= oos_start].copy()

    if is_df.empty or oos_df.empty:
        raise SystemExit("split produced empty IS or OOS segment")

    is_trades = build_trades(
        is_df, window, variant, horizons, rv_pct_min, rv_pct_max, shock_atr_min, shock_atr_max, fee_bps, slippage_bps
    )
    oos_trades = build_trades(
        oos_df, window, variant, horizons, rv_pct_min, rv_pct_max, shock_atr_min, shock_atr_max, fee_bps, slippage_bps
    )

    is_summary, is_equity = summarize_trades(is_trades, horizons)
    oos_summary, oos_equity = summarize_trades(oos_trades, horizons)

    is_summary["split"] = "IS"
    oos_summary["split"] = "OOS"
    summary_df = pd.concat([is_summary, oos_summary], ignore_index=True)
    summary_df = summary_df[["split", "h", "trades", "win_rate", "mean_return", "median_return", "std_return", "sharpe_like", "final_equity_r"]]

    equity_df = pd.concat(
        [
            is_equity.assign(split="IS"),
            oos_equity.assign(split="OOS"),
        ],
        ignore_index=True,
    )
    return summary_df, equity_df


def run_walkforward(
    df: pd.DataFrame,
    window: int,
    variant: str,
    horizons: list[int],
    rv_pct_min: float,
    rv_pct_max: float,
    shock_atr_min: float,
    shock_atr_max: float,
    train_days: int,
    test_days: int,
    step_days: int,
    fee_bps: float,
    slippage_bps: float,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if train_days <= 0 or test_days <= 0:
        raise SystemExit("train-days and test-days must be > 0")
    if step_days <= 0:
        step_days = test_days

    min_ts = int(df["ts"].min())
    end_ts = int(df["ts"].max()) + 1
    fold_rows = []
    fold_equities = []
    oos_all_trades = []

    fold_id = 1
    t = min_ts
    while t + ((train_days + test_days) * 86400) <= end_ts:
        train_start = t
        train_end = t + (train_days * 86400)
        test_start = train_end
        test_end = test_start + (test_days * 86400)

        fold_df = df[(df["ts"] >= train_start) & (df["ts"] < test_end)].copy()
        fold_trades = build_trades(
            fold_df,
            window,
            variant,
            horizons,
            rv_pct_min,
            rv_pct_max,
            shock_atr_min,
            shock_atr_max,
            fee_bps,
            slippage_bps,
        )
        if not fold_trades.empty:
            fold_trades = fold_trades[
                (fold_trades["signal_ts"] >= test_start)
                & (fold_trades["signal_ts"] < test_end)
                & (fold_trades["exit_ts"] < test_end)
            ].copy()

        fold_summary, fold_equity = summarize_trades(fold_trades, horizons)

        for _, row in fold_summary.iterrows():
            fold_rows.append(
                {
                    "fold_id": fold_id,
                    "train_start": datetime.fromtimestamp(train_start, tz=timezone.utc).strftime("%Y-%m-%d"),
                    "train_end": datetime.fromtimestamp(train_end, tz=timezone.utc).strftime("%Y-%m-%d"),
                    "test_start": datetime.fromtimestamp(test_start, tz=timezone.utc).strftime("%Y-%m-%d"),
                    "test_end": datetime.fromtimestamp(test_end, tz=timezone.utc).strftime("%Y-%m-%d"),
                    "h": int(row["h"]),
                    "trades": int(row["trades"]),
                    "mean_return": float(row["mean_return"]),
                    "std_return": float(row["std_return"]),
                    "sharpe_like": float(row["sharpe_like"]),
                    "final_equity_r": float(row["final_equity_r"]),
                }
            )

        if not fold_equity.empty:
            fold_equities.append(fold_equity.assign(fold_id=fold_id))
        if not fold_trades.empty:
            oos_all_trades.append(fold_trades.assign(fold_id=fold_id))

        fold_id += 1
        t += step_days * 86400

    if not fold_rows:
        raise SystemExit("walkforward produced no folds")

    per_fold_df = pd.DataFrame(fold_rows)
    fold_equity_df = pd.concat(fold_equities, ignore_index=True) if fold_equities else pd.DataFrame()

    oos_trades_df = pd.concat(oos_all_trades, ignore_index=True) if oos_all_trades else pd.DataFrame()
    agg_summary, _ = summarize_trades(oos_trades_df, horizons)
    agg_summary = agg_summary[["h", "trades", "mean_return", "std_return", "sharpe_like", "final_equity_r"]]

    return per_fold_df, agg_summary, fold_equity_df


def main() -> None:
    args = parse_args()
    horizons = parse_horizons(args.horizons)
    step_days = args.step_days if args.step_days > 0 else args.test_days

    df = load_data(args.days)

    print("=== H2S-VOL-EXPERT Level 0 (no stops) ===")
    print(f"Run: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"Days: {args.days}, Window: {args.window}, Horizons: {horizons}, Variant: {args.variant}")
    print(f"Split mode: {args.split_mode}")
    print(f"Friction: fee_bps={args.fee_bps}, slippage_bps={args.slippage_bps} (per side)")
    print(
        "Filters: "
        f"rv_pct in [{args.rv_pct_min:.2f}, {args.rv_pct_max:.2f}), "
        f"shock_atr in [{args.shock_atr_min:.2f}, {args.shock_atr_max:.2f})"
    )
    if args.variant == "A":
        print("Mapping: neg shock -> SHORT, pos shock -> SHORT")
    else:
        print("Mapping: neg shock -> SHORT, pos shock -> LONG")
    print()

    if args.split_mode == "none":
        trades_df = build_trades(
            df,
            args.window,
            args.variant,
            horizons,
            args.rv_pct_min,
            args.rv_pct_max,
            args.shock_atr_min,
            args.shock_atr_max,
            args.fee_bps,
            args.slippage_bps,
        )
        summary_df, equity_df = summarize_trades(trades_df, horizons)
        print("Summary by horizon:")
        print(summary_df.to_string(index=False))

        if args.print_equity:
            print()
            print("Equity curve (1R per trade, cumulative):")
            print(equity_df.to_string(index=False))

        if args.save_equity_csv:
            equity_df.to_csv(args.save_equity_csv, index=False)
            print()
            print(f"Saved equity curve CSV: {args.save_equity_csv}")

        if args.write_paper_trades:
            write_paper_trades(trades_df, args.strategy_prefix, args.reset_strategy)
            print()
            print(f"Wrote trades to paper_trades with strategy prefix: {args.strategy_prefix}")
            print(f"Strategies created: {args.strategy_prefix}_h5, {args.strategy_prefix}_h10, {args.strategy_prefix}_h20")
        return

    if args.split_mode == "holdout":
        summary_df, equity_df = run_holdout(
            df,
            args.window,
            args.variant,
            horizons,
            args.rv_pct_min,
            args.rv_pct_max,
            args.shock_atr_min,
            args.shock_atr_max,
            args.holdout_days,
            args.is_days,
            args.fee_bps,
            args.slippage_bps,
        )
        print("Holdout summary (IS/OOS):")
        print(summary_df.to_string(index=False))

        if args.print_equity:
            print()
            print("Equity curve (1R per trade, cumulative):")
            print(equity_df.to_string(index=False))

        if args.equity_csv_prefix:
            print()
            save_equity_by_horizon(equity_df[equity_df["split"] == "IS"], args.equity_csv_prefix, "is")
            save_equity_by_horizon(equity_df[equity_df["split"] == "OOS"], args.equity_csv_prefix, "oos")
        elif args.save_equity_csv:
            equity_df.to_csv(args.save_equity_csv, index=False)
            print()
            print(f"Saved equity curve CSV: {args.save_equity_csv}")
        return

    per_fold_df, agg_df, fold_equity_df = run_walkforward(
        df,
        args.window,
        args.variant,
        horizons,
        args.rv_pct_min,
        args.rv_pct_max,
        args.shock_atr_min,
        args.shock_atr_max,
        args.train_days,
        args.test_days,
        step_days,
        args.fee_bps,
        args.slippage_bps,
    )

    print("Walkforward per-fold results:")
    print(per_fold_df.to_string(index=False))
    print()
    print("Walkforward aggregated OOS by horizon:")
    print(agg_df.to_string(index=False))

    if args.equity_csv_prefix and not fold_equity_df.empty:
        print()
        for fold_id in sorted(fold_equity_df["fold_id"].unique()):
            fold_slice = fold_equity_df[fold_equity_df["fold_id"] == fold_id]
            for h in sorted(fold_slice["h"].unique()):
                out_path = f"{args.equity_csv_prefix}_wf_fold{int(fold_id)}_h{int(h)}.csv"
                fold_slice[fold_slice["h"] == h].to_csv(out_path, index=False)
                print(f"Saved equity CSV: {out_path}")


if __name__ == "__main__":
    main()
