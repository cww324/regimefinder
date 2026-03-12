"""
XGBoost Feature Engineering — Theory-First Features for ML Discovery
=====================================================================
Computes new theory-first features that are NOT proxies for existing
confirmed signals (CA/VS/LQ families). These capture mechanisms we
haven't yet tested:

  oi_expanding_3h     OI contracts increased each of last 3 consecutive 1h periods
  rv_compressed_4h    BTC RV below p20 for 4+ consecutive hours (vol coiling)
  funding_pos_hours   Consecutive hours BTC funding has been positive (crowded long)
  funding_neg_hours   Consecutive hours BTC funding has been negative (crowded short)
  liq_cluster_2h      Liquidations occurred in 2+ of last 3 hours (cascade still active)
  hour_sin            sin(2π × hour / 24) — cyclical UTC hour encoding
  hour_cos            cos(2π × hour / 24) — cyclical UTC hour encoding

Round 4 features (added 2026-03-12):
  funding_accel       2nd derivative of funding rate (acceleration, not just change)
  oi_vol_ratio        OI growth percentile / volume percentile (silent leverage buildup)

Also preserves all existing load_frame() features for comparison.

Output: results/ml/features_365d.parquet

Usage:
    PYTHONPATH=. .venv/bin/python scripts/ml/xgboost_feature_engineering.py \\
        --dsn "$RC_DB_DSN" \\
        --days 365 \\
        --output results/ml/features_365d.parquet
"""

import argparse
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from scripts.research_family_runner import load_frame


