import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from scripts import run_paper_portfolio as runner


def _events(rows):
    return pd.DataFrame(
        {
            "ts": [r[0] for r in rows],
            "dt": [pd.Timestamp(r[1], tz="UTC") for r in rows],
            "signal_dir": [r[2] for r in rows],
            "gross_r": [r[3] for r in rows],
        }
    )


def _row_portfolio(pid, fixed):
    return {
        "id": pid,
        "family": "portfolio_construction",
        "parameters": {"horizon_bars": 8, "fixed": fixed},
    }


class RunPaperPortfolioTests(unittest.TestCase):
    def test_parse_args_supports_required_and_optional_args(self):
        args = runner.parse_args(
            [
                "--hypothesis-ids",
                "H76,H77",
                "--days",
                "180",
                "--mode",
                "standalone",
                "--cost-mode",
                "bps8",
                "--output-json",
                "results/paper/test.json",
                "--dsn",
                "postgresql://u:p@localhost:5432/regime_crypto",
                "--timeframe",
                "5m",
                "--bootstrap-iters",
                "1000",
                "--seed",
                "7",
                "--max-gross-exposure",
                "0.9",
                "--max-asset-exposure",
                "0.8",
                "--max-strategy-weight",
                "0.3",
                "--cooldown-bars",
                "2",
                "--daily-loss-stop-pct",
                "0.05",
                "--report-csv-prefix",
                "results/paper/report",
            ]
        )

        self.assertEqual(args.hypothesis_ids, "H76,H77")
        self.assertEqual(args.days, 180)
        self.assertEqual(args.mode, "standalone")
        self.assertEqual(args.cost_mode, "bps8")
        self.assertTrue(args.output_json.endswith("test.json"))

    def test_load_portfolio_policy_and_member_resolution(self):
        row = _row_portfolio(
            "P01",
            {
                "candidate_universe": ["H76", "H77", "H79", "H81"],
                "include_members": ["H76", "H77", "H79", "H81"],
                "exclude_members": ["H81"],
                "dedup_keep": "H77",
                "dedup_drop": "H79",
                "weighting_mode": "equal_weight_active",
            },
        )
        policy = runner.load_portfolio_policy("P01", row)
        resolved = runner.resolve_policy_members(policy)
        self.assertEqual(resolved, ["H76", "H77"])

    def test_p02_rank_weight_behavior(self):
        p02 = _row_portfolio(
            "P02",
            {
                "candidate_universe": ["H76", "H77"],
                "rank_window_days": 30,
                "score_clip_floor": 0.0,
                "fallback_weighting": "equal_weight_active",
            },
        )

        hindex = {
            "P02": p02,
            "H76": {"id": "H76", "family": "cross_asset_regime", "parameters": {"horizon_bars": 8}},
            "H77": {"id": "H77", "family": "cross_asset_regime", "parameters": {"horizon_bars": 8}},
        }

        by_id = {
            "H76": runner.HypothesisRun(
                "H76",
                "cross_asset_regime",
                8,
                "BTC-USD",
                _events(
                    [
                        (1000, "2026-01-01T00:00:00Z", 1.0, 0.02),
                        (2000, "2026-01-01T00:05:00Z", 1.0, 0.01),
                        (3000, "2026-01-01T00:10:00Z", 1.0, 0.012),
                    ]
                ),
            ),
            "H77": runner.HypothesisRun(
                "H77",
                "cross_asset_regime",
                8,
                "BTC-USD",
                _events(
                    [
                        (1000, "2026-01-01T00:00:00Z", 1.0, -0.01),
                        (2000, "2026-01-01T00:05:00Z", 1.0, -0.02),
                        (3000, "2026-01-01T00:10:00Z", 1.0, -0.015),
                    ]
                ),
            ),
        }

        def _base(hypothesis_id, row, days, dsn):
            _ = row, days, dsn
            return by_id[hypothesis_id]

        with patch.object(runner, "build_base_hypothesis_run", side_effect=_base):
            prun = runner.build_portfolio_hypothesis_run("P02", p02, 180, "dsn", hindex)

        self.assertEqual(prun.hypothesis_id, "P02")
        self.assertTrue(len(prun.events) >= 1)
        wsum = prun.details["effective_strategy_weights_summary"]
        self.assertGreater(wsum["H76"]["mean_weight"], wsum["H77"]["mean_weight"])

    def test_p03_consensus_gate_blocks_weak_consensus(self):
        p03 = _row_portfolio(
            "P03",
            {
                "candidate_universe": ["H76", "H77", "H78"],
                "consensus_threshold": 0.67,
                "min_active_members": 3,
                "weighting_mode": "equal_weight",
            },
        )
        hindex = {
            "P03": p03,
            "H76": {"id": "H76", "family": "cross_asset_regime", "parameters": {"horizon_bars": 8}},
            "H77": {"id": "H77", "family": "cross_asset_regime", "parameters": {"horizon_bars": 8}},
            "H78": {"id": "H78", "family": "cross_asset_regime", "parameters": {"horizon_bars": 8}},
        }
        by_id = {
            "H76": runner.HypothesisRun("H76", "cross_asset_regime", 8, "BTC-USD", _events([(1, "2026-01-01T00:00:00Z", 1.0, 0.01)])),
            "H77": runner.HypothesisRun("H77", "cross_asset_regime", 8, "BTC-USD", _events([(1, "2026-01-01T00:00:00Z", -1.0, -0.01)])),
            "H78": runner.HypothesisRun("H78", "cross_asset_regime", 8, "BTC-USD", _events([(1, "2026-01-01T00:00:00Z", 1.0, 0.01)])),
        }

        with patch.object(runner, "build_base_hypothesis_run", side_effect=lambda hypothesis_id, row, days, dsn: by_id[hypothesis_id]):
            prun = runner.build_portfolio_hypothesis_run("P03", p03, 180, "dsn", hindex)

        self.assertEqual(len(prun.events), 0)

    def test_p04_session_blend_uses_specialist(self):
        p04 = _row_portfolio(
            "P04",
            {
                "candidate_universe": ["H76", "H77", "H79", "H78", "H81", "H82"],
                "core_set": ["H76", "H77", "H79", "H78"],
                "session_map": {"08:00-16:00": "H81", "16:00-24:00": "H82"},
                "core_weight_share": 0.6,
                "specialist_weight_share": 0.4,
                "fallback_mode": "core_only_equal_weight",
            },
        )

        hindex = {"P04": p04}
        for hid in ["H76", "H77", "H79", "H78", "H81", "H82"]:
            hindex[hid] = {"id": hid, "family": "cross_asset_regime", "parameters": {"horizon_bars": 8}}

        ts_in_window = pd.Timestamp("2026-01-01T09:00:00Z").timestamp()
        rows = [(int(ts_in_window), "2026-01-01T09:00:00Z", 1.0, 0.01)]
        by_id = {hid: runner.HypothesisRun(hid, "cross_asset_regime", 8, "BTC-USD", _events(rows)) for hid in ["H76", "H77", "H79", "H78", "H81"]}
        by_id["H82"] = runner.HypothesisRun("H82", "cross_asset_regime", 8, "BTC-USD", _events([]))

        with patch.object(runner, "build_base_hypothesis_run", side_effect=lambda hypothesis_id, row, days, dsn: by_id[hypothesis_id]):
            prun = runner.build_portfolio_hypothesis_run("P04", p04, 180, "dsn", hindex)

        self.assertEqual(len(prun.events), 1)
        wsum = prun.details["effective_strategy_weights_summary"]
        self.assertGreater(wsum["H81"]["mean_weight"], 0.0)

    def test_execute_deterministic_for_fixed_seed(self):
        runs = [
            runner.HypothesisRun(
                hypothesis_id="P01",
                family="portfolio_construction",
                horizon_bars=8,
                asset="BTC-USD",
                events=_events([(1, "2026-01-01T00:00:00Z", 1.0, 0.01)]),
                details={
                    "policy_config_snapshot": {"policy_id": "P01"},
                    "effective_strategy_weights_summary": {"H76": {"mean_weight": 1.0, "mean_abs_weight": 1.0, "observations": 1}},
                    "active_strategy_count_distribution": {"1": 1},
                    "family_contribution_summary": {"cross_asset_regime": 0.01},
                },
            )
        ]

        with patch.object(runner, "resolve_dsn", return_value="postgresql://dsn"), patch.object(
            runner, "collect_hypothesis_runs", return_value=runs
        ), patch.object(
            runner,
            "build_dataset_fingerprint",
            return_value={
                "start_ts": "2026-01-01T00:00:00+00:00",
                "end_ts": "2026-01-01T00:05:00+00:00",
                "bar_count": 2,
                "db_path": {"BTC-USD": "postgres:rc.candles", "ETH-USD": "postgres:rc.candles"},
                "db_last_modified": {
                    "BTC-USD": "2026-01-01T00:05:00+00:00",
                    "ETH-USD": "2026-01-01T00:05:00+00:00",
                },
            },
        ), patch.object(runner, "utc_now_iso", return_value="2026-02-19T00:00:00+00:00"):
            p1 = runner.execute(
                runner.parse_args(
                    [
                        "--hypothesis-ids",
                        "P01",
                        "--days",
                        "180",
                        "--mode",
                        "standalone",
                        "--cost-mode",
                        "bps8",
                        "--output-json",
                        "results/paper/out1.json",
                        "--seed",
                        "42",
                    ]
                )
            )
            p2 = runner.execute(
                runner.parse_args(
                    [
                        "--hypothesis-ids",
                        "P01",
                        "--days",
                        "180",
                        "--mode",
                        "standalone",
                        "--cost-mode",
                        "bps8",
                        "--output-json",
                        "results/paper/out2.json",
                        "--seed",
                        "42",
                    ]
                )
            )
        self.assertEqual(p1, p2)

    def test_failure_writes_error_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            os.chdir(tmp)
            try:
                out = Path(tmp) / "results" / "paper" / "artifact.json"

                def _boom(**_kwargs):
                    raise RuntimeError("boom")

                with patch.object(runner, "resolve_dsn", return_value="postgresql://dsn"), patch.object(
                    runner, "collect_hypothesis_runs", side_effect=_boom
                ):
                    with self.assertRaises(SystemExit) as ctx:
                        runner.main(
                            [
                                "--hypothesis-ids",
                                "H76",
                                "--days",
                                "180",
                                "--mode",
                                "standalone",
                                "--cost-mode",
                                "gross",
                                "--output-json",
                                str(out),
                            ]
                        )
                self.assertEqual(ctx.exception.code, 1)

                errors = sorted((Path(tmp) / "results" / "errors").glob("*_paper_portfolio.json"))
                self.assertTrue(errors, "expected failure artifact in results/errors")
                payload = json.loads(errors[-1].read_text(encoding="utf-8"))
                self.assertEqual(payload["error"], "boom")
                self.assertEqual(payload["context"]["mode"], "standalone")
            finally:
                os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()
