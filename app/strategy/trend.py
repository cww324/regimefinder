from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class TrendSignal:
    breakout_level: float
    er: float


def trend_regime(er: float) -> str:
    if np.isnan(er):
        return "unknown"
    if er >= 0.35:
        return "trend"
    if er <= 0.25:
        return "mean"
    return "uncertain"


def breakout_signal(
    df: pd.DataFrame,
    idx: int,
    lookback: int = 20,
    atr_buffer: float = 0.0,
    requires_close: bool = True,
) -> Optional[TrendSignal]:
    if idx < lookback:
        return None
    window = df.iloc[idx - lookback : idx]
    breakout_level = float(window["high"].max())
    close = float(df.iloc[idx]["close"])
    er = float(df.iloc[idx]["er20"])
    atr = float(df.iloc[idx]["atr14"])
    if np.isnan(er):
        return None
    if np.isnan(atr):
        return None
    # Current behavior uses close; requires_close keeps explicit intent.
    price = close
    if price > breakout_level + (atr_buffer * atr):
        return TrendSignal(breakout_level=breakout_level, er=er)
    return None
