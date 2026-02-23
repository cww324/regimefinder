"""
HMM Regime Discovery — Stage 1 of ML pipeline
===============================================
Discovers persistent market regimes from 1h BTC bar data using a
Gaussian Hidden Markov Model.

Walk-forward approach:
  - Train: 90 days of 1h bars
  - Label: next 30 days
  - Step: 30 days
  → ~9 labeled windows across 365 days

Output:
  - rc.regime_labels table (Postgres)
  - results/ml/hmm/hmm_regimes_YYYYMMDD.json

Usage:
  PYTHONPATH=. .venv/bin/python scripts/ml/hmm_regime_discovery.py \\
      --dsn "$RC_DB_DSN" \\
      --days 365 \\
      --n-states 3 \\
      --train-days 90 \\
      --step-days 30 \\
      --output-json results/ml/hmm/hmm_regimes_$(date +%Y%m%d).json

Design spec: docs/hmm_regime_plan.md
"""

import argparse
import json
import os
import sys
from datetime import date, timedelta

import numpy as np
import pandas as pd
from hmmlearn import hmm
from sklearn.preprocessing import StandardScaler

# ── DB connection ─────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import app.db.rc as rc
from app.db.market_data import load_btc_eth_merged_last_days
from app.db.derivatives import load_funding_rates_last_days


# ── Feature computation ───────────────────────────────────────────────────────

def build_1h_features(days: int, dsn: str) -> pd.DataFrame:
    """
    Load 5m BTC/ETH bars, aggregate to 1h, compute HMM input features.
    Returns a DataFrame indexed by 1h timestamps with columns:
        rv_1h, er20_1h, atr_pct_1h, funding_pct_1h
    """
    raw = load_btc_eth_merged_last_days(dsn=dsn, days=days)
    if raw.empty:
        raise RuntimeError("No candle data returned from DB — is Postgres running?")

    raw["dt"] = pd.to_datetime(raw["ts"], unit="s", utc=True)
    raw = raw.sort_values("dt").reset_index(drop=True)

    # Aggregate BTC OHLCV to 1h
    h1 = (
        raw.set_index("dt")[["open_btc", "high_btc", "low_btc", "close_btc", "volume_btc"]]
        .resample("1h")
        .agg({
            "open_btc":  "first",
            "high_btc":  "max",
            "low_btc":   "min",
            "close_btc": "last",
            "volume_btc": "sum",
        })
        .dropna()
    )

    # ── Realized volatility: rolling std of log returns (12-bar = 12h window)
    h1["log_ret"] = np.log(h1["close_btc"] / h1["close_btc"].shift(1))
    h1["rv_1h"] = h1["log_ret"].rolling(12).std()

    # ── Efficiency ratio: net price change / sum of absolute bar-by-bar changes
    # Measures trending (high ER) vs choppy (low ER). Window = 20 bars (20h).
    window_er = 20
    net_change = (h1["close_btc"] - h1["close_btc"].shift(window_er)).abs()
    path_length = h1["log_ret"].abs().rolling(window_er).sum()
    h1["er20_1h"] = (net_change / path_length.replace(0, np.nan)).clip(0, 1)

    # ── ATR percentile: rolling rank of ATR over 200-bar window
    prev_close = h1["close_btc"].shift(1)
    tr = pd.concat([
        h1["high_btc"] - h1["low_btc"],
        (h1["high_btc"] - prev_close).abs(),
        (h1["low_btc"]  - prev_close).abs(),
    ], axis=1).max(axis=1)
    h1["atr14_1h"] = tr.rolling(14).mean()
    h1["atr_pct_1h"] = h1["atr14_1h"].rolling(200).rank(pct=True)

    # ── Funding rate percentile: merge hourly funding, rolling rank
    try:
        funding = load_funding_rates_last_days(dsn=dsn, days=days)
        if not funding.empty:
            funding = funding.set_index("dt")[["funding_rate_btc"]].sort_index()
            funding.index = funding.index.tz_convert("UTC")
            h1 = h1.join(funding, how="left")
            h1["funding_rate_btc"] = h1["funding_rate_btc"].ffill()
            h1["funding_pct_1h"] = h1["funding_rate_btc"].rolling(200).rank(pct=True)
        else:
            h1["funding_pct_1h"] = 0.5  # neutral placeholder if unavailable
    except Exception:
        h1["funding_pct_1h"] = 0.5

    h1 = h1.dropna(subset=["rv_1h", "er20_1h", "atr_pct_1h", "funding_pct_1h"])
    return h1[["rv_1h", "er20_1h", "atr_pct_1h", "funding_pct_1h"]]


