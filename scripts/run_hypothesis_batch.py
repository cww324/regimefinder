import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml
try:
    import psycopg
except Exception:  # pragma: no cover
    psycopg = None


ONE_GB = 1024 * 1024 * 1024
QUEUE_PATH = Path("queue.yaml")
HYPOTHESES_PATH = Path("hypotheses.yaml")
RUNS_DIR = Path("results/runs")
ERRORS_DIR = Path("results/errors")
ARCHIVE_DIR = Path("results/archive")
ENV_PATH = Path(".env")


@dataclass
class RunOutput:
    hypothesis_id: str
    artifact_path: Path


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().replace(microsecond=0).isoformat()


def utc_stamp() -> str:
    return utc_now().strftime("%Y%m%dT%H%M%SZ")


def ensure_disk_ok() -> None:
    free = shutil.disk_usage(".").free
    if free < ONE_GB:
        raise RuntimeError(f"Disk free below 1GB (free_bytes={free})")


def load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"YAML root must be mapping: {path}")
    return payload


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Queue-driven hypothesis batch runner.")
    p.add_argument("--dsn", type=str, default="", help="Optional Postgres DSN. Overrides RC_DB_DSN env/.env.")
    p.add_argument(
        "--hypothesis-ids",
        type=str,
        default="",
        help="Optional comma-separated IDs for a targeted run (bypasses queue progression).",
    )
    return p.parse_args()


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


def resolve_rc_dsn(cli_dsn: str) -> str:
    if cli_dsn.strip():
        return cli_dsn.strip()
    env_dsn = os.getenv("RC_DB_DSN", "").strip()
    if env_dsn:
        return env_dsn
    return load_env_value(ENV_PATH, "RC_DB_DSN")


def atomic_write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    txt = yaml.safe_dump(payload, sort_keys=False)
    tmp.write_text(txt, encoding="utf-8")
    os.replace(tmp, path)


def load_queue(path: Path) -> dict[str, Any]:
    q = load_yaml(path)
    batch_size = int(q.get("batch_size", 5))
    next_index = int(q.get("next_index", 0))
    paused = bool(q.get("paused", False))
    queue = q.get("queue", [])
    notes = q.get("notes", "")
    if not isinstance(queue, list):
        raise ValueError("queue.yaml: queue must be a list")
    return {
        "batch_size": batch_size,
        "next_index": next_index,
        "paused": paused,
        "queue": [str(x) for x in queue],
        "notes": str(notes),
    }


def load_hypotheses(path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    doc = load_yaml(path)
    dataset_defaults = dict(doc.get("dataset_defaults", {}))
    gates = dict(doc.get("gates", {}))
    hyp_list = doc.get("hypotheses", [])
    if not isinstance(hyp_list, list):
        raise ValueError("hypotheses.yaml: hypotheses must be a list")
    index: dict[str, dict[str, Any]] = {}
    for row in hyp_list:
        if isinstance(row, dict) and row.get("id"):
            index[str(row["id"])] = row
    return dataset_defaults, gates, index


def symbol_to_db(symbol: str) -> Path:
    if symbol == "BTC-USD":
        return Path("data/market.sqlite")
    if symbol == "ETH-USD":
        return Path("data/market_eth.sqlite")
    raise ValueError(f"No DB mapping for symbol: {symbol}")


def ts_to_iso(ts: int | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).replace(microsecond=0).isoformat()


def db_last_modified_iso(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).replace(microsecond=0).isoformat()


def read_db_window(db_path: Path, cutoff_ts: int) -> dict[str, Any]:
    if not db_path.exists():
        raise FileNotFoundError(f"Missing DB: {db_path}")
    con = sqlite3.connect(str(db_path))
    try:
        cur = con.execute(
            "SELECT MIN(ts), MAX(ts), COUNT(*) FROM candles_5m WHERE ts >= ?",
            (int(cutoff_ts),),
        )
        row = cur.fetchone()
    finally:
        con.close()
    min_ts = int(row[0]) if row and row[0] is not None else None
    max_ts = int(row[1]) if row and row[1] is not None else None
    count = int(row[2]) if row and row[2] is not None else 0
    return {
        "start_ts": ts_to_iso(min_ts),
        "end_ts": ts_to_iso(max_ts),
        "bar_count": count,
        "db_path": str(db_path),
        "db_last_modified": db_last_modified_iso(db_path),
        "_min_ts": min_ts,
        "_max_ts": max_ts,
    }


def sqlite_has_candles(db_path: Path, cutoff_ts: int) -> bool:
    if not db_path.exists():
        return False
    con = sqlite3.connect(str(db_path))
    try:
        table_exists = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='candles_5m' LIMIT 1"
        ).fetchone()
        if not table_exists:
            return False
        row = con.execute("SELECT COUNT(*) FROM candles_5m WHERE ts >= ?", (int(cutoff_ts),)).fetchone()
        return bool(row and int(row[0]) > 0)
    finally:
        con.close()


