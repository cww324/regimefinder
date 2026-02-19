import argparse
from datetime import datetime, timezone

import pandas as pd

from app.data.db import connect, init_db
from app.db.market_data import load_symbol_candles_last_days, load_symbol_candles_with_features_last_days


HORIZONS = [5, 10, 20]
RV_BINS = [0.0, 0.1, 0.3, 0.7, 0.9, 1.0]
RV_LABELS = ["0-10%", "10-30%", "30-70%", "70-90%", "90-100%"]
SHOCK_BINS = [0.0, 0.9, 0.95, 0.99, 0.995, 1.0]
SHOCK_LABELS = ["0-90%", "90-95%", "95-99%", "99-99.5%", "99.5-100%"]
SHOCK_ATR_LABELS = ["0-1.5xATR", "1.5-2.5xATR", ">2.5xATR"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a single hypothesis study.")
    parser.add_argument("--hypothesis", required=True, help="Hypothesis id (e.g., H1)")
    parser.add_argument("--days", type=int, default=180, help="Lookback window in days.")
    parser.add_argument("--window", type=int, default=2000, help="Rolling window for percentiles.")
    parser.add_argument("--dsn", type=str, default="", help="Optional Postgres DSN for rc schema")
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


def _load_close(days: int, dsn: str = "") -> pd.DataFrame:
    if dsn:
        return load_symbol_candles_last_days(
            dsn=dsn, venue_code="coinbase", symbol_code="BTC-USD", timeframe_code="5m", days=days
        )[["ts", "close"]].copy()
    conn = connect("data/market.sqlite")
    init_db(conn)
    cutoff_ts = int(pd.Timestamp.utcnow().timestamp()) - (days * 86400)
    return pd.read_sql_query(
        """
        SELECT ts, close
        FROM candles_5m
        WHERE ts >= ?
        ORDER BY ts
        """,
        conn,
        params=(cutoff_ts,),
    )


def _load_close_rv(days: int, dsn: str = "") -> pd.DataFrame:
    if dsn:
        return load_symbol_candles_with_features_last_days(
            dsn=dsn, venue_code="coinbase", symbol_code="BTC-USD", timeframe_code="5m", days=days
        )[["ts", "close", "rv48"]].copy()
    conn = connect("data/market.sqlite")
    init_db(conn)
    cutoff_ts = int(pd.Timestamp.utcnow().timestamp()) - (days * 86400)
    return pd.read_sql_query(
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


def _load_open_close_atr_rv(days: int, dsn: str = "") -> pd.DataFrame:
    if dsn:
        return load_symbol_candles_with_features_last_days(
            dsn=dsn, venue_code="coinbase", symbol_code="BTC-USD", timeframe_code="5m", days=days
        )[["ts", "open", "close", "atr14", "rv48"]].copy()
    conn = connect("data/market.sqlite")
    init_db(conn)
    cutoff_ts = int(pd.Timestamp.utcnow().timestamp()) - (days * 86400)
    return pd.read_sql_query(
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


def run_h1(days: int, window: int, dsn: str = "") -> pd.DataFrame:
    df = _load_close_rv(days=days, dsn=dsn)

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


def run_h2(days: int, window: int, dsn: str = "") -> pd.DataFrame:
    df = _load_close(days=days, dsn=dsn)

    if df.empty:
        raise SystemExit("no data")

    df["r1"] = df["close"].pct_change()
    df["abs_r1"] = df["r1"].abs()
    # Percentile is computed on historical window ending at t (no lookahead).
    df["abs_r1_pct"] = df["abs_r1"].rolling(window).apply(
        lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False
    )
    df["shock_bucket"] = pd.cut(df["abs_r1_pct"], bins=SHOCK_BINS, labels=SHOCK_LABELS, right=False)

    rows = []
    for bucket in SHOCK_LABELS:
        subset = df[df["shock_bucket"] == bucket]
        for h in HORIZONS:
            continuation = subset["r1"].apply(lambda x: 1.0 if x > 0 else (-1.0 if x < 0 else 0.0)) * forward_returns(
                subset["close"], h
            )
            stats = summarize_series(continuation)
            rows.append({"bucket": bucket, "h": h, **stats})

    return pd.DataFrame(rows)


def run_h2s(days: int, window: int, dsn: str = "") -> tuple[pd.DataFrame, pd.DataFrame]:
    df = _load_close(days=days, dsn=dsn)

    if df.empty:
        raise SystemExit("no data")

    df["r1"] = df["close"].pct_change()
    df["abs_r1"] = df["r1"].abs()
    df["abs_r1_pct"] = df["abs_r1"].rolling(window).apply(
        lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False
    )
    df["shock_bucket"] = pd.cut(df["abs_r1_pct"], bins=SHOCK_BINS, labels=SHOCK_LABELS, right=False)
    df["shock_side"] = df["r1"].apply(lambda x: "pos" if x > 0 else ("neg" if x < 0 else "zero"))

    cont_rows = []
    fwd_rows = []
    for side in ["pos", "neg"]:
        side_df = df[df["shock_side"] == side]
        side_sign = 1.0 if side == "pos" else -1.0
        for bucket in SHOCK_LABELS:
            subset = side_df[side_df["shock_bucket"] == bucket]
            for h in HORIZONS:
                fwd = forward_returns(subset["close"], h)
                continuation = side_sign * fwd
                cont_stats = summarize_series(continuation)
                fwd_stats = summarize_series(fwd)

                cont_rows.append({"side": side, "bucket": bucket, "h": h, **cont_stats})
                fwd_rows.append(
                    {
                        "side": side,
                        "bucket": bucket,
                        "h": h,
                        "mean_fwd_return": fwd_stats["mean"],
                        "median_fwd_return": fwd_stats["median"],
                        "std_fwd_return": fwd_stats["std"],
                        "n": fwd_stats["n"],
                    }
                )

    return pd.DataFrame(cont_rows), pd.DataFrame(fwd_rows)


def run_h2s_vol(days: int, window: int, dsn: str = "") -> tuple[pd.DataFrame, pd.DataFrame]:
    df = _load_close_rv(days=days, dsn=dsn)

    if df.empty:
        raise SystemExit("no data")

    df["r1"] = df["close"].pct_change()
    df["abs_r1"] = df["r1"].abs()
    df["abs_r1_pct"] = df["abs_r1"].rolling(window).apply(
        lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False
    )
    # Same RV percentile definition as H1 (rolling, backward-looking only).
    df["rv_pct"] = df["rv48"].rolling(window).apply(lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False)

    df["shock_bucket"] = pd.cut(df["abs_r1_pct"], bins=SHOCK_BINS, labels=SHOCK_LABELS, right=False)
    df["rv_bucket"] = pd.cut(df["rv_pct"], bins=RV_BINS, labels=RV_LABELS, right=False)
    df["shock_side"] = df["r1"].apply(lambda x: "pos" if x > 0 else ("neg" if x < 0 else "zero"))

    cont_rows = []
    fwd_rows = []
    for side in ["pos", "neg"]:
        side_df = df[df["shock_side"] == side]
        side_sign = 1.0 if side == "pos" else -1.0
        for shock_bucket in SHOCK_LABELS:
            shock_df = side_df[side_df["shock_bucket"] == shock_bucket]
            for rv_bucket in RV_LABELS:
                subset = shock_df[shock_df["rv_bucket"] == rv_bucket]
                for h in HORIZONS:
                    fwd = forward_returns(subset["close"], h)
                    continuation = side_sign * fwd

                    cont_stats = summarize_series(continuation)
                    fwd_stats = summarize_series(fwd)

                    cont_rows.append(
                        {
                            "side": side,
                            "shock_bucket": shock_bucket,
                            "rv_bucket": rv_bucket,
                            "h": h,
                            **cont_stats,
                        }
                    )
                    fwd_rows.append(
                        {
                            "side": side,
                            "shock_bucket": shock_bucket,
                            "rv_bucket": rv_bucket,
                            "h": h,
                            **fwd_stats,
                        }
                    )

    return pd.DataFrame(cont_rows), pd.DataFrame(fwd_rows)


def add_robust_columns(table: pd.DataFrame) -> pd.DataFrame:
    out = table.copy()
    out["n_lt_20"] = out["n"] < 20
    out["t_stat"] = 0.0
    valid = (out["n"] > 0) & (out["std"] > 0)
    out.loc[valid, "t_stat"] = out.loc[valid, "mean"] / (out.loc[valid, "std"] / (out.loc[valid, "n"] ** 0.5))
    return out


def compute_h2s_vol_robust_tables(df: pd.DataFrame, window: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    df["r1"] = df["close"].pct_change()
    df["atr_r"] = df["atr14"] / df["close"]
    df["shock_atr"] = df["abs_r1"] = df["r1"].abs()
    df["shock_atr"] = df["shock_atr"] / df["atr_r"]
    df["rv_pct"] = df["rv48"].rolling(window).apply(lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False)

    df["shock_bucket"] = pd.Series("0-1.5xATR", index=df.index)
    df.loc[df["shock_atr"] > 1.5, "shock_bucket"] = "1.5-2.5xATR"
    df.loc[df["shock_atr"] > 2.5, "shock_bucket"] = ">2.5xATR"
    df["rv_bucket"] = pd.cut(df["rv_pct"], bins=RV_BINS, labels=RV_LABELS, right=False)
    df["shock_side"] = df["r1"].apply(lambda x: "pos" if x > 0 else ("neg" if x < 0 else "zero"))

    cont_rows = []
    fwd_rows = []
    for side in ["pos", "neg"]:
        side_df = df[df["shock_side"] == side]
        side_sign = 1.0 if side == "pos" else -1.0
        for shock_bucket in SHOCK_ATR_LABELS:
            shock_df = side_df[side_df["shock_bucket"] == shock_bucket]
            for rv_bucket in RV_LABELS:
                subset = shock_df[shock_df["rv_bucket"] == rv_bucket]
                for h in HORIZONS:
                    fwd = forward_returns(subset["close"], h)
                    continuation = side_sign * fwd
                    cont_stats = summarize_series(continuation)
                    fwd_stats = summarize_series(fwd)
                    cont_rows.append(
                        {
                            "side": side,
                            "shock_bucket": shock_bucket,
                            "rv_bucket": rv_bucket,
                            "h": h,
                            **cont_stats,
                        }
                    )
                    fwd_rows.append(
                        {
                            "side": side,
                            "shock_bucket": shock_bucket,
                            "rv_bucket": rv_bucket,
                            "h": h,
                            **fwd_stats,
                        }
                    )

    continuation_table = add_robust_columns(pd.DataFrame(cont_rows))
    fwd_table = add_robust_columns(pd.DataFrame(fwd_rows))
    return continuation_table, fwd_table


def load_h2s_vol_robust_data(days: int, dsn: str = "") -> pd.DataFrame:
    df = _load_open_close_atr_rv(days=days, dsn=dsn)

    if df.empty:
        raise SystemExit("no data")

    return df


def run_h2s_vol_robust(days: int, window: int, dsn: str = "") -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    df = load_h2s_vol_robust_data(days, dsn=dsn)
    continuation_table, fwd_table = compute_h2s_vol_robust_tables(df, window)

    top_tail = ["1.5-2.5xATR", ">2.5xATR"]
    high_rv = ["70-90%", "90-100%"]
    summary_cont = continuation_table[
        continuation_table["shock_bucket"].isin(top_tail)
        & continuation_table["rv_bucket"].isin(high_rv)
        & (continuation_table["n"] >= 20)
    ].copy()
    summary_fwd = fwd_table[
        fwd_table["shock_bucket"].isin(top_tail)
        & fwd_table["rv_bucket"].isin(high_rv)
        & (fwd_table["n"] >= 20)
    ].copy()

    return continuation_table, fwd_table, summary_cont, summary_fwd


def run_h2s_vol_robust_oos(days: int, window: int, dsn: str = "") -> pd.DataFrame:
    df = load_h2s_vol_robust_data(days, dsn=dsn)

    if len(df) < 2:
        raise SystemExit("not enough data")

    split_ts = int(df["ts"].min()) + (120 * 86400)
    is_df = df[df["ts"] < split_ts].copy()
    oos_df = df[df["ts"] >= split_ts].copy()

    if is_df.empty or oos_df.empty:
        raise SystemExit("split produced empty segment")

    is_cont, _ = compute_h2s_vol_robust_tables(is_df, window)
    oos_cont, _ = compute_h2s_vol_robust_tables(oos_df, window)

    filter_mask = (
        (is_cont["shock_bucket"] == "1.5-2.5xATR")
        & (is_cont["rv_bucket"].isin(["70-90%", "90-100%"]))
    )
    is_filtered = is_cont[filter_mask][["side", "shock_bucket", "rv_bucket", "h", "mean", "std", "n", "t_stat"]].copy()
    oos_filtered = oos_cont[
        (oos_cont["shock_bucket"] == "1.5-2.5xATR") & (oos_cont["rv_bucket"].isin(["70-90%", "90-100%"]))
    ][["side", "shock_bucket", "rv_bucket", "h", "mean", "std", "n", "t_stat"]].copy()

    comparison = is_filtered.merge(
        oos_filtered,
        on=["side", "shock_bucket", "rv_bucket", "h"],
        how="outer",
        suffixes=("_is", "_oos"),
    ).sort_values(["side", "rv_bucket", "h"])

    return comparison


def main(hypothesis: str, days: int, window: int, dsn: str = "") -> None:
    hypothesis = hypothesis.upper()
    if hypothesis == "H2S-VOL":
        hypothesis = "H2SVOL"
    if hypothesis == "H2S-VOL-ROBUST":
        hypothesis = "H2SVOLROBUST"
    if hypothesis == "H2S-VOL-ROBUST-OOS":
        hypothesis = "H2SVOLROBUSTOOS"
    if hypothesis == "H1":
        header = "H1: Volatility Compression → Expansion"
        table = run_h1(days, window, dsn=dsn)
    elif hypothesis == "H2":
        header = "H2: Large Shock Continuation"
        table = run_h2(days, window, dsn=dsn)
    elif hypothesis == "H2S":
        header = "H2S: Large Shock Continuation (By Side)"
        continuation_table, fwd_table = run_h2s(days, window, dsn=dsn)
        table_text = (
            "Continuation metric (sign-adjusted forward return):\n"
            f"{continuation_table.to_string(index=False)}\n\n"
            "Forward return metric (raw):\n"
            f"{fwd_table.to_string(index=False)}"
        )
        print(f"=== Running {header} ===")
        print(table_text)
        append_findings(hypothesis, header, table_text, days, window)
        return
    elif hypothesis == "H2SVOL":
        header = "H2S-VOL: Shock Asymmetry conditioned on RV regime"
        continuation_table, fwd_table = run_h2s_vol(days, window, dsn=dsn)
        table_text = (
            "Continuation metric (sign-adjusted forward return):\n"
            f"{continuation_table.to_string(index=False)}\n\n"
            "Forward return metric (raw):\n"
            f"{fwd_table.to_string(index=False)}"
        )
        print(f"=== Running {header} ===")
        print(table_text)
        append_findings("H2S-VOL", header, table_text, days, window)
        return
    elif hypothesis == "H2SVOLROBUST":
        header = "H2S-VOL-ROBUST: Shock Asymmetry Robustness Check"
        continuation_table, fwd_table, summary_cont, summary_fwd = run_h2s_vol_robust(days, window, dsn=dsn)
        table_text = (
            "Continuation metric (sign-adjusted forward return):\n"
            f"{continuation_table.to_string(index=False)}\n\n"
            "Forward return metric (raw):\n"
            f"{fwd_table.to_string(index=False)}\n\n"
            "Top-tail + high-RV summary (continuation metric; n >= 20):\n"
            f"{summary_cont.to_string(index=False)}\n\n"
            "Top-tail + high-RV summary (raw forward return; n >= 20):\n"
            f"{summary_fwd.to_string(index=False)}"
        )
        print(f"=== Running {header} ===")
        print(table_text)
        append_findings("H2S-VOL-ROBUST", header, table_text, days, window)
        return
    elif hypothesis == "H2SVOLROBUSTOOS":
        header = "H2S-VOL-ROBUST-OOS: In-sample vs Out-of-sample comparison"
        comparison = run_h2s_vol_robust_oos(days, window, dsn=dsn)
        table_text = comparison.to_string(index=False)
        print(f"=== Running {header} ===")
        print(table_text)
        append_findings("H2S-VOL-ROBUST-OOS", header, table_text, days, window)
        return
    else:
        raise SystemExit(
            "Unsupported hypothesis. Implemented: H1, H2, H2S, H2S-VOL, H2S-VOL-ROBUST, H2S-VOL-ROBUST-OOS."
        )

    print(f"=== Running {header} ===")
    print(table.to_string(index=False))

    append_findings(hypothesis, header, table.to_string(index=False), days, window)


if __name__ == "__main__":
    args = parse_args()
    main(args.hypothesis, args.days, args.window, args.dsn)
