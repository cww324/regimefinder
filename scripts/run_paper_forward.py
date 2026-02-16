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


def main() -> None:
    settings = get_settings()
    conn = connect(settings.db_path)
    init_db(conn)

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
                breakout_level, er, atr, exit_reason, pnl, pnl_pct
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            trades,
        )
        conn.commit()

    save_state(conn, state)
    if new_last_processed_ts:
        save_last_processed_ts(conn, new_last_processed_ts)

    print(f"forward trades inserted: {len(trades)}")


if __name__ == "__main__":
    main()