def validate_data_source(dsn: str, dataset_defaults: dict[str, Any], lookback_days: int) -> None:
    primary = list(dataset_defaults.get("primary_symbols", ["BTC-USD"]))
    secondary = list(dataset_defaults.get("secondary_symbols", ["ETH-USD"]))
    timeframe = str(dataset_defaults.get("timeframe", "5m"))
    symbols = primary + [s for s in secondary if s not in primary]
    cutoff_ts = int(utc_now().timestamp()) - (int(lookback_days) * 86400)
    if dsn:
        if psycopg is None:
            raise RuntimeError("Postgres DSN provided but psycopg is unavailable.")
        cutoff_dt = datetime.fromtimestamp(cutoff_ts, tz=timezone.utc)
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                for symbol in symbols:
                    cur.execute(
                        """
                        SELECT COUNT(*)
                        FROM rc.candles c
                        JOIN rc.symbols s ON s.symbol_id = c.symbol_id
                        JOIN rc.venues v ON v.venue_id = s.venue_id
                        JOIN rc.timeframes tf ON tf.timeframe_id = c.timeframe_id
                        WHERE v.venue_code = 'coinbase'
                          AND s.symbol_code = %s
                          AND tf.timeframe_code = %s
                          AND c.ts >= %s
                        """,
                        (symbol, timeframe, cutoff_dt),
                    )
                    row = cur.fetchone()
                    count = int(row[0]) if row and row[0] is not None else 0
                    if count <= 0:
                        raise RuntimeError(
                            f"Postgres source configured but no rc.candles rows for {symbol} timeframe={timeframe} "
                            f"in lookback_days={lookback_days}."
                        )
        return

    bad: list[str] = []
    for symbol in symbols:
        db = symbol_to_db(symbol)
        if not sqlite_has_candles(db, cutoff_ts=cutoff_ts):
            bad.append(f"{symbol}:{db}")
    if bad:
        raise RuntimeError(
            "No valid data source: RC_DB_DSN/--dsn is not set and legacy SQLite candles_5m is unavailable for "
            + ", ".join(bad)
        )


def build_dataset_fingerprint(dataset_defaults: dict[str, Any], lookback_days: int, horizon_bars: int) -> dict[str, Any]:
    primary = list(dataset_defaults.get("primary_symbols", ["BTC-USD"]))
    secondary = list(dataset_defaults.get("secondary_symbols", ["ETH-USD"]))
    timeframe = str(dataset_defaults.get("timeframe", "5m"))
    symbols = primary + [s for s in secondary if s not in primary]

    cutoff = int(utc_now().timestamp()) - (int(lookback_days) * 86400)
    source_windows: dict[str, dict[str, Any]] = {}

    starts: list[int] = []
    ends: list[int] = []
    counts: list[int] = []
    db_paths: dict[str, str] = {}
    db_last_mod: dict[str, str] = {}

    for symbol in symbols:
        db = symbol_to_db(symbol)
        w = read_db_window(db, cutoff_ts=cutoff)
        source_windows[symbol] = {
            "start_ts": w["start_ts"],
            "end_ts": w["end_ts"],
            "bar_count": w["bar_count"],
        }
        db_paths[symbol] = w["db_path"]
        db_last_mod[symbol] = w["db_last_modified"]
        if w["_min_ts"] is not None:
            starts.append(int(w["_min_ts"]))
        if w["_max_ts"] is not None:
            ends.append(int(w["_max_ts"]))
        counts.append(int(w["bar_count"]))

    start_ts = ts_to_iso(max(starts)) if starts else None
    end_ts = ts_to_iso(min(ends)) if ends else None
    bar_count = min(counts) if counts else 0

    return {
        "primary_symbols": primary,
        "secondary_symbols": secondary,
        "timeframe": timeframe,
        "lookback_days": int(lookback_days),
        "horizon_bars": int(horizon_bars),
        "start_ts": start_ts,
        "end_ts": end_ts,
        "bar_count": int(bar_count),
        "db_path": db_paths,
        "db_last_modified": db_last_mod,
        "source_windows": source_windows,
    }


