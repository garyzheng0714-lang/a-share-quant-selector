import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import views.view_manager as view_manager
from utils.hierarchical_decision import _active_model_bundle, run_close_decision


def _candidate(weekly_passed: bool = True) -> dict:
    return {
        "code": "600000", "name": "浦发银行", "industry": "银行",
        "signals": ["原始B1"], "signal_labels": ["原始B1"],
        "close": 10.0, "J": 10.0, "RSI": 15.0,
        "weekly": {
            "passed": weekly_passed, "aligned": weekly_passed,
            "rising": weekly_passed, "rising_count": 4 if weekly_passed else 2,
            "directions": {}, "ma_values": {},
        },
    }


class HierarchicalDecisionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original = view_manager.DB_PATH
        view_manager.DB_PATH = Path(self.tmp.name) / "test.db"
        self.common = [
            patch("utils.hierarchical_decision.local_data_status", return_value={
                "fresh": True, "local_date": "2026-07-14", "expected_date": "2026-07-14",
            }),
            patch("utils.hierarchical_decision.next_trade_date", return_value="2026-07-15"),
            patch("utils.hierarchical_decision.strategy_version", return_value="s1"),
            patch("utils.hierarchical_decision.data_version", return_value="d1"),
        ]
        for item in self.common:
            item.start()

    def tearDown(self):
        for item in reversed(self.common):
            item.stop()
        view_manager.DB_PATH = self.original
        self.tmp.cleanup()

    @patch("utils.hierarchical_decision._active_model_bundle", return_value=({}, "baseline-only"))
    @patch("utils.hierarchical_decision._baseline_candidates")
    @patch("utils.hierarchical_decision.get_decision_config")
    def test_weekly_gate_is_recorded_in_shadow_mode(self, config, baseline, _models):
        config.return_value = {
            "enabled": True, "strict_unvalidated_gate": True,
            "preopen_event_check": True, "weekly_gate_mode": "shadow",
        }
        baseline.return_value = ("2026-07-14", [_candidate(False)])

        result = run_close_decision()

        self.assertEqual(result["candidates"][0]["action"], "observe")
        self.assertIn("weekly_four_ma_shadow_fail", result["candidates"][0]["reason_codes"])
        self.assertEqual(result["market"]["layer_modes"]["weekly_four_ma"], "shadow")

    @patch("utils.hierarchical_decision.get_active_policy_models")
    def test_no_released_atomic_policy_means_baseline_only(self, active_policy):
        active_policy.return_value = ({}, "baseline-only")

        models, version = _active_model_bundle()

        self.assertEqual(models, {})
        self.assertEqual(version, "baseline-only")

    @patch("utils.hierarchical_decision._predict")
    @patch("utils.hierarchical_decision._live_feature_rows")
    @patch("utils.hierarchical_decision._active_model_bundle")
    @patch("utils.hierarchical_decision._baseline_candidates")
    @patch("utils.hierarchical_decision.get_decision_config")
    def test_market_can_activate_without_sector_model(
        self, config, baseline, models, live_rows, predict,
    ):
        config.return_value = {
            "enabled": True, "strict_unvalidated_gate": True,
            "preopen_event_check": True, "weekly_gate_mode": "shadow",
        }
        baseline.return_value = ("2026-07-14", [_candidate(True)])
        models.return_value = ({"market": {"version": "market-v1"}}, "market@market-v1")
        live_rows.return_value = pd.DataFrame([{"code": "600000", "feature_missing": False}])
        predict.return_value = {
            "600000": {"market": 0.8, "market_threshold": 0.5},
        }

        result = run_close_decision()

        self.assertEqual(result["candidates"][0]["action"], "buy")
        self.assertNotIn("hierarchy_models_unvalidated", result["reason_codes"])


if __name__ == "__main__":
    unittest.main()
