import argparse

import pandas as pd

from app.config import get_settings
from app.data.db import connect, init_db
from app.db import rc
from app.strategy.trend import breakout_signal, trend_regime


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit a paper trade by id.")
    parser.add_argument("trade_id", type=int, help="paper_trades.id to audit")
    parser.add_argument("--dsn", type=str, default="", help="Optional Postgres DSN for rc schema")
    return parser.parse_args()


def main(trade_id: int, dsn: str = "") -> None:
    if dsn:
        with rc.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        p.position_id,
                        h.hypothesis_id,
                        s.symbol_code,
                        EXTRACT(EPOCH FROM p.opened_at)::bigint AS entry_ts,
                        EXTRACT(EPOCH FROM p.closed_at)::bigint AS exit_ts,
                        p.avg_entry_price,
                        p.avg_exit_price,
                        p.qty,
                        p.realized_pnl,
                        p.max_adverse_excursion,
                        p.max_favorable_excursion,
                        p.status
                    FROM rc.paper_positions p
                    JOIN rc.hypotheses h ON h.hypothesis_pk = p.hypothesis_pk
                    JOIN rc.symbols s ON s.symbol_id = p.symbol_id
                    WHERE p.position_id = %s
                    """,
                    (trade_id,),
                )
                row = cur.fetchone()
                cur.execute(
                    """
                    SELECT
                        EXTRACT(EPOCH FROM ss.signal_ts)::bigint AS signal_ts,
                        ss.signal_open,
                        ss.signal_high,
                        ss.signal_low,
                        ss.signal_close,
                        ss.signal_volume,
                        ss.atr14,
                        ss.er20,
                        ss.rv48,
                        ss.vwap48,
                        ss.regime
                    FROM rc.paper_signal_snapshots ss
                    WHERE ss.position_id = %s
                    """,
                    (trade_id,),
                )
                snap = cur.fetchone()

        if not row:
            print("position not found")
            return

        (
            position_id,
            hypothesis_id,
            symbol_code,
            entry_ts,
            exit_ts,
            avg_entry,
            avg_exit,
            qty,
            realized_pnl,
            mae,
            mfe,
            status,
        ) = row
        print(f"position_id={position_id} hypothesis_id={hypothesis_id} symbol={symbol_code} status={status}")
        print(f"entry_ts={entry_ts} exit_ts={exit_ts}")
        print(f"entry_price={avg_entry} exit_price={avg_exit} qty={qty}")
        print(f"realized_pnl={realized_pnl} mae={mae} mfe={mfe}")
        if snap:
            (
                signal_ts,
                s_open,
                s_high,
                s_low,
                s_close,
                s_vol,
                atr14,
                er20,
                rv48,
                vwap48,
                regime,
            ) = snap
            print("-- signal snapshot --")
            print(f"signal_ts={signal_ts}")
            print(f"signal_ohlcv=({s_open},{s_high},{s_low},{s_close},{s_vol})")
            print(f"features atr14={atr14} er20={er20} rv48={rv48} vwap48={vwap48} regime={regime}")
        else:
            print("signal snapshot: missing (run scripts/capture_paper_signal_snapshots.py)")
        return

    settings = get_settings()
    conn = connect(settings.db_path)
    init_db(conn)

    trade = conn.execute(
        "SELECT * FROM paper_trades WHERE id = ?",
        (trade_id,),
    ).fetchone()

    if not trade:
        print("trade not found")
        return

    df = pd.read_sql_query(
        """
        SELECT c.ts, c.open, c.high, c.low, c.close, c.volume,
               f.atr14, f.er20, f.rv48, f.vwap48
        FROM candles_5m c
        JOIN features_5m f ON f.ts = c.ts
        ORDER BY c.ts
        """,
        conn,
    )

    df = df.reset_index(drop=True)
    ts_to_idx = {int(ts): int(idx) for idx, ts in enumerate(df["ts"].tolist())}

    entry_ts = int(trade["entry_ts"])
    exit_ts = int(trade["exit_ts"])

    if entry_ts not in ts_to_idx or exit_ts not in ts_to_idx:
        print("entry/exit ts not found in candles")
        return

    entry_idx = ts_to_idx[entry_ts]
    exit_idx = ts_to_idx[exit_ts]

    signal_idx = entry_idx - 1 if entry_idx > 0 else entry_idx
    exit_check_idx = exit_idx - 1 if exit_idx > 0 else exit_idx
    signal_row = df.iloc[signal_idx] if signal_idx >= 0 else None
    exit_row = df.iloc[exit_check_idx] if exit_check_idx >= 0 else None

    print(f"trade_id={trade_id}")
    print(f"entry_bar_ts={int(signal_row['ts']) if signal_row is not None else entry_ts}")
    print(f"entry_fill_bar_ts={entry_ts} exit_ts={exit_ts}")
    print(f"entry_price={trade['entry_price']:.2f} exit_price={trade['exit_price']:.2f}")
    print(f"exit_reason={trade['exit_reason']}")
    print(f"breakout_level={trade['breakout_level']:.2f} er={trade['er']:.4f} atr={trade['atr']:.2f}")

    if signal_row is not None:
        sig = breakout_signal(df, signal_idx, lookback=20, atr_buffer=settings.breakout_atr_buffer)
        regime = trend_regime(float(signal_row["er20"]))
        print(f"signal_bar_ts={int(signal_row['ts'])} close={signal_row['close']:.2f} high={signal_row['high']:.2f}")
        print(f"signal_regime={regime} signal_triggered={sig is not None}")

    if exit_row is not None:
        exit_regime = trend_regime(float(exit_row["er20"]))
        print(
            f"exit_check_bar_ts={int(exit_row['ts'])} close={exit_row['close']:.2f} high={exit_row['high']:.2f} low={exit_row['low']:.2f}"
        )
        print(f"exit_regime={exit_regime}")

        entry_regime = (
            trend_regime(float(signal_row["er20"])) if signal_row is not None else "unknown"
        )
        switch_count = 0
        for idx in range(signal_idx, exit_check_idx + 1):
            reg = trend_regime(float(df.iloc[idx]["er20"]))
            if reg == "unknown":
                continue
            if reg != entry_regime:
                switch_count += 1
            else:
                switch_count = 0
        print(f"hysteresis_counter={switch_count}")

    # Math audit
    risk_pct = settings.risk_pct
    initial_equity = settings.initial_equity
    prior_pnl = conn.execute(
        "SELECT COALESCE(SUM(pnl), 0) AS pnl FROM paper_trades WHERE exit_ts < ?",
        (entry_ts,),
    ).fetchone()["pnl"]
    equity_at_entry = initial_equity + float(prior_pnl)

    atr = float(trade["atr"])
    stop_dist = 1.2 * atr
    risk_usd = abs(equity_at_entry * risk_pct)
    qty = risk_usd / stop_dist if stop_dist > 0 else 0.0
    notional = qty * float(trade["entry_price"])

    bps = settings.half_spread_bps + settings.slippage_bps
    entry_cost = float(trade["entry_price"]) * qty * (bps / 10000.0)
    exit_cost = float(trade["exit_price"]) * qty * (bps / 10000.0)
    total_cost = entry_cost + exit_cost

    pnl = qty * (float(trade["exit_price"]) - float(trade["entry_price"])) - total_cost
    r_multiple = pnl / max(risk_usd, 1e-9)
    equity_after = equity_at_entry + pnl

    print("-- math audit --")
    print(f"equity_at_entry = {initial_equity:.2f} + {prior_pnl:.2f} = {equity_at_entry:.2f}")
    print(f"risk_pct = {risk_pct:.4f} -> risk_$ = {risk_usd:.2f}")
    print(f"ATR = {atr:.2f}")
    print(f"stop_dist_price = 1.2 * ATR = {stop_dist:.2f}")
    print(f"qty = risk_$ / stop_dist_price = {risk_usd:.2f} / {stop_dist:.2f} = {qty:.6f}")
    print(f"notional = qty * entry_price = {qty:.6f} * {trade['entry_price']:.2f} = {notional:.2f}")
    print(f"spread_bps + slippage_bps = {bps:.2f} bps (bps / 10000)")
    print(f"entry_cost_$ = entry_price * qty * (bps/10000) = {entry_cost:.2f}")
    print(f"exit_cost_$  = exit_price * qty * (bps/10000) = {exit_cost:.2f}")
    print(f"total_cost_$ = {total_cost:.2f}")
    print(f"pnl_$ = qty*(exit-entry) - costs = {pnl:.2f}")
    print(f"R = pnl_$ / risk_$ = {r_multiple:.3f}")
    print(f"equity_after = equity_at_entry + pnl_$ = {equity_after:.2f}")
    if "mae_r" in trade.keys():
        print(f"MAE_R = {trade['mae_r']:.3f} | MFE_R = {trade['mfe_r']:.3f}")
    if "bars_to_stop" in trade.keys() and trade["bars_to_stop"] is not None:
        print(f"bars_to_stop = {trade['bars_to_stop']}")
    if "stop_price_used" in trade.keys():
        print(
            f"stop_price_used = {trade['stop_price_used']} | exit_price_used = {trade['exit_price_used']} | risk_per_unit = {trade['risk_per_unit']}"
        )


if __name__ == "__main__":
    args = parse_args()
    main(args.trade_id, args.dsn)