def build_dataset_fingerprint_pg(
    dsn: str,
    dataset_defaults: dict[str, Any],
    lookback_days: int,
    horizon_bars: int,
) -> dict[str, Any]:
    if psycopg is None:
        raise RuntimeError("psycopg is required for Postgres dataset fingerprinting")
    primary = list(dataset_defaults.get("primary_symbols", ["BTC-USD"]))
    secondary = list(dataset_defaults.get("secondary_symbols", ["ETH-USD"]))
    timeframe = str(dataset_defaults.get("timeframe", "5m"))
    symbols = primary + [s for s in secondary if s not in primary]
    cutoff = datetime.now(timezone.utc) - timedelta(days=int(lookback_days))

    source_windows: dict[str, dict[str, Any]] = {}
    starts: list[datetime] = []
    ends: list[datetime] = []
    counts: list[int] = []
    db_paths: dict[str, str] = {}
    db_last_mod: dict[str, str] = {}

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            for symbol in symbols:
                cur.execute(
                    """
                    SELECT MIN(c.ts), MAX(c.ts), COUNT(*)
                    FROM rc.candles c
                    JOIN rc.symbols s ON s.symbol_id = c.symbol_id
                    JOIN rc.venues v ON v.venue_id = s.venue_id
                    JOIN rc.timeframes tf ON tf.timeframe_id = c.timeframe_id
                    WHERE v.venue_code = 'coinbase'
                      AND s.symbol_code = %s
                      AND tf.timeframe_code = %s
                      AND c.ts >= %s
                    """,
                    (symbol, timeframe, cutoff),
                )
                row = cur.fetchone()
                min_ts, max_ts, count = row if row else (None, None, 0)
                source_windows[symbol] = {
                    "start_ts": min_ts.replace(microsecond=0).isoformat() if min_ts else None,
                    "end_ts": max_ts.replace(microsecond=0).isoformat() if max_ts else None,
                    "bar_count": int(count or 0),
                }
                if min_ts:
                    starts.append(min_ts)
                if max_ts:
                    ends.append(max_ts)
                counts.append(int(count or 0))
                db_paths[symbol] = "postgres:rc.candles"
                db_last_mod[symbol] = utc_now_iso()

    start_ts = max(starts).replace(microsecond=0).isoformat() if starts else None
    end_ts = min(ends).replace(microsecond=0).isoformat() if ends else None
    bar_count = min(counts) if counts else 0

    return {
        "primary_symbols": primary,
        "secondary_symbols": secondary,
        "timeframe": timeframe,
        "lookback_days": int(lookback_days),
        "horizon_bars": int(horizon_bars),
        "start_ts": start_ts,
        "end_ts": end_ts,
        "bar_count": int(bar_count),
        "db_path": db_paths,
        "db_last_modified": db_last_mod,
        "source_windows": source_windows,
    }


def unique_run_artifact_path(hypothesis_id: str) -> Path:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    base = RUNS_DIR / f"{utc_stamp()}_{hypothesis_id}.json"
    if not base.exists():
        return base
    i = 1
    while True:
        p = RUNS_DIR / f"{utc_stamp()}_{hypothesis_id}_{i}.json"
        if not p.exists():
            return p
        i += 1


def write_error_record(hypothesis_id: str, err: Exception, context: dict[str, Any]) -> Path:
    ERRORS_DIR.mkdir(parents=True, exist_ok=True)
    out = ERRORS_DIR / f"{utc_stamp()}_{hypothesis_id}.json"
    payload = {
        "timestamp_utc": utc_now_iso(),
        "hypothesis_id": hypothesis_id,
        "error": str(err),
        "traceback": traceback.format_exc(),
        "context": context,
    }
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return out


