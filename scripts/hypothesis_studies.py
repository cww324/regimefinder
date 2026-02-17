import argparse
from datetime import datetime, timezone

import pandas as pd

from app.data.db import connect, init_db


HORIZONS = [5, 10, 20]
RV_BINS = [0.0, 0.1, 0.3, 0.7, 0.9, 1.0]
RV_LABELS = ["0-10%", "10-30%", "30-70%", "70-90%", "90-100%"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a single hypothesis study.")
    parser.add_argument("--hypothesis", required=True, help="Hypothesis id (e.g., H1)")
    parser.add_argument("--days", type=int, default=180, help="Lookback window in days.")
    parser.add_argument("--window", type=int, default=2000, help="Rolling window for percentiles.")
    return parser.parse_args()


def forward_returns(close: pd.Series, h: int) -> pd.Series:
    return close.shift(-h) / close - 1.0


def summarize_series(s: pd.Series) -> dict:
    s = s.dropna()
    if s.empty:
        return {"mean": 0.0, "median": 0.0, "std": 0.0, "n": 0}
    return {"mean": s.mean(), "median": s.median(), "std": s.std(ddof=0), "n": len(s)}


def append_findings(hypothesis: str, header: str, table_text: str, days: int, window: int) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    block = (
        f"\n### {header}\n"
        f"- Run: {ts}\n"
        f"- Days: {days}, Window: {window}\n\n"
        f"{table_text}\n"
    )

    with open("FINDINGS.md", "a", encoding="utf-8") as f:
        f.write(block)

    with open("FINDINGS_TECHNICAL.md", "a", encoding="utf-8") as f:
        f.write(
            f"\n## {header}\n"
            f"Run: {ts}\n\n"
            f"Command: python -m scripts.hypothesis_studies --hypothesis {hypothesis} --days {days} --window {window}\n\n"
            f"{table_text}\n"
        )


def run_h1(days: int, window: int) -> pd.DataFrame:
    conn = connect("data/market.sqlite")
    init_db(conn)

    cutoff_ts = int(pd.Timestamp.utcnow().timestamp()) - (days * 86400)
    df = pd.read_sql_query(
        """
        SELECT c.ts, c.close, f.rv48
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

    # Rolling RV percentile (backward-looking only)
    df["rv_pct"] = df["rv48"].rolling(window).apply(lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False)
    df["rv_bucket"] = pd.cut(df["rv_pct"], bins=RV_BINS, labels=RV_LABELS, right=False)

    rows = []
    for bucket in RV_LABELS:
        subset = df[df["rv_bucket"] == bucket]
        for h in HORIZONS:
            stats = summarize_series(forward_returns(subset["close"], h).abs())
            rows.append({"bucket": bucket, "h": h, **stats})

    return pd.DataFrame(rows)


def main(hypothesis: str, days: int, window: int) -> None:
    hypothesis = hypothesis.upper()
    if hypothesis != "H1":
        raise SystemExit("Only H1 is implemented in this version. Use --hypothesis H1.")

    header = "H1: Volatility Compression → Expansion"
    print(f"=== Running {header} ===")

    table = run_h1(days, window)
    print(table.to_string(index=False))

    append_findings("H1", header, table.to_string(index=False), days, window)


if __name__ == "__main__":
    args = parse_args()
    main(args.hypothesis, args.days, args.window)
