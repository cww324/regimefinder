from __future__ import annotations

import math
from typing import Iterable, List, Tuple

import numpy as np
import pandas as pd


def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    data = df.copy()
    data = data.sort_values("ts")

    close = data["close"].astype(float)
    high = data["high"].astype(float)
    low = data["low"].astype(float)
    volume = data["volume"].astype(float)

    # Returns
    data["r1"] = np.log(close / close.shift(1))

    # ATR(14) using simple moving average of True Range
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    data["atr14"] = tr.rolling(14).mean()

    # Efficiency Ratio (ER) over 20 bars
    n_er = 20
    net = (close - close.shift(n_er)).abs()
    gross = close.diff().abs().rolling(n_er).sum()
    data["er20"] = net / gross.replace(0, np.nan)

    # Realized Volatility (RV) over 48 bars
    data["rv48"] = data["r1"].rolling(48).std()

    # Rolling VWAP over 48 bars using typical price
    typical = (high + low + close) / 3.0
    vwap_num = (typical * volume).rolling(48).sum()
    vwap_den = volume.rolling(48).sum()
    data["vwap48"] = vwap_num / vwap_den.replace(0, np.nan)

    return data[["ts", "atr14", "er20", "rv48", "vwap48"]]


def to_feature_rows(df: pd.DataFrame) -> List[Tuple[int, float, float, float, float]]:
    rows: List[Tuple[int, float, float, float, float]] = []
    for _, row in df.iterrows():
        if any(math.isnan(x) for x in [row["atr14"], row["er20"], row["rv48"], row["vwap48"]]):
            continue
        rows.append(
            (
                int(row["ts"]),
                float(row["atr14"]),
                float(row["er20"]),
                float(row["rv48"]),
                float(row["vwap48"]),
            )
        )
    return rows
