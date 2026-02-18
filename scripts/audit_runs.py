import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RUNS_DIR = Path("results/runs")
AUDIT_DIR = Path("results/audit")

REQUIRED_TOP_KEYS = [
    "hypothesis_id",
    "timestamp_utc",
    "dataset",
    "baseline",
    "walkforward",
]

REQUIRED_DATASET_KEYS = [
    "timeframe",
    "start_ts",
    "end_ts",
    "bar_count",
    "db_path",
    "db_last_modified",
]

COST_MODES = ["gross", "bps8", "bps10"]


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def add_failure(failures: list[dict[str, Any]], artifact: str, reason: str, detail: str) -> None:
    failures.append({"artifact": artifact, "reason": reason, "detail": detail})


def is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def validate_artifact(path: Path) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    artifact = path.name

    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as err:
        add_failure(failures, artifact, "json_parse", str(err))
        return failures

    for k in REQUIRED_TOP_KEYS:
        if k not in obj:
            add_failure(failures, artifact, "missing_top_key", k)

    dataset = obj.get("dataset", {})
    if not isinstance(dataset, dict):
        add_failure(failures, artifact, "dataset_type", "dataset must be object")
        dataset = {}

    has_symbols = (
        isinstance(dataset.get("primary_symbols"), list)
        or isinstance(dataset.get("symbols"), list)
    )
    if not has_symbols:
        add_failure(
            failures,
            artifact,
            "missing_dataset_symbols",
            "dataset.primary_symbols (or dataset.symbols) is required",
        )

    for k in REQUIRED_DATASET_KEYS:
        if k not in dataset:
            add_failure(failures, artifact, "missing_dataset_key", k)

    if "bar_count" in dataset and not is_number(dataset.get("bar_count")):
        add_failure(failures, artifact, "dataset_bar_count_type", "bar_count must be numeric")

    baseline = obj.get("baseline", {})
    if not isinstance(baseline, dict):
        add_failure(failures, artifact, "baseline_type", "baseline must be object")
        baseline = {}

    wf = obj.get("walkforward", {})
    if not isinstance(wf, dict):
        add_failure(failures, artifact, "walkforward_type", "walkforward must be object")
        wf = {}

    split = wf.get("split", {})
    if not isinstance(split, dict):
        add_failure(failures, artifact, "walkforward_split_type", "walkforward.split must be object")
        split = {}
    else:
        expected = {"train_days": 60, "test_days": 15, "step_days": 15}
        for k, v in expected.items():
            if split.get(k) != v:
                add_failure(
                    failures,
                    artifact,
                    "walkforward_split_mismatch",
                    f"{k} expected {v}, got {split.get(k)}",
                )

    wf_modes = wf.get("modes", {})
    if not isinstance(wf_modes, dict):
        add_failure(failures, artifact, "walkforward_modes_type", "walkforward.modes must be object")
        wf_modes = {}

    for mode in COST_MODES:
        b = baseline.get(mode)
        if not isinstance(b, dict):
            add_failure(failures, artifact, "missing_baseline_mode", mode)
        else:
            for k in ["n", "mean", "ci_low", "ci_high", "p_mean_gt_0"]:
                if k not in b:
                    add_failure(failures, artifact, "missing_baseline_metric", f"{mode}.{k}")

        w = wf_modes.get(mode)
        if not isinstance(w, dict):
            add_failure(failures, artifact, "missing_wf_mode", mode)
            continue

        agg = w.get("aggregate")
        if not isinstance(agg, dict):
            add_failure(failures, artifact, "missing_wf_aggregate", mode)
        else:
            for k in ["n", "mean", "mean_ci_low", "mean_ci_high", "p_mean_gt_0"]:
                if k not in agg:
                    add_failure(failures, artifact, "missing_wf_aggregate_metric", f"{mode}.{k}")

        pos = w.get("positive_folds")
        if not isinstance(pos, dict):
            add_failure(failures, artifact, "missing_positive_folds", mode)
        else:
            for k in ["count", "pct", "total"]:
                if k not in pos:
                    add_failure(failures, artifact, "missing_positive_folds_metric", f"{mode}.{k}")

        folds = w.get("folds")
        if not isinstance(folds, list):
            add_failure(failures, artifact, "missing_folds_list", mode)

    return failures


def main() -> None:
    paths = sorted(RUNS_DIR.glob("*.json"))
    failures: list[dict[str, Any]] = []

    for p in paths:
        failures.extend(validate_artifact(p))

    report = {
        "timestamp_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "runs_dir": str(RUNS_DIR),
        "artifact_count": len(paths),
        "failure_count": len(failures),
        "ok": len(failures) == 0,
        "failures": failures,
    }

    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    out = AUDIT_DIR / f"audit_{utc_stamp()}.json"
    out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    print(f"audit_file={out}")
    print(f"artifact_count={len(paths)}")
    print(f"failure_count={len(failures)}")

    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
