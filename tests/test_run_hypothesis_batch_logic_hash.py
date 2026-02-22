import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import run_hypothesis_batch as batch


class RunHypothesisBatchLogicHashTests(unittest.TestCase):
    @staticmethod
    def _runner_payload(mode: str) -> dict:
        return {
            "baseline": {
                mode: {
                    "n": 120,
                    "win_rate": 0.6,
                    "mean": 0.001,
                    "std": 0.002,
                    "mean_ci_low": 0.0001,
                    "mean_ci_high": 0.002,
                    "p_mean_gt_0": 0.95,
                }
            },
            "wf": {
                "split": {"train_days": 60, "test_days": 15, "step_days": 15},
                "folds": [{"fold_id": 1, "n": 20, "mean": 0.001}],
                "aggregate": {
                    "n": 100,
                    "mean": 0.001,
                    "mean_ci_low": 0.0001,
                    "mean_ci_high": 0.002,
                    "p_mean_gt_0": 0.95,
                },
                "positive_folds": {"count": 6, "total": 7, "pct": 85.7142857},
            },
            "diagnostics": {},
        }

    def test_run_artifact_includes_logic_hash_for_all_families(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            os.chdir(tmp)
            try:
                out_dir = Path(tmp) / "results" / "runs"
                out_dir.mkdir(parents=True, exist_ok=True)

                def fake_exec(cmd):
                    out_path = Path(cmd[cmd.index("--output-json") + 1])
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    if "--all-modes" in cmd:
                        # Combined JSON produced by --all-modes path.
                        combined = {
                            "baseline": {
                                m: self._runner_payload(m)["baseline"][m]
                                for m in ["gross", "bps8", "bps10"]
                            },
                            "wf_by_mode": {
                                m: self._runner_payload(m)["wf"]
                                for m in ["gross", "bps8", "bps10"]
                            },
                            "diagnostics_by_mode": {
                                m: {} for m in ["gross", "bps8", "bps10"]
                            },
                        }
                        out_path.write_text(json.dumps(combined), encoding="utf-8")
                    else:
                        mode = cmd[cmd.index("--cost-mode") + 1]
                        out_path.write_text(json.dumps(self._runner_payload(mode)), encoding="utf-8")
                    return 0, "", ""

                dataset_defaults = {
                    "timeframe": "5m",
                    "lookback_default_days": 180,
                    "horizon_default_bars": 8,
                }
                gates = {
                    "walkforward": {"train_days": 60, "test_days": 15, "step_days": 15},
                    "bootstrap": {"iterations": 100},
                }

                cases = [
                    ("H39", "cross_asset_regime", "hash_cross_asset"),
                    ("H101", "volatility_state", "hash_vol_state"),
                    ("H105", "efficiency_mean_reversion", "hash_eff_mr"),
                    ("H108", "cross_asset_divergence", "hash_xad"),
                ]

                for hyp_id, family, logic_hash in cases:
                    artifact_path = out_dir / f"{hyp_id}.json"
                    hypothesis_def = {
                        "family": family,
                        "logic_hash": logic_hash,
                        "parameters": {"lookback_days": 180, "horizon_bars": 8},
                    }

                    with patch.object(batch, "ensure_disk_ok", return_value=None), patch.object(
                        batch, "validate_data_source", return_value=None
                    ), patch.object(batch, "execute_python_cmd", side_effect=fake_exec), patch.object(
                        batch,
                        "build_dataset_fingerprint",
                        return_value={
                            "start_ts": "2026-01-01T00:00:00+00:00",
                            "end_ts": "2026-01-02T00:00:00+00:00",
                            "bar_count": 100,
                            "db_path": {"BTC-USD": "postgres:rc.candles", "ETH-USD": "postgres:rc.candles"},
                            "db_last_modified": {
                                "BTC-USD": "2026-01-02T00:00:00+00:00",
                                "ETH-USD": "2026-01-02T00:00:00+00:00",
                            },
                        },
                    ), patch.object(batch, "unique_run_artifact_path", return_value=artifact_path):
                        batch.run_one_hypothesis(
                            hypothesis_id=hyp_id,
                            hypothesis_def=hypothesis_def,
                            dataset_defaults=dataset_defaults,
                            gates=gates,
                            dsn="",
                        )

                    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
                    self.assertIn("logic_hash", payload)
                    self.assertEqual(payload["logic_hash"], logic_hash)
            finally:
                os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()
