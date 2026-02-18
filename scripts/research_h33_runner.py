import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Deterministic non-live H33 research runner.")
    p.add_argument("--days", type=int, default=180)
    p.add_argument("--timeframe", type=str, default="5m")
    p.add_argument("--horizon", type=int, default=6)
    p.add_argument("--cost-mode", type=str, choices=["gross", "bps8", "bps10"], required=True)
    p.add_argument("--wf", nargs=3, type=int, metavar=("TRAIN_DAYS", "TEST_DAYS", "STEP_DAYS"), default=[60, 15, 15])
    p.add_argument("--bootstrap-iters", type=int, default=3000)
    p.add_argument("--output-json", type=str, required=True)
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


def dedup_idx(mask: pd.Series, gap: int) -> list[int]:
    idx = np.flatnonzero(mask.to_numpy())
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


def build_h33_events(days: int, horizon: int) -> pd.DataFrame:
    # H33 symmetry mirror of H32: same regime gate, opposite trade direction.
    btc_con = sqlite3.connect("data/market.sqlite")
    eth_con = sqlite3.connect("data/market_eth.sqlite")

    btc = pd.read_sql_query("SELECT ts, close FROM candles_5m ORDER BY ts", btc_con)
    eth = pd.read_sql_query("SELECT ts, close FROM candles_5m ORDER BY ts", eth_con)

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
    h1["spread_pct"] = h1["spread"].rolling(2000).apply(
        lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False
    )

    h1["eth_ema20_1h"] = h1["close_eth"].ewm(span=20, adjust=False).mean()
    h1["eth_ema_slope_1h"] = h1["eth_ema20_1h"].diff(3)
    h1["slope_sign"] = np.sign(h1["eth_ema_slope_1h"])
    h1["is_short_tail"] = h1["spread_pct"] < 0.10
    h1["signal_dir"] = np.where(h1["is_short_tail"] & (h1["slope_sign"] != 0), -h1["slope_sign"], 0.0)

    x = pd.merge_asof(
        m.sort_values("dt"),
        h1[["dt", "signal_dir"]].sort_values("dt"),
        on="dt",
        direction="backward",
    )
    x["entry_h33"] = x["signal_dir"] != 0
    x["fwd_r"] = x["close_btc"].shift(-horizon) / x["close_btc"] - 1.0

    idx = dedup_idx(x["entry_h33"], horizon)
    base = x.loc[idx, ["ts", "dt", "signal_dir", "fwd_r"]].dropna().copy()
    base["gross_r"] = base["signal_dir"] * base["fwd_r"]
    return base


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
        raise ValueError("research_h33_runner supports timeframe=5m only for frozen H33.")
    if args.horizon != 6:
        raise ValueError("Frozen H33 runner expects horizon=6.")

    mode = args.cost_mode
    cost = cost_value(mode)
    train_days, test_days, step_days = [int(x) for x in args.wf]

    events = build_h33_events(days=int(args.days), horizon=int(args.horizon))
    returns = (events["gross_r"] - cost).to_numpy(dtype=float)
    n = int(len(returns))
    mean = float(returns.mean()) if n else 0.0
    std = float(returns.std(ddof=0)) if n else 0.0
    win = float((returns > 0).mean()) if n else 0.0
    boot = bootstrap_mean_stats(returns, iters=int(args.bootstrap_iters), seed=int(args.seed))

    wf = walkforward_eval(
        events=events,
        cost=cost,
        train_days=train_days,
        test_days=test_days,
        step_days=step_days,
        bootstrap_iters=int(args.bootstrap_iters),
        seed=int(args.seed),
    )

    payload = {
        "hypothesis_id": "H33",
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
            mode: {
                "n": n,
                "win_rate": win,
                "mean": mean,
                "std": std,
                "mean_ci_low": boot["mean_ci_low"],
                "mean_ci_high": boot["mean_ci_high"],
                "p_mean_gt_0": boot["p_mean_gt_0"],
            }
        },
        "wf": wf,
    }

    out = Path(args.output_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    b = payload["baseline"][mode]
    print(f"H33_RUNNER {mode} n={b['n']} mean={b['mean']:+.6f} ci=[{b['mean_ci_low']},{b['mean_ci_high']}] p={b['p_mean_gt_0']}")
    print(f"H33_WF {mode} n={wf['aggregate']['n']} mean={wf['aggregate']['mean']:+.6f} ci=[{wf['aggregate']['mean_ci_low']},{wf['aggregate']['mean_ci_high']}] p={wf['aggregate']['p_mean_gt_0']}")
    print(f"output_json={out}")


if __name__ == "__main__":
    main()
