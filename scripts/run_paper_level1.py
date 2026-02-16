import argparse

import pandas as pd

from app.config import get_settings
from app.data.db import connect, init_db
from app.execution.paper import run_trend_level1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Level 1 paper backtest for trend strategy.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Clear existing paper_trades before inserting new results.",
    )
    return parser.parse_args()


def main(reset: bool) -> None:
    settings = get_settings()
    conn = connect(settings.db_path)
    init_db(conn)

    if reset:
        conn.execute("DELETE FROM paper_trades")
        conn.commit()

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

    trades = run_trend_level1(df, settings)

    conn.executemany(
        """
        INSERT OR IGNORE INTO paper_trades (
            strategy_name, entry_ts, exit_ts, entry_price, exit_price,
            breakout_level, er, atr, exit_reason, pnl, pnl_pct
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        trades,
    )
    conn.commit()

    print(f"paper trades inserted: {len(trades)}")


if __name__ == "__main__":
    args = parse_args()
    main(args.reset)
