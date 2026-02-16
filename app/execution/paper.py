from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

from app.config import Settings
from app.strategy.trend import breakout_signal, trend_regime


@dataclass
class Position:
    entry_idx: int
    entry_ts: int
    entry_price: float
    entry_regime: str
    entry_atr: float
    entry_er: float
    breakout_level: float
    regime_switch_count: int = 0


def _fill_price(price: float, bps: float, side: str) -> float:
    cost = price * (bps / 10000.0)
    if side == "buy":
        return price + cost
    return price - cost


def _exit_reason(
    row: pd.Series,
    position: Position,
    time_stop_candles: int,
    stop_loss_atr_mult: float,
    target_atr_mult: float,
    breakeven_atr_mult: float,
) -> Optional[Tuple[str, float]]:
    atr = float(row["atr14"])
    high = float(row["high"])
    low = float(row["low"])
    close_idx = int(row["idx"])

    if np.isnan(atr):
        return None

    bars_held = close_idx - position.entry_idx

    stop_price = position.entry_price - stop_loss_atr_mult * atr
    target_price = position.entry_price + target_atr_mult * atr

    # Move stop to breakeven once in favor
    if high >= position.entry_price + breakeven_atr_mult * atr:
        stop_price = max(stop_price, position.entry_price)

    # Stop/target checks use current bar high/low, fills at next open
    if low <= stop_price:
        return "exit_stop_hit", stop_price
    if high >= target_price:
        return "exit_target_hit", target_price

    # Time stop
    if bars_held >= time_stop_candles:
        return "exit_time_stop", float(row["close"])

    # Regime switch with hysteresis
    current_regime = trend_regime(float(row["er20"]))
    if current_regime == "unknown":
        return None

    if current_regime != position.entry_regime:
        position.regime_switch_count += 1
    else:
        position.regime_switch_count = 0

    if current_regime == "uncertain" and position.regime_switch_count < 2:
        return None
    if current_regime != position.entry_regime and position.regime_switch_count >= 1:
        return "exit_regime_switch", float(row["close"])

    return None


def run_trend_level1(
    df: pd.DataFrame,
    settings: Settings,
    lookback: int = 20,
) -> List[Tuple]:
    trades: List[Tuple] = []
    position: Optional[Position] = None
    cooldown_until_idx = -1
    cost_bps = settings.half_spread_bps + settings.slippage_bps

    data = df.copy()
    data = data.sort_values("ts").reset_index(drop=True)
    data["idx"] = data.index

    for i in range(len(data) - 1):
        row = data.iloc[i]
        next_row = data.iloc[i + 1]
        next_open = float(next_row["open"])
        next_ts = int(next_row["ts"])

        if position:
            exit_info = _exit_reason(
                row=row,
                position=position,
                time_stop_candles=10,
                stop_loss_atr_mult=1.2,
                target_atr_mult=2.0,
                breakeven_atr_mult=1.0,
            )
            if exit_info:
                reason, _ = exit_info
                exit_price = _fill_price(next_open, cost_bps, "sell")
                pnl = exit_price - position.entry_price
                pnl_pct = pnl / position.entry_price
                trades.append(
                    (
                        "trend_level1",
                        position.entry_ts,
                        next_ts,
                        position.entry_price,
                        exit_price,
                        position.breakout_level,
                        position.entry_er,
                        position.entry_atr,
                        reason,
                        pnl,
                        pnl_pct,
                    )
                )
                position = None
                cooldown_until_idx = i + settings.cooldown_bars
                continue

        if position is None and i > cooldown_until_idx:
            regime = trend_regime(float(row["er20"]))
            if regime != "trend":
                continue

            signal = breakout_signal(
                data, i, lookback=lookback, atr_buffer=settings.breakout_atr_buffer
            )
            if not signal:
                continue

            if np.isnan(float(row["atr14"])):
                continue

            entry_price = _fill_price(next_open, cost_bps, "buy")
            position = Position(
                entry_idx=i + 1,
                entry_ts=next_ts,
                entry_price=entry_price,
                entry_regime=regime,
                entry_atr=float(row["atr14"]),
                entry_er=signal.er,
                breakout_level=signal.breakout_level,
            )

    return trades
