from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from app.config import Settings
from app.strategy.trend import breakout_signal, trend_regime
from app.execution.paper import Position, _fill_price, _exit_reason, _trade_cost


@dataclass
class ForwardState:
    cooldown_until_ts: int
    position: Optional[Position]
    pending_level: Optional[float] = None
    pending_idx: Optional[int] = None


def _state_from_row(row: Optional[Dict]) -> ForwardState:
    if not row:
        return ForwardState(cooldown_until_ts=0, position=None)

    payload = json.loads(row["value"])
    pos = payload.get("position")
    position = None
    if pos:
        defaults = {
            "entry_idx": -1,
            "entry_ts": 0,
            "entry_price": 0.0,
            "entry_regime": "unknown",
            "entry_atr": 0.0,
            "entry_er": 0.0,
            "breakout_level": 0.0,
            "regime_switch_count": 0,
            "qty": 0.0,
            "risk_usd": 0.0,
            "stop_dist": 0.0,
            "worst_price": 0.0,
            "best_price": 0.0,
            "initial_stop_price": 0.0,
        }
        defaults.update(pos)
        position = Position(**defaults)
        if position.entry_idx is None:
            position.entry_idx = -1
        if position.entry_price > 0 and position.worst_price == 0.0:
            position.worst_price = position.entry_price
        if position.entry_price > 0 and position.best_price == 0.0:
            position.best_price = position.entry_price
        if position.initial_stop_price == 0.0 and position.stop_dist > 0:
            position.initial_stop_price = position.entry_price - position.stop_dist
    return ForwardState(
        cooldown_until_ts=payload.get("cooldown_until_ts", 0),
        position=position,
        pending_level=payload.get("pending_level"),
        pending_idx=payload.get("pending_idx"),
    )


def _state_to_payload(state: ForwardState) -> str:
    data = {
        "cooldown_until_ts": state.cooldown_until_ts,
        "position": asdict(state.position) if state.position else None,
        "pending_level": state.pending_level,
        "pending_idx": state.pending_idx,
    }
    return json.dumps(data)


def load_state(conn) -> ForwardState:
    row = conn.execute("SELECT value FROM paper_state WHERE key = 'trend_level1'").fetchone()
    return _state_from_row(row)


def save_state(conn, state: ForwardState) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO paper_state (key, value) VALUES ('trend_level1', ?)",
        (_state_to_payload(state),),
    )
    conn.commit()


def load_last_processed_ts(conn) -> int:
    row = conn.execute(
        "SELECT value FROM bot_state WHERE key = 'trend_level1_last_ts'"
    ).fetchone()
    if not row:
        return 0
    try:
        return int(row["value"])
    except (TypeError, ValueError):
        return 0


def save_last_processed_ts(conn, ts: int) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO bot_state (key, value) VALUES ('trend_level1_last_ts', ?)",
        (str(ts),),
    )
    conn.commit()