def run_command(cmd: list[str]) -> tuple[int, str, str]:
    cp = subprocess.run(cmd, text=True, capture_output=True, check=False)
    return cp.returncode, cp.stdout, cp.stderr


def mode_cmd(
    hypothesis_id: str,
    family: str,
    mode: str,
    days: int,
    timeframe: str,
    horizon: int,
    train_days: int,
    test_days: int,
    step_days: int,
    bootstrap_iters: int,
    out_path: Path,
    dsn: str = "",
) -> list[str]:
    if hypothesis_id == "H32":
        cmd = [
            "PYTHONPATH=.",
            ".venv/bin/python",
            "scripts/research_h32_runner.py",
            "--days",
            str(days),
            "--timeframe",
            timeframe,
            "--horizon",
            str(horizon),
            "--cost-mode",
            mode,
            "--wf",
            str(train_days),
            str(test_days),
            str(step_days),
            "--bootstrap-iters",
            str(bootstrap_iters),
            "--output-json",
            str(out_path),
        ]
        if dsn:
            cmd.extend(["--dsn", dsn])
        return cmd
    if hypothesis_id == "H33":
        cmd = [
            "PYTHONPATH=.",
            ".venv/bin/python",
            "scripts/research_h33_runner.py",
            "--days",
            str(days),
            "--timeframe",
            timeframe,
            "--horizon",
            str(horizon),
            "--cost-mode",
            mode,
            "--wf",
            str(train_days),
            str(test_days),
            str(step_days),
            "--bootstrap-iters",
            str(bootstrap_iters),
            "--output-json",
            str(out_path),
        ]
        if dsn:
            cmd.extend(["--dsn", dsn])
        return cmd
    cmd = [
        "PYTHONPATH=.",
        ".venv/bin/python",
        "scripts/research_family_runner.py",
        "--hypothesis-id",
        hypothesis_id,
        "--family",
        family,
        "--days",
        str(days),
        "--timeframe",
        timeframe,
        "--horizon",
        str(horizon),
        "--cost-mode",
        mode,
        "--wf",
        str(train_days),
        str(test_days),
        str(step_days),
        "--bootstrap-iters",
        str(bootstrap_iters),
        "--output-json",
        str(out_path),
    ]
    if dsn:
        cmd.extend(["--dsn", dsn])
    return cmd


def flatten_cmd(cmd: list[str]) -> list[str]:
    if cmd[0] == "PYTHONPATH=.":
        env = os.environ.copy()
        env["PYTHONPATH"] = "."
        real = cmd[1:]
        return ["ENV", json.dumps({"PYTHONPATH": "."}), *real]
    return cmd


def execute_python_cmd(cmd: list[str]) -> tuple[int, str, str]:
    env = os.environ.copy()
    real_cmd = cmd
    if cmd and cmd[0] == "PYTHONPATH=.":
        env["PYTHONPATH"] = "."
        real_cmd = cmd[1:]
    cp = subprocess.run(real_cmd, text=True, capture_output=True, check=False, env=env)
    return cp.returncode, cp.stdout, cp.stderr


def classify_mode(baseline: dict[str, Any], wf_mode: dict[str, Any]) -> tuple[str, str, str]:
    n = int(baseline.get("n", 0) or 0)
    agg = wf_mode.get("aggregate", {})
    folds = wf_mode.get("positive_folds", {})
    fold_count = int(folds.get("total", 0) or 0)
    positive_fold_pct = float(folds.get("pct", 0.0) or 0.0)

    b_mean = baseline.get("mean")
    b_ci_low = baseline.get("ci_low")
    wf_mean = agg.get("mean")
    wf_ci_low = agg.get("mean_ci_low")

    if n < 50 or fold_count < 5:
        return "INCONCLUSIVE", "INCONCLUSIVE", "INCONCLUSIVE"

    baseline_ok = (b_mean is not None and float(b_mean) > 0) and (b_ci_low is not None and float(b_ci_low) > 0)

    if wf_mean is None:
        return ("PASS" if baseline_ok else "FAIL"), "INCONCLUSIVE", "INCONCLUSIVE"

    wf_mean_v = float(wf_mean)
    wf_ci_low_v = float(wf_ci_low) if wf_ci_low is not None else None

    if wf_mean_v <= 0 or positive_fold_pct < 50.0:
        wf_status = "FAIL"
    elif wf_ci_low_v is not None and wf_ci_low_v > 0 and positive_fold_pct >= 60.0 and fold_count >= 7:
        wf_status = "PASS"
    else:
        wf_status = "BORDERLINE"

    baseline_status = "PASS" if baseline_ok else ("BORDERLINE" if (b_mean is not None and float(b_mean) > 0) else "FAIL")

    if baseline_status == "FAIL" or wf_status == "FAIL":
        final_status = "FAIL"
    elif baseline_status == "PASS" and wf_status == "PASS":
        final_status = "PASS"
    else:
        final_status = "BORDERLINE"

    return baseline_status, wf_status, final_status


