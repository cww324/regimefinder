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
    qty: float = 0.0
    risk_usd: float = 0.0
    stop_dist: float = 0.0
    worst_price: float = 0.0
    best_price: float = 0.0
    initial_stop_price: float = 0.0


def _fill_price(price: float, bps: float, side: str) -> float:
    cost = price * (bps / 10000.0)
    if side == "buy":
        return price + cost
    return price - cost


def _trade_cost(price: float, qty: float, bps: float) -> float:
    return price * qty * (bps / 10000.0)


def _exit_reason(
    row: pd.Series,
    position: Position,
    time_stop_candles: int,
    stop_loss_atr_mult: float,
    target_atr_mult: float,
    breakeven_atr_mult: float,
    freeze_atr_at_entry: bool,
) -> Optional[Tuple[str, float]]:
    atr = float(position.entry_atr if freeze_atr_at_entry else row["atr14"])
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
    equity = settings.initial_equity

    data = df.copy()
    data = data.sort_values("ts").reset_index(drop=True)
    data["idx"] = data.index
    data["ema_fast"] = data["close"].ewm(span=settings.ema_fast_period, adjust=False).mean()
    data["ema_slow"] = data["close"].ewm(span=settings.ema_slow_period, adjust=False).mean()
    data["ema_slope"] = data["ema_slow"].diff(settings.ema_slope_bars)
    if settings.skip_top_decile_rv:
        data["rv_p90"] = (
            data["rv48"].shift(1).rolling(settings.rv_quantile_window).quantile(0.9)
        )

    pending_level = None
    pending_idx = None

    for i in range(len(data) - 1):
        row = data.iloc[i]
        next_row = data.iloc[i + 1]
        next_open = float(next_row["open"])
        next_ts = int(next_row["ts"])

        if position:
            # Track intratrade extremes (long-only)
            position.worst_price = min(position.worst_price, float(row["low"]))
            position.best_price = max(position.best_price, float(row["high"]))

            exit_info = _exit_reason(
                row=row,
                position=position,
                time_stop_candles=10,
                stop_loss_atr_mult=1.2,
                target_atr_mult=2.0,
                breakeven_atr_mult=1.0,
                freeze_atr_at_entry=settings.freeze_atr_at_entry,
            )
            if exit_info:
                reason, stop_price_used = exit_info
                exit_price = _fill_price(next_open, cost_bps, "sell")
                if position.risk_usd <= 0 or position.qty <= 0:
                    raise ValueError("Invalid sizing: risk_usd or qty <= 0")
                entry_cost = _trade_cost(position.entry_price, position.qty, cost_bps)
                exit_cost = _trade_cost(exit_price, position.qty, cost_bps)
                total_cost = entry_cost + exit_cost
                pnl = position.qty * (exit_price - position.entry_price) - total_cost
                pnl_pct = pnl / max(position.entry_price * position.qty, 1e-9)
                equity_before = equity
                equity_after = equity_before + pnl
                r_multiple = pnl / max(position.risk_usd, 1e-9)
                mae = position.worst_price - position.entry_price
                mfe = position.best_price - position.entry_price
                risk_per_unit = abs(position.entry_price - position.initial_stop_price)
                mae_r = mae / risk_per_unit if risk_per_unit > 0 else 0.0
                mfe_r = mfe / risk_per_unit if risk_per_unit > 0 else 0.0
                bars_to_stop = None
                if reason == "exit_stop_hit":
                    bars_to_stop = int(row["idx"]) - position.entry_idx
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
                        position.qty,
                        position.risk_usd,
                        position.stop_dist,
                        entry_cost,
                        exit_cost,
                        total_cost,
                        equity_before,
                        equity_after,
                        r_multiple,
                        mae_r,
                        mfe_r,
                        bars_to_stop,
                        stop_price_used,
                        exit_price,
                        risk_per_unit,
                    )
                )
                equity = equity_after
                position = None
                cooldown_until_idx = i + settings.cooldown_bars
                continue

        if position is None and i > cooldown_until_idx:
            if equity <= 0:
                break
            regime = trend_regime(float(row["er20"]))
            if regime != "trend":
                continue

            er = float(row["er20"])
            if (
                settings.er_no_trade_band_low is not None
                and settings.er_no_trade_band_high is not None
                and settings.er_no_trade_band_low <= er < settings.er_no_trade_band_high
            ):
                continue

            if er < settings.entry_er_min:
                continue

            if settings.skip_top_decile_rv:
                rv = float(row["rv48"])
                rv_p90 = float(row.get("rv_p90", np.nan))
                if not np.isnan(rv_p90) and rv >= rv_p90:
                    continue

            # EMA confirmation (optional)
            if settings.require_ema_confirm:
                if float(row["close"]) <= float(row["ema_slow"]):
                    continue
                if float(row["ema_slope"]) <= settings.ema_slope_min:
                    continue

            signal = breakout_signal(
                data,
                i,
                lookback=lookback,
                atr_buffer=settings.breakout_atr_buffer,
                requires_close=settings.breakout_requires_close,
            )

            # Retest logic (optional)
            if settings.enable_retest:
                if signal:
                    pending_level = signal.breakout_level
                    pending_idx = i
                if pending_level is None or pending_idx is None:
                    continue
                if i - pending_idx > settings.retest_max_bars:
                    pending_level = None
                    pending_idx = None
                    continue
                atr = float(row["atr14"])
                band = settings.retest_atr_band * atr
                pulled_back = float(row["low"]) <= (pending_level + band)
                reclaimed = float(row["close"]) >= pending_level
                if not (pulled_back and reclaimed):
                    continue
            else:
                if not signal:
                    continue

            if np.isnan(float(row["atr14"])):
                continue

            stop_dist = 1.2 * float(row["atr14"])
            if stop_dist <= 0:
                continue

            risk_usd = abs(equity * settings.risk_pct)
            if risk_usd <= 0 or risk_usd > equity:
                continue

            qty = risk_usd / stop_dist
            if qty <= 0:
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
            position.qty = qty
            position.risk_usd = risk_usd
            position.stop_dist = stop_dist
            position.worst_price = entry_price
            position.best_price = entry_price
            position.initial_stop_price = entry_price - stop_dist
            pending_level = None
            pending_idx = None

    return trades
