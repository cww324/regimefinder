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
        return {"mean_ci_low": None, "mean_ci_high": None, "p_mean_gt_0": None}
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
    h1["btc_ema20_1h"] = h1["close_btc"].ewm(span=20, adjust=False).mean()
    h1["btc_slope_1h"] = h1["btc_ema20_1h"].diff(3)
    h1["btc_slope_sign_1h"] = np.sign(h1["btc_slope_1h"])

    x = pd.merge_asof(
        m.sort_values("dt"),
        h1[["dt", "spread_pct", "eth_slope_sign_1h", "btc_slope_sign_1h"]].sort_values("dt"),
        on="dt",
        direction="backward",
    )

    x["fwd_r"] = x["close_btc"].shift(-6) / x["close_btc"] - 1.0
    x["ret1_btc"] = x["close_btc"].pct_change()
    x["ret1_eth"] = x["close_eth"].pct_change()
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
    x["ret1_abs_btc_q90"] = x["ret1_btc"].abs().rolling(w20d).quantile(0.90)
    x["ret1_abs_eth_q90"] = x["ret1_eth"].abs().rolling(w20d).quantile(0.90)
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

    return x


def build_signal(frame: pd.DataFrame, hypothesis_id: str, family: str) -> pd.Series:
    x = frame

    if family == "cross_asset_regime":
        spread = x["spread_pct"]
        eth_sign = x["eth_slope_sign_1h"]
        btc_sign = x["btc_slope_sign_1h"]

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
        if hypothesis_id == "H51":
            mask = x["vwap_z"].le(-2.0) & neutral
            return pd.Series(np.where(mask, 1.0, 0.0), index=x.index)
        if hypothesis_id == "H52":
            mask = x["vwap_z"].ge(2.0) & neutral
            return pd.Series(np.where(mask, -1.0, 0.0), index=x.index)
        if hypothesis_id == "H53":
            mask = x["vwap_z"].abs().ge(3.0)
            return pd.Series(np.where(mask, -np.sign(x["vwap_z"]), 0.0), index=x.index)

    if family == "range_structure":
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

    close_s = x[trade_close_col]
    x["entry_px"] = close_s.shift(-entry_offset)
    x["exit_px"] = close_s.shift(-(entry_offset + horizon))
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
        ex_i = ent_i + horizon
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
    if int(args.horizon) not in {4, 6, 8}:
        raise ValueError("Standard runner expects horizon in {4,6,8}.")
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