def combine_status(statuses: list[str]) -> str:
    if any(s == "FAIL" for s in statuses):
        return "FAIL"
    if any(s == "INCONCLUSIVE" for s in statuses):
        return "INCONCLUSIVE"
    if any(s == "BORDERLINE" for s in statuses):
        return "BORDERLINE"
    return "PASS"


def run_one_hypothesis(
    hypothesis_id: str,
    hypothesis_def: dict[str, Any],
    dataset_defaults: dict[str, Any],
    gates: dict[str, Any],
    dsn: str = "",
) -> RunOutput:
    ensure_disk_ok()

    family = str(hypothesis_def.get("family", "")).strip()
    if family in {"", "frozen_legacy", "frozen_missing_definition"}:
        raise RuntimeError(f"Hypothesis {hypothesis_id} is not runnable (family={family}).")

    params = dict(hypothesis_def.get("parameters", {}))
    days = int(params.get("lookback_days", dataset_defaults.get("lookback_default_days", 180)))
    horizon = int(params.get("horizon_bars", dataset_defaults.get("horizon_default_bars", 6)))
    timeframe = str(dataset_defaults.get("timeframe", "5m"))
    validate_data_source(dsn=dsn, dataset_defaults=dataset_defaults, lookback_days=days)

    wf = dict(gates.get("walkforward", {}))
    train_days = int(wf.get("train_days", 60))
    test_days = int(wf.get("test_days", 15))
    step_days = int(wf.get("step_days", 15))

    bootstrap = dict(gates.get("bootstrap", {}))
    bootstrap_iters = int(bootstrap.get("iterations", 3000))

    mode_paths: dict[str, Path] = {}
    commands: list[str] = []
    modes = ["gross", "bps8", "bps10"]

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    for mode in modes:
        ensure_disk_ok()
        out_path = ARCHIVE_DIR / f"{hypothesis_id.lower()}_runner_{utc_stamp()}_{mode}.json"
        cmd = mode_cmd(
            hypothesis_id=hypothesis_id,
            family=family,
            mode=mode,
            days=days,
            timeframe=timeframe,
            horizon=horizon,
            train_days=train_days,
            test_days=test_days,
            step_days=step_days,
            bootstrap_iters=bootstrap_iters,
            out_path=out_path,
            dsn=dsn,
        )
        commands.append(" ".join(flatten_cmd(cmd)))
        rc, stdout, stderr = execute_python_cmd(cmd)
        if rc != 0:
            raise RuntimeError(
                f"Runner failed for {hypothesis_id} mode={mode} rc={rc} stdout={stdout[-600:]} stderr={stderr[-600:]}"
            )
        if not out_path.exists():
            raise RuntimeError(f"Runner did not produce JSON output: {out_path}")
        mode_paths[mode] = out_path

    baseline: dict[str, dict[str, Any]] = {}
    wf_modes: dict[str, dict[str, Any]] = {}
    mode_status: dict[str, dict[str, str]] = {}
    split_ref = {"train_days": train_days, "test_days": test_days, "step_days": step_days}

    for mode in modes:
        payload = json.loads(mode_paths[mode].read_text(encoding="utf-8"))
        b = payload.get("baseline", {}).get(mode, {})
        w = payload.get("wf", {})
        d = payload.get("diagnostics", {})
        split_ref = w.get("split", split_ref)

        baseline[mode] = {
            "n": b.get("n"),
            "win_rate": b.get("win_rate"),
            "mean": b.get("mean"),
            "std": b.get("std"),
            "ci_low": b.get("mean_ci_low"),
            "ci_high": b.get("mean_ci_high"),
            "p_mean_gt_0": b.get("p_mean_gt_0"),
        }
        wf_modes[mode] = {
            "folds": w.get("folds", []),
            "aggregate": w.get("aggregate", {}),
            "positive_folds": w.get("positive_folds", {}),
            "diagnostics": d,
        }

        baseline_status, wf_status, final_status = classify_mode(baseline[mode], wf_modes[mode])
        mode_status[mode] = {
            "baseline_status": baseline_status,
            "wf_status": wf_status,
            "final_status": final_status,
        }

    if dsn:
        dataset = build_dataset_fingerprint_pg(
            dsn=dsn,
            dataset_defaults=dataset_defaults,
            lookback_days=days,
            horizon_bars=horizon,
        )
    else:
        dataset = build_dataset_fingerprint(
            dataset_defaults=dataset_defaults,
            lookback_days=days,
            horizon_bars=horizon,
        )

    final_status = combine_status([mode_status[m]["final_status"] for m in modes])

    artifact_payload = {
        "hypothesis_id": hypothesis_id,
        "logic_hash": hypothesis_def.get("logic_hash"),
        "timestamp_utc": utc_now_iso(),
        "commands": commands,
        "dataset": dataset,
        "baseline": baseline,
        "walkforward": {
            "split": split_ref,
            "modes": wf_modes,
        },
        "classification": final_status,
        "mode_classification": mode_status,
        "notes": "Append-only artifact generated by queue-driven batch runner.",
    }

    artifact_path = unique_run_artifact_path(hypothesis_id)
    artifact_path.write_text(json.dumps(artifact_payload, indent=2, sort_keys=True), encoding="utf-8")
    return RunOutput(hypothesis_id=hypothesis_id, artifact_path=artifact_path)


