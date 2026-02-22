"""
Derivatives data loader for rc schema.

Loads funding rates from rc.funding_rates
(sourced from Hyperliquid public API via scripts/backfill_derivatives.py).

These are 1h-resolution series. In research runners they are merged onto the
5m candle frame via pd.merge_asof (direction='backward') so each 5m bar
carries the most recent hourly settlement value forward.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from app.db import rc


def _fetch_df(conn, query: str, params: tuple[Any, ...], columns: list[str]) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall()
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows, columns=columns)


def load_funding_rates_last_days(
    dsn: str,
    days: int,
    venue_code: str = "hyperliquid",
) -> pd.DataFrame:
    """
    Load BTC and ETH hourly funding rate settlements for the last `days` days.

    Returns a DataFrame with columns:
        dt              TIMESTAMPTZ-aware datetime (1h settlement times)
        funding_rate_btc  float  (e.g. 0.0001 = 0.01% per 1h)
        funding_rate_eth  float

    Rows are aligned to settlement timestamps where both BTC and ETH settled.
    Sorted ascending by dt. Suitable for merge_asof onto 5m frames.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=int(days))

    with rc.connect(dsn) as conn:
        q = """
            SELECT
                fb.ts                              AS dt,
                fb.funding_rate::double precision  AS funding_rate_btc,
                fe.funding_rate::double precision  AS funding_rate_eth
            FROM rc.funding_rates fb
            JOIN rc.symbols sb ON sb.symbol_id = fb.symbol_id
            JOIN rc.venues vb  ON vb.venue_id  = fb.venue_id
            JOIN rc.funding_rates fe ON fe.ts = fb.ts AND fe.venue_id = fb.venue_id
            JOIN rc.symbols se ON se.symbol_id = fe.symbol_id
            WHERE vb.venue_code = %s
              AND sb.symbol_code = 'BTC'
              AND se.symbol_code = 'ETH'
              AND fb.ts >= %s
            ORDER BY fb.ts
        """
        df = _fetch_df(conn, q, (venue_code, cutoff), ["dt", "funding_rate_btc", "funding_rate_eth"])

    if not df.empty:
        df["dt"] = pd.to_datetime(df["dt"], utc=True)
        df["funding_rate_btc"] = pd.to_numeric(df["funding_rate_btc"], errors="coerce")
        df["funding_rate_eth"] = pd.to_numeric(df["funding_rate_eth"], errors="coerce")

    return df


