import argparse
import csv
import json
import os
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from app.data.db import connect, init_db
from scripts.ingest_5m import main as ingest_main


@dataclass
class H32LiveState:
    last_processed_ts: int
    equity: float
    peak_equity: float
    position_open: bool
    entry_ts: int
    entry_idx: int
    entry_price: float
    signal_dir: float
    halt_day_utc: str
    latest_btc_ts: int
    latest_eth_ts: int


def default_state(initial_equity: float) -> H32LiveState:
    return H32LiveState(
        last_processed_ts=0,
        equity=initial_equity,
        peak_equity=initial_equity,
        position_open=False,
        entry_ts=0,
        entry_idx=-1,
        entry_price=0.0,
        signal_dir=0.0,
        halt_day_utc="",
        latest_btc_ts=0,
        latest_eth_ts=0,
    )


def load_state(conn, key: str, initial_equity: float) -> H32LiveState:
    row = conn.execute("SELECT value FROM bot_state WHERE key = ?", (key,)).fetchone()
    if not row:
        return default_state(initial_equity)
    payload = json.loads(row["value"])
    defaults = asdict(default_state(initial_equity))
    defaults.update(payload)
    return H32LiveState(**defaults)


def save_state(conn, key: str, state: H32LiveState) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO bot_state (key, value) VALUES (?, ?)",
        (key, json.dumps(asdict(state))),
    )
    conn.commit()


