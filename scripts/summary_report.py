import pandas as pd

from app.config import get_settings
from app.data.db import connect, init_db


def max_drawdown(equity):
    peak = equity[0]
    max_dd = 0.0
    for x in equity:
        peak = max(peak, x)
        dd = (peak - x)
        max_dd = max(max_dd, dd)
    return max_dd


def main() -> None:
    settings = get_settings()
    conn = connect(settings.db_path)
    init_db(conn)

    trades = pd.read_sql_query(
        "SELECT entry_ts, exit_ts, pnl, pnl_pct, exit_reason FROM paper_trades ORDER BY exit_ts",
        conn,
    )

    if trades.empty:
        print("no trades found")
        return

    total_pnl = trades["pnl"].sum()
    avg_pnl = trades["pnl"].mean()
    avg_pnl_pct = trades["pnl_pct"].mean()
    wins = (trades["pnl"] > 0).sum()
    losses = (trades["pnl"] <= 0).sum()
    win_rate = wins / len(trades)

    equity = trades["pnl"].cumsum().tolist()
    dd = max_drawdown(equity)

    by_reason = trades.groupby("exit_reason")["pnl"].agg(["count", "sum", "mean"])

    print(f"trades: {len(trades)}")
    print(f"wins: {wins} losses: {losses} win_rate: {win_rate:.2%}")
    print(f"total_pnl: {total_pnl:.2f} avg_pnl: {avg_pnl:.2f} avg_pnl_pct: {avg_pnl_pct:.4f}")
    print(f"max_drawdown (pnl units): {dd:.2f}")
    print("by exit_reason:")
    print(by_reason.to_string())


if __name__ == "__main__":
    main()