def compute_theory_first_features(x: pd.DataFrame) -> pd.DataFrame:
    """
    Compute new theory-first features on the 5m frame.
    All features are based on economic logic chosen BEFORE any ML runs.
    """
    x = x.copy()

    # ── Cyclical time encoding ─────────────────────────────────────────────────
    hour = x["dt"].dt.hour + x["dt"].dt.minute / 60.0
    x["hour_sin"] = np.sin(2 * np.pi * hour / 24.0)
    x["hour_cos"] = np.cos(2 * np.pi * hour / 24.0)

    # ── Vol compression: RV below p20 for 4+ consecutive hours (48 5m bars) ───
    # Economic logic: compressed vol = coiling spring. The next directional
    # move after compression tends to be stronger than average.
    if "rv48_pct_btc" in x.columns:
        compressed = x["rv48_pct_btc"].lt(0.20).astype(float)
        x["rv_compressed_4h"] = (
            compressed.rolling(48).min().fillna(0).gt(0).astype(int)
        )
    else:
        x["rv_compressed_4h"] = 0
        print("  [warn] rv48_pct_btc not found — rv_compressed_4h set to 0")

    # ── OI expansion trend: OI increased each of last 3 consecutive hours ─────
    # Economic logic: actively growing OI = leverage accumulating right now.
    # When it stops/reverses, those new positions unwind simultaneously.
    # At 5m resolution: 1h = 12 bars.
    if "oi_contracts_btc" in x.columns:
        oi = x["oi_contracts_btc"]
        x["oi_expanding_3h"] = (
            oi.gt(oi.shift(12)) &          # higher than 1h ago
            oi.shift(12).gt(oi.shift(24)) &  # 1h ago higher than 2h ago
            oi.shift(24).gt(oi.shift(36))    # 2h ago higher than 3h ago
        ).astype(int)
    else:
        x["oi_expanding_3h"] = 0
        print("  [warn] oi_contracts_btc not found — oi_expanding_3h set to 0")

    # ── Funding persistence: consecutive hours positive/negative ──────────────
    # Economic logic: funding positive 6h+ = structurally crowded long.
    # Not testing instantaneous extremes (already done H121-H144) — testing
    # the DURATION of crowding as an independent positioning signal.
    if "funding_rate_btc" in x.columns:
        f = x["funding_rate_btc"].fillna(0)
        pos = (f > 0).astype(float).values
        neg = (f < 0).astype(float).values

        # Compute run-length: consecutive 1s ending at each position
        def consecutive_run(arr: np.ndarray) -> np.ndarray:
            out = np.zeros(len(arr), dtype=float)
            count = 0.0
            for i in range(len(arr)):
                if arr[i]:
                    count += 1.0
                else:
                    count = 0.0
                out[i] = count
            return out

        # Convert from 5m bars to approximate hours (funding updates every 1h = 12 bars)
        x["funding_pos_hours"] = consecutive_run(pos) / 12.0
        x["funding_neg_hours"] = consecutive_run(neg) / 12.0
    else:
        x["funding_pos_hours"] = 0.0
        x["funding_neg_hours"] = 0.0
        print("  [warn] funding_rate_btc not found — funding_pos/neg_hours set to 0")

    # ── Liquidation clustering: liq in 2+ of last 3 hours ────────────────────
    # Economic logic: cascades don't end in 1 hour. If liq was active in
    # 2 of the last 3 hours, the deleveraging pressure is ongoing.
    # At 5m resolution: check liq activity at 0h, 1h (12 bars), 2h (24 bars) ago.
    if "total_liq_btc_pct" in x.columns:
        liq = x["total_liq_btc_pct"]
        active_now = liq.gt(0).astype(int)
        active_1h = liq.shift(12).gt(0).astype(int)
        active_2h = liq.shift(24).gt(0).astype(int)
        x["liq_cluster_2h"] = (
            (active_now + active_1h + active_2h).ge(2).astype(int)
        )
    else:
        x["liq_cluster_2h"] = 0
        print("  [warn] total_liq_btc_pct not found — liq_cluster_2h set to 0")

    # ── Funding rate momentum: change in funding over last hour ───────────────
    # Economic logic: accelerating funding (getting more positive/negative) is
    # different from stable funding. A spike in funding rate may precede a
    # reversal as the crowded side gets squeezed. Tests CHANGE, not level.
    if "funding_rate_btc" in x.columns:
        f = x["funding_rate_btc"].fillna(0)
        # 1h change: current funding vs 12 bars ago (1h = 12 5m bars)
        x["funding_chg_1h"] = f - f.shift(12)
    else:
        x["funding_chg_1h"] = 0.0
        print("  [warn] funding_rate_btc not found — funding_chg_1h set to 0")

    # ── BTC/ETH relative performance divergence (1h) ──────────────────────────
    # Economic logic: when BTC and ETH diverge (one up, other flat/down), it may
    # signal a rotation or a regime shift. Cross-asset alignment is already in CA
    # family, but this measures MAGNITUDE of divergence as a continuous variable.
    if "close_btc" in x.columns and "close_eth" in x.columns:
        ret_1h_btc = x["close_btc"].pct_change(12).fillna(0)
        ret_1h_eth = x["close_eth"].pct_change(12).fillna(0)
        x["btc_eth_div_1h"] = ret_1h_btc - ret_1h_eth
    else:
        x["btc_eth_div_1h"] = 0.0
        print("  [warn] close_btc/eth not found — btc_eth_div_1h set to 0")

    # ── OI velocity: rate of change of OI (not just trending up) ─────────────
    # Economic logic: OI accelerating (growing faster than before) is a different
    # signal than OI simply being higher. Rapid OI growth = leverage accumulating
    # faster than usual = higher risk of sudden unwind.
    if "oi_contracts_btc" in x.columns:
        oi = x["oi_contracts_btc"]
        oi_chg_1h = oi - oi.shift(12)           # 1h change
        oi_chg_2h = oi.shift(12) - oi.shift(24) # previous 1h change
        x["oi_velocity"] = oi_chg_1h - oi_chg_2h  # acceleration
    else:
        x["oi_velocity"] = 0.0
        print("  [warn] oi_contracts_btc not found — oi_velocity set to 0")

    # ── Liquidation imbalance: directional pressure ───────────────────────────
    # Economic logic: when long liq >> short liq, forced sellers dominate
    # (bearish pressure). When short liq >> long liq, forced buyers dominate
    # (bullish squeeze). We already have long/short liq_pct separately, but
    # the RATIO of long to total is a single signed directional-pressure feature.
    if "long_liq_btc_pct" in x.columns and "total_liq_btc_pct" in x.columns:
        total = x["total_liq_btc_pct"].replace(0, np.nan)
        x["liq_imbalance_dir"] = (x["long_liq_btc_pct"] / total).fillna(0.5) - 0.5
        # Ranges from -0.5 (all short liq = bullish squeeze) to +0.5 (all long liq = bearish cascade)
    else:
        x["liq_imbalance_dir"] = 0.0
        print("  [warn] liq columns not found — liq_imbalance_dir set to 0")

    # ── Spread momentum: is spread widening or narrowing ─────────────────────
    # Economic logic: a spread widening (moving to extremes) may anticipate a
    # mean-reversion signal. A spread narrowing (moving to neutral) means the
    # regime is resetting. Tests directional CHANGE in spread, not absolute level.
    if "spread_pct" in x.columns:
        sp = x["spread_pct"].fillna(0.5)
        x["spread_chg_1h"] = sp - sp.shift(12)
    else:
        x["spread_chg_1h"] = 0.0
        print("  [warn] spread_pct not found — spread_chg_1h set to 0")

    # ── 4h BTC return: medium-term momentum context ───────────────────────────
    # Economic logic: 5m signals may behave differently when embedded in a
    # multi-hour trend vs. in a choppy consolidation. A positive 4h return means
    # we're in upward drift — tests whether CA/LQ signals are momentum-amplified.
    if "close_btc" in x.columns:
        x["ret_4h_btc"] = x["close_btc"].pct_change(48).fillna(0)
    else:
        x["ret_4h_btc"] = 0.0
        print("  [warn] close_btc not found — ret_4h_btc set to 0")

    # ── Volume-price divergence: high volume but small price move ─────────────
    # Economic logic: large volume with little price movement = absorption.
    # A buyer or seller is willing to absorb all flow without moving the market.
    # This often precedes a directional move when the absorption side runs out.
    if "volume_btc_pct" in x.columns and "ret1_btc" in x.columns:
        vol_high = x["volume_btc_pct"].gt(0.70).astype(float)
        price_small = x["ret1_btc"].abs().lt(x["ret1_btc"].abs().rolling(288).quantile(0.30))
        x["vol_price_div"] = (vol_high * price_small.astype(float)).fillna(0)
    else:
        x["vol_price_div"] = 0.0
        print("  [warn] volume/ret columns not found — vol_price_div set to 0")

    # ── Round 3 features — added 2026-03-11 ──────────────────────────────────

    # ── 4h ETH and BTC slope: medium-term momentum context ───────────────────
    # Economic logic: we only have 1h slopes currently. The 4h slope tells us
    # whether we're in an up-trend or down-trend on a larger timeframe. Signals
    # that align with the 4h slope may be higher-quality than counter-trend ones.
    if "close_eth" in x.columns and "close_btc" in x.columns:
        # 4h slope = return over last 48 5m bars (4h = 48 bars)
        x["ret_4h_eth"] = x["close_eth"].pct_change(48).fillna(0)
        x["eth_slope_4h"] = np.sign(x["ret_4h_eth"])  # direction only
        x["btc_slope_4h"] = np.sign(x["close_btc"].pct_change(48).fillna(0))
    else:
        x["ret_4h_eth"] = 0.0
        x["eth_slope_4h"] = 0.0
        x["btc_slope_4h"] = 0.0
        print("  [warn] close_eth/btc not found — 4h slope features set to 0")

    # ── Rolling BTC-ETH 2h correlation ───────────────────────────────────────
    # Economic logic: when BTC and ETH decouple (correlation drops), it signals
    # unusual conditions — one is responding to an idiosyncratic event. When they
    # are tightly correlated, momentum signals on one asset predict the other.
    if "ret1_btc" in x.columns and "ret1_eth" in x.columns:
        r_btc = x["ret1_btc"].fillna(0)
        r_eth = x["ret1_eth"].fillna(0)
        # 2h = 24 5m bars rolling correlation
        x["btc_eth_corr_2h"] = r_btc.rolling(24).corr(r_eth).fillna(0)
    else:
        x["btc_eth_corr_2h"] = 0.0
        print("  [warn] ret1 columns not found — btc_eth_corr_2h set to 0")

    # ── Consecutive bar direction (run length) ────────────────────────────────
    # Economic logic: 5 consecutive up-bars means momentum or cascade; tends to
    # exhaust. 5 consecutive down-bars same. Measures streak length — both a
    # continuation signal at low values and a reversal signal at high values.
    if "ret1_btc" in x.columns:
        bar_dir = np.sign(x["ret1_btc"].fillna(0)).values

        def run_length_signed(arr: np.ndarray) -> np.ndarray:
            """Consecutive same-direction bars, signed (+/-)."""
            out = np.zeros(len(arr), dtype=float)
            count = 0.0
            for i in range(len(arr)):
                if arr[i] == 0:
                    count = 0.0
                elif i == 0 or arr[i] == arr[i - 1]:
                    count += arr[i]
                else:
                    count = arr[i]
                out[i] = count
            return out

        x["bar_dir_run"] = run_length_signed(bar_dir)
    else:
        x["bar_dir_run"] = 0.0
        print("  [warn] ret1_btc not found — bar_dir_run set to 0")

    # ── Volatility of volatility (RV change momentum) ─────────────────────────
    # Economic logic: not just "is vol high" but "is vol changing fast". Rapidly
    # rising vol = regime shift incoming. Rapidly falling vol = compression before
    # breakout. Captures the TRANSITION in vol regime, not the level.
    if "rv48_pct_btc" in x.columns:
        rv = x["rv48_pct_btc"].fillna(0.5)
        # 1h change in RV percentile
        x["rv_chg_1h"] = rv - rv.shift(12)
    else:
        x["rv_chg_1h"] = 0.0
        print("  [warn] rv48_pct_btc not found — rv_chg_1h set to 0")

    # ── Round 4 features — added 2026-03-12 ──────────────────────────────────

    # ── Funding rate acceleration: rate of change of funding rate ─────────────
    # Economic logic: funding_chg_1h measures 1h delta in funding. But we want
    # the SECOND derivative — is funding accelerating or decelerating?
    # Rapidly accelerating positive funding = crowding building fast = squeeze risk.
    # Rapidly decelerating funding = crowding unwinding = potential cascade.
    # Different from funding_chg_1h (which is 1st derivative = level of change).
    if "funding_rate_btc" in x.columns:
        f = x["funding_rate_btc"].fillna(0)
        chg_1h = f - f.shift(12)        # 1h change (1st derivative)
        chg_2h = f.shift(12) - f.shift(24)  # prior 1h change
        x["funding_accel"] = chg_1h - chg_2h  # 2nd derivative: acceleration
    else:
        x["funding_accel"] = 0.0
        print("  [warn] funding_rate_btc not found — funding_accel set to 0")

    # ── OI-to-volume ratio: positioning without price discovery ───────────────
    # Economic logic: OI growing while volume is LOW = new positions being opened
    # quietly without much price movement. This is fragile positioning — no price
    # discovery means no natural stop levels. A sharp move can cascade quickly.
    # OI growing WITH high volume is normal (price found). OI growing without
    # volume = hidden leverage buildup. Normalize both to their percentile ranks.
    if "oi_contracts_btc" in x.columns and "volume_btc_pct" in x.columns:
        _w = 288  # 1-day rolling window
        oi = x["oi_contracts_btc"]
        oi_chg_1h = (oi - oi.shift(12)).fillna(0)
        # OI growth percentile: how unusual is the current OI expansion?
        oi_chg_pct = oi_chg_1h.rolling(_w, min_periods=100).rank(pct=True).fillna(0.5)
        vol_pct = x["volume_btc_pct"].fillna(0.5)
        # High ratio = OI growing fast relative to volume = fragile positioning
        x["oi_vol_ratio"] = oi_chg_pct / (vol_pct + 0.01)  # +0.01 avoids div/0
    else:
        x["oi_vol_ratio"] = 1.0
        print("  [warn] oi/volume columns not found — oi_vol_ratio set to 1")

    return x