def run_trend_level1_forward(
    df: pd.DataFrame, settings: Settings, state: ForwardState, last_processed_ts: int
) -> Tuple[List[Tuple], ForwardState, int]:
    trades: List[Tuple] = []
    equity = settings.initial_equity

    data = df.copy().sort_values("ts").reset_index(drop=True)
    data["idx"] = data.index
    ts_to_idx = {int(ts): int(idx) for idx, ts in enumerate(data["ts"].tolist())}
    data["ema_fast"] = data["close"].ewm(span=settings.ema_fast_period, adjust=False).mean()
    data["ema_slow"] = data["close"].ewm(span=settings.ema_slow_period, adjust=False).mean()
    data["ema_slope"] = data["ema_slow"].diff(settings.ema_slope_bars)
    if settings.skip_top_decile_rv:
        data["rv_p90"] = (
            data["rv48"].shift(1).rolling(settings.rv_quantile_window).quantile(0.9)
        )

    start_idx = 0
    if last_processed_ts and last_processed_ts in ts_to_idx:
        start_idx = ts_to_idx[last_processed_ts] + 1

    cost_bps = settings.half_spread_bps + settings.slippage_bps

    last_idx = len(data) - 2
    for i in range(start_idx, last_idx + 1):
        row = data.iloc[i]
        next_row = data.iloc[i + 1]
        next_open = float(next_row["open"])
        next_ts = int(next_row["ts"])

        # update position entry_idx if we restored from state
        if state.position and state.position.entry_idx == -1:
            if state.position.entry_ts in ts_to_idx:
                state.position.entry_idx = ts_to_idx[state.position.entry_ts]

        if state.position:
            # Track intratrade extremes (long-only)
            state.position.worst_price = min(state.position.worst_price, float(row["low"]))
            state.position.best_price = max(state.position.best_price, float(row["high"]))

            exit_info = _exit_reason(
                row=row,
                position=state.position,
                time_stop_candles=10,
                stop_loss_atr_mult=1.2,
                target_atr_mult=2.0,
                breakeven_atr_mult=1.0,
                freeze_atr_at_entry=settings.freeze_atr_at_entry,
            )
            if exit_info:
                reason, stop_price_used = exit_info
                exit_price = _fill_price(next_open, cost_bps, "sell")
                if state.position.risk_usd <= 0 or state.position.qty <= 0:
                    raise ValueError("Invalid sizing: risk_usd or qty <= 0")
                entry_cost = _trade_cost(state.position.entry_price, state.position.qty, cost_bps)
                exit_cost = _trade_cost(exit_price, state.position.qty, cost_bps)
                total_cost = entry_cost + exit_cost
                pnl = state.position.qty * (exit_price - state.position.entry_price) - total_cost
                pnl_pct = pnl / max(state.position.entry_price * state.position.qty, 1e-9)
                equity_before = equity
                equity_after = equity_before + pnl
                r_multiple = pnl / max(state.position.risk_usd, 1e-9)
                mae = state.position.worst_price - state.position.entry_price
                mfe = state.position.best_price - state.position.entry_price
                risk_per_unit = abs(state.position.entry_price - state.position.initial_stop_price)
                mae_r = mae / risk_per_unit if risk_per_unit > 0 else 0.0
                mfe_r = mfe / risk_per_unit if risk_per_unit > 0 else 0.0
                bars_to_stop = None
                if reason == "exit_stop_hit":
                    bars_to_stop = int(row["idx"]) - state.position.entry_idx
                trades.append(
                    (
                        "trend_level1",
                        state.position.entry_ts,
                        next_ts,
                        state.position.entry_price,
                        exit_price,
                        state.position.breakout_level,
                        state.position.entry_er,
                        state.position.entry_atr,
                        reason,
                        pnl,
                        pnl_pct,
                        state.position.qty,
                        state.position.risk_usd,
                        state.position.stop_dist,
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
                state.position = None
                state.cooldown_until_ts = next_ts

        if state.position is None:
            if equity <= 0:
                break
            if state.cooldown_until_ts and int(row["ts"]) <= state.cooldown_until_ts:
                continue

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
                lookback=20,
                atr_buffer=settings.breakout_atr_buffer,
                requires_close=settings.breakout_requires_close,
            )

            # Retest logic (optional)
            if settings.enable_retest:
                if signal:
                    state.pending_level = signal.breakout_level
                    state.pending_idx = i
                if state.pending_level is None or state.pending_idx is None:
                    continue
                if i - state.pending_idx > settings.retest_max_bars:
                    state.pending_level = None
                    state.pending_idx = None
                    continue
                atr = float(row["atr14"])
                band = settings.retest_atr_band * atr
                pulled_back = float(row["low"]) <= (state.pending_level + band)
                reclaimed = float(row["close"]) >= state.pending_level
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
            state.position = Position(
                entry_idx=i + 1,
                entry_ts=next_ts,
                entry_price=entry_price,
                entry_regime=regime,
                entry_atr=float(row["atr14"]),
                entry_er=signal.er,
                breakout_level=signal.breakout_level,
            )
            state.position.qty = qty
            state.position.risk_usd = risk_usd
            state.position.stop_dist = stop_dist
            state.position.worst_price = entry_price
            state.position.best_price = entry_price
            state.position.initial_stop_price = entry_price - stop_dist
            state.pending_level = None
            state.pending_idx = None

    new_last_processed_ts = int(data.iloc[last_idx]["ts"]) if len(data) > 1 else last_processed_ts
    return trades, state, new_last_processed_ts
