import argparse
import json
import os
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from scripts.research_family_runner import build_events, cost_value, load_frame


HYPOTHESES_PATH = Path("hypotheses.yaml")
ENV_PATH = Path(".env")
ERRORS_DIR = Path("results/errors")

ETH_TRADE_HYPOTHESES = {
    "H60",
    "H64",
    "H65",
    "H67",
    "H70",
    "H71",
    "H73",
    "H75",
    "H77",
    "H79",
    "H83",
    "H84",
    "H85",
}


@dataclass
class PortfolioPolicy:
    policy_id: str
    candidate_universe: list[str]
    include_members: list[str]
    exclude_members: list[str]
    dedup_keep: str
    dedup_drop: str
    weighting_mode: str
    rank_window_days: int
    score_clip_floor: float
    fallback_weighting: str
    consensus_threshold: float
    min_active_members: int
    core_set: list[str]
    session_map: dict[str, str]
    core_weight_share: float
    specialist_weight_share: float
    fallback_mode: str
    policy_snapshot: dict[str, Any]


@dataclass
class HypothesisRun:
    hypothesis_id: str
    family: str
    horizon_bars: int
    asset: str
    events: pd.DataFrame
    details: dict[str, Any] = field(default_factory=dict)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().replace(microsecond=0).isoformat()


def utc_stamp() -> str:
    return utc_now().strftime("%Y%m%dT%H%M%SZ")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run offline paper portfolio simulation for multiple hypotheses.")
    p.add_argument("--hypothesis-ids", type=str, required=True, help="Comma-separated hypothesis IDs.")
    p.add_argument("--days", type=int, choices=[180, 365], required=True)
    p.add_argument("--mode", type=str, choices=["standalone", "combined"], required=True)
    p.add_argument("--cost-mode", type=str, choices=["gross", "bps8", "bps10"], required=True)
    p.add_argument("--output-json", type=str, required=True)

    p.add_argument("--dsn", type=str, default="", help="Postgres DSN (fallback RC_DB_DSN / .env).")
    p.add_argument("--timeframe", type=str, default="5m")
    p.add_argument("--bootstrap-iters", type=int, default=3000)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--max-gross-exposure", type=float, default=1.0)
    p.add_argument("--max-asset-exposure", type=float, default=1.0)
    p.add_argument("--max-strategy-weight", type=float, default=0.35)
    p.add_argument("--cooldown-bars", type=int, default=0)
    p.add_argument("--daily-loss-stop-pct", type=float, default=0.03)
    p.add_argument("--report-csv-prefix", type=str, default="")
    return p.parse_args(argv)


def load_env_value(path: Path, key: str) -> str:
    if not path.exists():
        return ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip() != key:
            continue
        val = v.strip()
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        return val.strip()
    return ""


def resolve_dsn(cli_dsn: str) -> str:
    if cli_dsn.strip():
        return cli_dsn.strip()
    env_dsn = os.getenv("RC_DB_DSN", "").strip()
    if env_dsn:
        return env_dsn
    return load_env_value(ENV_PATH, "RC_DB_DSN")


def parse_hypothesis_ids(raw: str) -> list[str]:
    ids = [x.strip() for x in raw.split(",") if x.strip()]
    if not ids:
        raise ValueError("--hypothesis-ids must contain at least one id")
    seen: set[str] = set()
    out: list[str] = []
    for hyp_id in ids:
        if hyp_id not in seen:
            out.append(hyp_id)
            seen.add(hyp_id)
    return out


def hypothesis_asset(hypothesis_id: str) -> str:
    return "ETH-USD" if hypothesis_id in ETH_TRADE_HYPOTHESES else "BTC-USD"


def load_hypothesis_index(path: Path) -> dict[str, dict[str, Any]]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("hypotheses.yaml must have a mapping root")
    rows = payload.get("hypotheses", [])
    if not isinstance(rows, list):
        raise ValueError("hypotheses.yaml 'hypotheses' must be a list")
    index: dict[str, dict[str, Any]] = {}
    for row in rows:
        if isinstance(row, dict) and row.get("id"):
            index[str(row["id"])] = row
    return index


def to_float_array(series: pd.Series) -> np.ndarray:
    arr = np.asarray(series.to_numpy(), dtype=float)
    return arr[np.isfinite(arr)]


