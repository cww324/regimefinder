import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.research_family_runner import SUPPORTED_FAMILIES, build_signal
from scripts.run_hypothesis_batch import mode_cmd


class FamilyDispatchSupportTests(unittest.TestCase):
    def _frame(self, n: int = 40) -> pd.DataFrame:
        dt = pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC")
        x = pd.DataFrame({"dt": dt})
        x["atr14_pct"] = np.linspace(0.1, 0.95, n)
        x["rv48_pct"] = np.linspace(0.1, 0.95, n)
        x["atr14"] = np.linspace(1.0, 2.0, n)
        x["dist_to_vwap48"] = np.where(np.arange(n) % 2 == 0, 1.0, -1.0)
        x["dist_to_vwap48_z"] = np.linspace(0.2, 1.6, n)
        x["atr_rv_ratio_pct_btc"] = np.linspace(0.2, 0.8, n)
        x["abs_vwap_dist_pct"] = np.linspace(0.2, 0.9, n)
        x["er20"] = np.linspace(0.1, 0.8, n)

        x["delta_er"] = np.linspace(-1.0, 1.0, n)
        x["abs_delta_er_pct"] = np.linspace(0.1, 0.95, n)
        x["dist_to_vwap48_z_btc"] = np.linspace(0.2, 1.8, n)
        x["dist_to_vwap48_z_eth"] = np.linspace(0.3, 1.8, n)
        x["rv48_pct_btc"] = np.linspace(0.1, 0.95, n)
        x["atr14_pct_eth"] = np.linspace(0.2, 0.95, n)
        x["atr14_pct_btc"] = np.linspace(0.1, 0.7, n)
        x["dist_to_vwap48_eth"] = np.where(np.arange(n) % 3 == 0, 1.0, -1.0)
        x["dist_to_vwap48_btc"] = np.where(np.arange(n) % 3 == 0, -1.0, 1.0)
        x["er20_btc"] = np.linspace(0.1, 0.6, n)
        x["er20_eth"] = np.linspace(0.1, 0.6, n)[::-1]
        return x

    def test_supported_families_contains_new_entries(self):
        self.assertIn("volatility_state", SUPPORTED_FAMILIES)
        self.assertIn("efficiency_mean_reversion", SUPPORTED_FAMILIES)
        self.assertIn("cross_asset_divergence", SUPPORTED_FAMILIES)

    def test_build_signal_accepts_new_family_routes(self):
        x = self._frame()
        routes = [
            ("H101", "volatility_state"),
            ("H102", "volatility_state"),
            ("H103", "volatility_state"),
            ("H104", "volatility_state"),
            ("H105", "efficiency_mean_reversion"),
            ("H106", "efficiency_mean_reversion"),
            ("H107", "efficiency_mean_reversion"),
            ("H108", "cross_asset_divergence"),
            ("H109", "cross_asset_divergence"),
            ("H110", "cross_asset_divergence"),
        ]
        for hyp_id, family in routes:
            s = build_signal(x, hypothesis_id=hyp_id, family=family)
            self.assertEqual(len(s), len(x), msg=f"len mismatch for {hyp_id}/{family}")
            self.assertTrue(np.isfinite(np.asarray(s, dtype=float)).all(), msg=f"non-finite for {hyp_id}/{family}")

    def test_batch_mode_cmd_uses_generic_runner_for_new_families(self):
        cmd = mode_cmd(
            hypothesis_id="H101",
            family="volatility_state",
            mode="gross",
            days=180,
            timeframe="5m",
            horizon=8,
            train_days=60,
            test_days=15,
            step_days=15,
            bootstrap_iters=3000,
            out_path=Path("results/archive/tmp.json"),
            dsn="postgresql://dsn",
        )
        self.assertIn("scripts/research_family_runner.py", cmd)
        self.assertIn("--family", cmd)
        i = cmd.index("--family")
        self.assertEqual(cmd[i + 1], "volatility_state")


if __name__ == "__main__":
    unittest.main()