# ── Walk-forward HMM ──────────────────────────────────────────────────────────

def run_walkforward_hmm(
    features: pd.DataFrame,
    n_states: int,
    train_days: int,
    step_days: int,
) -> pd.DataFrame:
    """
    Walk-forward HMM labeling.

    For each step window:
      1. Fit GaussianHMM on train_days of 1h bars
      2. Decode states for next step_days of bars
      3. Record labels with model_train_end metadata

    Returns DataFrame with columns:
        state_id, model_train_end
    Indexed by the same timestamps as `features`.
    """
    feature_cols = features.columns.tolist()
    timestamps = features.index

    train_bars = train_days * 24
    step_bars  = step_days * 24

    labels = pd.Series(index=timestamps, dtype="Int64", name="state_id")
    train_ends = pd.Series(index=timestamps, dtype="object", name="model_train_end")

    n = len(features)
    fold = 0

    for train_end_idx in range(train_bars, n, step_bars):
        test_end_idx = min(train_end_idx + step_bars, n)
        train_slice  = features.iloc[train_end_idx - train_bars : train_end_idx]
        test_slice   = features.iloc[train_end_idx : test_end_idx]

        if len(test_slice) == 0:
            break

        X_train = train_slice[feature_cols].values.astype(float)
        X_test  = test_slice[feature_cols].values.astype(float)

        # Skip fold if NaNs remain
        if np.isnan(X_train).any() or np.isnan(X_test).any():
            fold += 1
            continue

        # Normalize per-fold to prevent covariance singularity issues
        scaler = StandardScaler()
        X_train = scaler.fit_transform(X_train)
        X_test  = scaler.transform(X_test)

        model = hmm.GaussianHMM(
            n_components=n_states,
            covariance_type="diag",   # more numerically stable than full; 4 features → diag is fine
            n_iter=100,
            random_state=42,
            verbose=False,
        )
        try:
            model.fit(X_train)
            decoded = model.predict(X_test)
        except Exception as e:
            print(f"  [fold {fold}] HMM fit failed: {e}", file=sys.stderr)
            fold += 1
            continue

        # Map local state IDs (0/1/2) to be consistent across folds
        # by sorting states by mean rv_1h ascending:
        # state with lowest rv → state 0 (RANGING), highest → state 2 (VOLATILE)
        rv_col = feature_cols.index("rv_1h")
        state_rv_means = {
            s: X_test[decoded == s, rv_col].mean() if (decoded == s).any() else 0.0
            for s in range(n_states)
        }
        sorted_states = sorted(state_rv_means, key=lambda s: state_rv_means[s])
        remap = {orig: new for new, orig in enumerate(sorted_states)}
        remapped = np.array([remap[s] for s in decoded])

        test_idx = test_slice.index
        labels.loc[test_idx] = remapped
        train_end_ts = train_slice.index[-1]
        train_ends.loc[test_idx] = str(train_end_ts)

        fold += 1
        print(f"  fold {fold:2d}: train_end={train_end_ts.date()}  "
              f"test_bars={len(test_slice):4d}  "
              f"states={dict(zip(*np.unique(remapped, return_counts=True)))}")

    result = pd.concat([labels, train_ends], axis=1).dropna()
    return result


# ── State labeling ────────────────────────────────────────────────────────────

STATE_NAMES = {0: "RANGING", 1: "TRENDING", 2: "VOLATILE"}