def max_drawdown_from_returns(returns: np.ndarray) -> float:
    if returns.size == 0:
        return 0.0
    equity = np.cumprod(1.0 + returns)
    running_max = np.maximum.accumulate(equity)
    dd = equity / running_max - 1.0
    return float(dd.min())


def monthly_table(ts: pd.Series, returns: pd.Series) -> dict[str, dict[str, float | int]]:
    if ts.empty:
        return {}
    month = ts.dt.strftime("%Y-%m")
    frame = pd.DataFrame({"month": month, "r": returns})
    out: dict[str, dict[str, float | int]] = {}
    for m, g in frame.groupby("month", sort=True):
        arr = to_float_array(g["r"])
        out[m] = {
            "trades": int(len(arr)),
            "net_return": float(np.sum(arr)) if arr.size else 0.0,
            "mean_return": float(np.mean(arr)) if arr.size else 0.0,
            "win_rate": float(np.mean(arr > 0)) if arr.size else 0.0,
        }
    return out


def _stable_unique(xs: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for x in xs:
        if x not in seen:
            out.append(x)
            seen.add(x)
    return out


def _as_str_list(v: Any) -> list[str]:
    if isinstance(v, list):
        return [str(x) for x in v]
    return []


def load_portfolio_policy(hypothesis_id: str, row: dict[str, Any]) -> PortfolioPolicy:
    params = row.get("parameters", {}) if isinstance(row.get("parameters", {}), dict) else {}
    fixed = params.get("fixed", {}) if isinstance(params.get("fixed", {}), dict) else {}

    candidate_universe = _as_str_list(fixed.get("candidate_universe", []))
    include_members = _as_str_list(fixed.get("include_members", []))
    exclude_members = _as_str_list(fixed.get("exclude_members", []))

    dedup_keep = str(fixed.get("dedup_keep", "")).strip()
    dedup_drop = str(fixed.get("dedup_drop", "")).strip()

    weighting_mode = str(fixed.get("weighting_mode", "equal_weight_active"))
    if hypothesis_id == "P02":
        weighting_mode = "rank_weight"

    rank_window_days = int(fixed.get("rank_window_days", params.get("rank_window_days", 30)))
    score_clip_floor = float(fixed.get("score_clip_floor", 0.0))
    fallback_weighting = str(fixed.get("fallback_weighting", "equal_weight_active"))

    consensus_threshold = float(fixed.get("consensus_threshold", params.get("consensus_threshold", 0.0)))
    min_active_members = int(fixed.get("min_active_members", params.get("min_active_members", 1)))

    core_set = _as_str_list(fixed.get("core_set", []))
    session_map = fixed.get("session_map", {}) if isinstance(fixed.get("session_map", {}), dict) else {}
    session_map_str = {str(k): str(v) for k, v in session_map.items()}

    core_weight_share = float(fixed.get("core_weight_share", 0.60))
    specialist_weight_share = float(fixed.get("specialist_weight_share", 0.40))
    fallback_mode = str(fixed.get("fallback_mode", "core_only_equal_weight"))

    if not candidate_universe:
        raise ValueError(f"{hypothesis_id} missing candidate_universe")

    policy_snapshot = {
        "policy_id": hypothesis_id,
        "candidate_universe": candidate_universe,
        "include_members": include_members,
        "exclude_members": exclude_members,
        "dedup_keep": dedup_keep,
        "dedup_drop": dedup_drop,
        "weighting_mode": weighting_mode,
        "rank_window_days": rank_window_days,
        "score_clip_floor": score_clip_floor,
        "fallback_weighting": fallback_weighting,
        "consensus_threshold": consensus_threshold,
        "min_active_members": min_active_members,
        "core_set": core_set,
        "session_map": session_map_str,
        "core_weight_share": core_weight_share,
        "specialist_weight_share": specialist_weight_share,
        "fallback_mode": fallback_mode,
    }

    return PortfolioPolicy(
        policy_id=hypothesis_id,
        candidate_universe=candidate_universe,
        include_members=include_members,
        exclude_members=exclude_members,
        dedup_keep=dedup_keep,
        dedup_drop=dedup_drop,
        weighting_mode=weighting_mode,
        rank_window_days=rank_window_days,
        score_clip_floor=score_clip_floor,
        fallback_weighting=fallback_weighting,
        consensus_threshold=consensus_threshold,
        min_active_members=min_active_members,
        core_set=core_set,
        session_map=session_map_str,
        core_weight_share=core_weight_share,
        specialist_weight_share=specialist_weight_share,
        fallback_mode=fallback_mode,
        policy_snapshot=policy_snapshot,
    )


def resolve_policy_members(policy: PortfolioPolicy) -> list[str]:
    members = list(policy.candidate_universe)
    if policy.include_members:
        include_set = set(policy.include_members)
        members = [m for m in members if m in include_set]
    if policy.exclude_members:
        exclude_set = set(policy.exclude_members)
        members = [m for m in members if m not in exclude_set]
    if policy.dedup_drop and policy.dedup_keep and policy.dedup_keep in members:
        members = [m for m in members if m != policy.dedup_drop]
    return _stable_unique(members)


def _session_specialist(session_map: dict[str, str], dt: pd.Timestamp) -> str:
    hour = dt.hour
    for window, specialist in sorted(session_map.items()):
        parts = str(window).split("-")
        if len(parts) != 2:
            continue
        start_h = int(parts[0].split(":")[0])
        end_h = int(parts[1].split(":")[0])
        if start_h <= hour < end_h:
            return specialist
    return ""


def _rank_scores(member_history: dict[str, pd.DataFrame], ts: int, window_days: int, clip_floor: float) -> dict[str, float]:
    out: dict[str, float] = {}
    cutoff = int(ts - (window_days * 86400))
    for member, df in member_history.items():
        hist = df[(df["ts"] < ts) & (df["ts"] >= cutoff)]
        if hist.empty:
            out[member] = 0.0
            continue
        vals = hist["gross_r"].to_numpy(dtype=float)
        vals = vals[np.isfinite(vals)]
        if vals.size == 0:
            out[member] = 0.0
            continue
        mean = float(np.mean(vals))
        std = float(np.std(vals, ddof=0))
        score = 0.0 if std <= 0 else (mean / std)
        out[member] = max(float(clip_floor), float(score))
    return out


def _weights_equal(active: list[str]) -> dict[str, float]:
    if not active:
        return {}
    w = 1.0 / float(len(active))
    return {m: w for m in active}


def _weights_rank(active: list[str], scores: dict[str, float], fallback_mode: str) -> dict[str, float]:
    pos = {m: max(0.0, float(scores.get(m, 0.0))) for m in active}
    total = float(sum(pos.values()))
    if total > 0:
        return {m: float(pos[m] / total) for m in active}
    if fallback_mode == "equal_weight_active":
        return _weights_equal(active)
    return {m: 0.0 for m in active}


def build_hypothesis_metrics(events: pd.DataFrame, cost: float, hypothesis_id: str, asset: str) -> dict[str, Any]:
    net = events["gross_r"].astype(float) - float(cost)
    arr = to_float_array(net)
    trade_count = int(arr.size)
    net_return = float(np.sum(arr)) if trade_count else 0.0
    win_rate = float(np.mean(arr > 0)) if trade_count else 0.0
    expectancy = float(np.mean(arr)) if trade_count else 0.0

    return {
        "hypothesis_id": hypothesis_id,
        "asset": asset,
        "trade_count": trade_count,
        "turnover": float(trade_count),
        "net_return": net_return,
        "max_drawdown": max_drawdown_from_returns(arr),
        "win_rate": win_rate,
        "expectancy": expectancy,
        "monthly_stability": monthly_table(events["dt"], net),
    }


def combined_risk_controls(
    rows: list[dict[str, Any]],
    max_gross_exposure: float,
    max_asset_exposure: float,
    max_strategy_weight: float,
) -> tuple[list[dict[str, Any]], dict[str, float], float]:
    if not rows:
        return [], {}, 0.0

    raw = np.asarray([float(r["signal_dir"]) for r in rows], dtype=float)
    denom = float(np.sum(np.abs(raw)))
    if denom <= 0:
        return [], {}, 0.0

    weights = raw / denom
    weights = np.clip(weights, -max_strategy_weight, max_strategy_weight)

    gross = float(np.sum(np.abs(weights)))
    if gross > max_gross_exposure and gross > 0:
        weights *= max_gross_exposure / gross

    asset_net: dict[str, float] = {}
    for i, row in enumerate(rows):
        asset = str(row["asset"])
        asset_net[asset] = asset_net.get(asset, 0.0) + float(weights[i])

    for asset, net in list(asset_net.items()):
        if abs(net) > max_asset_exposure and abs(net) > 0:
            scale = max_asset_exposure / abs(net)
            for i, row in enumerate(rows):
                if row["asset"] == asset:
                    weights[i] *= scale

    out_rows: list[dict[str, Any]] = []
    final_asset_net: dict[str, float] = {}
    for i, row in enumerate(rows):
        w = float(weights[i])
        if abs(w) <= 1e-12:
            continue
        item = dict(row)
        item["weight"] = w
        out_rows.append(item)
        asset = str(row["asset"])
        final_asset_net[asset] = final_asset_net.get(asset, 0.0) + w

    gross_final = float(sum(abs(v) for v in final_asset_net.values()))
    return out_rows, final_asset_net, gross_final


def build_combined_metrics(
    runs: list[HypothesisRun],
    cost: float,
    cooldown_bars: int,
    max_gross_exposure: float,
    max_asset_exposure: float,
    max_strategy_weight: float,
    daily_loss_stop_pct: float,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for run in runs:
        for row in run.events.itertuples(index=False):
            rows.append(
                {
                    "ts": int(row.ts),
                    "dt": row.dt,
                    "hypothesis_id": run.hypothesis_id,
                    "asset": run.asset,
                    "signal_dir": float(row.signal_dir),
                    "gross_r": float(row.gross_r),
                }
            )

    rows.sort(key=lambda x: (x["ts"], x["hypothesis_id"]))
    by_ts: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        by_ts.setdefault(int(row["ts"]), []).append(row)

    last_trade_ts: dict[str, int] = {}
    stopped_days: set[str] = set()
    day_pnl: dict[str, float] = {}

    combined_returns: list[float] = []
    combined_dt: list[pd.Timestamp] = []
    gross_exposure_series: list[float] = []
    asset_exposure_series: dict[str, list[float]] = {}
    strategy_pnl: dict[str, float] = {r.hypothesis_id: 0.0 for r in runs}
    strategy_trade_counts: dict[str, int] = {r.hypothesis_id: 0 for r in runs}

    cooldown_secs = int(cooldown_bars) * 300

    for ts in sorted(by_ts):
        bucket = by_ts[ts]
        trade_dt = pd.Timestamp(bucket[0]["dt"])
        day_key = trade_dt.strftime("%Y-%m-%d")
        if day_key in stopped_days:
            continue

        filtered: list[dict[str, Any]] = []
        for row in bucket:
            hyp_id = str(row["hypothesis_id"])
            prev = last_trade_ts.get(hyp_id)
            if prev is not None and cooldown_secs > 0 and (ts - prev) < cooldown_secs:
                continue
            filtered.append(row)

        weighted_rows, asset_net, gross_net = combined_risk_controls(
            filtered,
            max_gross_exposure=max_gross_exposure,
            max_asset_exposure=max_asset_exposure,
            max_strategy_weight=max_strategy_weight,
        )
        if not weighted_rows:
            continue

        pnl = 0.0
        for row in weighted_rows:
            hyp_id = str(row["hypothesis_id"])
            net_r = float(row["gross_r"]) - float(cost)
            weighted_r = float(row["weight"]) * net_r
            pnl += weighted_r
            strategy_pnl[hyp_id] = strategy_pnl.get(hyp_id, 0.0) + weighted_r
            strategy_trade_counts[hyp_id] = strategy_trade_counts.get(hyp_id, 0) + 1
            last_trade_ts[hyp_id] = ts

        day_pnl[day_key] = day_pnl.get(day_key, 0.0) + pnl
        if day_pnl[day_key] <= -abs(daily_loss_stop_pct):
            stopped_days.add(day_key)

        combined_returns.append(float(pnl))
        combined_dt.append(trade_dt)
        gross_exposure_series.append(float(gross_net))
        for asset, value in asset_net.items():
            asset_exposure_series.setdefault(asset, []).append(float(abs(value)))

    ret_arr = np.asarray(combined_returns, dtype=float)
    trade_count = int(ret_arr.size)
    total_abs_pnl = float(sum(abs(v) for v in strategy_pnl.values()))

    concentration = {
        "strategy_pnl_share": {
            k: (float(abs(v)) / total_abs_pnl if total_abs_pnl > 0 else 0.0)
            for k, v in sorted(strategy_pnl.items())
        },
        "strategy_trade_counts": {k: int(v) for k, v in sorted(strategy_trade_counts.items())},
        "mean_gross_exposure": float(np.mean(gross_exposure_series)) if gross_exposure_series else 0.0,
        "max_gross_exposure": float(np.max(gross_exposure_series)) if gross_exposure_series else 0.0,
        "mean_abs_asset_exposure": {
            k: float(np.mean(v)) if v else 0.0 for k, v in sorted(asset_exposure_series.items())
        },
    }

    corr = cross_strategy_correlation(runs=runs, cost=cost)

    if trade_count == 0:
        monthly = {}
        win_rate = 0.0
        expectancy = 0.0
        net_return = 0.0
        max_dd = 0.0
    else:
        ts_series = pd.Series(combined_dt, dtype="datetime64[ns, UTC]")
        r_series = pd.Series(ret_arr, dtype=float)
        monthly = monthly_table(ts_series, r_series)
        win_rate = float(np.mean(ret_arr > 0))
        expectancy = float(np.mean(ret_arr))
        net_return = float(np.sum(ret_arr))
        max_dd = max_drawdown_from_returns(ret_arr)

    return {
        "summary": {
            "trade_count": trade_count,
            "turnover": float(trade_count),
            "net_return": net_return,
            "max_drawdown": max_dd,
            "win_rate": win_rate,
            "expectancy": expectancy,
            "monthly_stability": monthly,
        },
        "concentration": concentration,
        "cross_strategy_correlation": corr,
    }


def cross_strategy_correlation(runs: list[HypothesisRun], cost: float) -> dict[str, dict[str, float]]:
    frames: list[pd.DataFrame] = []
    for run in runs:
        if run.events.empty:
            continue
        day = run.events["dt"].dt.floor("D")
        vals = (run.events["gross_r"].astype(float) - float(cost)).groupby(day).sum()
        frames.append(vals.rename(run.hypothesis_id).to_frame())
    if not frames:
        return {}
    mat = pd.concat(frames, axis=1).fillna(0.0)
    corr_df = mat.corr().fillna(0.0)
    out: dict[str, dict[str, float]] = {}
    for row_id in corr_df.index:
        out[str(row_id)] = {str(col): float(corr_df.loc[row_id, col]) for col in corr_df.columns}
    return out


def aggregate_standalone(per_hypothesis: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not per_hypothesis:
        return {
            "hypothesis_count": 0,
            "trade_count": 0,
            "turnover": 0.0,
            "mean_net_return": 0.0,
            "mean_max_drawdown": 0.0,
            "mean_win_rate": 0.0,
            "mean_expectancy": 0.0,
        }

    metrics = list(per_hypothesis.values())
    return {
        "hypothesis_count": len(metrics),
        "trade_count": int(sum(int(m["trade_count"]) for m in metrics)),
        "turnover": float(sum(float(m["turnover"]) for m in metrics)),
        "mean_net_return": float(np.mean([float(m["net_return"]) for m in metrics])),
        "mean_max_drawdown": float(np.mean([float(m["max_drawdown"]) for m in metrics])),
        "mean_win_rate": float(np.mean([float(m["win_rate"]) for m in metrics])),
        "mean_expectancy": float(np.mean([float(m["expectancy"]) for m in metrics])),
    }


def build_dataset_fingerprint(dsn: str, days: int) -> dict[str, Any]:
    frame = load_frame(days=days, dsn=dsn)
    if frame.empty:
        raise ValueError("No market data returned for the requested window")

    start_ts = pd.Timestamp(frame["dt"].min()).replace(microsecond=0).isoformat()
    end_ts = pd.Timestamp(frame["dt"].max()).replace(microsecond=0).isoformat()
    bar_count = int(len(frame))

    db_last_modified = {
        "BTC-USD": end_ts,
        "ETH-USD": end_ts,
    }

    return {
        "start_ts": start_ts,
        "end_ts": end_ts,
        "bar_count": bar_count,
        "db_path": {
            "BTC-USD": "postgres:rc.candles",
            "ETH-USD": "postgres:rc.candles",
        },
        "db_last_modified": db_last_modified,
    }


def maybe_write_reports(runs: list[HypothesisRun], prefix: str, cost: float) -> None:
    if not prefix:
        return
    base = Path(prefix)
    base.parent.mkdir(parents=True, exist_ok=True)

    trade_rows: list[dict[str, Any]] = []
    for run in runs:
        for row in run.events.itertuples(index=False):
            trade_rows.append(
                {
                    "hypothesis_id": run.hypothesis_id,
                    "asset": run.asset,
                    "ts": int(row.ts),
                    "dt": row.dt,
                    "signal_dir": float(row.signal_dir),
                    "gross_r": float(row.gross_r),
                    "net_r": float(row.gross_r) - float(cost),
                }
            )
    trades_path = base.with_name(base.name + "_trades.csv")
    pd.DataFrame(trade_rows).to_csv(trades_path, index=False)


def build_base_hypothesis_run(hypothesis_id: str, row: dict[str, Any], days: int, dsn: str) -> HypothesisRun:
    family = str(row.get("family", "")).strip()
    if not family:
        raise ValueError(f"Hypothesis {hypothesis_id} missing family")
    params = row.get("parameters", {}) if isinstance(row.get("parameters", {}), dict) else {}
    horizon = int(params.get("horizon_bars", 6))
    events = build_events(days=days, horizon=horizon, hypothesis_id=hypothesis_id, family=family, dsn=dsn)
    return HypothesisRun(
        hypothesis_id=hypothesis_id,
        family=family,
        horizon_bars=horizon,
        asset=hypothesis_asset(hypothesis_id),
        events=events,
        details={},
    )


def build_portfolio_hypothesis_run(
    hypothesis_id: str,
    row: dict[str, Any],
    days: int,
    dsn: str,
    hyp_index: dict[str, dict[str, Any]],
) -> HypothesisRun:
    policy = load_portfolio_policy(hypothesis_id, row)
    members = resolve_policy_members(policy)
    if not members:
        raise ValueError(f"{hypothesis_id} has empty effective member set")

    member_runs: dict[str, HypothesisRun] = {}
    for member in members:
        if member not in hyp_index:
            raise ValueError(f"{hypothesis_id} references unknown member {member}")
        member_row = hyp_index[member]
        member_family = str(member_row.get("family", "")).strip()
        if member_family == "portfolio_construction":
            raise ValueError(f"{hypothesis_id} cannot reference portfolio member {member}")
        member_runs[member] = build_base_hypothesis_run(member, member_row, days, dsn)

    timeline: dict[int, dict[str, Any]] = {}
    member_history: dict[str, pd.DataFrame] = {m: r.events.sort_values("ts").reset_index(drop=True) for m, r in member_runs.items()}

    for member, run in member_runs.items():
        for ev in run.events.itertuples(index=False):
            ts = int(ev.ts)
            slot = timeline.setdefault(ts, {"dt": ev.dt, "members": {}})
            slot["members"][member] = {
                "signal_dir": float(ev.signal_dir),
                "gross_r": float(ev.gross_r),
                "family": run.family,
            }

    rows: list[dict[str, Any]] = []
    strategy_weight_obs: dict[str, list[float]] = {m: [] for m in members}
    active_count_obs: list[int] = []
    family_pnl: dict[str, float] = {}

    for ts in sorted(timeline):
        bucket = timeline[ts]
        dt = pd.Timestamp(bucket["dt"])  # type: ignore[arg-type]
        member_items: dict[str, dict[str, Any]] = bucket["members"]

        active = [m for m in sorted(member_items) if float(member_items[m]["signal_dir"]) != 0.0]
        if not active:
            continue

        if policy.policy_id == "P04":
            core_active = [m for m in active if m in set(policy.core_set)]
            specialist = _session_specialist(policy.session_map, dt)
            use_specialist = specialist in active and specialist != ""
            weights: dict[str, float] = {}
            if core_active and use_specialist:
                core_w = float(policy.core_weight_share)
                spec_w = float(policy.specialist_weight_share)
                each_core = core_w / float(len(core_active))
                for m in core_active:
                    weights[m] = each_core
                weights[specialist] = spec_w
            elif core_active and policy.fallback_mode == "core_only_equal_weight":
                weights = _weights_equal(core_active)
            else:
                continue
        elif policy.weighting_mode == "rank_weight":
            scores = _rank_scores(member_history=member_history, ts=ts, window_days=policy.rank_window_days, clip_floor=policy.score_clip_floor)
            weights = _weights_rank(active=active, scores=scores, fallback_mode=policy.fallback_weighting)
        else:
            weights = _weights_equal(active)

        if not weights:
            continue

        active_count = len([m for m, w in weights.items() if abs(w) > 1e-12])
        if active_count == 0:
            continue

        signed = 0.0
        abs_w = 0.0
        for member, weight in sorted(weights.items()):
            sign = float(np.sign(member_items[member]["signal_dir"]))
            signed += sign * float(weight)
            abs_w += abs(float(weight))

        consensus = abs(signed) / abs_w if abs_w > 0 else 0.0
        if policy.policy_id == "P03":
            if active_count < policy.min_active_members or consensus < policy.consensus_threshold:
                continue

        direction = float(np.sign(signed))
        if direction == 0.0:
            continue

        gross_r = 0.0
        for member, weight in sorted(weights.items()):
            mr = float(member_items[member]["gross_r"])
            gross_r += float(weight) * mr
            strategy_weight_obs[member].append(float(weight))
            fam = str(member_items[member]["family"])
            family_pnl[fam] = family_pnl.get(fam, 0.0) + float(weight) * mr
        active_count_obs.append(active_count)

        rows.append({
            "ts": ts,
            "dt": dt,
            "signal_dir": direction,
            "gross_r": float(gross_r),
        })

    events = pd.DataFrame(rows, columns=["ts", "dt", "signal_dir", "gross_r"]) if rows else pd.DataFrame(columns=["ts", "dt", "signal_dir", "gross_r"])

    weight_summary = {
        m: {
            "mean_weight": float(np.mean(v)) if v else 0.0,
            "mean_abs_weight": float(np.mean(np.abs(np.asarray(v, dtype=float)))) if v else 0.0,
            "observations": int(len(v)),
        }
        for m, v in sorted(strategy_weight_obs.items())
    }

    active_dist: dict[str, int] = {}
    for n in active_count_obs:
        k = str(int(n))
        active_dist[k] = active_dist.get(k, 0) + 1

    details = {
        "policy_config_snapshot": policy.policy_snapshot,
        "effective_strategy_weights_summary": weight_summary,
        "active_strategy_count_distribution": dict(sorted(active_dist.items(), key=lambda x: int(x[0]))),
        "family_contribution_summary": {k: float(v) for k, v in sorted(family_pnl.items())},
        "resolved_members": members,
    }

    return HypothesisRun(
        hypothesis_id=hypothesis_id,
        family="portfolio_construction",
        horizon_bars=int((row.get("parameters", {}) or {}).get("horizon_bars", 8)),
        asset="BTC-USD",
        events=events,
        details=details,
    )


def collect_hypothesis_runs(hypothesis_ids: list[str], days: int, dsn: str) -> list[HypothesisRun]:
    hyp_index = load_hypothesis_index(HYPOTHESES_PATH)
    runs: list[HypothesisRun] = []
    for hyp_id in hypothesis_ids:
        if hyp_id not in hyp_index:
            raise ValueError(f"Hypothesis id not found in hypotheses.yaml: {hyp_id}")
        row = hyp_index[hyp_id]
        family = str(row.get("family", "")).strip()
        if family == "portfolio_construction":
            runs.append(build_portfolio_hypothesis_run(hypothesis_id=hyp_id, row=row, days=days, dsn=dsn, hyp_index=hyp_index))
        else:
            runs.append(build_base_hypothesis_run(hypothesis_id=hyp_id, row=row, days=days, dsn=dsn))
    return runs


def build_heat_audit(runs: list[HypothesisRun]) -> dict[str, Any]:
    audit_rows = [r for r in runs if r.family == "portfolio_construction" and r.details]
    if not audit_rows:
        return {
            "effective_strategy_weights_summary": {},
            "active_strategy_count_distribution": {},
            "family_contribution_summary": {},
            "policy_config_snapshot": {},
        }

    agg_weights: dict[str, list[float]] = {}
    agg_active: dict[str, int] = {}
    agg_family: dict[str, float] = {}
    policy_snapshot: dict[str, Any] = {}

    for run in audit_rows:
        policy_snapshot[run.hypothesis_id] = run.details.get("policy_config_snapshot", {})
        wsum = run.details.get("effective_strategy_weights_summary", {})
        for strat, vals in wsum.items():
            agg_weights.setdefault(strat, []).append(float(vals.get("mean_weight", 0.0)))
        ad = run.details.get("active_strategy_count_distribution", {})
        for k, v in ad.items():
            agg_active[str(k)] = agg_active.get(str(k), 0) + int(v)
        fam = run.details.get("family_contribution_summary", {})
        for k, v in fam.items():
            agg_family[k] = agg_family.get(k, 0.0) + float(v)

    weight_summary = {
        s: {
            "mean_weight": float(np.mean(vals)),
            "mean_abs_weight": float(np.mean(np.abs(np.asarray(vals, dtype=float)))),
            "runs": int(len(vals)),
        }
        for s, vals in sorted(agg_weights.items())
    }

    return {
        "effective_strategy_weights_summary": weight_summary,
        "active_strategy_count_distribution": dict(sorted(agg_active.items(), key=lambda x: int(x[0]))),
        "family_contribution_summary": {k: float(v) for k, v in sorted(agg_family.items())},
        "policy_config_snapshot": policy_snapshot,
    }


def execute(args: argparse.Namespace) -> dict[str, Any]:
    if args.timeframe != "5m":
        raise ValueError("run_paper_portfolio supports timeframe=5m only")

    dsn = resolve_dsn(args.dsn)
    if not dsn:
        raise ValueError("Postgres DSN required: provide --dsn or set RC_DB_DSN")

    hypothesis_ids = parse_hypothesis_ids(args.hypothesis_ids)
    cost = cost_value(args.cost_mode)

    runs = collect_hypothesis_runs(hypothesis_ids=hypothesis_ids, days=int(args.days), dsn=dsn)
    dataset = build_dataset_fingerprint(dsn=dsn, days=int(args.days))
    heat_audit = build_heat_audit(runs)

    if args.mode == "standalone":
        per_hypothesis: dict[str, dict[str, Any]] = {}
        for run in runs:
            item = build_hypothesis_metrics(
                run.events,
                cost=cost,
                hypothesis_id=run.hypothesis_id,
                asset=run.asset,
            )
            if run.details:
                item["policy_details"] = run.details
            per_hypothesis[run.hypothesis_id] = item
        metrics: dict[str, Any] = {
            "per_hypothesis": per_hypothesis,
            "aggregate": aggregate_standalone(per_hypothesis),
            "heat_audit": heat_audit,
        }
    else:
        metrics = build_combined_metrics(
            runs=runs,
            cost=cost,
            cooldown_bars=int(args.cooldown_bars),
            max_gross_exposure=float(args.max_gross_exposure),
            max_asset_exposure=float(args.max_asset_exposure),
            max_strategy_weight=float(args.max_strategy_weight),
            daily_loss_stop_pct=float(args.daily_loss_stop_pct),
        )
        metrics["heat_audit"] = heat_audit

    payload = {
        "timestamp_utc": utc_now_iso(),
        "mode": args.mode,
        "hypothesis_ids": hypothesis_ids,
        "window_days": int(args.days),
        "cost_mode": args.cost_mode,
        "metrics": metrics,
        "dataset": dataset,
        "config": {
            "dsn_source": "--dsn" if args.dsn.strip() else "RC_DB_DSN",
            "timeframe": args.timeframe,
            "bootstrap_iters": int(args.bootstrap_iters),
            "seed": int(args.seed),
            "max_gross_exposure": float(args.max_gross_exposure),
            "max_asset_exposure": float(args.max_asset_exposure),
            "max_strategy_weight": float(args.max_strategy_weight),
            "cooldown_bars": int(args.cooldown_bars),
            "daily_loss_stop_pct": float(args.daily_loss_stop_pct),
            "report_csv_prefix": args.report_csv_prefix,
        },
    }

    maybe_write_reports(runs=runs, prefix=args.report_csv_prefix, cost=cost)
    return payload


def write_error_record(err: Exception, args: argparse.Namespace) -> Path:
    ERRORS_DIR.mkdir(parents=True, exist_ok=True)
    out = ERRORS_DIR / f"{utc_stamp()}_paper_portfolio.json"
    payload = {
        "timestamp_utc": utc_now_iso(),
        "error": str(err),
        "traceback": traceback.format_exc(),
        "context": {
            "hypothesis_ids": args.hypothesis_ids,
            "days": args.days,
            "mode": args.mode,
            "cost_mode": args.cost_mode,
            "output_json": args.output_json,
        },
    }
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        payload = execute(args)
        out_path = Path(args.output_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        print(f"output_json={out_path}")
    except Exception as err:  # pragma: no cover
        error_path = write_error_record(err, args)
        print(f"run_paper_portfolio failed: {err}")
        print(f"error_json={error_path}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
