import argparse

import numpy as np
import pandas as pd

from scripts.experts.h2s_vol_expert import build_trades, load_data, parse_horizons


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap uncertainty stats for H2S-VOL walkforward OOS returns.")
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--window", type=int, default=2000)
    parser.add_argument("--variant", choices=["A", "B"], default="B")
    parser.add_argument("--horizons", default="20")
    parser.add_argument("--train-days", type=int, required=True)
    parser.add_argument("--test-days", type=int, required=True)
    parser.add_argument("--step-days", type=int, default=0)
    parser.add_argument("--rv-pct-min", type=float, default=0.70)
    parser.add_argument("--rv-pct-max", type=float, default=0.90)
    parser.add_argument("--shock-atr-min", type=float, default=1.5)
    parser.add_argument("--shock-atr-max", type=float, default=2.5)
    parser.add_argument("--fee_bps", type=float, default=2.0)
    parser.add_argument("--slippage_bps", type=float, default=2.0)
    parser.add_argument("--bootstrap-iters", type=int, default=3000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--label", default="")
    return parser.parse_args()


def collect_oos_trades(
    df: pd.DataFrame,
    window: int,
    variant: str,
    horizons: list[int],
    rv_pct_min: float,
    rv_pct_max: float,
    shock_atr_min: float,
    shock_atr_max: float,
    train_days: int,
    test_days: int,
    step_days: int,
    fee_bps: float,
    slippage_bps: float,
) -> pd.DataFrame:
    if step_days <= 0:
        step_days = test_days

    min_ts = int(df["ts"].min())
    end_ts = int(df["ts"].max()) + 1
    all_oos = []

    t = min_ts
    fold_id = 1
    while t + ((train_days + test_days) * 86400) <= end_ts:
        train_end = t + (train_days * 86400)
        test_start = train_end
        test_end = test_start + (test_days * 86400)

        fold_df = df[(df["ts"] >= t) & (df["ts"] < test_end)].copy()
        fold_trades = build_trades(
            fold_df,
            window,
            variant,
            horizons,
            rv_pct_min,
            rv_pct_max,
            shock_atr_min,
            shock_atr_max,
            fee_bps,
            slippage_bps,
        )
        if not fold_trades.empty:
            fold_trades = fold_trades[
                (fold_trades["signal_ts"] >= test_start)
                & (fold_trades["signal_ts"] < test_end)
                & (fold_trades["exit_ts"] < test_end)
            ].copy()
            fold_trades["fold_id"] = fold_id
            all_oos.append(fold_trades)

        fold_id += 1
        t += step_days * 86400

    if not all_oos:
        return pd.DataFrame(columns=["h", "ret", "fold_id"])
    return pd.concat(all_oos, ignore_index=True)


def bootstrap_ci(values: np.ndarray, iters: int, seed: int) -> tuple[float, float, float]:
    n = len(values)
    if n == 0:
        return 0.0, 0.0, 0.0
    rng = np.random.default_rng(seed)
    samples = rng.choice(values, size=(iters, n), replace=True)
    means = samples.mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 50)), float(np.percentile(means, 97.5))


def main() -> None:
    args = parse_args()
    horizons = parse_horizons(args.horizons)
    step_days = args.step_days if args.step_days > 0 else args.test_days

    df = load_data(args.days)
    oos = collect_oos_trades(
        df,
        args.window,
        args.variant,
        horizons,
        args.rv_pct_min,
        args.rv_pct_max,
        args.shock_atr_min,
        args.shock_atr_max,
        args.train_days,
        args.test_days,
        step_days,
        args.fee_bps,
        args.slippage_bps,
    )

    print("=== H2S-VOL Uncertainty (bootstrap OOS) ===")
    if args.label:
        print(f"Label: {args.label}")
    print(
        "Config: "
        f"train/test/step={args.train_days}/{args.test_days}/{step_days}, "
        f"rv=[{args.rv_pct_min:.2f},{args.rv_pct_max:.2f}), "
        f"shock=[{args.shock_atr_min:.2f},{args.shock_atr_max:.2f}), "
        f"fee/slip={args.fee_bps}/{args.slippage_bps} bps per side"
    )
    print()

    rows = []
    for h in horizons:
        subset = oos[oos["h"] == h].copy()
        rets = subset["ret"].to_numpy(dtype=float)
        n = len(rets)
        if n == 0:
            rows.append(
                {
                    "h": h,
                    "trades": 0,
                    "mean_return": 0.0,
                    "mean_ci_low": 0.0,
                    "mean_ci_high": 0.0,
                    "sharpe_like": 0.0,
                    "p_mean_gt_0": 0.0,
                }
            )
            continue

        mean_ret = float(rets.mean())
        std_ret = float(rets.std(ddof=0))
        sharpe_like = 0.0 if std_ret == 0 else mean_ret / std_ret

        low, _, high = bootstrap_ci(rets, args.bootstrap_iters, args.seed + int(h))

        rng = np.random.default_rng(args.seed + 10_000 + int(h))
        samples = rng.choice(rets, size=(args.bootstrap_iters, n), replace=True)
        sample_means = samples.mean(axis=1)
        p_mean_gt_0 = float((sample_means > 0).mean())

        rows.append(
            {
                "h": int(h),
                "trades": int(n),
                "mean_return": mean_ret,
                "mean_ci_low": low,
                "mean_ci_high": high,
                "sharpe_like": sharpe_like,
                "p_mean_gt_0": p_mean_gt_0,
            }
        )

    out = pd.DataFrame(rows)
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