def main() -> None:
    args = parse_args()
    ensure_disk_ok()
    queue = load_queue(QUEUE_PATH)
    rc_dsn = resolve_rc_dsn(args.dsn)
    targeted_ids = [x.strip() for x in str(args.hypothesis_ids).split(",") if x.strip()]
    targeted_mode = len(targeted_ids) > 0

    if queue["paused"] and not targeted_mode:
        raise SystemExit("queue.yaml has paused: true; refusing to run batch.")

    dataset_defaults, gates, hyp_index = load_hypotheses(HYPOTHESES_PATH)

    batch_size = int(queue["batch_size"])
    next_index = int(queue["next_index"])
    queue_ids = list(queue["queue"])
    batch_ids = targeted_ids if targeted_mode else queue_ids[next_index : next_index + batch_size]

    if not batch_ids:
        print("No hypotheses remaining in queue slice; nothing to run.")
        return

    for hyp_id in batch_ids:
        if hyp_id not in hyp_index:
            err = RuntimeError(f"Hypothesis id not found in hypotheses.yaml: {hyp_id}")
            error_path = write_error_record(hyp_id, err, {"batch_ids": batch_ids, "next_index": next_index})
            print(f"Batch stopped: {hyp_id} failed. Error written to {error_path}")
            raise SystemExit(1)

    results: list[RunOutput] = []
    for hyp_id in batch_ids:
        ensure_disk_ok()
        try:
            result = run_one_hypothesis(
                hypothesis_id=hyp_id,
                hypothesis_def=hyp_index[hyp_id],
                dataset_defaults=dataset_defaults,
                gates=gates,
                dsn=rc_dsn,
            )
            results.append(result)
            print(f"{hyp_id} ok -> {result.artifact_path}")
        except Exception as err:  # pragma: no cover
            error_path = write_error_record(
                hyp_id,
                err,
                {
                    "batch_ids": batch_ids,
                    "next_index": next_index,
                    "completed": [r.hypothesis_id for r in results],
                    "targeted_mode": targeted_mode,
                },
            )
            print(f"Batch stopped: {hyp_id} failed. Error written to {error_path}")
            raise SystemExit(1)

    if targeted_mode:
        print(f"Targeted batch success: completed ids={batch_ids}. queue.yaml unchanged.")
        return

    queue["next_index"] = next_index + len(batch_ids)
    atomic_write_yaml(QUEUE_PATH, queue)
    print(f"Batch success: advanced next_index to {queue['next_index']}")


if __name__ == "__main__":
    main()
