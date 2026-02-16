import argparse
import pandas as pd

from app.config import get_settings
from app.data.db import connect, init_db
from app.execution.forward import (
    load_last_processed_ts,
    load_state,
    run_trend_level1_forward,
    save_last_processed_ts,
    save_state,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run forward paper engine once.")
    parser.add_argument("--verbose", action="store_true", help="Print last_processed_ts updates")
    return parser.parse_args()


def main(verbose: bool) -> None:
    settings = get_settings()
    conn = connect(settings.db_path)
    init_db(conn)

    last_feature_ts = conn.execute("SELECT MAX(ts) AS ts FROM features_5m").fetchone()["ts"] or 0

    df = pd.read_sql_query(
        """
        SELECT c.ts, c.open, c.high, c.low, c.close, c.volume,
               f.atr14, f.er20, f.rv48, f.vwap48
        FROM candles_5m c
        JOIN features_5m f ON f.ts = c.ts
        WHERE c.ts <= ?
        ORDER BY c.ts
        """,
        conn,
        params=(last_feature_ts,),
    )

    state = load_state(conn)
    last_processed_ts = load_last_processed_ts(conn)
    trades, state, new_last_processed_ts = run_trend_level1_forward(
        df, settings, state, last_processed_ts
    )

    if trades:
        conn.executemany(
            """
            INSERT OR IGNORE INTO paper_trades (
                strategy_name, entry_ts, exit_ts, entry_price, exit_price,
                breakout_level, er, atr, exit_reason, pnl, pnl_pct,
                qty, risk_usd, stop_dist, entry_cost, exit_cost, total_cost,
                equity_before, equity_after, r_multiple, mae_r, mfe_r, bars_to_stop,
                stop_price_used, exit_price_used, risk_per_unit
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            trades,
        )
        conn.commit()

    save_state(conn, state)
    if new_last_processed_ts:
        save_last_processed_ts(conn, new_last_processed_ts)

    if verbose:
        print(f"last_processed_ts: {last_processed_ts} -> {new_last_processed_ts}")

    print(f"forward trades inserted: {len(trades)}")


if __name__ == "__main__":
    args = parse_args()
    main(args.verbose)