def label_states(features: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    """
    Attach human-readable regime names based on the RV-sorted state convention:
      0 = lowest RV  → RANGING
      1 = medium RV  → TRENDING
      2 = highest RV → VOLATILE
    """
    labels = labels.copy()
    labels["regime_name"] = labels["state_id"].map(STATE_NAMES).fillna("UNKNOWN")
    return labels


# ── Postgres write ────────────────────────────────────────────────────────────

def write_to_postgres(labels: pd.DataFrame, dsn: str, symbol: str, run_date: date):
    """Upsert regime labels into rc.regime_labels."""
    rows = []
    for ts, row in labels.iterrows():
        rows.append((
            symbol,
            ts,
            "1h",
            int(row["state_id"]),
            row["regime_name"],
            row["model_train_end"],
            run_date,
        ))

    with rc.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO rc.regime_labels
                    (symbol, ts, timeframe, state_id, regime_name, model_train_end, run_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (symbol, ts, timeframe, run_date)
                DO UPDATE SET
                    state_id        = EXCLUDED.state_id,
                    regime_name     = EXCLUDED.regime_name,
                    model_train_end = EXCLUDED.model_train_end
                """,
                rows,
            )
        conn.commit()
    print(f"  wrote {len(rows)} regime labels to rc.regime_labels")


# ── Summary stats ─────────────────────────────────────────────────────────────

def build_summary(
    features: pd.DataFrame,
    labels: pd.DataFrame,
    config: dict,
    run_date: date,
) -> dict:
    """Build the JSON summary output."""
    joined = features.join(labels, how="inner")

    state_summary = []
    for state_id, name in STATE_NAMES.items():
        mask = joined["state_id"] == state_id
        if mask.sum() == 0:
            continue
        grp = joined.loc[mask]
        state_summary.append({
            "state_id":    state_id,
            "regime_name": name,
            "pct_bars":    round(float(mask.sum() / len(joined)), 3),
            "mean_rv_1h":  round(float(grp["rv_1h"].mean()), 6),
            "mean_er20":   round(float(grp["er20_1h"].mean()), 3),
            "mean_atr_pct": round(float(grp["atr_pct_1h"].mean()), 3),
            "mean_funding_pct": round(float(grp["funding_pct_1h"].mean()), 3),
        })

    return {
        "run_date":        str(run_date),
        "config":          config,
        "n_labeled_bars":  int(len(labels)),
        "n_total_bars":    int(len(features)),
        "state_summary":   state_summary,
        "note": (
            "States sorted by rv_1h ascending: 0=RANGING (low vol), "
            "1=TRENDING (mid vol, directional), 2=VOLATILE (high vol/shock). "
            "365d window is mostly bull-market — all regimes are bull-market variants."
        ),
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="HMM Regime Discovery")
    parser.add_argument("--dsn",          required=True,  help="Postgres DSN")
    parser.add_argument("--days",         type=int, default=365)
    parser.add_argument("--n-states",     type=int, default=3)
    parser.add_argument("--train-days",   type=int, default=90)
    parser.add_argument("--step-days",    type=int, default=30)
    parser.add_argument("--symbol",       default="BTC-USD")
    parser.add_argument("--output-json",  default="results/ml/hmm/hmm_regimes.json")
    parser.add_argument("--no-db-write",  action="store_true",
                        help="Skip writing to Postgres (dry run)")
    args = parser.parse_args()

    run_date = date.today()
    config = {
        "days":       args.days,
        "n_states":   args.n_states,
        "train_days": args.train_days,
        "step_days":  args.step_days,
        "symbol":     args.symbol,
        "timeframe":  "1h",
    }

    print(f"[HMM] Loading 1h features — {args.days}d of {args.symbol} data...")
    features = build_1h_features(days=args.days, dsn=args.dsn)
    print(f"[HMM] Feature matrix: {len(features)} bars "
          f"({features.index[0].date()} → {features.index[-1].date()})")

    print(f"[HMM] Running walk-forward HMM (n_states={args.n_states}, "
          f"train={args.train_days}d, step={args.step_days}d)...")
    labels = run_walkforward_hmm(
        features,
        n_states=args.n_states,
        train_days=args.train_days,
        step_days=args.step_days,
    )
    labels = label_states(features, labels)

    print(f"\n[HMM] Regime distribution across {len(labels)} labeled bars:")
    for _, row in pd.DataFrame(
        labels["regime_name"].value_counts(normalize=True).reset_index()
    ).iterrows():
        print(f"  {row['regime_name']:12s}  {row['proportion']:.1%}")

    if not args.no_db_write:
        print(f"\n[HMM] Writing labels to rc.regime_labels...")
        write_to_postgres(labels, dsn=args.dsn, symbol=args.symbol, run_date=run_date)
    else:
        print("\n[HMM] --no-db-write set, skipping Postgres write.")

    summary = build_summary(features, labels, config, run_date)
    os.makedirs(os.path.dirname(args.output_json), exist_ok=True)
    with open(args.output_json, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\n[HMM] Summary written to {args.output_json}")
    print("\n[HMM] Done. Next step: review summary JSON, then run rf_hypothesis_generator.py")


if __name__ == "__main__":
    main()