def ensure_csv(path: Path, headers: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(headers)


def append_csv(path: Path, row: list) -> None:
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(row)


def ingest_latest_for_both_assets() -> None:
    old_db = os.environ.get("DB_PATH")
    old_product = os.environ.get("COINBASE_PRODUCT_ID")
    try:
        os.environ["DB_PATH"] = "data/market.sqlite"
        os.environ["COINBASE_PRODUCT_ID"] = "BTC-USD"
        ingest_main(lookback_bars=0, backfill_bars=0, backfill_older_bars=0)

        os.environ["DB_PATH"] = "data/market_eth.sqlite"
        os.environ["COINBASE_PRODUCT_ID"] = "ETH-USD"
        try:
            ingest_main(lookback_bars=0, backfill_bars=0, backfill_older_bars=0)
        except Exception as e:  # noqa: BLE001
            print(f"ingest warning: ETH-USD ingestion failed: {e}")
    finally:
        if old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = old_db
        if old_product is None:
            os.environ.pop("COINBASE_PRODUCT_ID", None)
        else:
            os.environ["COINBASE_PRODUCT_ID"] = old_product


def latest_ts_or_zero(conn) -> int:
    row = conn.execute("SELECT MAX(ts) AS max_ts FROM candles_5m").fetchone()
    if not row or row["max_ts"] is None:
        return 0
    return int(row["max_ts"])


def build_h32_frame(days: int, h: int) -> tuple[pd.DataFrame, int, int]:
    btc_conn = connect("data/market.sqlite")
    eth_conn = connect("data/market_eth.sqlite")
    latest_btc_ts = latest_ts_or_zero(btc_conn)
    latest_eth_ts = latest_ts_or_zero(eth_conn)
    btc = pd.read_sql_query("SELECT ts, close FROM candles_5m ORDER BY ts", btc_conn)
    eth = pd.read_sql_query("SELECT ts, close FROM candles_5m ORDER BY ts", eth_conn)
    cutoff = int(pd.Timestamp.now("UTC").timestamp()) - (days * 86400)
    btc = btc[btc.ts >= cutoff].copy().reset_index(drop=True)
    eth = eth[eth.ts >= cutoff].copy().reset_index(drop=True)

    m = btc.merge(eth, on="ts", how="inner", suffixes=("_btc", "_eth")).sort_values("ts").reset_index(drop=True)
    m["dt"] = pd.to_datetime(m["ts"], unit="s", utc=True)

    h1 = (
        m.set_index("dt")[["close_btc", "close_eth"]]
        .resample("1h")
        .last()
        .dropna()
        .reset_index()
    )
    h1["ret_btc_1h_6h"] = h1["close_btc"] / h1["close_btc"].shift(6) - 1.0
    h1["ret_eth_1h_6h"] = h1["close_eth"] / h1["close_eth"].shift(6) - 1.0
    h1["spread"] = h1["ret_eth_1h_6h"] - h1["ret_btc_1h_6h"]
    h1["spread_pct"] = h1["spread"].rolling(2000).apply(
        lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False
    )
    h1["eth_ema20_1h"] = h1["close_eth"].ewm(span=20, adjust=False).mean()
    h1["eth_ema_slope_1h"] = h1["eth_ema20_1h"].diff(3)
    h1["slope_sign"] = np.sign(h1["eth_ema_slope_1h"])
    h1["signal_dir"] = np.where((h1["spread_pct"] < 0.10) & (h1["slope_sign"] != 0), h1["slope_sign"], 0.0)

    x = pd.merge_asof(m.sort_values("dt"), h1[["dt", "signal_dir"]].sort_values("dt"), on="dt", direction="backward")
    x["idx"] = np.arange(len(x))
    x["entry"] = x["signal_dir"] != 0
    x["exit_idx_from_entry"] = x["idx"] + h
    return x, latest_btc_ts, latest_eth_ts


def refresh_daily_metrics(trades_csv: Path, daily_csv: Path) -> None:
    if not trades_csv.exists():
        return
    t = pd.read_csv(trades_csv)
    if t.empty:
        return
    t["exit_dt"] = pd.to_datetime(t["exit_ts"], unit="s", utc=True)
    t["exit_day"] = t["exit_dt"].dt.date.astype(str)
    d = t.groupby("exit_day", as_index=False).agg(
        trades=("net_return", "count"),
        day_return=("net_return", "sum"),
        day_pnl_usd=("pnl_usd", "sum"),
        equity_end=("equity_after", "last"),
        win_rate=("net_return", lambda s: float((s > 0).mean())),
        mean_return=("net_return", "mean"),
    )
    # Exposure proxy: sum of closed-trade holding time / day seconds.
    t["entry_dt"] = pd.to_datetime(t["entry_ts"], unit="s", utc=True)
    t["hold_seconds"] = (t["exit_dt"] - t["entry_dt"]).dt.total_seconds().clip(lower=0.0)
    exp = t.groupby("exit_day", as_index=False).agg(hold_seconds=("hold_seconds", "sum"))
    d = d.merge(exp, on="exit_day", how="left")
    d["exposure_time"] = d["hold_seconds"] / 86400.0
    d["peak_equity"] = d["equity_end"].cummax()
    d["drawdown"] = d["equity_end"] / d["peak_equity"] - 1.0
    d.to_csv(daily_csv, index=False)


def load_day_realized_pnl(trades_csv: Path, day_utc: str) -> float:
    if not trades_csv.exists():
        return 0.0
    t = pd.read_csv(trades_csv)
    if t.empty:
        return 0.0
    t["exit_day"] = pd.to_datetime(t["exit_ts"], unit="s", utc=True).dt.date.astype(str)
    return float(t.loc[t["exit_day"] == day_utc, "pnl_usd"].sum())


def print_daily_summary(daily_csv: Path, state: H32LiveState) -> None:
    if not daily_csv.exists():
        return
    d = pd.read_csv(daily_csv)
    if d.empty:
        return
    last = d.iloc[-1]
    print(
        "daily_summary "
        f"day={last['exit_day']} "
        f"trades={int(last['trades'])} "
        f"win={float(last['win_rate']):.2%} "
        f"mean={float(last['mean_return']):+.6f} "
        f"pnl_usd={float(last['day_pnl_usd']):+.2f} "
        f"max_dd={float(last['drawdown']):+.4f} "
        f"exposure={float(last['exposure_time']):.2%} "
        f"equity={state.equity:.2f}"
    )


def run_once(
    conn,
    state: H32LiveState,
    signals_csv: Path,
    trades_csv: Path,
    daily_csv: Path,
    h: int,
    cost: float,
    days: int,
    max_daily_loss_usd: float,
    max_open_dd_pct: float,
    verbose: bool,
) -> H32LiveState:
    x, latest_btc_ts, latest_eth_ts = build_h32_frame(days=days, h=h)
    state.latest_btc_ts = latest_btc_ts
    state.latest_eth_ts = latest_eth_ts
    if x.empty:
        return state

    eth_stale = (
        state.latest_btc_ts > 0
        and state.latest_eth_ts > 0
        and (state.latest_btc_ts - state.latest_eth_ts) > 300
    )
    if eth_stale:
        print(
            "signal block: ETH data stale "
            f"(btc_ts={state.latest_btc_ts}, eth_ts={state.latest_eth_ts}, lag_s={state.latest_btc_ts - state.latest_eth_ts})"
        )

    ts_to_idx = {int(ts): int(i) for i, ts in enumerate(x["ts"].tolist())}
    start_i = 0
    if state.last_processed_ts and state.last_processed_ts in ts_to_idx:
        start_i = ts_to_idx[state.last_processed_ts] + 1

    day_pnl_realized = None
    current_day = ""

    for i in range(start_i, len(x)):
        row = x.iloc[i]
        ts = int(row["ts"])
        dt = row["dt"]
        day_utc = dt.date().isoformat()
        close_btc = float(row["close_btc"])
        signal_dir = float(row["signal_dir"])
        signal_for_entry = 0.0 if eth_stale else signal_dir

        if day_utc != current_day:
            current_day = day_utc
            # Reset daily halt when a new UTC day begins.
            if state.halt_day_utc and state.halt_day_utc != day_utc:
                state.halt_day_utc = ""
            day_pnl_realized = load_day_realized_pnl(trades_csv, day_utc)

        if signal_for_entry != 0.0:
            append_csv(
                signals_csv,
                [
                    int(ts),
                    dt.isoformat(),
                    signal_for_entry,
                    int(state.position_open),
                    "enter_candidate" if (not state.position_open) else "skip_position_open",
                ],
            )

        # Open-DD kill-switch on mark-to-market equity.
        if (
            max_open_dd_pct > 0
            and state.position_open
            and state.peak_equity > 0
        ):
            mtm_r = state.signal_dir * (close_btc / state.entry_price - 1.0) - cost
            mtm_equity = state.equity * (1.0 + mtm_r)
            mtm_dd = mtm_equity / state.peak_equity - 1.0
            if mtm_dd <= -max_open_dd_pct:
                # Force close on current bar close and halt for the day.
                gross_r = state.signal_dir * (close_btc / state.entry_price - 1.0)
                net_r = gross_r - cost
                equity_before = state.equity
                pnl_usd = equity_before * net_r
                state.equity = equity_before + pnl_usd
                state.peak_equity = max(state.peak_equity, state.equity)
                dd = state.equity / state.peak_equity - 1.0

                append_csv(
                    trades_csv,
                    [
                        state.entry_ts,
                        int(ts),
                        pd.to_datetime(state.entry_ts, unit="s", utc=True).isoformat(),
                        dt.isoformat(),
                        state.signal_dir,
                        state.entry_price,
                        close_btc,
                        gross_r,
                        net_r,
                        pnl_usd,
                        equity_before,
                        state.equity,
                        dd,
                    ],
                )
                day_pnl_realized = (day_pnl_realized or 0.0) + pnl_usd
                state.halt_day_utc = day_utc
                append_csv(
                    signals_csv,
                    [int(ts), dt.isoformat(), signal_for_entry, int(state.position_open), "kill_switch_open_dd"],
                )
                if verbose:
                    print(
                        f"KILL_OPEN_DD ts={ts} mtm_dd={mtm_dd:+.4f} pnl={pnl_usd:+.2f} "
                        f"equity={state.equity:.2f}"
                    )
                state.position_open = False
                state.entry_ts = 0
                state.entry_idx = -1
                state.entry_price = 0.0
                state.signal_dir = 0.0

        # Exit check first to ensure max 1 position active.
        if state.position_open and i >= state.entry_idx + h:
            exit_price = close_btc
            gross_r = state.signal_dir * (exit_price / state.entry_price - 1.0)
            net_r = gross_r - cost
            equity_before = state.equity
            pnl_usd = equity_before * net_r
            state.equity = equity_before + pnl_usd
            state.peak_equity = max(state.peak_equity, state.equity)
            dd = state.equity / state.peak_equity - 1.0

            append_csv(
                trades_csv,
                [
                    state.entry_ts,
                    int(ts),
                    pd.to_datetime(state.entry_ts, unit="s", utc=True).isoformat(),
                    dt.isoformat(),
                    state.signal_dir,
                    state.entry_price,
                    exit_price,
                    gross_r,
                    net_r,
                    pnl_usd,
                    equity_before,
                    state.equity,
                    dd,
                ],
            )
            day_pnl_realized = (day_pnl_realized or 0.0) + pnl_usd

            if verbose:
                print(
                    f"EXIT ts={ts} dir={state.signal_dir:+.0f} gross={gross_r:+.6f} "
                    f"net={net_r:+.6f} equity={state.equity:.2f} dd={dd:+.4f}"
                )

            state.position_open = False
            state.entry_ts = 0
            state.entry_idx = -1
            state.entry_price = 0.0
            state.signal_dir = 0.0

        # Daily realized-loss kill-switch.
        if max_daily_loss_usd > 0 and (day_pnl_realized or 0.0) <= -max_daily_loss_usd:
            state.halt_day_utc = day_utc
            append_csv(
                signals_csv,
                [int(ts), dt.isoformat(), signal_for_entry, int(state.position_open), "kill_switch_daily_loss"],
            )

        # Entry check after exit (1-position rule)
        if (
            (not state.position_open)
            and signal_for_entry != 0.0
            and state.halt_day_utc != day_utc
        ):
            state.position_open = True
            state.entry_ts = ts
            state.entry_idx = i
            state.entry_price = close_btc
            state.signal_dir = signal_for_entry
            if verbose:
                print(f"ENTER ts={ts} dir={signal_for_entry:+.0f} price={close_btc:.2f}")
        elif (not state.position_open) and signal_for_entry != 0.0 and state.halt_day_utc == day_utc:
            append_csv(
                signals_csv,
                [int(ts), dt.isoformat(), signal_for_entry, int(state.position_open), "skip_kill_switch_halt"],
            )
        elif (not state.position_open) and signal_dir != 0.0 and eth_stale:
            append_csv(
                signals_csv,
                [int(ts), dt.isoformat(), signal_dir, int(state.position_open), "skip_eth_stale"],
            )

        state.last_processed_ts = ts

    refresh_daily_metrics(trades_csv, daily_csv)
    return state


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run frozen H32 real-time paper trader.")
    p.add_argument("--once", action="store_true", help="Run one processing cycle and exit.")
    p.add_argument("--poll-seconds", type=float, default=10.0, help="Loop sleep interval.")
    p.add_argument("--days", type=int, default=180, help="Lookback window for signal computation.")
    p.add_argument("--h", type=int, default=6, help="Holding horizon; keep at frozen h=6.")
    p.add_argument("--cost", type=float, default=0.0008, help="Roundtrip return cost (8 bps = 0.0008).")
    p.add_argument("--initial-equity", type=float, default=10000.0, help="Initial paper equity.")
    p.add_argument("--ingest", action="store_true", help="Ingest latest BTC/ETH bars each cycle.")
    p.add_argument("--verbose", action="store_true", help="Print signal/fill events.")
    p.add_argument(
        "--state-key",
        type=str,
        default="h32_live_state",
        help="bot_state key for persisted runner state.",
    )
    p.add_argument("--signals-csv", type=str, default="logs/h32_live_signals.csv")
    p.add_argument("--trades-csv", type=str, default="logs/h32_live_trades.csv")
    p.add_argument("--daily-csv", type=str, default="logs/h32_live_daily.csv")
    p.add_argument(
        "--max-daily-loss-usd",
        type=float,
        default=0.0,
        help="Paper kill-switch: halt new entries for UTC day if realized PnL <= -value. 0 disables.",
    )
    p.add_argument(
        "--max-open-dd-pct",
        type=float,
        default=0.0,
        help="Paper kill-switch: if open-position mark-to-market drawdown exceeds this fraction, force exit and halt day. 0 disables.",
    )
    p.add_argument("--replay-mode", action="store_true", help="Replay recent bars and verify live logs against replayed trades.")
    p.add_argument("--replay-days", type=int, default=30, help="Replay lookback days for verification mode.")
    p.add_argument("--replay-tolerance-bars", type=int, default=1, help="Timestamp tolerance in bars for replay verification.")
    return p.parse_args()


def replay_trades(
    x: pd.DataFrame,
    h: int,
    cost: float,
    start_ts: int,
    max_daily_loss_usd: float,
    max_open_dd_pct: float,
) -> list[tuple[int, int, int]]:
    equity = 10000.0
    peak = equity
    position_open = False
    entry_ts = 0
    entry_idx = -1
    entry_price = 0.0
    signal_dir = 0.0
    day_pnl = 0.0
    day = ""
    halted = False
    out: list[tuple[int, int, int]] = []

    for i in range(len(x)):
        row = x.iloc[i]
        ts = int(row["ts"])
        if ts < start_ts:
            continue
        dt = row["dt"]
        close_btc = float(row["close_btc"])
        sig = float(row["signal_dir"])
        day_utc = dt.date().isoformat()
        if day_utc != day:
            day = day_utc
            day_pnl = 0.0
            halted = False

        if max_open_dd_pct > 0 and position_open:
            mtm_r = signal_dir * (close_btc / entry_price - 1.0) - cost
            mtm_equity = equity * (1.0 + mtm_r)
            mtm_dd = mtm_equity / peak - 1.0
            if mtm_dd <= -max_open_dd_pct:
                gross = signal_dir * (close_btc / entry_price - 1.0)
                net = gross - cost
                pnl = equity * net
                equity += pnl
                peak = max(peak, equity)
                day_pnl += pnl
                out.append((entry_ts, ts, int(signal_dir)))
                position_open = False
                halted = True

        if position_open and i >= entry_idx + h:
            gross = signal_dir * (close_btc / entry_price - 1.0)
            net = gross - cost
            pnl = equity * net
            equity += pnl
            peak = max(peak, equity)
            day_pnl += pnl
            out.append((entry_ts, ts, int(signal_dir)))
            position_open = False

        if max_daily_loss_usd > 0 and day_pnl <= -max_daily_loss_usd:
            halted = True

        if (not position_open) and (not halted) and sig != 0.0:
            position_open = True
            entry_ts = ts
            entry_idx = i
            entry_price = close_btc
            signal_dir = sig

    return out


def run_replay_verification(args: argparse.Namespace, trades_csv: Path) -> int:
    x, _, _ = build_h32_frame(days=max(args.days, args.replay_days + 5), h=args.h)
    if x.empty:
        print("replay: no data")
        return 1

    start_ts = int(pd.Timestamp.now("UTC").timestamp()) - (args.replay_days * 86400)
    expected = replay_trades(
        x=x,
        h=args.h,
        cost=args.cost,
        start_ts=start_ts,
        max_daily_loss_usd=args.max_daily_loss_usd,
        max_open_dd_pct=args.max_open_dd_pct,
    )

    if trades_csv.exists():
        t = pd.read_csv(trades_csv)
        if not t.empty:
            t = t[t["entry_ts"] >= start_ts]
            actual = [
                (int(r.entry_ts), int(r.exit_ts), int(r.signal_dir))
                for r in t.itertuples(index=False)
            ]
        else:
            actual = []
    else:
        actual = []

    tol_sec = int(args.replay_tolerance_bars * 300)
    n = min(len(expected), len(actual))
    mismatches = []
    matches = 0
    for i in range(n):
        e = expected[i]
        a = actual[i]
        ok = (
            abs(e[0] - a[0]) <= tol_sec
            and abs(e[1] - a[1]) <= tol_sec
            and e[2] == a[2]
        )
        if ok:
            matches += 1
        else:
            mismatches.append((i, e, a))

    print("H32_REPLAY_VERIFICATION")
    print(f"replay_days={args.replay_days} tolerance_bars={args.replay_tolerance_bars}")
    print(f"expected_trades={len(expected)} actual_trades={len(actual)}")
    print(f"matched_prefix={matches}/{n}")
    print(f"mismatches={len(mismatches)}")
    if mismatches:
        print("first_mismatches (idx, expected(entry,exit,dir), actual(entry,exit,dir)):")
        for i, e, a in mismatches[:10]:
            print(f"{i} | {e} | {a}")
    length_gap = abs(len(expected) - len(actual))
    print(f"length_gap={length_gap}")
    return 0 if (len(mismatches) == 0 and length_gap == 0) else 2


def main() -> None:
    args = parse_args()
    if args.h != 6:
        raise ValueError("H32 is frozen at h=6. Do not change --h.")

    conn = connect("data/market.sqlite")
    init_db(conn)
    state = load_state(conn, args.state_key, args.initial_equity)

    signals_csv = Path(args.signals_csv)
    trades_csv = Path(args.trades_csv)
    daily_csv = Path(args.daily_csv)
    ensure_csv(signals_csv, ["ts", "dt_utc", "signal_dir", "position_open_before", "action"])
    ensure_csv(
        trades_csv,
        [
            "entry_ts",
            "exit_ts",
            "entry_dt_utc",
            "exit_dt_utc",
            "signal_dir",
            "entry_price",
            "exit_price",
            "gross_return",
            "net_return",
            "pnl_usd",
            "equity_before",
            "equity_after",
            "drawdown_after",
        ],
    )
    ensure_csv(
        daily_csv,
        [
            "exit_day",
            "trades",
            "day_return",
            "day_pnl_usd",
            "equity_end",
            "win_rate",
            "mean_return",
            "hold_seconds",
            "exposure_time",
            "peak_equity",
            "drawdown",
        ],
    )

    if args.replay_mode:
        raise_code = run_replay_verification(args, trades_csv)
        raise SystemExit(raise_code)

    while True:
        if args.ingest:
            try:
                ingest_latest_for_both_assets()
            except Exception as e:  # noqa: BLE001
                print(f"ingest warning: {e}")

        state = run_once(
            conn=conn,
            state=state,
            signals_csv=signals_csv,
            trades_csv=trades_csv,
            daily_csv=daily_csv,
            h=args.h,
            cost=args.cost,
            days=args.days,
            max_daily_loss_usd=args.max_daily_loss_usd,
            max_open_dd_pct=args.max_open_dd_pct,
            verbose=args.verbose,
        )
        save_state(conn, args.state_key, state)
        print_daily_summary(daily_csv, state)

        if args.once:
            break
        time.sleep(args.poll_seconds)

    print(f"state_key={args.state_key}")
    print(f"signals_csv={signals_csv}")
    print(f"trades_csv={trades_csv}")
    print(f"daily_csv={daily_csv}")
    print(f"equity={state.equity:.2f}")
    print(f"peak_equity={state.peak_equity:.2f}")
    print(f"last_processed_ts={state.last_processed_ts}")
    print(f"max_daily_loss_usd={args.max_daily_loss_usd}")
    print(f"max_open_dd_pct={args.max_open_dd_pct}")


if __name__ == "__main__":
    main()
