from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from app.config import Settings
from app.strategy.trend import breakout_signal, trend_regime
from app.execution.paper import Position, _fill_price, _exit_reason


@dataclass
class ForwardState:
    cooldown_until_ts: int
    position: Optional[Position]


def _state_from_row(row: Optional[Dict]) -> ForwardState:
    if not row:
        return ForwardState(cooldown_until_ts=0, position=None)

    payload = json.loads(row["value"])
    pos = payload.get("position")
    position = None
    if pos:
        position = Position(**pos)
        if position.entry_idx is None:
            position.entry_idx = -1
    return ForwardState(cooldown_until_ts=payload.get("cooldown_until_ts", 0), position=position)


def _state_to_payload(state: ForwardState) -> str:
    data = {
        "cooldown_until_ts": state.cooldown_until_ts,
        "position": asdict(state.position) if state.position else None,
    }
    return json.dumps(data)


def load_state(conn) -> ForwardState:
    row = conn.execute("SELECT value FROM paper_state WHERE key = 'trend_level1'").fetchone()
    return _state_from_row(row)


def save_state(conn, state: ForwardState) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO paper_state (key, value) VALUES ('trend_level1', ?)",
        ( _state_to_payload(state), ),
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

    data = df.copy().sort_values("ts").reset_index(drop=True)
    data["idx"] = data.index
    ts_to_idx = {int(ts): int(idx) for idx, ts in enumerate(data["ts"].tolist())}

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
            exit_info = _exit_reason(
                row=row,
                position=state.position,
                time_stop_candles=10,
                stop_loss_atr_mult=1.2,
                target_atr_mult=2.0,
                breakeven_atr_mult=1.0,
            )
            if exit_info:
                reason, _ = exit_info
                exit_price = _fill_price(next_open, cost_bps, "sell")
                pnl = exit_price - state.position.entry_price
                pnl_pct = pnl / state.position.entry_price
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
                    )
                )
                state.position = None
                state.cooldown_until_ts = next_ts

        if state.position is None:
            if state.cooldown_until_ts and int(row["ts"]) <= state.cooldown_until_ts:
                continue

            regime = trend_regime(float(row["er20"]))
            if regime != "trend":
                continue

            signal = breakout_signal(
                data, i, lookback=20, atr_buffer=settings.breakout_atr_buffer
            )
            if not signal:
                continue

            if np.isnan(float(row["atr14"])):
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

    new_last_processed_ts = int(data.iloc[last_idx]["ts"]) if len(data) > 1 else last_processed_ts
    return trades, state, new_last_processed_ts
