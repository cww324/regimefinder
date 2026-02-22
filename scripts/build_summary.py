import json
from pathlib import Path
from typing import Any


RUNS_DIR = Path("results/runs")
SUMMARY_PATH = Path("results/summary.json")
COST_MODES = ["gross", "bps8", "bps10"]


def parse_artifact_ts(path: Path, payload: dict[str, Any]) -> str:
    stem = path.stem
    if "_" in stem:
        prefix = stem.split("_", 1)[0]
        if len(prefix) >= 16 and "T" in prefix:
            return prefix
    return str(payload.get("timestamp_utc", ""))


def classify_mode(baseline: dict[str, Any], wf_mode: dict[str, Any]) -> tuple[str, str, str, str]:
    n = int(baseline.get("n", 0) or 0)
    agg = wf_mode.get("aggregate", {})
    folds = wf_mode.get("positive_folds", {})
    fold_count = int(folds.get("total", 0) or 0)
    positive_fold_pct = float(folds.get("pct", 0.0) or 0.0)

    b_mean = baseline.get("mean")
    b_ci_low = baseline.get("ci_low")
    wf_mean = agg.get("mean")
    wf_ci_low = agg.get("mean_ci_low")

    if n < 50:
        return "INCONCLUSIVE", "INCONCLUSIVE", "INCONCLUSIVE", "baseline_n_lt_50"
    if fold_count < 5:
        return "INCONCLUSIVE", "INCONCLUSIVE", "INCONCLUSIVE", "fold_count_lt_5"

    baseline_status = "FAIL"
    if b_mean is not None and float(b_mean) > 0:
        baseline_status = "PASS" if (b_ci_low is not None and float(b_ci_low) > 0) else "BORDERLINE"

    if wf_mean is None:
        return baseline_status, "INCONCLUSIVE", "INCONCLUSIVE", "wf_aggregate_missing"

    wf_mean_v = float(wf_mean)
    wf_ci_low_v = float(wf_ci_low) if wf_ci_low is not None else None

    if wf_mean_v <= 0 or positive_fold_pct < 50.0:
        wf_status = "FAIL"
        reason = "non_positive_wf_or_fold_support_lt_50"
    elif wf_ci_low_v is not None and wf_ci_low_v > 0 and positive_fold_pct >= 60.0 and fold_count >= 7:
        wf_status = "PASS"
        reason = "wf_ci_above_zero_and_fold_support_ge_60_with_ge7_folds"
    else:
        wf_status = "BORDERLINE"
        reason = "positive_wf_with_weak_ci_or_fold_support"

    if baseline_status == "FAIL" or wf_status == "FAIL":
        final_status = "FAIL"
    elif baseline_status == "PASS" and wf_status == "PASS":
        final_status = "PASS"
    else:
        final_status = "BORDERLINE"

    return baseline_status, wf_status, final_status, reason


def combine_status(statuses: list[str]) -> str:
    if any(s == "FAIL" for s in statuses):
        return "FAIL"
    if any(s == "INCONCLUSIVE" for s in statuses):
        return "INCONCLUSIVE"
    if any(s == "BORDERLINE" for s in statuses):
        return "BORDERLINE"
    return "PASS"


def load_runs() -> dict[str, tuple[Path, dict[str, Any], str]]:
    latest: dict[str, tuple[Path, dict[str, Any], str]] = {}
    for path in sorted(RUNS_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        hyp_id = str(payload.get("hypothesis_id", "")).strip()
        if not hyp_id:
            continue
        ts = parse_artifact_ts(path, payload)
        old = latest.get(hyp_id)
        if old is None or ts >= old[2]:
            latest[hyp_id] = (path, payload, ts)
    return latest


def build_summary() -> dict[str, Any]:
    latest = load_runs()
    out: dict[str, Any] = {}

    for hyp_id in sorted(latest.keys()):
        path, payload, _ts = latest[hyp_id]
        dataset = payload.get("dataset", {})
        baseline = payload.get("baseline", {})
        walkforward = payload.get("walkforward", {})
        wf_modes = walkforward.get("modes", {}) if isinstance(walkforward, dict) else {}
        wf_split = walkforward.get("split", {}) if isinstance(walkforward, dict) else {}
        mode_classification = payload.get("mode_classification", {})

        mode_summary: dict[str, Any] = {}
        statuses: list[str] = []
        for mode in COST_MODES:
            b = baseline.get(mode, {}) if isinstance(baseline, dict) else {}
            w = wf_modes.get(mode, {}) if isinstance(wf_modes, dict) else {}
            mode_cls = mode_classification.get(mode, {}) if isinstance(mode_classification, dict) else {}
            d_baseline_status, d_wf_status, d_final_status, reason = classify_mode(b, w)
            baseline_status = str(mode_cls.get("baseline_status", d_baseline_status))
            wf_status = str(mode_cls.get("wf_status", d_wf_status))
            final_status = str(mode_cls.get("final_status", d_final_status))
            statuses.append(final_status)

            agg = w.get("aggregate", {}) if isinstance(w, dict) else {}
            pos = w.get("positive_folds", {}) if isinstance(w, dict) else {}

            mode_summary[mode] = {
                "baseline_status": baseline_status,
                "wf_status": wf_status,
                "final_status": final_status,
                "reason": reason,
                "metrics": {
                    "baseline": {
                        "n": b.get("n"),
                        "mean": b.get("mean"),
                        "ci_low": b.get("ci_low"),
                        "ci_high": b.get("ci_high"),
                        "p_mean_gt_0": b.get("p_mean_gt_0"),
                    },
                    "walkforward": {
                        "n": agg.get("n"),
                        "aggregate_mean": agg.get("mean"),
                        "ci_low": agg.get("mean_ci_low"),
                        "ci_high": agg.get("mean_ci_high"),
                        "p_mean_gt_0": agg.get("p_mean_gt_0"),
                        "positive_fold_pct": pos.get("pct"),
                        "positive_folds": pos.get("count"),
                        "fold_count": pos.get("total"),
                    },
                },
            }

        out[hyp_id] = {
            "hypothesis_id": hyp_id,
            "latest_artifact": path.name,
            "timestamp_utc": payload.get("timestamp_utc"),
            "dataset": {
                "primary_symbols": dataset.get("primary_symbols"),
                "secondary_symbols": dataset.get("secondary_symbols"),
                "timeframe": dataset.get("timeframe"),
                "start_ts": dataset.get("start_ts"),
                "end_ts": dataset.get("end_ts"),
                "bar_count": dataset.get("bar_count"),
                "db_path": dataset.get("db_path"),
                "db_last_modified": dataset.get("db_last_modified"),
            },
            "walkforward_split": {
                "train_days": wf_split.get("train_days"),
                "test_days": wf_split.get("test_days"),
                "step_days": wf_split.get("step_days"),
            },
            "cost_modes": mode_summary,
            "final_status": combine_status(statuses),
        }

    return out


def main() -> None:
    summary = build_summary()
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"summary_path={SUMMARY_PATH}")
    print(f"hypothesis_count={len(summary)}")


if __name__ == "__main__":
    main()
