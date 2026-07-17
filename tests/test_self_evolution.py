import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import views.view_manager as view_manager
from utils.csv_manager import CSVManager
from utils.decision_ledger import outcome_summary, save_decision_run
from utils.self_evolution import run_daily_evolution, update_decision_outcomes


class SelfEvolutionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original = view_manager.DB_PATH
        view_manager.DB_PATH = Path(self.tmp.name) / "test.db"

    def tearDown(self):
        view_manager.DB_PATH = self.original
        self.tmp.cleanup()

    def test_observe_is_labeled_to_measure_missed_winners(self):
        manager = CSVManager(Path(self.tmp.name) / "data")
        manager.write_stock("600000", pd.DataFrame([
            {"date": "2026-01-05", "open": 10, "high": 10.2, "low": 9.8, "close": 10, "volume": 100},
            {"date": "2026-01-06", "open": 10, "high": 10.6, "low": 9.9, "close": 10.5, "volume": 100},
            {"date": "2026-01-07", "open": 10.5, "high": 10.8, "low": 10.3, "close": 10.7, "volume": 100},
            {"date": "2026-01-08", "open": 10.7, "high": 11.0, "low": 10.6, "close": 10.9, "volume": 100},
            {"date": "2026-01-09", "open": 10.9, "high": 11.2, "low": 10.8, "close": 11.1, "volume": 100},
            {"date": "2026-01-12", "open": 11.1, "high": 11.5, "low": 11.0, "close": 11.4, "volume": 100},
        ]))
        save_decision_run({
            "trade_date": "2026-01-05", "stage": "close",
            "as_of": "2026-01-05T15:00:00+08:00", "status": "degraded",
            "final_action": "observe", "strategy_version": "s1",
            "feature_version": "f1", "model_version": "m1", "data_version": "d1",
        }, [{"code": "600000", "action": "observe"}])

        result = update_decision_outcomes(manager)
        summary = outcome_summary()
        self.assertEqual(result["complete"], 1)
        self.assertEqual(summary["observe"]["count"], 1)
        self.assertEqual(summary["missed_winner_rate"], 1.0)

    def test_training_is_skipped_before_universe_coverage_gate(self):
        manager = CSVManager(Path(self.tmp.name) / "data")
        with ExitStack() as stack:
            stack.enter_context(patch("utils.self_evolution.local_data_status", return_value={
                "fresh": True, "local_date": "2026-07-14", "expected_date": "2026-07-14",
            }))
            stack.enter_context(patch("utils.self_evolution.Path.read_text", return_value='{"600000":"银行"}'))
            stack.enter_context(patch("utils.self_evolution._coverage", return_value={
                "universe_count": 100, "covered_count": 8, "coverage_ratio": 0.08,
            }))
            stack.enter_context(patch("utils.self_evolution.update_decision_outcomes", return_value={
                "updated": 0, "complete": 0, "pending": 0, "missing_data": 0,
            }))
            stack.enter_context(patch("utils.self_evolution.data_version", return_value="d1"))
            stack.enter_context(patch("utils.self_evolution.save_evolution_run", return_value="e1"))
            stack.enter_context(patch("utils.reference_snapshots.capture_reference_snapshot", return_value={
                "available": True, "as_of": "2026-07-14",
            }))
            build_dataset = stack.enter_context(patch("tools.hierarchical_walk_forward.build_dataset"))
            result = run_daily_evolution(manager)

        build_dataset.assert_not_called()
        self.assertEqual(result["metrics"]["training_status"], "skipped_data_gate")
        self.assertEqual(result["dataset_rows"], 0)

    def test_training_is_skipped_until_reference_history_is_long_enough(self):
        manager = CSVManager(Path(self.tmp.name) / "data")
        with ExitStack() as stack:
            stack.enter_context(patch("utils.self_evolution.local_data_status", return_value={
                "fresh": True, "local_date": "2026-07-14", "expected_date": "2026-07-14",
            }))
            stack.enter_context(patch(
                "utils.self_evolution.Path.read_text", return_value='{"600000":"银行"}',
            ))
            stack.enter_context(patch("utils.self_evolution._coverage", return_value={
                "universe_count": 100, "covered_count": 80, "coverage_ratio": 0.8,
            }))
            stack.enter_context(patch("utils.self_evolution.update_decision_outcomes", return_value={
                "updated": 0, "complete": 0, "pending": 0, "missing_data": 0,
            }))
            stack.enter_context(patch("utils.self_evolution.data_version", return_value="d1"))
            stack.enter_context(patch("utils.self_evolution.save_evolution_run", return_value="e1"))
            stack.enter_context(patch(
                "utils.reference_snapshots.capture_reference_snapshot",
                return_value={"available": True, "as_of": "2026-07-14"},
            ))
            stack.enter_context(patch(
                "utils.reference_snapshots.load_reference_snapshots",
                return_value={"2026-07-14": {"as_of": "2026-07-14"}},
            ))
            build_dataset = stack.enter_context(
                patch("tools.hierarchical_walk_forward.build_dataset")
            )
            result = run_daily_evolution(manager)

        build_dataset.assert_not_called()
        self.assertEqual(result["metrics"]["training_status"], "skipped_reference_history")
        self.assertEqual(result["dataset_rows"], 0)

    def test_daily_training_registers_shadow_but_never_promotes(self):
        manager = CSVManager(Path(self.tmp.name) / "data")
        frame = pd.DataFrame({
            "date": [f"202{year}-{month:02d}-05" for year in (4, 5)
                     for month in range(1, 13)],
            "code": ["600000"] * 24,
        })
        report = {
            "bundle": {"version": "challenger-1"},
            "status": {key: "active" for key in ("market", "sector", "risk", "quality")},
            "aggregate": {key: {"n": 100, "months": 6, "avg": 1.0, "cvar10": -2.0}
                          for key in ("market", "sector", "risk", "quality")},
        }
        with ExitStack() as stack:
            stack.enter_context(patch("utils.self_evolution.local_data_status", return_value={
                "fresh": True, "local_date": "2026-07-14", "expected_date": "2026-07-14",
            }))
            stack.enter_context(patch(
                "utils.self_evolution.Path.read_text", side_effect=['{"600000":"银行"}',
                                                                    '{"600000":"银行"}'],
            ))
            stack.enter_context(patch("utils.self_evolution._coverage", return_value={
                "universe_count": 100, "covered_count": 80, "coverage_ratio": 0.8,
            }))
            stack.enter_context(patch("utils.self_evolution.update_decision_outcomes", return_value={
                "updated": 0, "complete": 0, "pending": 0, "missing_data": 0,
            }))
            stack.enter_context(patch("utils.self_evolution.data_version", return_value="d1"))
            stack.enter_context(patch("utils.self_evolution.save_evolution_run", return_value="e1"))
            stack.enter_context(patch(
                "utils.reference_snapshots.capture_reference_snapshot",
                return_value={"available": True, "as_of": "2026-07-14"},
            ))
            stack.enter_context(patch(
                "utils.reference_snapshots.load_reference_snapshots",
                return_value={f"202{year}-{month:02d}-01": {} for year in (4, 5)
                              for month in range(1, 13)},
            ))
            stack.enter_context(patch(
                "tools.hierarchical_walk_forward.build_dataset", return_value=frame,
            ))
            stack.enter_context(patch(
                "tools.hierarchical_walk_forward.train_and_register", return_value=report,
            ))
            stack.enter_context(patch("pandas.DataFrame.to_csv"))
            stack.enter_context(patch("pathlib.Path.write_text"))
            promote = stack.enter_context(patch("utils.decision_ledger.promote_model_bundle"))

            result = run_daily_evolution(manager)

        promote.assert_not_called()
        self.assertEqual(result["promotion_status"], "shadow_registered")
        self.assertIn("release_review_required", result["reason_codes"])


if __name__ == "__main__":
    unittest.main()
