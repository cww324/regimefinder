import argparse

import pandas as pd

from app.config import get_settings
from app.data.db import connect, init_db
from app.strategy.trend import breakout_signal, trend_regime


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit a paper trade by id.")
    parser.add_argument("trade_id", type=int, help="paper_trades.id to audit")
    return parser.parse_args()


def main(trade_id: int) -> None:
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

        # Hysteresis counter simulation between entry signal bar and exit check bar
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


if __name__ == "__main__":
    args = parse_args()
    main(args.trade_id)