def main():
    parser = argparse.ArgumentParser(description="Compute theory-first ML features")
    parser.add_argument("--dsn", default=os.environ.get("RC_DB_DSN"),
                        help="Postgres DSN (or set RC_DB_DSN)")
    parser.add_argument("--days", type=int, default=365, help="Lookback days")
    parser.add_argument("--output", default="results/ml/features_365d.parquet",
                        help="Output parquet path")
    args = parser.parse_args()

    if not args.dsn:
        print("ERROR: set RC_DB_DSN or pass --dsn", file=sys.stderr)
        sys.exit(1)

    print(f"[features] Loading {args.days}d frame from Postgres...")
    x = load_frame(days=args.days, dsn=args.dsn)
    print(f"[features] Loaded {len(x):,} bars  "
          f"({x['dt'].min().date()} → {x['dt'].max().date()})")
    print(f"[features] {len(x.columns)} columns from load_frame()")

    print("[features] Computing theory-first features...")
    x = compute_theory_first_features(x)

    # Coverage stats for new features
    new_features = [
        "oi_expanding_3h", "rv_compressed_4h",
        "funding_pos_hours", "funding_neg_hours",
        "liq_cluster_2h", "hour_sin", "hour_cos",
        # Round 2 — added 2026-03-11 after first ML run
        "funding_chg_1h", "btc_eth_div_1h", "oi_velocity",
        "liq_imbalance_dir", "spread_chg_1h", "ret_4h_btc", "vol_price_div",
        # Round 3 — added 2026-03-11 after second ML run
        "ret_4h_eth", "eth_slope_4h", "btc_slope_4h",
        "btc_eth_corr_2h", "bar_dir_run", "rv_chg_1h",
    ]
    print("\n[features] Coverage stats for new theory-first features:")
    for col in new_features:
        n_valid = int(x[col].notna().sum())
        if x[col].nunique() <= 3:
            n_active = int((x[col] > 0).sum())
            pct = n_active / n_valid * 100 if n_valid > 0 else 0
            print(f"  {col:<28} {n_valid:>8,} valid  {n_active:>8,} active ({pct:.1f}%)")
        else:
            print(f"  {col:<28} {n_valid:>8,} valid  "
                  f"mean={x[col].mean():.3f}  max={x[col].max():.1f}")

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    x.to_parquet(out_path, index=False)
    print(f"\n[features] Saved → {out_path}  ({len(x):,} rows, {len(x.columns)} cols)")


if __name__ == "__main__":
    main()
