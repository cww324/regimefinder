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


def _coerce_numeric_columns(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    for col in cols:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def load_symbol_ohlcv_last_days(
    dsn: str,
    venue_code: str,
    symbol_code: str,
    timeframe_code: str,
    days: int,
) -> pd.DataFrame:
    cutoff = datetime.now(timezone.utc) - timedelta(days=int(days))
    with rc.connect(dsn) as conn:
        q = """
            SELECT
                EXTRACT(EPOCH FROM c.ts)::bigint AS ts,
                c.open,
                c.high,
                c.low,
                c.close,
                c.volume
            FROM rc.candles c
            JOIN rc.symbols s ON s.symbol_id = c.symbol_id
            JOIN rc.venues v ON v.venue_id = s.venue_id
            JOIN rc.timeframes tf ON tf.timeframe_id = c.timeframe_id
            WHERE v.venue_code = %s
              AND s.symbol_code = %s
              AND tf.timeframe_code = %s
              AND c.ts >= %s
            ORDER BY c.ts
        """
        df = _fetch_df(conn, q, (venue_code, symbol_code, timeframe_code, cutoff), ["ts", "open", "high", "low", "close", "volume"])
    if not df.empty:
        df["ts"] = df["ts"].astype(int)
        df = _coerce_numeric_columns(df, ["open", "high", "low", "close", "volume"])
    return df


def load_symbol_candles_last_days(
    dsn: str,
    venue_code: str,
    symbol_code: str,
    timeframe_code: str,
    days: int,
) -> pd.DataFrame:
    return load_symbol_ohlcv_last_days(
        dsn=dsn,
        venue_code=venue_code,
        symbol_code=symbol_code,
        timeframe_code=timeframe_code,
        days=days,
    )


def load_symbol_candles_with_features_last_days(
    dsn: str,
    venue_code: str,
    symbol_code: str,
    timeframe_code: str,
    days: int,
    feature_version: str = "v1",
) -> pd.DataFrame:
    cutoff = datetime.now(timezone.utc) - timedelta(days=int(days))
    with rc.connect(dsn) as conn:
        q = """
            SELECT
                EXTRACT(EPOCH FROM c.ts)::bigint AS ts,
                c.open,
                c.high,
                c.low,
                c.close,
                c.volume,
                MAX(CASE WHEN f.feature_name = 'atr14' THEN f.feature_value END) AS atr14,
                MAX(CASE WHEN f.feature_name = 'er20' THEN f.feature_value END) AS er20,
                MAX(CASE WHEN f.feature_name = 'rv48' THEN f.feature_value END) AS rv48,
                MAX(CASE WHEN f.feature_name = 'vwap48' THEN f.feature_value END) AS vwap48
            FROM rc.candles c
            JOIN rc.symbols s ON s.symbol_id = c.symbol_id
            JOIN rc.venues v ON v.venue_id = s.venue_id
            JOIN rc.timeframes tf ON tf.timeframe_id = c.timeframe_id
            LEFT JOIN rc.features f
              ON f.symbol_id = c.symbol_id
             AND f.timeframe_id = c.timeframe_id
             AND f.ts = c.ts
             AND f.feature_version = %s
            WHERE v.venue_code = %s
              AND s.symbol_code = %s
              AND tf.timeframe_code = %s
              AND c.ts >= %s
            GROUP BY c.ts, c.open, c.high, c.low, c.close, c.volume
            ORDER BY c.ts
        """
        cols = ["ts", "open", "high", "low", "close", "volume", "atr14", "er20", "rv48", "vwap48"]
        df = _fetch_df(conn, q, (feature_version, venue_code, symbol_code, timeframe_code, cutoff), cols)
    if not df.empty:
        df["ts"] = df["ts"].astype(int)
        df = _coerce_numeric_columns(df, ["open", "high", "low", "close", "volume", "atr14", "er20", "rv48", "vwap48"])
    return df


def load_btc_eth_merged_last_days(dsn: str, days: int) -> pd.DataFrame:
    cutoff = datetime.now(timezone.utc) - timedelta(days=int(days))
    with rc.connect(dsn) as conn:
        q = """
            SELECT
                EXTRACT(EPOCH FROM cb.ts)::bigint AS ts,
                cb.open  AS open_btc,
                cb.high  AS high_btc,
                cb.low   AS low_btc,
                cb.close AS close_btc,
                cb.volume AS volume_btc,
                ce.open  AS open_eth,
                ce.high  AS high_eth,
                ce.low   AS low_eth,
                ce.close AS close_eth,
                ce.volume AS volume_eth
            FROM rc.candles cb
            JOIN rc.symbols sb ON sb.symbol_id = cb.symbol_id
            JOIN rc.venues vb ON vb.venue_id = sb.venue_id
            JOIN rc.timeframes tfb ON tfb.timeframe_id = cb.timeframe_id
            JOIN rc.candles ce ON ce.ts = cb.ts AND ce.timeframe_id = cb.timeframe_id
            JOIN rc.symbols se ON se.symbol_id = ce.symbol_id
            JOIN rc.venues ve ON ve.venue_id = se.venue_id
            WHERE vb.venue_code = 'coinbase'
              AND ve.venue_code = 'coinbase'
              AND tfb.timeframe_code = '5m'
              AND sb.symbol_code = 'BTC-USD'
              AND se.symbol_code = 'ETH-USD'
              AND cb.ts >= %s
            ORDER BY cb.ts
        """
        cols = [
            "ts",
            "open_btc",
            "high_btc",
            "low_btc",
            "close_btc",
            "volume_btc",
            "open_eth",
            "high_eth",
            "low_eth",
            "close_eth",
            "volume_eth",
        ]
        df = _fetch_df(conn, q, (cutoff,), cols)
    if not df.empty:
        df["ts"] = df["ts"].astype(int)
        df = _coerce_numeric_columns(
            df,
            [
                "open_btc",
                "high_btc",
                "low_btc",
                "close_btc",
                "volume_btc",
                "open_eth",
                "high_eth",
                "low_eth",
                "close_eth",
                "volume_eth",
            ],
        )
    return df


def upsert_feature_rows(
    dsn: str,
    venue_code: str,
    symbol_code: str,
    timeframe_code: str,
    rows: list[tuple[int, float, float, float, float]],
    feature_version: str = "v1",
) -> int:
    if not rows:
        return 0

    with rc.connect(dsn) as conn:
        venue_id = rc.get_venue_id(conn, venue_code)
        timeframe_id = rc.get_timeframe_id(conn, timeframe_code)
        symbol = rc.get_symbols(conn, venue_id, [symbol_code])[0]

        payload: list[tuple[Any, ...]] = []
        for ts, atr14, er20, rv48, vwap48 in rows:
            dt = datetime.fromtimestamp(int(ts), tz=timezone.utc).replace(microsecond=0)
            payload.extend(
                [
                    (symbol.symbol_id, timeframe_id, dt, "atr14", feature_version, float(atr14)),
                    (symbol.symbol_id, timeframe_id, dt, "er20", feature_version, float(er20)),
                    (symbol.symbol_id, timeframe_id, dt, "rv48", feature_version, float(rv48)),
                    (symbol.symbol_id, timeframe_id, dt, "vwap48", feature_version, float(vwap48)),
                ]
            )

        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO rc.features (
                    symbol_id, timeframe_id, ts, feature_name, feature_version, feature_value
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (symbol_id, timeframe_id, ts, feature_name, feature_version)
                DO UPDATE SET feature_value = EXCLUDED.feature_value
                """,
                payload,
            )
        conn.commit()
    return len(payload)
