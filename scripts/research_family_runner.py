import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from app.db.market_data import load_btc_eth_merged_last_days
from app.db.derivatives import load_funding_rates_last_days, compute_funding_features


SUPPORTED_FAMILIES = {
    "cross_asset_regime",
    "shock_structure",
    "volatility_conditioning",
    "mean_reversion",
    "range_structure",
    "volatility_state",
    "efficiency_mean_reversion",
    "cross_asset_divergence",
    "funding_regime",
    "momentum",
    "cross_asset",
    "volume_state",
}
HYPOTHESES_PATH = Path("hypotheses.yaml")
EPS = 1e-12

SUPPORTED_IDS_BY_FAMILY: dict[str, set[str]] = {
    "cross_asset_regime": {
        "H19",
        "H29",
        "H30",
        "H37",
        "H38",
        "H39",
        "H40",
        "H41",
        "H59",
        "H60",
        "H61",
        "H62",
        "H63",
        "H64",
        "H65",
        "H66",
        "H67",
        "H68",
        "H69",
        "H70",
        "H71",
        "H72",
        "H73",
        "H74",
        "H75",
        "H76",
        "H77",
        "H78",
        "H79",
        "H80",
        "H81",
        "H82",
        "H83",
        "H84",
        "H85",
        "H86",
        "H87",
        "H88",
        "H89",
        "H90",
        "H91",
        "H92",
        "H93",
        "H94",
        "H95",
        "H96",
        "H97",
        "H98",
        "H99",
        "H100",
        "H124",
        "H135",
        "H136",
        "H137",
        "H139",
    },
    "shock_structure": {"H27", "H42", "H43", "H44", "H45", "H46"},
    "volatility_conditioning": {"H47", "H48", "H49", "H50"},
    "mean_reversion": {"H15", "H18", "H22", "H23", "H26", "H51", "H52", "H53", "H130", "H131"},
    "range_structure": {"H28", "H54", "H55", "H56", "H113"},
    "volatility_state": {"H101", "H102", "H103", "H104", "H112", "H128", "H129", "H133", "H134", "H138"},
    "efficiency_mean_reversion": {"H105", "H106", "H107"},
    "cross_asset_divergence": {"H108", "H109", "H110", "H111"},
    "funding_regime": {"H121", "H122", "H123", "H127", "H132", "H140", "H141", "H142", "H143", "H144"},
    "momentum": {"H125"},
    "cross_asset": {"H126"},
    "volume_state": {"H145", "H146", "H147", "H159", "H160", "H161", "H162", "H163",
                     "H164", "H165", "H166", "H167", "H168",
                     "H169", "H170", "H171", "H172", "H173"},
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generic deterministic research runner for H37-H56 families.")
    p.add_argument("--hypothesis-id", type=str, required=True)
    p.add_argument("--family", type=str, required=True)
    p.add_argument("--days", type=int, default=180)
    p.add_argument("--timeframe", type=str, default="5m")
    p.add_argument("--horizon", type=int, default=6)
    p.add_argument("--cost-mode", type=str, choices=["gross", "bps8", "bps10"], default=None)
    p.add_argument("--all-modes", action="store_true",
                   help="Run gross+bps8+bps10 in one process. Output JSON contains all three modes.")
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


def require_columns(frame: pd.DataFrame, hypothesis_id: str, columns: list[str]) -> None:
    missing = [c for c in columns if c not in frame.columns]
    if missing:
        raise ValueError(f"{hypothesis_id} missing required columns: {missing}")


def parse_utc_hhmm(value: str, hypothesis_id: str, param_name: str) -> tuple[int, int]:
    raw = str(value).strip()
    parts = raw.split(":")
    if len(parts) != 2:
        raise ValueError(f"{hypothesis_id} invalid {param_name}='{value}' (expected HH:MM)")
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError as exc:
        raise ValueError(f"{hypothesis_id} invalid {param_name}='{value}' (expected HH:MM)") from exc
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError(f"{hypothesis_id} invalid {param_name}='{value}' (hour 0-23, minute 0-59)")
    return hour, minute


def load_fixed_params(hypothesis_id: str) -> dict[str, object]:
    if not HYPOTHESES_PATH.exists():
        raise ValueError(f"{hypothesis_id} cannot load params: missing {HYPOTHESES_PATH}")
    payload = yaml.safe_load(HYPOTHESES_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{hypothesis_id} cannot parse {HYPOTHESES_PATH}: root must be mapping")
    rows = payload.get("hypotheses", [])
    if not isinstance(rows, list):
        raise ValueError(f"{hypothesis_id} cannot parse {HYPOTHESES_PATH}: hypotheses must be a list")
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("id", "")).strip() != hypothesis_id:
            continue
        params = row.get("parameters", {})
        if not isinstance(params, dict):
            return {}
        fixed = params.get("fixed", {})
        if isinstance(fixed, dict):
            return dict(fixed)
        return {}
    return {}


def validate_route_and_params(
    hypothesis_id: str,
    family: str,
    horizon: int,
    fixed_params: dict[str, object] | None = None,
) -> dict[str, object]:
    allowed = SUPPORTED_IDS_BY_FAMILY.get(family, set())
    if hypothesis_id not in allowed:
        allowed_list = ", ".join(sorted(allowed)) if allowed else "(none)"
        raise ValueError(
            f"Unsupported hypothesis/family route: {hypothesis_id} ({family}). "
            f"Allowed IDs for family '{family}': {allowed_list}"
        )
    fixed = dict(fixed_params or {})
    if hypothesis_id == "H111":
        try:
            spread_window = int(fixed.get("spread_z_window_bars", 96))
            z_entry = float(fixed.get("z_entry_threshold", 2.0))
            rv_min = float(fixed.get("rv48_pct_min", 0.25))
            rv_max = float(fixed.get("rv48_pct_max", 0.80))
            cooldown_bars = int(fixed.get("cooldown_bars", 2))
            start_hour, start_min = parse_utc_hhmm(str(fixed.get("session_start_utc", "08:00")), hypothesis_id, "session_start_utc")
            end_hour, end_min = parse_utc_hhmm(str(fixed.get("session_end_utc", "22:00")), hypothesis_id, "session_end_utc")
        except Exception as exc:
            raise ValueError(f"{hypothesis_id} invalid parameter set: {exc}") from exc
        if spread_window < 2:
            raise ValueError(f"{hypothesis_id} invalid spread_z_window_bars={spread_window}; expected >= 2")
        if z_entry <= 0:
            raise ValueError(f"{hypothesis_id} invalid z_entry_threshold={z_entry}; expected > 0")
        if not (0.0 <= rv_min < rv_max <= 1.0):
            raise ValueError(
                f"{hypothesis_id} invalid rv48 pct range [{rv_min},{rv_max}); expected 0 <= min < max <= 1"
            )
        if cooldown_bars < 0:
            raise ValueError(f"{hypothesis_id} invalid cooldown_bars={cooldown_bars}; expected >= 0")
        if (start_hour, start_min) == (end_hour, end_min):
            raise ValueError(f"{hypothesis_id} invalid session window: start equals end")
    elif hypothesis_id == "H112":
        try:
            rv_min = float(fixed.get("rv48_pct_min", 0.30))
            rv_max = float(fixed.get("rv48_pct_max", 0.75))
            ratio_min = float(fixed.get("atr_rv_pct_ratio_pct_min", 0.60))
            ratio_max = float(fixed.get("atr_rv_pct_ratio_pct_max", 0.90))
            z_min = float(fixed.get("abs_vwap_dist_z_min", 0.8))
            z_max = float(fixed.get("abs_vwap_dist_z_max", 2.0))
        except Exception as exc:
            raise ValueError(f"{hypothesis_id} invalid parameter set: {exc}") from exc
        if not (0.0 <= rv_min < rv_max <= 1.0):
            raise ValueError(
                f"{hypothesis_id} invalid rv48 pct range [{rv_min},{rv_max}); expected 0 <= min < max <= 1"
            )
        if not (0.0 <= ratio_min < ratio_max <= 1.0):
            raise ValueError(
                f"{hypothesis_id} invalid atr_rv_pct_ratio percentile range [{ratio_min},{ratio_max}); expected 0 <= min < max <= 1"
            )
        if not (0.0 <= z_min < z_max):
            raise ValueError(
                f"{hypothesis_id} invalid abs_vwap_dist_z range [{z_min},{z_max}); expected 0 <= min < max"
            )
    elif hypothesis_id == "H113":
        try:
            lookback = int(fixed.get("breakout_lookback_bars", 24))
            er_min = float(fixed.get("er20_min", 0.45))
            rv_min = float(fixed.get("rv48_pct_min", 0.35))
            rv_max = float(fixed.get("rv48_pct_max", 0.85))
            z_max = float(fixed.get("abs_vwap_dist_z_max", 2.2))
        except Exception as exc:
            raise ValueError(f"{hypothesis_id} invalid parameter set: {exc}") from exc
        if lookback < 2:
            raise ValueError(f"{hypothesis_id} invalid breakout_lookback_bars={lookback}; expected >= 2")
        if not (0.0 <= er_min <= 1.0):
            raise ValueError(f"{hypothesis_id} invalid er20_min={er_min}; expected in [0,1]")
        if not (0.0 <= rv_min < rv_max <= 1.0):
            raise ValueError(
                f"{hypothesis_id} invalid rv48 pct range [{rv_min},{rv_max}); expected 0 <= min < max <= 1"
            )
        if z_max <= 0:
            raise ValueError(f"{hypothesis_id} invalid abs_vwap_dist_z_max={z_max}; expected > 0")
        if int(horizon) <= 0:
            raise ValueError(f"{hypothesis_id} invalid horizon={horizon}; expected > 0")
    return fixed


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
    h1["spread_pct"] = h1["spread"].rolling(2000).rank(pct=True)

    h1["eth_ema20_1h"] = h1["close_eth"].ewm(span=20, adjust=False).mean()
    h1["eth_slope_1h"] = h1["eth_ema20_1h"].diff(3)
    h1["eth_slope_sign_1h"] = np.sign(h1["eth_slope_1h"])
    h1["eth_slope_stable_2_1h"] = h1["eth_slope_sign_1h"].ne(0) & h1["eth_slope_sign_1h"].eq(h1["eth_slope_sign_1h"].shift(1))
    h1["eth_slope_abs_1h"] = h1["eth_slope_1h"].abs()
    w20d_1h = 20 * 24
    h1["eth_slope_abs_q70_1h"] = h1["eth_slope_abs_1h"].rolling(w20d_1h).quantile(0.70)
    h1["eth_slope_abs_pct_1h"] = h1["eth_slope_abs_1h"].rolling(w20d_1h).rank(pct=True)
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
    x["ret1_abs_btc_pct"] = x["ret1_abs_btc"].rolling(w20d).rank(pct=True)
    x["ret1_abs_eth_pct"] = x["ret1_abs_eth"].rolling(w20d).rank(pct=True)
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
    x["prior_high_24"] = x["high_btc"].shift(1).rolling(24).max()
    x["prior_low_24"] = x["low_btc"].shift(1).rolling(24).min()

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

    x["atr14_pct_btc"] = x["atr14_btc"].rolling(w20d).rank(pct=True)
    x["atr14_pct_eth"] = x["atr14_eth"].rolling(w20d).rank(pct=True)
    x["rv48_pct_btc"] = x["rv48_btc"].rolling(w20d).rank(pct=True)
    x["rv48_pct_eth"] = x["rv48_eth"].rolling(w20d).rank(pct=True)

    atr_rv_ratio = x["atr14_btc"] / x["rv48_btc"].replace(0, np.nan)
    x["atr_rv_ratio_pct_btc"] = atr_rv_ratio.rolling(w20d).rank(pct=True)
    atr_rv_pct_ratio = x["atr14_pct_btc"] / x["rv48_pct_btc"].clip(lower=EPS)
    x["atr_rv_pct_ratio"] = atr_rv_pct_ratio
    x["atr_rv_pct_ratio_pct"] = atr_rv_pct_ratio.rolling(w20d).rank(pct=True)
    x["abs_vwap_dist_pct_btc"] = x["dist_to_vwap48_btc"].abs().rolling(w20d).rank(pct=True)

    x["delta_er"] = x["er20_btc"] - x["er20_eth"]
    x["abs_delta_er_pct"] = x["delta_er"].abs().rolling(w20d).rank(pct=True)

    # Backward-compatible aliases used by single-asset family rules.
    x["atr14"] = x["atr14_btc"]
    x["rv48"] = x["rv48_btc"]
    x["er20"] = x["er20_btc"]
    x["vwap48"] = x["vwap48_btc"]
    x["atr14_pct"] = x["atr14_pct_btc"]
    x["rv48_pct"] = x["rv48_pct_btc"]

    # Volume percentile features (30d rolling window)
    x["volume_btc_pct"] = x["volume_btc"].rolling(w20d).rank(pct=True)
    x["volume_eth_pct"] = x["volume_eth"].rolling(w20d).rank(pct=True)

    # Funding rate features (requires Postgres DSN; skipped for legacy SQLite path)
    if dsn:
        try:
            funding = load_funding_rates_last_days(dsn=dsn, days=days)
            if not funding.empty:
                # Normalize both dt columns to microsecond resolution before merge_asof
                x["dt"] = x["dt"].dt.as_unit("us")
                funding["dt"] = funding["dt"].dt.as_unit("us")
                x = pd.merge_asof(
                    x.sort_values("dt"),
                    funding.sort_values("dt"),
                    on="dt",
                    direction="backward",
                )
                x = compute_funding_features(x)
        except Exception:
            pass  # funding data unavailable — non-funding families continue normally
    x["dist_to_vwap48"] = x["dist_to_vwap48_btc"]
    x["dist_to_vwap48_z"] = x["dist_to_vwap48_z_btc"]
    x["abs_vwap_dist_pct"] = x["abs_vwap_dist_pct_btc"]

    # HMM regime labels (requires Postgres DSN; skipped for legacy SQLite path)
    if dsn:
        try:
            import psycopg as _psycopg
            with _psycopg.connect(dsn) as _conn:
                _rl = pd.read_sql(
                    "SELECT ts, regime_name FROM rc.regime_labels WHERE symbol = 'BTC-USD' ORDER BY ts",
                    _conn,
                )
            if not _rl.empty:
                _rl["dt"] = pd.to_datetime(_rl["ts"], utc=True).dt.as_unit("us")
                _rl = _rl[["dt", "regime_name"]].rename(columns={"regime_name": "hmm_regime"})
                x["dt"] = x["dt"].dt.as_unit("us")
                x = pd.merge_asof(
                    x.sort_values("dt"),
                    _rl.sort_values("dt"),
                    on="dt",
                    direction="backward",
                )
        except Exception:
            pass  # regime labels unavailable — non-regime families continue normally

    return x


def build_signal(
    frame: pd.DataFrame,
    hypothesis_id: str,
    family: str,
    fixed_params: dict[str, object] | None = None,
    horizon: int = 0,
) -> pd.Series:
    x = frame
    fixed = dict(fixed_params or {})

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
        if hypothesis_id == "H124":
            # H32 + funding ceiling, ultra-tight spread threshold (0.97/0.03 vs 0.90/0.10)
            # targets ~1-2 trades/day to clear 8bps cost gate
            h124_f_pct = x["funding_btc_pct"]
            funding_ok = h124_f_pct.lt(0.85)
            mask = spread.ge(0.97) & eth_sign.eq(1) & funding_ok
            mask |= spread.le(0.03) & eth_sign.eq(-1) & funding_ok
            return pd.Series(np.where(mask, eth_sign, 0.0), index=x.index)

        if hypothesis_id == "H135":
            # Multi-feature LONG: spread_pct > p70 AND vwap_z < p30 (no regime gate)
            # RF SHAP interaction (full dataset, 7/7 folds), mean_fwd_r=+0.081%
            # "CA trend strong + BTC temporarily oversold" = buy the dip within trend
            _w = 20 * 24 * 12  # 8640 bars ≈ 30d rolling window
            vwap_z_pct = x["vwap_z"].rolling(_w).rank(pct=True)
            mask = spread.ge(0.70) & vwap_z_pct.le(0.30)
            return pd.Series(np.where(mask, 1.0, 0.0), index=x.index)

        if hypothesis_id == "H136":
            # Tighter version of H135: spread_pct > p85 AND vwap_z < p15
            # H135 showed P>0=0.996 gross but only 5.48bps — tighter thresholds
            # aim for higher per-trade magnitude to clear 8bps cost gate
            _w = 20 * 24 * 12  # 8640 bars ≈ 30d rolling window
            vwap_z_pct = x["vwap_z"].rolling(_w).rank(pct=True)
            mask = spread.ge(0.85) & vwap_z_pct.le(0.15)
            return pd.Series(np.where(mask, 1.0, 0.0), index=x.index)

        if hypothesis_id == "H137":
            # RANGING: atr14_pct_btc > p70 AND spread_pct > p70 → LONG
            # High BTC volatility spike + bullish CA signal in RANGING = upward breakout
            # RF SHAP interaction (RANGING-only, 4/6 folds), mean_fwd_r=+0.109%
            ranging = x.get("hmm_regime", pd.Series("", index=x.index)).eq("RANGING")
            mask = x["atr14_pct_btc"].ge(0.70) & spread.ge(0.70) & ranging
            return pd.Series(np.where(mask, 1.0, 0.0), index=x.index)

        if hypothesis_id == "H139":
            # Full-dataset SHORT: rv48_pct_btc > p70 AND spread_pct < p30
            # High BTC vol + BTC underperforming ETH → short. Both are percentile features.
            # RF SHAP interaction (7/7 folds), mean_fwd_r=-0.099%, 71% consistent
            mask = x["rv48_pct_btc"].ge(0.70) & spread.le(0.30)
            return pd.Series(np.where(mask, -1.0, 0.0), index=x.index)

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

        if hypothesis_id == "H130":
            # vwap_z mean-reversion in TRENDING: short above 70th pct, long below 30th pct
            _w = 20 * 24 * 12
            trending = x.get("hmm_regime", pd.Series("", index=x.index)).eq("TRENDING")
            vwap_z_pct = x["vwap_z"].rolling(_w).rank(pct=True)
            sig = pd.Series(0.0, index=x.index)
            sig = sig.where(~(vwap_z_pct.le(0.30) & trending), 1.0)
            sig = sig.where(~(vwap_z_pct.ge(0.70) & trending), -1.0)
            return sig

        if hypothesis_id == "H131":
            # vwap_z momentum in RANGING: long above 70th pct, short below 30th pct
            _w = 20 * 24 * 12
            ranging = x.get("hmm_regime", pd.Series("", index=x.index)).eq("RANGING")
            vwap_z_pct = x["vwap_z"].rolling(_w).rank(pct=True)
            sig = pd.Series(0.0, index=x.index)
            sig = sig.where(~(vwap_z_pct.ge(0.70) & ranging), 1.0)
            sig = sig.where(~(vwap_z_pct.le(0.30) & ranging), -1.0)
            return sig

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
        if hypothesis_id == "H112":
            require_columns(
                x,
                hypothesis_id,
                [
                    "rv48_pct",
                    "atr_rv_pct_ratio_pct",
                    "dist_to_vwap48_z",
                    "dist_to_vwap48",
                ],
            )
            rv_min = float(fixed.get("rv48_pct_min", 0.30))
            rv_max = float(fixed.get("rv48_pct_max", 0.75))
            ratio_min = float(fixed.get("atr_rv_pct_ratio_pct_min", 0.60))
            ratio_max = float(fixed.get("atr_rv_pct_ratio_pct_max", 0.90))
            z_min = float(fixed.get("abs_vwap_dist_z_min", 0.8))
            z_max = float(fixed.get("abs_vwap_dist_z_max", 2.0))

            rv_ok = x["rv48_pct"].ge(rv_min) & x["rv48_pct"].lt(rv_max)
            ratio_ok = x["atr_rv_pct_ratio_pct"].ge(ratio_min) & x["atr_rv_pct_ratio_pct"].lt(ratio_max)
            abs_z = x["dist_to_vwap48_z"].abs()
            dist_ok = abs_z.ge(z_min) & abs_z.lt(z_max)
            sign = pd.Series(np.sign(x["dist_to_vwap48"]), index=x.index)
            mask = rv_ok & ratio_ok & dist_ok & sign.ne(0)
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
        if hypothesis_id == "H111":
            require_columns(x, hypothesis_id, ["dt", "ret1_btc", "ret1_eth", "rv48_pct_btc", "rv48_pct_eth"])
            spread_window = int(fixed.get("spread_z_window_bars", 96))
            z_entry = float(fixed.get("z_entry_threshold", 2.0))
            rv_min = float(fixed.get("rv48_pct_min", 0.25))
            rv_max = float(fixed.get("rv48_pct_max", 0.80))
            cooldown_bars = int(fixed.get("cooldown_bars", 2))
            start_h, start_m = parse_utc_hhmm(str(fixed.get("session_start_utc", "08:00")), hypothesis_id, "session_start_utc")
            end_h, end_m = parse_utc_hhmm(str(fixed.get("session_end_utc", "22:00")), hypothesis_id, "session_end_utc")

            spread = x["ret1_btc"] - x["ret1_eth"]
            spread_mean = spread.rolling(spread_window).mean()
            spread_std = spread.rolling(spread_window).std(ddof=0).replace(0, np.nan)
            spread_z = (spread - spread_mean) / spread_std
            x["spread_z"] = spread_z

            minutes = x["dt"].dt.hour * 60 + x["dt"].dt.minute
            start_minutes = (start_h * 60) + start_m
            end_minutes = (end_h * 60) + end_m
            if start_minutes < end_minutes:
                session_ok = minutes.ge(start_minutes) & minutes.lt(end_minutes)
            else:
                session_ok = minutes.ge(start_minutes) | minutes.lt(end_minutes)
            rv_ok = (
                x["rv48_pct_btc"].ge(rv_min)
                & x["rv48_pct_btc"].lt(rv_max)
                & x["rv48_pct_eth"].ge(rv_min)
                & x["rv48_pct_eth"].lt(rv_max)
            )

            direction = np.where(spread_z.ge(z_entry), -1.0, np.where(spread_z.le(-z_entry), 1.0, 0.0))
            candidate = pd.Series(direction, index=x.index).ne(0) & rv_ok & session_ok
            gap = max(1, int(horizon) + max(0, cooldown_bars))
            idx = dedup_idx(candidate, gap=gap)
            out = np.zeros(len(x), dtype=float)
            if idx:
                out_idx = np.asarray(idx, dtype=int)
                out[out_idx] = np.asarray(direction, dtype=float)[out_idx]
            return pd.Series(out, index=x.index)

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
        if hypothesis_id == "H113":
            require_columns(
                x,
                hypothesis_id,
                [
                    "close_btc",
                    "high_btc",
                    "low_btc",
                    "er20",
                    "rv48_pct",
                    "dist_to_vwap48_z",
                    "prior_high_24",
                    "prior_low_24",
                ],
            )
            lookback = int(fixed.get("breakout_lookback_bars", 24))
            er_min = float(fixed.get("er20_min", 0.45))
            rv_min = float(fixed.get("rv48_pct_min", 0.35))
            rv_max = float(fixed.get("rv48_pct_max", 0.85))
            z_max = float(fixed.get("abs_vwap_dist_z_max", 2.2))

            prior_high = x["high_btc"].shift(1).rolling(lookback).max()
            prior_low = x["low_btc"].shift(1).rolling(lookback).min()
            close = x["close_btc"]
            up_break = close.gt(prior_high)
            dn_break = close.lt(prior_low)
            er_ok = x["er20"].ge(er_min)
            rv_ok = x["rv48_pct"].ge(rv_min) & x["rv48_pct"].lt(rv_max)
            z_ok = x["dist_to_vwap48_z"].abs().lt(z_max)
            mask = er_ok & rv_ok & z_ok
            return pd.Series(np.where(mask & up_break, 1.0, np.where(mask & dn_break, -1.0, 0.0)), index=x.index)

    if family == "funding_regime":
        require_columns(
            x,
            hypothesis_id,
            ["funding_rate_btc", "funding_btc_pct", "funding_btc_sign", "funding_btc_flip"],
        )
        f_pct = x["funding_btc_pct"]
        f_sign = x["funding_btc_sign"]
        f_flip = x["funding_btc_flip"]

        if hypothesis_id == "H121":
            # Funding extreme long fade: short BTC when funding extremely elevated
            # (crowded long = mean reversion pressure) + ETH macro trend up (spread < 0.10)
            extreme_long = f_pct.ge(0.90)
            eth_up = x["spread_pct"].lt(0.10)
            mask = extreme_long & eth_up
            return pd.Series(np.where(mask, -1.0, 0.0), index=x.index)

        if hypothesis_id == "H122":
            # Funding sign flip momentum: trade in direction of BTC funding sign change
            # Funding flipping positive → longs paying → momentum continuation
            # Funding flipping negative → shorts paying → mean reversion / downside
            idx = dedup_idx(f_flip.fillna(False), gap=int(horizon))
            out = np.zeros(len(x), dtype=float)
            if idx:
                out_idx = np.asarray(idx, dtype=int)
                out[out_idx] = f_sign.to_numpy(dtype=float)[out_idx]
            return pd.Series(out, index=x.index)

        if hypothesis_id == "H123":
            # H32 filtered by non-extreme funding: same spread_pct + eth_slope signal
            # but gated out when funding is extreme (overcrowded, mean reversion risk)
            spread = x["spread_pct"]
            eth_sign = x["eth_slope_sign_1h"]
            funding_ok = f_pct.lt(0.85)  # exclude top 15% crowding
            mask = spread.ge(0.90) & eth_sign.eq(1) & funding_ok
            mask |= spread.le(0.10) & eth_sign.eq(-1) & funding_ok
            return pd.Series(np.where(mask, eth_sign, 0.0), index=x.index)

        if hypothesis_id == "H127":
            # High BTC funding percentile in TRENDING regime → long
            trending = x.get("hmm_regime", pd.Series("", index=x.index)).eq("TRENDING")
            mask = f_pct.ge(0.70) & trending
            return pd.Series(np.where(mask, 1.0, 0.0), index=x.index)

        if hypothesis_id == "H132":
            # High BTC funding percentile in VOLATILE regime → long
            volatile = x.get("hmm_regime", pd.Series("", index=x.index)).eq("VOLATILE")
            mask = f_pct.ge(0.70) & volatile
            return pd.Series(np.where(mask, 1.0, 0.0), index=x.index)

        if hypothesis_id == "H140":
            # Extreme negative funding → LONG (over-short market, squeeze potential)
            # Theory: when shorts pay large premium (funding < p10), market is over-short.
            # Enter once when condition FIRST becomes true (edge-triggered, not persistent).
            condition = f_pct.le(0.10)
            onset = condition & (~condition.shift(1).fillna(False))
            idx = dedup_idx(onset, gap=int(horizon))
            out = np.zeros(len(x), dtype=float)
            if idx:
                out[np.asarray(idx, dtype=int)] = 1.0
            return pd.Series(out, index=x.index)

        if hypothesis_id == "H141":
            # Extreme positive funding + ETH slope flip DOWN → SHORT
            # Theory: crowded longs (high funding) + slope turning negative = forced unwind.
            # The CA-1 slope flip is amplified when longs are over-leveraged.
            eth_sign_141 = x["eth_slope_sign_1h"]
            slope_flip_down = eth_sign_141.eq(-1) & eth_sign_141.shift(1).eq(1)
            crowded = f_pct.ge(0.85)
            candidate = slope_flip_down & crowded
            idx = dedup_idx(candidate, gap=int(horizon))
            out = np.zeros(len(x), dtype=float)
            if idx:
                out[np.asarray(idx, dtype=int)] = -1.0
            return pd.Series(out, index=x.index)

        if hypothesis_id == "H142":
            # Cross-asset funding divergence: ETH funding >> BTC funding → SHORT BTC
            # Theory: when ETH perps are more crowded long than BTC, ETH longs are at higher
            # risk of forced liquidation. ETH correction drags BTC down.
            # Fire on onset (first bar condition becomes true), not persistently.
            require_columns(x, hypothesis_id, ["funding_spread_pct"])
            condition = x["funding_spread_pct"].ge(0.80)
            onset = condition & (~condition.shift(1).fillna(False))
            idx = dedup_idx(onset, gap=int(horizon))
            out = np.zeros(len(x), dtype=float)
            if idx:
                out[np.asarray(idx, dtype=int)] = -1.0
            return pd.Series(out, index=x.index)

        if hypothesis_id == "H143":
            # Funding sign + ETH slope sign consensus → trade in that direction
            # Theory: when both the perpetual funding direction AND price momentum agree,
            # the signal has higher conviction. Funding confirms market participants are
            # positioned in the same direction as the slope trend.
            # Fire on onset (first bar both agree), not persistently.
            eth_sign_143 = x["eth_slope_sign_1h"]
            condition = eth_sign_143.eq(f_sign) & eth_sign_143.ne(0) & f_sign.ne(0)
            onset = condition & (~condition.shift(1).fillna(False))
            idx = dedup_idx(onset, gap=int(horizon))
            out = np.zeros(len(x), dtype=float)
            if idx:
                out_idx = np.asarray(idx, dtype=int)
                out[out_idx] = eth_sign_143.to_numpy(dtype=float)[out_idx]
            return pd.Series(out, index=x.index)

        if hypothesis_id == "H144":
            # Sustained extreme funding (3+ hours) + ETH slope flip → amplified SHORT
            # Theory: if funding has been extreme positive for 3+ consecutive hours, the
            # market is deeply crowded — not just a spike. When slope flips down in this
            # context, the forced unwind is more severe and persistent.
            # 3 hours × 12 5m-bars/hour = 36 bars rolling minimum of extreme flag.
            sustained = f_pct.ge(0.85).astype(float).rolling(36).min().eq(1.0)
            eth_sign_144 = x["eth_slope_sign_1h"]
            slope_flip_down = eth_sign_144.eq(-1) & eth_sign_144.shift(1).eq(1)
            candidate = slope_flip_down & sustained
            idx = dedup_idx(candidate, gap=int(horizon))
            out = np.zeros(len(x), dtype=float)
            if idx:
                out[np.asarray(idx, dtype=int)] = -1.0
            return pd.Series(out, index=x.index)

    if family == "volume_state":
        require_columns(x, hypothesis_id, ["volume_btc_pct", "volume_eth_pct"])
        vol_pct = x["volume_btc_pct"]
        eth_sign = x["eth_slope_sign_1h"]

        if hypothesis_id == "H145":
            # Volume spike + ETH slope flip → amplified CA direction
            # Theory: high-volume slope flips have more conviction — large participants
            # are driving the move, not noise. Expect stronger continuation.
            slope_flip = eth_sign.ne(eth_sign.shift(1)) & eth_sign.ne(0)
            high_vol = vol_pct.ge(0.80)
            candidate = slope_flip & high_vol
            idx = dedup_idx(candidate, gap=int(horizon))
            out = np.zeros(len(x), dtype=float)
            if idx:
                out_idx = np.asarray(idx, dtype=int)
                out[out_idx] = eth_sign.to_numpy(dtype=float)[out_idx]
            return pd.Series(out, index=x.index)

        if hypothesis_id == "H146":
            # High volume + price breakout above 12-bar rolling high → LONG
            # Theory: when price breaks to a new short-term high on expanding volume,
            # buyers are absorbing supply; momentum likely continues.
            rolling_high = x["close_btc"].rolling(12).max().shift(1)
            breakout = x["close_btc"].gt(rolling_high)
            high_vol = vol_pct.ge(0.75)
            candidate = breakout & high_vol
            idx = dedup_idx(candidate, gap=int(horizon))
            out = np.zeros(len(x), dtype=float)
            if idx:
                out[np.asarray(idx, dtype=int)] = 1.0
            return pd.Series(out, index=x.index)

        if hypothesis_id == "H147":
            # Low volume + large bar → fade (mean reversion)
            # Theory: a large price move on very low volume lacks genuine participation.
            # The move is likely noise or a thin-book artifact; expect reversion.
            large_move = x["ret1_abs_btc_pct"].ge(0.80)
            low_vol = vol_pct.le(0.20)
            bar_dir = x["bar_dir_btc"]
            candidate = large_move & low_vol & bar_dir.ne(0)
            idx = dedup_idx(candidate, gap=int(horizon))
            out = np.zeros(len(x), dtype=float)
            if idx:
                out_idx = np.asarray(idx, dtype=int)
                out[out_idx] = (-bar_dir).to_numpy(dtype=float)[out_idx]
            return pd.Series(out, index=x.index)

        # VS-1 session-gated expansion (H164-H166): same signal as H145, session filter in build_events
        # H167: VS-2 — longer horizon h=12 (signal identical to H145; horizon arg controls hold)
        # H169-H173: VS-2 robustness checks (same signal as H167; subsample/lag/threshold variants)
        if hypothesis_id in {"H164", "H165", "H166", "H167", "H169", "H170", "H171"}:
            slope_flip = eth_sign.ne(eth_sign.shift(1)) & eth_sign.ne(0)
            high_vol = vol_pct.ge(0.80)
            candidate = slope_flip & high_vol
            idx = dedup_idx(candidate, gap=int(horizon))
            out = np.zeros(len(x), dtype=float)
            if idx:
                out_idx = np.asarray(idx, dtype=int)
                out[out_idx] = eth_sign.to_numpy(dtype=float)[out_idx]
            return pd.Series(out, index=x.index)

        if hypothesis_id == "H172":
            # VS-2 with looser volume threshold: p75 (more trades, test sensitivity)
            slope_flip = eth_sign.ne(eth_sign.shift(1)) & eth_sign.ne(0)
            high_vol = vol_pct.ge(0.75)
            candidate = slope_flip & high_vol
            idx = dedup_idx(candidate, gap=int(horizon))
            out = np.zeros(len(x), dtype=float)
            if idx:
                out_idx = np.asarray(idx, dtype=int)
                out[out_idx] = eth_sign.to_numpy(dtype=float)[out_idx]
            return pd.Series(out, index=x.index)

        if hypothesis_id == "H173":
            # VS-2 with tighter volume threshold: p85
            slope_flip = eth_sign.ne(eth_sign.shift(1)) & eth_sign.ne(0)
            high_vol = vol_pct.ge(0.85)
            candidate = slope_flip & high_vol
            idx = dedup_idx(candidate, gap=int(horizon))
            out = np.zeros(len(x), dtype=float)
            if idx:
                out_idx = np.asarray(idx, dtype=int)
                out[out_idx] = eth_sign.to_numpy(dtype=float)[out_idx]
            return pd.Series(out, index=x.index)

        if hypothesis_id == "H168":
            # VS-1 with ETH volume gate instead of BTC volume
            # Theory: ETH volume expansion during ETH slope flip is a purer self-referential
            # signal — the ETH market itself is validating its own directional flip.
            require_columns(x, hypothesis_id, ["volume_eth_pct"])
            eth_vol_pct = x["volume_eth_pct"]
            slope_flip = eth_sign.ne(eth_sign.shift(1)) & eth_sign.ne(0)
            high_eth_vol = eth_vol_pct.ge(0.80)
            candidate = slope_flip & high_eth_vol
            idx = dedup_idx(candidate, gap=int(horizon))
            out = np.zeros(len(x), dtype=float)
            if idx:
                out_idx = np.asarray(idx, dtype=int)
                out[out_idx] = eth_sign.to_numpy(dtype=float)[out_idx]
            return pd.Series(out, index=x.index)

        # VS-1 robustness checks (H159-H163): same core as H145, vary threshold or subsample
        if hypothesis_id in {"H159", "H160", "H161"}:
            # H159: odd-day subsample of VS-1 (filtered in build_events)
            # H160: even-day subsample of VS-1 (filtered in build_events)
            # H161: VS-1 with 1-bar execution lag (signal is same; build_events shifts entry)
            # All three use identical H145 signal logic — subsample/lag applied downstream.
            slope_flip = eth_sign.ne(eth_sign.shift(1)) & eth_sign.ne(0)
            high_vol = vol_pct.ge(0.80)
            candidate = slope_flip & high_vol
            idx = dedup_idx(candidate, gap=int(horizon))
            out = np.zeros(len(x), dtype=float)
            if idx:
                out_idx = np.asarray(idx, dtype=int)
                out[out_idx] = eth_sign.to_numpy(dtype=float)[out_idx]
            return pd.Series(out, index=x.index)

        if hypothesis_id == "H162":
            # VS-1 with looser volume threshold: p75 (more trades, test sensitivity)
            slope_flip = eth_sign.ne(eth_sign.shift(1)) & eth_sign.ne(0)
            high_vol = vol_pct.ge(0.75)
            candidate = slope_flip & high_vol
            idx = dedup_idx(candidate, gap=int(horizon))
            out = np.zeros(len(x), dtype=float)
            if idx:
                out_idx = np.asarray(idx, dtype=int)
                out[out_idx] = eth_sign.to_numpy(dtype=float)[out_idx]
            return pd.Series(out, index=x.index)

        if hypothesis_id == "H163":
            # VS-1 with tighter volume threshold: p85 (fewer trades, test sensitivity)
            slope_flip = eth_sign.ne(eth_sign.shift(1)) & eth_sign.ne(0)
            high_vol = vol_pct.ge(0.85)
            candidate = slope_flip & high_vol
            idx = dedup_idx(candidate, gap=int(horizon))
            out = np.zeros(len(x), dtype=float)
            if idx:
                out_idx = np.asarray(idx, dtype=int)
                out[out_idx] = eth_sign.to_numpy(dtype=float)[out_idx]
            return pd.Series(out, index=x.index)

    if family == "momentum":
        if hypothesis_id == "H125":
            # vwap_z above 70th pct in TRENDING regime → long
            _w = 20 * 24 * 12
            trending = x.get("hmm_regime", pd.Series("", index=x.index)).eq("TRENDING")
            vwap_z_pct = x["vwap_z"].rolling(_w).rank(pct=True)
            mask = vwap_z_pct.ge(0.70) & trending
            return pd.Series(np.where(mask, 1.0, 0.0), index=x.index)

    if family == "cross_asset":
        if hypothesis_id == "H126":
            # ETH dist_to_vwap48_z above 70th pct in TRENDING regime → long BTC
            _w = 20 * 24 * 12
            trending = x.get("hmm_regime", pd.Series("", index=x.index)).eq("TRENDING")
            dist_pct = x["dist_to_vwap48_z_eth"].rolling(_w).rank(pct=True)
            mask = dist_pct.ge(0.70) & trending
            return pd.Series(np.where(mask, 1.0, 0.0), index=x.index)

    if family == "volatility_state":
        if hypothesis_id == "H128":
            # rv48_pct_btc above 70th pct in TRENDING regime → long
            trending = x.get("hmm_regime", pd.Series("", index=x.index)).eq("TRENDING")
            mask = x["rv48_pct_btc"].ge(0.70) & trending
            return pd.Series(np.where(mask, 1.0, 0.0), index=x.index)

        if hypothesis_id == "H129":
            # atr14_pct_eth above 70th pct in TRENDING regime → long BTC
            trending = x.get("hmm_regime", pd.Series("", index=x.index)).eq("TRENDING")
            mask = x["atr14_pct_eth"].ge(0.70) & trending
            return pd.Series(np.where(mask, 1.0, 0.0), index=x.index)

        if hypothesis_id == "H133":
            # atr14_pct_btc above 70th pct in RANGING regime → long
            ranging = x.get("hmm_regime", pd.Series("", index=x.index)).eq("RANGING")
            mask = x["atr14_pct_btc"].ge(0.70) & ranging
            return pd.Series(np.where(mask, 1.0, 0.0), index=x.index)

        if hypothesis_id == "H134":
            # Multi-feature SHORT in VOLATILE: dist_to_vwap48_z_eth > p70 AND rv48_pct_btc > p70
            # RF SHAP interaction (VOLATILE-only, 5/5 folds), mean_fwd_r=-0.167%
            _w = 20 * 24 * 12  # 8640 bars ≈ 30d rolling window
            volatile = x.get("hmm_regime", pd.Series("", index=x.index)).eq("VOLATILE")
            dist_eth_pct = x["dist_to_vwap48_z_eth"].rolling(_w).rank(pct=True)
            mask = dist_eth_pct.ge(0.70) & x["rv48_pct_btc"].ge(0.70) & volatile
            return pd.Series(np.where(mask, -1.0, 0.0), index=x.index)

        if hypothesis_id == "H138":
            # RANGING: atr14_pct_eth < p30 AND funding_btc_pct < p30 → SHORT
            # Low ETH vol + bearish funding in RANGING = downward resolution
            # RF SHAP interaction (RANGING-only, 3/6 folds, 100% consistent), mean_fwd_r=-0.083%
            ranging = x.get("hmm_regime", pd.Series("", index=x.index)).eq("RANGING")
            mask = x["atr14_pct_eth"].le(0.30) & x["funding_btc_pct"].le(0.30) & ranging
            return pd.Series(np.where(mask, -1.0, 0.0), index=x.index)

    raise ValueError(
        f"Unsupported hypothesis/family route: {hypothesis_id} ({family}). "
        f"Known IDs for family: {sorted(SUPPORTED_IDS_BY_FAMILY.get(family, set()))}"
    )


def build_events(days: int, horizon: int, hypothesis_id: str, family: str, dsn: str = "") -> pd.DataFrame:
    fixed_params = load_fixed_params(hypothesis_id)
    fixed_params = validate_route_and_params(
        hypothesis_id=hypothesis_id,
        family=family,
        horizon=int(horizon),
        fixed_params=fixed_params,
    )
    x = load_frame(days=days, dsn=dsn)
    signal = build_signal(
        x,
        hypothesis_id=hypothesis_id,
        family=family,
        fixed_params=fixed_params,
        horizon=int(horizon),
    )
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
    elif hypothesis_id in {"H161", "H171"}:
        # VS-1/VS-2 with 1-bar execution lag.
        trade_close_col = "close_btc"
        entry_offset = 1
    else:
        trade_close_col = "close_btc"

    if hypothesis_id not in {"H61", "H76", "H77", "H161", "H171"}:
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
    # VS-1 robustness: odd-day (H159), even-day (H160) subsamples.
    if hypothesis_id == "H159":
        base = base[base["dt"].dt.day % 2 == 1].copy()
    if hypothesis_id == "H160":
        base = base[base["dt"].dt.day % 2 == 0].copy()
    # VS-1 session-gated expansion.
    if hypothesis_id == "H165":
        base = base[(base["dt"].dt.hour >= 0) & (base["dt"].dt.hour < 8)].copy()
    if hypothesis_id == "H164":
        base = base[(base["dt"].dt.hour >= 8) & (base["dt"].dt.hour < 16)].copy()
    if hypothesis_id == "H166":
        base = base[(base["dt"].dt.hour >= 16) & (base["dt"].dt.hour < 24)].copy()
    # VS-2 robustness: odd-day (H169), even-day (H170) subsamples.
    if hypothesis_id == "H169":
        base = base[base["dt"].dt.day % 2 == 1].copy()
    if hypothesis_id == "H170":
        base = base[base["dt"].dt.day % 2 == 0].copy()

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


def _main_all_modes(args: argparse.Namespace) -> None:
    train_days, test_days, step_days = [int(v) for v in args.wf]
    events = build_events(
        days=int(args.days),
        horizon=int(args.horizon),
        hypothesis_id=args.hypothesis_id,
        family=args.family,
        dsn=args.dsn.strip(),
    )
    all_results: dict[str, dict] = {}
    for mode in ["gross", "bps8", "bps10"]:
        cost = cost_value(mode)
        baseline_mode, wf, diag = compute_for_cost(
            events=events,
            cost=cost,
            train_days=train_days,
            test_days=test_days,
            step_days=step_days,
            bootstrap_iters=int(args.bootstrap_iters),
            seed=int(args.seed),
        )
        all_results[mode] = {"baseline": baseline_mode, "wf": wf, "diagnostics": diag}

    payload = {
        "hypothesis_id": args.hypothesis_id,
        "family": args.family,
        "timestamp_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "config": {
            "days": int(args.days),
            "timeframe": args.timeframe,
            "horizon": int(args.horizon),
            "cost_mode": "all",
            "wf": {"train_days": train_days, "test_days": test_days, "step_days": step_days},
            "bootstrap_iters": int(args.bootstrap_iters),
        },
        "baseline": {m: all_results[m]["baseline"] for m in all_results},
        "wf_by_mode": {m: all_results[m]["wf"] for m in all_results},
        "diagnostics_by_mode": {m: all_results[m]["diagnostics"] for m in all_results},
    }
    out = Path(args.output_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    for mode in ["gross", "bps8", "bps10"]:
        b = all_results[mode]["baseline"]
        wf_mode = all_results[mode]["wf"]
        print(
            f"{args.hypothesis_id}_RUNNER {mode} n={b['n']} mean={b['mean']:+.6f} "
            f"ci=[{b['mean_ci_low']},{b['mean_ci_high']}] p={b['p_mean_gt_0']}"
        )
        print(
            f"{args.hypothesis_id}_WF {mode} n={wf_mode['aggregate']['n']} "
            f"mean={wf_mode['aggregate']['mean']:+.6f} "
            f"ci=[{wf_mode['aggregate']['mean_ci_low']},{wf_mode['aggregate']['mean_ci_high']}] "
            f"p={wf_mode['aggregate']['p_mean_gt_0']}"
        )
    print(f"output_json={out}")


def main() -> None:
    args = parse_args()
    if args.timeframe != "5m":
        raise ValueError("research_family_runner supports timeframe=5m only.")
    if int(args.horizon) not in {4, 6, 8, 10, 12, 24}:
        raise ValueError("Standard runner expects horizon in {4,6,8,10,12,24}.")
    if args.family not in SUPPORTED_FAMILIES:
        raise ValueError(f"Unsupported family: {args.family}")

    if args.all_modes:
        _main_all_modes(args)
        return

    if args.cost_mode is None:
        raise ValueError("--cost-mode is required when --all-modes is not set.")

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
