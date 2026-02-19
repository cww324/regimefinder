import argparse
import hashlib
import sqlite3
from typing import Iterable

import pandas as pd

from app.db.market_data import load_symbol_ohlcv_last_days


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Compare legacy SQLite candles vs rc Postgres candles for overlap window.")
    p.add_argument("--dsn", required=True, help="Postgres DSN")
    p.add_argument("--days", type=int, default=30, help="Overlap window in days")
    p.add_argument("--venue", default="coinbase")
    p.add_argument("--timeframe", default="5m")
    p.add_argument("--btc-sqlite", default="data/market.sqlite")
    p.add_argument("--eth-sqlite", default="data/market_eth.sqlite")
    return p.parse_args()


def load_legacy(path: str, days: int) -> pd.DataFrame:
    con = sqlite3.connect(path)
    try:
        now_ts = int(pd.Timestamp.now("UTC").timestamp())
        cutoff = now_ts - (int(days) * 86400)
        df = pd.read_sql_query(
            "SELECT ts, open, high, low, close, volume FROM candles_5m WHERE ts >= ? ORDER BY ts",
            con,
            params=(cutoff,),
        )
    finally:
        con.close()
    if not df.empty:
        df["ts"] = df["ts"].astype(int)
    return df


def fingerprint(df: pd.DataFrame) -> str:
    if df.empty:
        return ""
    h = hashlib.sha256()
    for row in df.itertuples(index=False):
        line = f"{int(row.ts)}|{float(row.open):.8f}|{float(row.high):.8f}|{float(row.low):.8f}|{float(row.close):.8f}|{float(row.volume):.8f}\n"
        h.update(line.encode("ascii"))
    return h.hexdigest()


def summarize(name: str, legacy: pd.DataFrame, rc_df: pd.DataFrame) -> dict:
    legacy_ts = set(legacy["ts"].tolist()) if not legacy.empty else set()
    rc_ts = set(rc_df["ts"].tolist()) if not rc_df.empty else set()
    missing_in_rc = sorted(legacy_ts - rc_ts)
    extra_in_rc = sorted(rc_ts - legacy_ts)

    return {
        "symbol": name,
        "legacy_count": int(len(legacy)),
        "rc_count": int(len(rc_df)),
        "legacy_min_ts": int(legacy["ts"].min()) if not legacy.empty else None,
        "legacy_max_ts": int(legacy["ts"].max()) if not legacy.empty else None,
        "rc_min_ts": int(rc_df["ts"].min()) if not rc_df.empty else None,
        "rc_max_ts": int(rc_df["ts"].max()) if not rc_df.empty else None,
        "legacy_fingerprint": fingerprint(legacy),
        "rc_fingerprint": fingerprint(rc_df),
        "missing_ts_in_rc_count": len(missing_in_rc),
        "extra_ts_in_rc_count": len(extra_in_rc),
        "missing_ts_in_rc_sample": missing_in_rc[:10],
        "extra_ts_in_rc_sample": extra_in_rc[:10],
    }


def print_summary(summary: dict) -> None:
    print(f"symbol={summary['symbol']}")
    print(f"  counts legacy={summary['legacy_count']} rc={summary['rc_count']}")
    print(f"  ts_range legacy=[{summary['legacy_min_ts']},{summary['legacy_max_ts']}] rc=[{summary['rc_min_ts']},{summary['rc_max_ts']}]")
    print(f"  fingerprints legacy={summary['legacy_fingerprint']} rc={summary['rc_fingerprint']}")
    print(f"  missing_ts_in_rc={summary['missing_ts_in_rc_count']} extra_ts_in_rc={summary['extra_ts_in_rc_count']}")
    if summary["missing_ts_in_rc_sample"]:
        print(f"  missing_ts_in_rc_sample={summary['missing_ts_in_rc_sample']}")
    if summary["extra_ts_in_rc_sample"]:
        print(f"  extra_ts_in_rc_sample={summary['extra_ts_in_rc_sample']}")


def main() -> None:
    args = parse_args()

    legacy_btc = load_legacy(args.btc_sqlite, args.days)
    legacy_eth = load_legacy(args.eth_sqlite, args.days)

    rc_btc = load_symbol_ohlcv_last_days(args.dsn, args.venue, "BTC-USD", args.timeframe, args.days)
    rc_eth = load_symbol_ohlcv_last_days(args.dsn, args.venue, "ETH-USD", args.timeframe, args.days)

    btc_summary = summarize("BTC-USD", legacy_btc, rc_btc)
    eth_summary = summarize("ETH-USD", legacy_eth, rc_eth)

    print_summary(btc_summary)
    print_summary(eth_summary)


if __name__ == "__main__":
    main()
