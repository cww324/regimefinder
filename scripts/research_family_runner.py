import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from app.db.market_data import load_btc_eth_merged_last_days


SUPPORTED_FAMILIES = {
    "cross_asset_regime",
    "shock_structure",
    "volatility_conditioning",
    "mean_reversion",
    "range_structure",
    "volatility_state",
    "efficiency_mean_reversion",
    "cross_asset_divergence",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generic deterministic research runner for H37-H56 families.")
    p.add_argument("--hypothesis-id", type=str, required=True)
    p.add_argument("--family", type=str, required=True)
    p.add_argument("--days", type=int, default=180)
    p.add_argument("--timeframe", type=str, default="5m")
    p.add_argument("--horizon", type=int, default=6)
    p.add_argument("--cost-mode", type=str, choices=["gross", "bps8", "bps10"], required=True)
    p.add_argument("--wf", nargs=3, type=int, metavar=("TRAIN_DAYS", "TEST_DAYS", "STEP_DAYS"), default=[60, 15, 15])
    p.add_argument("--bootstrap-iters", type=int, default=3000)
    p.add_argument("--output-json", type=str, required=True)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--dsn", type=str, default="", help="Optional Postgres DSN for rc schema data source.")
    return p.parse_args()


def dedup_idx(mask: pd.Series, gap: int) -> list[int]:
    idx = np.flatnonzero(mask.fillna(False).to_numpy())
    out: list[int] = []
    last = -10**9
    for i in idx:
        if i - last >= gap:
            out.append(int(i))
            last = int(i)
    return out


def bootstrap_mean_stats(values: np.ndarray, iters: int, seed: int, ci: float = 0.95) -> dict:
    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n == 0:
        return {"mean_ci_low": 0.0, "mean_ci_high": 0.0, "p_mean_gt_0": 0.0}
    rng = np.random.default_rng(seed)
    samples = rng.choice(x, size=(iters, n), replace=True)
    means = samples.mean(axis=1)
    alpha = (1.0 - ci) / 2.0
    lo = float(np.quantile(means, alpha))
    hi = float(np.quantile(means, 1.0 - alpha))
    p = float((means > 0).mean())
    return {"mean_ci_low": lo, "mean_ci_high": hi, "p_mean_gt_0": p}


def cost_value(mode: str) -> float:
    if mode == "gross":
        return 0.0
    if mode == "bps8":
        return 0.0008
    if mode == "bps10":
        return 0.0010
    raise ValueError(f"unsupported cost mode: {mode}")


def pct_rank_last(window: pd.Series) -> float:
    s = pd.Series(window)
    return float(s.rank(pct=True).iloc[-1])


def require_columns(frame: pd.DataFrame, hypothesis_id: str, columns: list[str]) -> None:
    missing = [c for c in columns if c not in frame.columns]
    if missing:
        raise ValueError(f"{hypothesis_id} missing required columns: {missing}")


def load_frame(days: int, dsn: str = "") -> pd.DataFrame:
    if dsn:
        m = load_btc_eth_merged_last_days(dsn=dsn, days=days).copy()
    else:
        btc_con = sqlite3.connect("data/market.sqlite")
        eth_con = sqlite3.connect("data/market_eth.sqlite")

        btc = pd.read_sql_query("SELECT ts, open, high, low, close, volume FROM candles_5m ORDER BY ts", btc_con)
        eth = pd.read_sql_query("SELECT ts, open, high, low, close, volume FROM candles_5m ORDER BY ts", eth_con)

        cutoff = int(pd.Timestamp.now("UTC").timestamp()) - (days * 86400)
        btc = btc[btc.ts >= cutoff].copy().reset_index(drop=True)
        eth = eth[eth.ts >= cutoff].copy().reset_index(drop=True)

        m = btc.merge(eth, on="ts", how="inner", suffixes=("_btc", "_eth")).sort_values("ts").reset_index(drop=True)

    for col in [
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
    ]:
        if col in m.columns:
            m[col] = pd.to_numeric(m[col], errors="coerce")
    m["dt"] = pd.to_datetime(m["ts"], unit="s", utc=True)

    h1 = (
        m.set_index("dt")[["close_btc", "close_eth"]]
        .resample("1h")
        .last()
        .dropna()
        .reset_index()
    )
    h1["ret_btc_1h_6h"] = h1["close_btc"] / h1["close_btc"].shift(6) - 1.0
    h1["ret_eth_1h_6h"] = h1["close_eth"] / h1["close_eth"].shift(6) - 1.0
    h1["spread"] = h1["ret_eth_1h_6h"] - h1["ret_btc_1h_6h"]
    h1["spread_pct"] = h1["spread"].rolling(2000).apply(pct_rank_last, raw=False)

    h1["eth_ema20_1h"] = h1["close_eth"].ewm(span=20, adjust=False).mean()
    h1["eth_slope_1h"] = h1["eth_ema20_1h"].diff(3)
    h1["eth_slope_sign_1h"] = np.sign(h1["eth_slope_1h"])
    h1["eth_slope_stable_2_1h"] = h1["eth_slope_sign_1h"].ne(0) & h1["eth_slope_sign_1h"].eq(h1["eth_slope_sign_1h"].shift(1))
    h1["eth_slope_abs_1h"] = h1["eth_slope_1h"].abs()
    w20d_1h = 20 * 24
    h1["eth_slope_abs_q70_1h"] = h1["eth_slope_abs_1h"].rolling(w20d_1h).quantile(0.70)
    h1["eth_slope_abs_pct_1h"] = h1["eth_slope_abs_1h"].rolling(w20d_1h).apply(pct_rank_last, raw=False)
    h1["eth_slope_mean_1h"] = h1["eth_slope_1h"].rolling(w20d_1h).mean()
    h1["eth_slope_std_1h"] = h1["eth_slope_1h"].rolling(w20d_1h).std(ddof=0)
    h1["eth_slope_z_1h"] = (h1["eth_slope_1h"] - h1["eth_slope_mean_1h"]) / h1["eth_slope_std_1h"].replace(0, np.nan)
    h1["eth_above_ema20_1h"] = h1["close_eth"] > h1["eth_ema20_1h"]
    h1["btc_ema20_1h"] = h1["close_btc"].ewm(span=20, adjust=False).mean()
    h1["btc_slope_1h"] = h1["btc_ema20_1h"].diff(3)
    h1["btc_slope_sign_1h"] = np.sign(h1["btc_slope_1h"])

    x = pd.merge_asof(
        m.sort_values("dt"),
        h1[
            [
                "dt",
                "spread_pct",
                "eth_slope_sign_1h",
                "eth_slope_stable_2_1h",
                "eth_slope_abs_1h",
                "eth_slope_abs_q70_1h",
                "eth_slope_abs_pct_1h",
                "eth_slope_z_1h",
                "btc_slope_sign_1h",
                "eth_above_ema20_1h",
            ]
        ].sort_values("dt"),
        on="dt",
        direction="backward",
    )

    x["fwd_r"] = x["close_btc"].shift(-6) / x["close_btc"] - 1.0
    x["ret1_btc"] = x["close_btc"].pct_change()
    x["ret1_eth"] = x["close_eth"].pct_change()
    x["ret1_abs_btc"] = x["ret1_btc"].abs()
    x["ret1_abs_eth"] = x["ret1_eth"].abs()
    x["bar_dir_btc"] = np.sign(x["close_btc"] - x["open_btc"])
    x["bar_dir_eth"] = np.sign(x["close_eth"] - x["open_eth"])

    prev_close_btc = x["close_btc"].shift(1)
    prev_close_eth = x["close_eth"].shift(1)
    x["tr_btc"] = np.maximum.reduce(
        [
            (x["high_btc"] - x["low_btc"]).to_numpy(dtype=float),
            (x["high_btc"] - prev_close_btc).abs().to_numpy(dtype=float),
            (x["low_btc"] - prev_close_btc).abs().to_numpy(dtype=float),
        ]
    )
    x["tr_eth"] = np.maximum.reduce(
        [
            (x["high_eth"] - x["low_eth"]).to_numpy(dtype=float),
            (x["high_eth"] - prev_close_eth).abs().to_numpy(dtype=float),
            (x["low_eth"] - prev_close_eth).abs().to_numpy(dtype=float),
        ]
    )

    w20d = 20 * 24 * 12
    x["ret1_abs_btc_q30"] = x["ret1_abs_btc"].rolling(w20d).quantile(0.30)
    x["ret1_abs_btc_q40"] = x["ret1_abs_btc"].rolling(w20d).quantile(0.40)
    x["ret1_abs_btc_q70"] = x["ret1_abs_btc"].rolling(w20d).quantile(0.70)
    x["ret1_abs_btc_q80"] = x["ret1_abs_btc"].rolling(w20d).quantile(0.80)
    x["ret1_abs_btc_q90"] = x["ret1_abs_btc"].rolling(w20d).quantile(0.90)
    x["ret1_abs_eth_q90"] = x["ret1_abs_eth"].rolling(w20d).quantile(0.90)
    x["ret1_abs_btc_pct"] = x["ret1_abs_btc"].rolling(w20d).apply(pct_rank_last, raw=False)
    x["ret1_abs_eth_pct"] = x["ret1_abs_eth"].rolling(w20d).apply(pct_rank_last, raw=False)
    x["tr_btc_q90"] = x["tr_btc"].rolling(w20d).quantile(0.90)
    x["tr_btc_q10"] = x["tr_btc"].rolling(w20d).quantile(0.10)
    x["tr_btc_q25"] = x["tr_btc"].rolling(w20d).quantile(0.25)
    x["tr_eth_q90"] = x["tr_eth"].rolling(w20d).quantile(0.90)

    vwap_num = (x["close_btc"] * x["volume_btc"]).rolling(288).sum()
    vwap_den = x["volume_btc"].rolling(288).sum().replace(0, np.nan)
    x["vwap_btc"] = vwap_num / vwap_den
    dev = x["close_btc"] - x["vwap_btc"]
    dev_std = dev.rolling(288).std(ddof=0)
    x["vwap_z"] = dev / dev_std.replace(0, np.nan)

    prior_high_12 = x["high_btc"].shift(1).rolling(12).max()
    prior_low_12 = x["low_btc"].shift(1).rolling(12).min()
    x["prior_high_12"] = prior_high_12
    x["prior_low_12"] = prior_low_12

    # Deterministic feature set for newer families (H101+), computed locally
    # from merged BTC/ETH OHLCV to avoid changing data-source contracts.
    x["atr14_btc"] = x["tr_btc"].rolling(14).mean()
    x["atr14_eth"] = x["tr_eth"].rolling(14).mean()
    x["rv48_btc"] = x["ret1_btc"].rolling(48).std(ddof=0)
    x["rv48_eth"] = x["ret1_eth"].rolling(48).std(ddof=0)

    x["er20_btc"] = x["close_btc"].diff(20).abs() / x["close_btc"].diff().abs().rolling(20).sum().replace(0, np.nan)
    x["er20_eth"] = x["close_eth"].diff(20).abs() / x["close_eth"].diff().abs().rolling(20).sum().replace(0, np.nan)

    vwap48_num_btc = (x["close_btc"] * x["volume_btc"]).rolling(48).sum()
    vwap48_den_btc = x["volume_btc"].rolling(48).sum().replace(0, np.nan)
    x["vwap48_btc"] = vwap48_num_btc / vwap48_den_btc
    vwap48_num_eth = (x["close_eth"] * x["volume_eth"]).rolling(48).sum()
    vwap48_den_eth = x["volume_eth"].rolling(48).sum().replace(0, np.nan)
    x["vwap48_eth"] = vwap48_num_eth / vwap48_den_eth

    x["dist_to_vwap48_btc"] = x["close_btc"] - x["vwap48_btc"]
    x["dist_to_vwap48_eth"] = x["close_eth"] - x["vwap48_eth"]
    dist_std_btc = x["dist_to_vwap48_btc"].rolling(w20d).std(ddof=0).replace(0, np.nan)
    dist_std_eth = x["dist_to_vwap48_eth"].rolling(w20d).std(ddof=0).replace(0, np.nan)
    x["dist_to_vwap48_z_btc"] = x["dist_to_vwap48_btc"] / dist_std_btc
    x["dist_to_vwap48_z_eth"] = x["dist_to_vwap48_eth"] / dist_std_eth

    x["atr14_pct_btc"] = x["atr14_btc"].rolling(w20d).apply(pct_rank_last, raw=False)
    x["atr14_pct_eth"] = x["atr14_eth"].rolling(w20d).apply(pct_rank_last, raw=False)
    x["rv48_pct_btc"] = x["rv48_btc"].rolling(w20d).apply(pct_rank_last, raw=False)
    x["rv48_pct_eth"] = x["rv48_eth"].rolling(w20d).apply(pct_rank_last, raw=False)

    atr_rv_ratio = x["atr14_btc"] / x["rv48_btc"].replace(0, np.nan)
    x["atr_rv_ratio_pct_btc"] = atr_rv_ratio.rolling(w20d).apply(pct_rank_last, raw=False)
    x["abs_vwap_dist_pct_btc"] = x["dist_to_vwap48_btc"].abs().rolling(w20d).apply(pct_rank_last, raw=False)

    x["delta_er"] = x["er20_btc"] - x["er20_eth"]
    x["abs_delta_er_pct"] = x["delta_er"].abs().rolling(w20d).apply(pct_rank_last, raw=False)

    # Backward-compatible aliases used by single-asset family rules.
    x["atr14"] = x["atr14_btc"]
    x["rv48"] = x["rv48_btc"]
    x["er20"] = x["er20_btc"]
    x["vwap48"] = x["vwap48_btc"]
    x["atr14_pct"] = x["atr14_pct_btc"]
    x["rv48_pct"] = x["rv48_pct_btc"]
    x["dist_to_vwap48"] = x["dist_to_vwap48_btc"]
    x["dist_to_vwap48_z"] = x["dist_to_vwap48_z_btc"]
    x["abs_vwap_dist_pct"] = x["abs_vwap_dist_pct_btc"]

    return x


def build_signal(frame: pd.DataFrame, hypothesis_id: str, family: str) -> pd.Series:
    x = frame

    if family == "cross_asset_regime":
        spread = x["spread_pct"]
        eth_sign = x["eth_slope_sign_1h"]
        btc_sign = x["btc_slope_sign_1h"]

        if hypothesis_id == "H86":
            require_columns(x, hypothesis_id, ["dt", "eth_slope_sign_1h", "eth_slope_stable_2_1h"])
            in_window = x["dt"].dt.hour.ge(12) & x["dt"].dt.hour.lt(20)
            stable = x["eth_slope_stable_2_1h"].fillna(False)
            mask = in_window & stable & eth_sign.ne(0)
            return pd.Series(np.where(mask, eth_sign, 0.0), index=x.index)
        if hypothesis_id == "H87":
            require_columns(x, hypothesis_id, ["spread_pct", "eth_slope_sign_1h"])
            regime = pd.Series(
                np.where(spread.lt(0.10), -1, np.where(spread.ge(0.90), 1, 0)),
                index=x.index,
            )
            transition = regime.ne(regime.shift(1)) & regime.shift(1).notna()
            candidate = transition & eth_sign.ne(0)
            idx = dedup_idx(candidate, gap=12)
            out = np.zeros(len(x), dtype=float)
            if idx:
                out_idx = np.asarray(idx, dtype=int)
                out[out_idx] = eth_sign.to_numpy(dtype=float)[out_idx]
            return pd.Series(out, index=x.index)
        if hypothesis_id == "H88":
            require_columns(x, hypothesis_id, ["ret1_abs_btc", "ret1_abs_btc_q40", "ret1_abs_btc_q80", "eth_slope_sign_1h"])
            vol_mid = x["ret1_abs_btc"].ge(x["ret1_abs_btc_q40"]) & x["ret1_abs_btc"].lt(x["ret1_abs_btc_q80"])
            mask = vol_mid & eth_sign.ne(0)
            return pd.Series(np.where(mask, eth_sign, 0.0), index=x.index)
        if hypothesis_id == "H89":
            require_columns(x, hypothesis_id, ["eth_slope_z_1h"])
            z = x["eth_slope_z_1h"]
            return pd.Series(np.where(z.ge(1.0), 1.0, np.where(z.le(-1.0), -1.0, 0.0)), index=x.index)
        if hypothesis_id == "H90":
            require_columns(
                x,
                hypothesis_id,
                [
                    "btc_slope_sign_1h",
                    "eth_slope_sign_1h",
                    "eth_slope_abs_1h",
                    "eth_slope_abs_q70_1h",
                    "ret1_abs_btc",
                    "ret1_abs_btc_q30",
                    "ret1_abs_btc_q70",
                ],
            )
            agree = btc_sign.eq(eth_sign) & eth_sign.ne(0)
            eth_abs_gate = x["eth_slope_abs_1h"].ge(x["eth_slope_abs_q70_1h"])
            vol_mid = x["ret1_abs_btc"].ge(x["ret1_abs_btc_q30"]) & x["ret1_abs_btc"].lt(x["ret1_abs_btc_q70"])
            candidate = agree & eth_abs_gate & vol_mid
            idx = dedup_idx(candidate, gap=18)
            out = np.zeros(len(x), dtype=float)
            if idx:
                out_idx = np.asarray(idx, dtype=int)
                out[out_idx] = eth_sign.to_numpy(dtype=float)[out_idx]
            return pd.Series(out, index=x.index)
        if hypothesis_id == "H91":
            require_columns(x, hypothesis_id, ["spread_pct", "eth_slope_sign_1h"])
            regime = pd.Series(
                np.where(spread.lt(0.10), -1, np.where(spread.ge(0.90), 1, 0)),
                index=x.index,
            )
            transition = regime.ne(regime.shift(1)) & regime.shift(1).notna()
            candidate = transition & eth_sign.ne(0)
            idx = dedup_idx(candidate, gap=10)
            out = np.zeros(len(x), dtype=float)
            if idx:
                out_idx = np.asarray(idx, dtype=int)
                out[out_idx] = eth_sign.to_numpy(dtype=float)[out_idx]
            return pd.Series(out, index=x.index)
        if hypothesis_id == "H92":
            require_columns(x, hypothesis_id, ["eth_slope_sign_1h", "eth_slope_abs_pct_1h"])
            abs_gate = x["eth_slope_abs_pct_1h"].ge(0.50)
            long_confirm = eth_sign.eq(1) & eth_sign.shift(1).eq(1) & eth_sign.shift(2).eq(1)
            short_confirm = eth_sign.eq(-1)
            return pd.Series(
                np.where(abs_gate & long_confirm, 1.0, np.where(abs_gate & short_confirm, -1.0, 0.0)),
                index=x.index,
            )
        if hypothesis_id == "H93":
            require_columns(x, hypothesis_id, ["ret1_abs_btc_pct", "ret1_abs_eth_pct", "eth_slope_sign_1h"])
            vol_gate = x["ret1_abs_btc_pct"].ge(0.25) & x["ret1_abs_btc_pct"].lt(0.75)
            shock = x["ret1_abs_eth_pct"].ge(0.95)
            post_shock_blackout = shock.shift(1).rolling(6, min_periods=1).max().fillna(0).gt(0)
            eligible = vol_gate & (~shock) & (~post_shock_blackout) & eth_sign.ne(0)
            return pd.Series(np.where(eligible, eth_sign, 0.0), index=x.index)
        if hypothesis_id == "H94":
            require_columns(x, hypothesis_id, ["dt", "btc_slope_sign_1h", "eth_slope_sign_1h"])
            hour = x["dt"].dt.hour
            weekday = x["dt"].dt.dayofweek.le(4)
            in_window = (hour.ge(7) & hour.lt(11)) | (hour.ge(13) & hour.lt(17))
            agree = btc_sign.eq(eth_sign) & eth_sign.ne(0)
            mask = weekday & in_window & agree
            return pd.Series(np.where(mask, eth_sign, 0.0), index=x.index)
        if hypothesis_id == "H95":
            require_columns(x, hypothesis_id, ["eth_slope_z_1h", "eth_slope_sign_1h"])
            abs_z = x["eth_slope_z_1h"].abs()
            high = abs_z.ge(1.25) & eth_sign.ne(0)
            medium = abs_z.ge(0.90) & abs_z.lt(1.25) & eth_sign.ne(0)
            cand = high | medium
            cand_idx = np.flatnonzero(cand.fillna(False).to_numpy())
            sig_arr = eth_sign.to_numpy(dtype=float)
            high_arr = high.fillna(False).to_numpy()
            med_arr = medium.fillna(False).to_numpy()
            out = np.zeros(len(x), dtype=float)
            last_entry = -10**9
            for i in cand_idx:
                i = int(i)
                if i - last_entry < 6:
                    continue
                if high_arr[i] or (med_arr[i] and i - last_entry >= 24):
                    out[i] = sig_arr[i]
                    last_entry = i
            return pd.Series(out, index=x.index)
        if hypothesis_id == "H96":
            require_columns(x, hypothesis_id, ["spread_pct", "eth_slope_sign_1h"])
            regime = pd.Series(
                np.where(spread.lt(0.10), -1, np.where(spread.ge(0.90), 1, 0)),
                index=x.index,
            )
            prev = regime.shift(1)
            transition = regime.ne(prev) & prev.notna()
            enters_tail = transition & prev.eq(0) & regime.ne(0)
            exits_tail_to_neutral = transition & prev.ne(0) & regime.eq(0)
            candidate = (enters_tail | exits_tail_to_neutral) & eth_sign.ne(0)
            direction = np.where(enters_tail, -eth_sign, np.where(exits_tail_to_neutral, eth_sign, 0.0))
            idx = dedup_idx(candidate, gap=14)
            out = np.zeros(len(x), dtype=float)
            if idx:
                out_idx = np.asarray(idx, dtype=int)
                out[out_idx] = np.asarray(direction, dtype=float)[out_idx]
            return pd.Series(out, index=x.index)
        if hypothesis_id == "H97":
            require_columns(x, hypothesis_id, ["spread_pct", "eth_slope_sign_1h", "eth_slope_abs_pct_1h"])
            abs_gate = x["eth_slope_abs_pct_1h"].ge(0.60)
            long_ok = spread.ge(0.10) & eth_sign.gt(0) & abs_gate
            short_ok = spread.lt(0.10) & eth_sign.lt(0) & abs_gate
            raw = np.where(long_ok, 1.0, np.where(short_ok, -1.0, 0.0))
            candidate = pd.Series(raw, index=x.index).ne(0)
            idx = dedup_idx(candidate, gap=8)
            out = np.zeros(len(x), dtype=float)
            if idx:
                out_idx = np.asarray(idx, dtype=int)
                out[out_idx] = np.asarray(raw, dtype=float)[out_idx]
            return pd.Series(out, index=x.index)
        if hypothesis_id == "H98":
            require_columns(x, hypothesis_id, ["ret1_abs_btc_pct", "eth_slope_sign_1h"])
            vol_pct = x["ret1_abs_btc_pct"]
            shock = vol_pct.ge(0.90)
            shock_exit = shock.shift(1).fillna(False) & (~shock)
            delay = shock_exit.rolling(4, min_periods=1).max().fillna(0).gt(0)
            eligible_vol = vol_pct.ge(0.20) & vol_pct.lt(0.90)
            mask = eligible_vol & (~delay) & eth_sign.ne(0)
            return pd.Series(np.where(mask, eth_sign, 0.0), index=x.index)
        if hypothesis_id == "H99":
            require_columns(x, hypothesis_id, ["dt", "btc_slope_sign_1h", "eth_slope_sign_1h"])
            hour = x["dt"].dt.hour
            in_window = (hour.ge(6) & hour.lt(8)) | (hour.ge(12) & hour.lt(14))
            flip = eth_sign.ne(eth_sign.shift(1)) & eth_sign.ne(0)
            recent_flip = flip.shift(1).rolling(3, min_periods=1).max().fillna(0).gt(0)
            agree = btc_sign.eq(eth_sign) & eth_sign.ne(0)
            mask = in_window & recent_flip & agree
            return pd.Series(np.where(mask, eth_sign, 0.0), index=x.index)
        if hypothesis_id == "H100":
            require_columns(x, hypothesis_id, ["dt", "btc_slope_sign_1h", "eth_slope_sign_1h", "eth_slope_abs_pct_1h", "ret1_abs_btc_pct"])
            agree = btc_sign.eq(eth_sign) & eth_sign.ne(0)
            abs_gate = x["eth_slope_abs_pct_1h"].ge(0.75)
            vol_gate = x["ret1_abs_btc_pct"].ge(0.30) & x["ret1_abs_btc_pct"].lt(0.85)
            candidate = agree & abs_gate & vol_gate
            day = x["dt"].dt.floor("D")
            score = x["eth_slope_abs_pct_1h"].where(candidate)
            rank = score.groupby(day).rank(method="first", ascending=False)
            keep = candidate & rank.le(2)
            return pd.Series(np.where(keep, eth_sign, 0.0), index=x.index)

        if hypothesis_id == "H19":
            # Frozen regime tails: long on short-tail, short on long-tail.
            return pd.Series(np.where(spread.lt(0.10), 1.0, np.where(spread.ge(0.90), -1.0, 0.0)), index=x.index)
        if hypothesis_id == "H29":
            neutral = spread.ge(0.10) & spread.lt(0.90)
            entered_neutral = neutral & (~neutral.shift(1).fillna(False))
            return pd.Series(np.where(entered_neutral, 1.0, 0.0), index=x.index)
        if hypothesis_id == "H30":
            mask = eth_sign.ne(btc_sign) & eth_sign.ne(0) & btc_sign.ne(0)
            return pd.Series(np.where(mask, eth_sign, 0.0), index=x.index)
        if hypothesis_id == "H37":
            mask = spread.ge(0.10) & spread.lt(0.90) & eth_sign.ne(0)
            return pd.Series(np.where(mask, eth_sign, 0.0), index=x.index)
        if hypothesis_id == "H38":
            mask = spread.ge(0.90) & eth_sign.ne(0)
            return pd.Series(np.where(mask, eth_sign, 0.0), index=x.index)
        if hypothesis_id == "H39":
            flip = eth_sign.ne(eth_sign.shift(1)) & eth_sign.ne(0)
            return pd.Series(np.where(flip, eth_sign, 0.0), index=x.index)
        if hypothesis_id == "H40":
            mask = btc_sign.eq(eth_sign) & btc_sign.ne(0)
            return pd.Series(np.where(mask, btc_sign, 0.0), index=x.index)
        if hypothesis_id == "H41":
            mask = btc_sign.ne(eth_sign) & btc_sign.ne(0) & eth_sign.ne(0)
            return pd.Series(np.where(mask, -btc_sign, 0.0), index=x.index)
        if hypothesis_id in {"H59", "H62", "H63", "H66", "H68", "H69", "H72", "H74", "H76", "H78", "H80", "H81", "H82"}:
            flip = btc_sign.ne(btc_sign.shift(1)) & btc_sign.ne(0)
            return pd.Series(np.where(flip, btc_sign, 0.0), index=x.index)
        if hypothesis_id in {"H60", "H64", "H65", "H67", "H70", "H71", "H73", "H75", "H77", "H79", "H83", "H84", "H85"}:
            flip = eth_sign.ne(eth_sign.shift(1)) & eth_sign.ne(0)
            return pd.Series(np.where(flip, eth_sign, 0.0), index=x.index)
        if hypothesis_id == "H61":
            flip = eth_sign.ne(eth_sign.shift(1)) & eth_sign.ne(0)
            return pd.Series(np.where(flip, eth_sign, 0.0), index=x.index)

    if family == "shock_structure":
        if hypothesis_id == "H27":
            tr = x["high_btc"] - x["low_btc"]
            tr_med20 = tr.rolling(20).median()
            vol_med20 = x["volume_btc"].rolling(20).median()
            mask = tr.gt(1.8 * tr_med20) & x["volume_btc"].gt(1.8 * vol_med20)
            return pd.Series(np.where(mask, np.sign(x["close_btc"] - x["open_btc"]), 0.0), index=x.index)

        btc_shock = x["ret1_btc"].abs().ge(x["ret1_abs_btc_q90"])
        eth_shock = x["ret1_eth"].abs().ge(x["ret1_abs_eth_q90"])
        btc_dir = np.sign(x["ret1_btc"])
        eth_dir = np.sign(x["ret1_eth"])

        if hypothesis_id == "H42":
            return pd.Series(np.where(btc_shock, btc_dir, 0.0), index=x.index)
        if hypothesis_id == "H43":
            return pd.Series(np.where(btc_shock, -btc_dir, 0.0), index=x.index)
        if hypothesis_id == "H44":
            return pd.Series(np.where(eth_shock, eth_dir, 0.0), index=x.index)
        if hypothesis_id == "H45":
            mask = eth_shock & (~btc_shock)
            return pd.Series(np.where(mask, eth_dir, 0.0), index=x.index)
        if hypothesis_id == "H46":
            mask = eth_shock & btc_shock & eth_dir.eq(btc_dir) & eth_dir.ne(0)
            return pd.Series(np.where(mask, eth_dir, 0.0), index=x.index)

    if family == "volatility_conditioning":
        if hypothesis_id == "H47":
            mask = x["tr_btc"].ge(x["tr_btc_q90"])
            return pd.Series(np.where(mask, x["bar_dir_btc"], 0.0), index=x.index)
        if hypothesis_id == "H48":
            low_vol = x["tr_btc"].le(x["tr_btc_q10"])
            mask = low_vol.shift(1).fillna(False)
            return pd.Series(np.where(mask, x["bar_dir_btc"], 0.0), index=x.index)
        if hypothesis_id == "H49":
            compressed = x["tr_btc"].le(x["tr_btc_q25"])
            prev5_compressed = compressed.shift(1).rolling(5).sum().eq(5)
            expansion = x["tr_btc"].gt(x["tr_btc_q25"])
            mask = prev5_compressed & expansion
            return pd.Series(np.where(mask, x["bar_dir_btc"], 0.0), index=x.index)
        if hypothesis_id == "H50":
            mask = x["tr_eth"].ge(x["tr_eth_q90"])
            return pd.Series(np.where(mask, x["bar_dir_eth"], 0.0), index=x.index)

    if family == "mean_reversion":
        neutral = x["spread_pct"].ge(0.10) & x["spread_pct"].lt(0.90)
        h15_base = x["vwap_z"].le(-2.0) & x["eth_above_ema20_1h"].fillna(False) & x["eth_slope_sign_1h"].gt(0)
        h17_gate = x["ret1_eth"].abs().ge(x["ret1_abs_eth_q90"])

        if hypothesis_id == "H15":
            return pd.Series(np.where(h15_base, 1.0, 0.0), index=x.index)
        if hypothesis_id == "H18":
            mask = h15_base & h17_gate
            return pd.Series(np.where(mask, 1.0, 0.0), index=x.index)
        if hypothesis_id == "H22":
            mask = h15_base & h17_gate & neutral
            return pd.Series(np.where(mask, 1.0, 0.0), index=x.index)
        if hypothesis_id == "H23":
            mask = h15_base & neutral
            return pd.Series(np.where(mask, 1.0, 0.0), index=x.index)
        if hypothesis_id == "H26":
            mid = x["spread_pct"].ge(0.25) & x["spread_pct"].lt(0.75)
            mask = h15_base & mid
            return pd.Series(np.where(mask, 1.0, 0.0), index=x.index)

        if hypothesis_id == "H51":
            mask = x["vwap_z"].le(-2.0) & neutral
            return pd.Series(np.where(mask, 1.0, 0.0), index=x.index)
        if hypothesis_id == "H52":
            mask = x["vwap_z"].ge(2.0) & neutral
            return pd.Series(np.where(mask, -1.0, 0.0), index=x.index)
        if hypothesis_id == "H53":
            mask = x["vwap_z"].abs().ge(3.0)
            return pd.Series(np.where(mask, -np.sign(x["vwap_z"]), 0.0), index=x.index)

    if family == "volatility_state":
        if hypothesis_id == "H101":
            require_columns(x, hypothesis_id, ["atr14_pct", "rv48_pct", "dist_to_vwap48"])
            vol_ok = x["atr14_pct"].ge(0.65) & x["atr14_pct"].lt(0.90)
            rv_ok = x["rv48_pct"].ge(0.40) & x["rv48_pct"].lt(0.80)
            sign = pd.Series(np.sign(x["dist_to_vwap48"]), index=x.index)
            mask = vol_ok & rv_ok & sign.ne(0)
            return pd.Series(np.where(mask, sign, 0.0), index=x.index)
        if hypothesis_id == "H102":
            require_columns(x, hypothesis_id, ["atr14_pct", "rv48_pct", "dist_to_vwap48", "dist_to_vwap48_z"])
            compressed = x["atr14_pct"].lt(0.30) & x["rv48_pct"].lt(0.35)
            abs_z = x["dist_to_vwap48_z"].abs()
            breakout = abs_z.gt(1.2) & abs_z.shift(1).le(1.2)
            sign = pd.Series(np.sign(x["dist_to_vwap48"]), index=x.index)
            mask = compressed & breakout & sign.ne(0)
            return pd.Series(np.where(mask, sign, 0.0), index=x.index)
        if hypothesis_id == "H103":
            require_columns(x, hypothesis_id, ["rv48_pct", "atr14", "dist_to_vwap48"])
            rv_shock = x["rv48_pct"].ge(0.90)
            atr_decline = x["atr14"].diff().lt(0)
            decline_3 = atr_decline & atr_decline.shift(1).fillna(False) & atr_decline.shift(2).fillna(False)
            sign = pd.Series(np.sign(x["dist_to_vwap48"]), index=x.index)
            stable_2 = sign.eq(sign.shift(1)) & sign.ne(0)
            mask = rv_shock & decline_3 & stable_2
            return pd.Series(np.where(mask, -sign, 0.0), index=x.index)
        if hypothesis_id == "H104":
            require_columns(x, hypothesis_id, ["atr_rv_ratio_pct_btc", "abs_vwap_dist_pct", "dist_to_vwap48"])
            ratio_ok = x["atr_rv_ratio_pct_btc"].ge(0.45) & x["atr_rv_ratio_pct_btc"].lt(0.70)
            dist_ok = x["abs_vwap_dist_pct"].ge(0.50) & x["abs_vwap_dist_pct"].lt(0.85)
            sign = pd.Series(np.sign(x["dist_to_vwap48"]), index=x.index)
            mask = ratio_ok & dist_ok & sign.ne(0)
            return pd.Series(np.where(mask, sign, 0.0), index=x.index)

    if family == "efficiency_mean_reversion":
        if hypothesis_id == "H105":
            require_columns(x, hypothesis_id, ["er20", "dist_to_vwap48", "dist_to_vwap48_z", "rv48_pct"])
            low_eff = x["er20"].le(0.25)
            dist_ok = x["dist_to_vwap48_z"].abs().ge(1.5)
            rv_ok = x["rv48_pct"].lt(0.85)
            sign = pd.Series(np.sign(x["dist_to_vwap48"]), index=x.index)
            mask = low_eff & dist_ok & rv_ok & sign.ne(0)
            return pd.Series(np.where(mask, -sign, 0.0), index=x.index)
        if hypothesis_id == "H106":
            require_columns(x, hypothesis_id, ["er20", "dist_to_vwap48", "dist_to_vwap48_z", "atr14_pct"])
            high_eff = x["er20"].ge(0.60)
            abs_z = x["dist_to_vwap48_z"].abs()
            dist_ok = abs_z.ge(0.6) & abs_z.lt(1.8)
            atr_ok = x["atr14_pct"].ge(0.35) & x["atr14_pct"].lt(0.85)
            sign = pd.Series(np.sign(x["dist_to_vwap48"]), index=x.index)
            mask = high_eff & dist_ok & atr_ok & sign.ne(0)
            return pd.Series(np.where(mask, sign, 0.0), index=x.index)
        if hypothesis_id == "H107":
            require_columns(x, hypothesis_id, ["er20", "dist_to_vwap48", "dist_to_vwap48_z", "rv48_pct"])
            abs_z_ok = x["dist_to_vwap48_z"].abs().ge(0.9)
            rv_ok = x["rv48_pct"].lt(0.92)
            sign = pd.Series(np.sign(x["dist_to_vwap48"]), index=x.index)
            low_eff = x["er20"].lt(0.40)
            direction = np.where(low_eff, -sign, sign)
            mask = abs_z_ok & rv_ok & sign.ne(0)
            return pd.Series(np.where(mask, direction, 0.0), index=x.index)

    if family == "cross_asset_divergence":
        if hypothesis_id == "H108":
            require_columns(x, hypothesis_id, ["delta_er", "abs_delta_er_pct", "dist_to_vwap48_z_btc", "rv48_pct_btc"])
            div_ok = x["abs_delta_er_pct"].ge(0.85)
            btc_dist_ok = x["dist_to_vwap48_z_btc"].abs().ge(0.7)
            btc_rv_ok = x["rv48_pct_btc"].lt(0.90)
            delta_sign = pd.Series(np.sign(x["delta_er"]), index=x.index)
            direction = np.where(delta_sign.gt(0), -1.0, np.where(delta_sign.lt(0), 1.0, 0.0))
            mask = div_ok & btc_dist_ok & btc_rv_ok & delta_sign.ne(0)
            return pd.Series(np.where(mask, direction, 0.0), index=x.index)
        if hypothesis_id == "H109":
            require_columns(x, hypothesis_id, ["atr14_pct_eth", "atr14_pct_btc", "rv48_pct_btc", "dist_to_vwap48_eth"])
            atr_state = x["atr14_pct_eth"].ge(0.70) & x["atr14_pct_btc"].lt(0.50)
            btc_rv_ok = x["rv48_pct_btc"].ge(0.30) & x["rv48_pct_btc"].lt(0.85)
            eth_sign = pd.Series(np.sign(x["dist_to_vwap48_eth"]), index=x.index)
            mask = atr_state & btc_rv_ok & eth_sign.ne(0)
            return pd.Series(np.where(mask, eth_sign, 0.0), index=x.index)
        if hypothesis_id == "H110":
            require_columns(x, hypothesis_id, ["dist_to_vwap48_btc", "dist_to_vwap48_eth", "dist_to_vwap48_z_btc", "dist_to_vwap48_z_eth", "er20_btc", "er20_eth"])
            btc_sign = pd.Series(np.sign(x["dist_to_vwap48_btc"]), index=x.index)
            eth_sign = pd.Series(np.sign(x["dist_to_vwap48_eth"]), index=x.index)
            opposite = btc_sign.ne(0) & eth_sign.ne(0) & btc_sign.ne(eth_sign)
            dist_ok = x["dist_to_vwap48_z_btc"].abs().ge(1.0) & x["dist_to_vwap48_z_eth"].abs().ge(1.0)
            er_ok = x["er20_btc"].le(0.50) & x["er20_eth"].le(0.50)
            mask = opposite & dist_ok & er_ok
            return pd.Series(np.where(mask, -btc_sign, 0.0), index=x.index)

    if family == "range_structure":
        if hypothesis_id == "H28":
            close = x["close_btc"]
            prior_high = x["high_btc"].shift(1).rolling(12).max()
            prior_low = x["low_btc"].shift(1).rolling(12).min()
            up_break = close.gt(prior_high)
            dn_break = close.lt(prior_low)
            failed_high = (
                (up_break.shift(1).fillna(False) & close.le(prior_high.shift(1)))
                | (up_break.shift(2).fillna(False) & close.le(prior_high.shift(2)))
            )
            failed_low = (
                (dn_break.shift(1).fillna(False) & close.ge(prior_low.shift(1)))
                | (dn_break.shift(2).fillna(False) & close.ge(prior_low.shift(2)))
            )
            return pd.Series(np.where(failed_high, -1.0, np.where(failed_low, 1.0, 0.0)), index=x.index)

        close = x["close_btc"]
        high_brk = close.gt(x["prior_high_12"])
        low_brk = close.lt(x["prior_low_12"])

        if hypothesis_id == "H54":
            return pd.Series(np.where(high_brk, 1.0, np.where(low_brk, -1.0, 0.0)), index=x.index)
        if hypothesis_id == "H55":
            failed_high = high_brk.shift(1).fillna(False) & close.le(x["prior_high_12"].shift(1))
            failed_low = low_brk.shift(1).fillna(False) & close.ge(x["prior_low_12"].shift(1))
            return pd.Series(np.where(failed_high, -1.0, np.where(failed_low, 1.0, 0.0)), index=x.index)
        if hypothesis_id == "H56":
            d = x["bar_dir_btc"]
            up3 = d.eq(1) & d.shift(1).eq(1) & d.shift(2).eq(1)
            dn3 = d.eq(-1) & d.shift(1).eq(-1) & d.shift(2).eq(-1)
            return pd.Series(np.where(up3, 1.0, np.where(dn3, -1.0, 0.0)), index=x.index)

    raise ValueError(f"Unsupported hypothesis/family route: {hypothesis_id} ({family})")


def build_events(days: int, horizon: int, hypothesis_id: str, family: str, dsn: str = "") -> pd.DataFrame:
    x = load_frame(days=days, dsn=dsn)
    signal = build_signal(x, hypothesis_id=hypothesis_id, family=family)
    x["signal_dir"] = signal
    x["entry"] = x["signal_dir"].ne(0)
    entry_offset = 0

    # Default: trade BTC with signal-bar close reference.
    if hypothesis_id in {"H60", "H64", "H65", "H67", "H70", "H71", "H73", "H75", "H77", "H79", "H83", "H84", "H85"}:
        # ETH self-trade control: signal and traded asset are both ETH.
        trade_close_col = "close_eth"
    elif hypothesis_id in {"H61", "H76", "H77"}:
        trade_close_col = "close_btc"
        # Execution realism: signal at t, enter on close[t+1], hold horizon bars from entry.
        # Trades without t+1 or t+1+horizon are dropped downstream via dropna.
        entry_offset = 1
    else:
        trade_close_col = "close_btc"

    if hypothesis_id not in {"H61", "H76", "H77"}:
        entry_offset = 0

    effective_horizon = pd.Series(int(horizon), index=x.index, dtype=int)
    if hypothesis_id == "H91":
        spread = x["spread_pct"]
        regime = pd.Series(
            np.where(spread.lt(0.10), -1, np.where(spread.ge(0.90), 1, 0)),
            index=x.index,
        )
        prev = regime.shift(1)
        is_tail_to_neutral = prev.ne(0) & regime.eq(0)
        effective_horizon = pd.Series(np.where(is_tail_to_neutral, 4, int(horizon)), index=x.index, dtype=int)

    close_s = x[trade_close_col]
    x["entry_px"] = close_s.shift(-entry_offset)
    x["exit_px"] = np.nan
    for h in sorted({int(v) for v in effective_horizon.dropna().unique().tolist()}):
        mask_h = effective_horizon.eq(h)
        x.loc[mask_h, "exit_px"] = close_s.shift(-(entry_offset + int(h))).loc[mask_h]
    x["fwd_r"] = x["exit_px"] / x["entry_px"] - 1.0

    idx = dedup_idx(x["entry"], horizon)
    base = x.loc[idx, ["ts", "dt", "signal_dir", "fwd_r", "entry_px"]].dropna().copy()
    base["gross_r"] = base["signal_dir"] * base["fwd_r"]

    # Odd/even day split replication variants for H63/H65.
    if hypothesis_id in {"H68", "H70"}:
        base = base[base["dt"].dt.day % 2 == 1].copy()
    if hypothesis_id in {"H69", "H71"}:
        base = base[base["dt"].dt.day % 2 == 0].copy()
    if hypothesis_id in {"H80", "H83"}:
        base = base[(base["dt"].dt.hour >= 0) & (base["dt"].dt.hour < 8)].copy()
    if hypothesis_id in {"H81", "H84"}:
        base = base[(base["dt"].dt.hour >= 8) & (base["dt"].dt.hour < 16)].copy()
    if hypothesis_id in {"H82", "H85"}:
        base = base[(base["dt"].dt.hour >= 16) & (base["dt"].dt.hour < 24)].copy()

    # MAE proxy using close-path from entry to horizon.
    close_arr = close_s.to_numpy(dtype=float)
    sig_arr = x["signal_dir"].to_numpy(dtype=float)
    mae_vals: list[float] = []
    for i in idx:
        i = int(i)
        direction = sig_arr[i]
        if direction == 0:
            continue
        ent_i = i + entry_offset
        ex_i = ent_i + int(effective_horizon.iloc[i])
        if ent_i < 0 or ex_i >= len(close_arr):
            continue
        ep = close_arr[ent_i]
        if not np.isfinite(ep) or ep == 0:
            continue
        path = (close_arr[ent_i + 1 : ex_i + 1] / ep - 1.0) * direction
        if path.size == 0:
            continue
        finite_path = path[np.isfinite(path)]
        if finite_path.size == 0:
            continue
        mae_vals.append(float(np.min(finite_path)))

    if len(mae_vals) == len(base):
        base["mae_proxy"] = mae_vals
    else:
        base["mae_proxy"] = np.nan
    return base


def diagnostics_from_events(events: pd.DataFrame, cost: float) -> dict:
    if events.empty:
        return {
            "trades_per_day": 0.0,
            "median_hold_return": None,
            "top10_pct_pnl_contribution": None,
            "mae_proxy_median": None,
            "return_histogram_bins": [],
            "return_histogram_counts": [],
        }

    net = (events["gross_r"].to_numpy(dtype=float) - cost)
    dt_min = events["dt"].min()
    dt_max = events["dt"].max()
    days_span = max(1.0, float((dt_max - dt_min).total_seconds() / 86400.0))
    trades_per_day = float(len(events) / days_span)
    median_hold_return = float(np.median(net))
    total_pnl = float(np.sum(net))
    top_n = max(1, int(np.ceil(0.10 * len(net))))
    top_sum = float(np.sum(np.sort(net)[-top_n:]))
    top_contrib = None if abs(total_pnl) < 1e-12 else float(top_sum / total_pnl)
    mae_med = None
    if "mae_proxy" in events.columns:
        mae = events["mae_proxy"].to_numpy(dtype=float)
        mae = mae[np.isfinite(mae)]
        mae_med = float(np.median(mae)) if len(mae) else None

    bins = [-np.inf, -0.01, -0.005, -0.002, 0.0, 0.002, 0.005, 0.01, np.inf]
    counts, _ = np.histogram(net, bins=bins)
    labels = ["(-inf,-1%)", "[-1%,-0.5%)", "[-0.5%,-0.2%)", "[-0.2%,0%)", "[0%,0.2%)", "[0.2%,0.5%)", "[0.5%,1%)", "[1%,inf)"]

    return {
        "trades_per_day": trades_per_day,
        "median_hold_return": median_hold_return,
        "top10_pct_pnl_contribution": top_contrib,
        "mae_proxy_median": mae_med,
        "return_histogram_bins": labels,
        "return_histogram_counts": [int(x) for x in counts.tolist()],
    }


def compute_for_cost(
    events: pd.DataFrame,
    cost: float,
    train_days: int,
    test_days: int,
    step_days: int,
    bootstrap_iters: int,
    seed: int,
) -> tuple[dict, dict, dict]:
    returns = (events["gross_r"].to_numpy(dtype=float) - cost)
    n = int(len(returns))
    mean = float(returns.mean()) if n else 0.0
    std = float(returns.std(ddof=0)) if n else 0.0
    win = float((returns > 0).mean()) if n else 0.0
    boot = bootstrap_mean_stats(returns, iters=int(bootstrap_iters), seed=int(seed))
    wf = walkforward_eval(
        events=events,
        cost=cost,
        train_days=train_days,
        test_days=test_days,
        step_days=step_days,
        bootstrap_iters=int(bootstrap_iters),
        seed=int(seed),
    )
    diag = diagnostics_from_events(events, cost=cost)
    baseline = {
        "n": n,
        "win_rate": win,
        "mean": mean,
        "std": std,
        "mean_ci_low": boot["mean_ci_low"],
        "mean_ci_high": boot["mean_ci_high"],
        "p_mean_gt_0": boot["p_mean_gt_0"],
    }
    return baseline, wf, diag


def walkforward_eval(
    events: pd.DataFrame,
    cost: float,
    train_days: int,
    test_days: int,
    step_days: int,
    bootstrap_iters: int,
    seed: int,
) -> dict:
    if events.empty:
        return {
            "split": {"train_days": train_days, "test_days": test_days, "step_days": step_days},
            "folds": [],
            "aggregate": {"n": 0, "mean": 0.0, "mean_ci_low": None, "mean_ci_high": None, "p_mean_gt_0": None},
            "positive_folds": {"count": 0, "total": 0, "pct": 0.0},
        }

    e = events.sort_values("dt").reset_index(drop=True).copy()
    min_dt = e["dt"].min().floor("D")
    max_dt = e["dt"].max()

    train_td = pd.Timedelta(days=train_days)
    test_td = pd.Timedelta(days=test_days)
    step_td = pd.Timedelta(days=step_days)

    cursor = min_dt + train_td
    folds: list[dict] = []
    agg_returns: list[float] = []
    fold_id = 1
    while cursor + test_td <= max_dt:
        te_s = cursor
        te_e = cursor + test_td
        part = e[(e["dt"] >= te_s) & (e["dt"] < te_e)].copy()
        r = (part["gross_r"] - cost).to_numpy(dtype=float)
        n = int(len(r))
        mean = float(r.mean()) if n else 0.0
        folds.append(
            {
                "fold_id": fold_id,
                "test_start": te_s.isoformat(),
                "test_end": te_e.isoformat(),
                "n": n,
                "mean": mean,
            }
        )
        if n:
            agg_returns.extend(r.tolist())
        cursor = cursor + step_td
        fold_id += 1

    agg = np.asarray(agg_returns, dtype=float)
    n_agg = int(len(agg))
    mean_agg = float(agg.mean()) if n_agg else 0.0
    boot = bootstrap_mean_stats(agg, iters=bootstrap_iters, seed=seed + 17)

    pos = sum(1 for f in folds if f["mean"] > 0)
    total = len(folds)
    return {
        "split": {"train_days": train_days, "test_days": test_days, "step_days": step_days},
        "folds": folds,
        "aggregate": {
            "n": n_agg,
            "mean": mean_agg,
            "mean_ci_low": boot["mean_ci_low"],
            "mean_ci_high": boot["mean_ci_high"],
            "p_mean_gt_0": boot["p_mean_gt_0"],
        },
        "positive_folds": {"count": pos, "total": total, "pct": (100.0 * pos / total) if total else 0.0},
    }


def main() -> None:
    args = parse_args()
    if args.timeframe != "5m":
        raise ValueError("research_family_runner supports timeframe=5m only.")
    if int(args.horizon) not in {4, 6, 8, 10}:
        raise ValueError("Standard runner expects horizon in {4,6,8,10}.")
    if args.family not in SUPPORTED_FAMILIES:
        raise ValueError(f"Unsupported family: {args.family}")

    mode = args.cost_mode
    cost = cost_value(mode)
    train_days, test_days, step_days = [int(x) for x in args.wf]

    events = build_events(
        days=int(args.days),
        horizon=int(args.horizon),
        hypothesis_id=args.hypothesis_id,
        family=args.family,
        dsn=args.dsn.strip(),
    )

    baseline_mode, wf, diagnostics = compute_for_cost(
        events=events,
        cost=cost,
        train_days=train_days,
        test_days=test_days,
        step_days=step_days,
        bootstrap_iters=int(args.bootstrap_iters),
        seed=int(args.seed),
    )

    stress = {}
    if args.hypothesis_id in {"H78", "H79"}:
        for name, c in [("bps12", 0.0012), ("bps15", 0.0015)]:
            b_s, wf_s, d_s = compute_for_cost(
                events=events,
                cost=c,
                train_days=train_days,
                test_days=test_days,
                step_days=step_days,
                bootstrap_iters=int(args.bootstrap_iters),
                seed=int(args.seed),
            )
            stress[name] = {"cost": c, "baseline": b_s, "wf": wf_s, "diagnostics": d_s}

    payload = {
        "hypothesis_id": args.hypothesis_id,
        "family": args.family,
        "timestamp_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "config": {
            "days": int(args.days),
            "timeframe": args.timeframe,
            "horizon": int(args.horizon),
            "cost_mode": mode,
            "cost": cost,
            "wf": {"train_days": train_days, "test_days": test_days, "step_days": step_days},
            "bootstrap_iters": int(args.bootstrap_iters),
        },
        "baseline": {
            mode: baseline_mode
        },
        "wf": wf,
        "diagnostics": diagnostics,
    }
    if stress:
        payload["stress"] = stress

    out = Path(args.output_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    b = payload["baseline"][mode]
    print(
        f"{args.hypothesis_id}_RUNNER {mode} n={b['n']} mean={b['mean']:+.6f} "
        f"ci=[{b['mean_ci_low']},{b['mean_ci_high']}] p={b['p_mean_gt_0']}"
    )
    print(
        f"{args.hypothesis_id}_WF {mode} n={wf['aggregate']['n']} mean={wf['aggregate']['mean']:+.6f} "
        f"ci=[{wf['aggregate']['mean_ci_low']},{wf['aggregate']['mean_ci_high']}] p={wf['aggregate']['p_mean_gt_0']}"
    )
    print(f"output_json={out}")


if __name__ == "__main__":
    main()