def load_open_interest_last_days(
    dsn: str,
    days: int,
    venue_code: str = "hyperliquid",
) -> pd.DataFrame:
    """
    Load BTC and ETH open interest snapshots for the last `days` days.

    Returns a DataFrame with columns:
        dt              TIMESTAMPTZ-aware datetime
        oi_contracts_btc  float  (base-asset contracts)
        oi_contracts_eth  float
        oi_usd_btc        float  (USD notional, may be NULL)
        oi_usd_eth        float

    Sorted ascending by dt.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=int(days))

    with rc.connect(dsn) as conn:
        q = """
            SELECT
                ob.ts                              AS dt,
                ob.oi_contracts::double precision  AS oi_contracts_btc,
                ob.oi_usd::double precision        AS oi_usd_btc,
                oe.oi_contracts::double precision  AS oi_contracts_eth,
                oe.oi_usd::double precision        AS oi_usd_eth
            FROM rc.open_interest ob
            JOIN rc.symbols sb ON sb.symbol_id = ob.symbol_id
            JOIN rc.venues vb  ON vb.venue_id  = ob.venue_id
            JOIN rc.open_interest oe ON oe.ts = ob.ts AND oe.venue_id = ob.venue_id
            JOIN rc.symbols se ON se.symbol_id = oe.symbol_id
            WHERE vb.venue_code = %s
              AND sb.symbol_code = 'BTC'
              AND se.symbol_code = 'ETH'
              AND ob.ts >= %s
            ORDER BY ob.ts
        """
        cols = ["dt", "oi_contracts_btc", "oi_usd_btc", "oi_contracts_eth", "oi_usd_eth"]
        df = _fetch_df(conn, q, (venue_code, cutoff), cols)

    if not df.empty:
        df["dt"] = pd.to_datetime(df["dt"], utc=True)
        for col in ["oi_contracts_btc", "oi_usd_btc", "oi_contracts_eth", "oi_usd_eth"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def load_derivatives_merged_last_days(dsn: str, days: int) -> pd.DataFrame:
    """
    Load funding rates and OI, merged into a single 8h-resolution DataFrame.

    Merges on settlement timestamp (inner join — only rows where both
    funding and OI records exist). Returns columns:
        dt
        funding_rate_btc, funding_rate_eth
        oi_contracts_btc, oi_contracts_eth, oi_usd_btc, oi_usd_eth

    Suitable for merge_asof onto a 5m candle frame:

        x = pd.merge_asof(
            x.sort_values("dt"),
            deriv.sort_values("dt"),
            on="dt",
            direction="backward",
        )
    """
    funding = load_funding_rates_last_days(dsn=dsn, days=days)
    oi = load_open_interest_last_days(dsn=dsn, days=days)

    if funding.empty and oi.empty:
        return pd.DataFrame(columns=[
            "dt",
            "funding_rate_btc", "funding_rate_eth",
            "oi_contracts_btc", "oi_contracts_eth",
            "oi_usd_btc", "oi_usd_eth",
        ])

    if funding.empty:
        return oi
    if oi.empty:
        return funding

    merged = pd.merge(funding, oi, on="dt", how="inner").sort_values("dt").reset_index(drop=True)
    return merged


def compute_funding_features(deriv: pd.DataFrame, window_bars: int = 8640) -> pd.DataFrame:
    """
    Compute derived features from the 1h-resolution Hyperliquid funding frame.
    Call this AFTER merge_asof onto the 5m candle frame so rolling windows
    operate on the 5m-granularity carry-forward values.

    `window_bars` is in number of 5m bars:
        8640 = 30 days (30 * 24 * 12)   ← default, good for 180-day dataset
       17280 = 60 days
       25920 = 90 days

    Since Hyperliquid funding updates every hour (12 bars at 5m), the rolling
    window sees a new unique value every 12 bars.

    Args:
        deriv: The 5m-indexed frame AFTER merge_asof (has funding_rate_btc etc.)
        window_bars: rolling window in number of 5m bars for percentile rank.

    Returns the input frame with additional columns added in-place.
    """
    import numpy as np

    w = int(window_bars)

    for asset in ("btc", "eth"):
        col = f"funding_rate_{asset}"
        if col not in deriv.columns:
            continue

        f = deriv[col]

        # Annualized rate for context (24 settlements/day × 365 days for hourly funding)
        deriv[f"funding_{asset}_ann"] = f * 24 * 365

        # Rolling percentile rank and z-score over `w` 5m bars
        deriv[f"funding_{asset}_pct"] = f.rolling(w).rank(pct=True)
        roll_mean = f.rolling(w).mean()
        roll_std = f.rolling(w).std(ddof=0).replace(0, np.nan)
        deriv[f"funding_{asset}_z"] = (f - roll_mean) / roll_std

        # Regime flags
        deriv[f"funding_{asset}_extreme_long"] = deriv[f"funding_{asset}_pct"].ge(0.90)
        deriv[f"funding_{asset}_extreme_short"] = deriv[f"funding_{asset}_pct"].le(0.10)
        deriv[f"funding_{asset}_sign"] = np.sign(f)

        # Flip: funding sign changed vs prior settlement
        # Since funding is carry-forwarded, use .diff() on the raw value
        # A flip is when sign of f changes
        deriv[f"funding_{asset}_flip"] = (
            np.sign(f).ne(np.sign(f).shift(1)) & np.sign(f).ne(0)
        )

    for asset in ("btc", "eth"):
        oi_col = f"oi_contracts_{asset}"
        if oi_col not in deriv.columns:
            continue

        oi = deriv[oi_col]
        deriv[f"oi_{asset}_pct"] = oi.rolling(w).rank(pct=True)
        # OI % change from prior settlement (meaningful change, not every 5m bar)
        deriv[f"oi_{asset}_chg"] = oi.pct_change().where(oi.diff().ne(0))

    return deriv
