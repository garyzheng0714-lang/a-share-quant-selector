import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import views.view_manager as view_manager
from utils.csv_manager import CSVManager
from utils.decision_ledger import (
    init_decision_ledger,
    list_decision_outcomes,
    outcome_summary,
    save_decision_run,
)
from utils.self_evolution import run_daily_evolution, update_decision_outcomes


class SelfEvolutionTest(unittest.TestCase):
    SNAPSHOT_ID = "a" * 64

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original = view_manager.DB_PATH
        view_manager.DB_PATH = Path(self.tmp.name) / "test.db"
        init_decision_ledger()

    def tearDown(self):
        view_manager.DB_PATH = self.original
        self.tmp.cleanup()

    def test_observe_is_labeled_to_measure_missed_winners(self):
        payload = Path(self.tmp.name) / "snapshot" / "payload"
        manager = CSVManager(payload, resolve_snapshot=False)
        manager.snapshot_id = self.SNAPSHOT_ID
        (payload.parent / "manifest.json").write_text(
            json.dumps({"trade_date": "2026-01-13"}),
            encoding="utf-8",
        )
        (manager.data_dir / "trade_calendar.json").write_text(
            json.dumps(
                [
                    "2026-01-05",
                    "2026-01-06",
                    "2026-01-07",
                    "2026-01-08",
                    "2026-01-09",
                    "2026-01-12",
                    "2026-01-13",
                ]
            ),
            encoding="utf-8",
        )
        manager.write_stock(
            "600000",
            pd.DataFrame(
                [
                    {
                        "date": "2026-01-05",
                        "open": 10,
                        "high": 10.2,
                        "low": 9.8,
                        "close": 10,
                        "volume": 100,
                    },
                    {
                        "date": "2026-01-06",
                        "open": 10,
                        "high": 10.6,
                        "low": 9.9,
                        "close": 10.5,
                        "volume": 100,
                    },
                    {
                        "date": "2026-01-07",
                        "open": 10.5,
                        "high": 10.8,
                        "low": 10.3,
                        "close": 10.7,
                        "volume": 100,
                    },
                    {
                        "date": "2026-01-08",
                        "open": 10.7,
                        "high": 11.0,
                        "low": 10.6,
                        "close": 10.9,
                        "volume": 100,
                    },
                    {
                        "date": "2026-01-09",
                        "open": 10.9,
                        "high": 11.2,
                        "low": 10.8,
                        "close": 11.1,
                        "volume": 100,
                    },
                    {
                        "date": "2026-01-12",
                        "open": 11.1,
                        "high": 11.5,
                        "low": 11.0,
                        "close": 11.4,
                        "volume": 100,
                    },
                    {
                        "date": "2026-01-13",
                        "open": 11.4,
                        "high": 11.7,
                        "low": 11.3,
                        "close": 11.6,
                        "volume": 100,
                    },
                ]
            ),
        )
        save_decision_run(
            {
                "trade_date": "2026-01-05",
                "stage": "close",
                "as_of": "2026-01-05T15:00:00+08:00",
                "status": "degraded",
                "final_action": "observe",
                "strategy_version": "s1",
                "feature_version": "f1",
                "model_version": "m1",
                "data_version": "d1",
            },
            [{"code": "600000", "action": "observe"}],
        )

        states = {
            date: {
                "security_states": {
                    "600000": {
                        "as_of": date,
                        "is_st": False,
                        "trading_status": "active",
                        "source": "test",
                        "listing_rule_verified": True,
                        "listing_session_number": 100,
                    }
                },
            }
            for date in (
                "2026-01-06",
                "2026-01-07",
                "2026-01-08",
                "2026-01-09",
                "2026-01-12",
                "2026-01-13",
            )
        }
        with patch(
            "utils.reference_snapshots.load_reference_snapshots", return_value=states
        ):
            result = update_decision_outcomes(manager)
        summary = outcome_summary("close")
        outcomes = list_decision_outcomes(stage="close")
        self.assertEqual(result["complete"], 1)
        self.assertEqual(summary["observe"]["count"], 1)
        self.assertEqual(summary["missed_winner_rate"], 1.0)
        self.assertEqual(outcomes[0]["ret_1"], 4.78)
        self.assertNotEqual(outcomes[0]["ret_1"], 5.0)
        self.assertEqual(
            outcomes[0]["execution_policy_version"],
            "a-share-eod-open-open-v5",
        )
        self.assertEqual(outcomes[0]["source_snapshot_id"], self.SNAPSHOT_ID)

    def test_training_is_skipped_before_universe_coverage_gate(self):
        manager = CSVManager(Path(self.tmp.name) / "data")
        manager.snapshot_id = self.SNAPSHOT_ID
        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "utils.self_evolution.local_data_status",
                    return_value={
                        "fresh": True,
                        "local_date": "2026-07-14",
                        "expected_date": "2026-07-14",
                    },
                )
            )
            stack.enter_context(
                patch(
                    "utils.self_evolution.read_snapshot_metadata",
                    side_effect=[
                        ({"600000": "浦发银行"}, self.SNAPSHOT_ID),
                        ({"600000": "银行"}, self.SNAPSHOT_ID),
                    ],
                )
            )
            stack.enter_context(
                patch(
                    "utils.self_evolution._coverage",
                    return_value={
                        "universe_count": 100,
                        "covered_count": 8,
                        "coverage_ratio": 0.08,
                    },
                )
            )
            stack.enter_context(
                patch(
                    "utils.self_evolution.update_decision_outcomes",
                    return_value={
                        "updated": 0,
                        "complete": 0,
                        "pending": 0,
                        "missing_data": 0,
                    },
                )
            )
            stack.enter_context(
                patch("utils.self_evolution.data_version", return_value="d1")
            )
            stack.enter_context(
                patch("utils.self_evolution.save_evolution_run", return_value="e1")
            )
            stack.enter_context(
                patch(
                    "utils.reference_snapshots.capture_reference_snapshot",
                    return_value={
                        "available": True,
                        "as_of": "2026-07-14",
                        "market_snapshot_id": self.SNAPSHOT_ID,
                    },
                )
            )
            build_dataset = stack.enter_context(
                patch("tools.hierarchical_walk_forward.build_dataset")
            )
            result = run_daily_evolution(manager)

        build_dataset.assert_not_called()
        self.assertEqual(result["metrics"]["training_status"], "skipped_data_gate")
        self.assertEqual(result["dataset_rows"], 0)

    def test_training_is_skipped_until_reference_history_is_long_enough(self):
        manager = CSVManager(Path(self.tmp.name) / "data")
        manager.snapshot_id = self.SNAPSHOT_ID
        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "utils.self_evolution.local_data_status",
                    return_value={
                        "fresh": True,
                        "local_date": "2026-07-14",
                        "expected_date": "2026-07-14",
                    },
                )
            )
            stack.enter_context(
                patch(
                    "utils.self_evolution.read_snapshot_metadata",
                    side_effect=[
                        ({"600000": "浦发银行"}, self.SNAPSHOT_ID),
                        ({"600000": "银行"}, self.SNAPSHOT_ID),
                    ],
                )
            )
            stack.enter_context(
                patch(
                    "utils.self_evolution._coverage",
                    return_value={
                        "universe_count": 100,
                        "covered_count": 80,
                        "coverage_ratio": 0.8,
                    },
                )
            )
            stack.enter_context(
                patch(
                    "utils.self_evolution.update_decision_outcomes",
                    return_value={
                        "updated": 0,
                        "complete": 0,
                        "pending": 0,
                        "missing_data": 0,
                    },
                )
            )
            stack.enter_context(
                patch("utils.self_evolution.data_version", return_value="d1")
            )
            stack.enter_context(
                patch("utils.self_evolution.save_evolution_run", return_value="e1")
            )
            stack.enter_context(
                patch(
                    "utils.reference_snapshots.capture_reference_snapshot",
                    return_value={
                        "available": True,
                        "as_of": "2026-07-14",
                        "market_snapshot_id": self.SNAPSHOT_ID,
                    },
                )
            )
            stack.enter_context(
                patch(
                    "utils.reference_snapshots.load_reference_snapshots",
                    return_value={"2026-07-14": {"as_of": "2026-07-14"}},
                )
            )
            stack.enter_context(
                patch(
                    "tools.hierarchical_walk_forward.materialize_pit_feature_ledger",
                    return_value={"complete": True},
                )
            )
            build_dataset = stack.enter_context(
                patch("tools.hierarchical_walk_forward.build_dataset")
            )
            result = run_daily_evolution(manager)

        build_dataset.assert_not_called()
        self.assertEqual(
            result["metrics"]["training_status"], "skipped_reference_history"
        )
        self.assertEqual(result["dataset_rows"], 0)

    def test_unverified_historical_features_keep_champion(self):
        manager = CSVManager(Path(self.tmp.name) / "data")
        manager.snapshot_id = self.SNAPSHOT_ID
        sessions = [
            value.strftime("%Y-%m-%d")
            for value in pd.bdate_range("2024-01-01", "2025-12-31")
        ]
        frame = pd.DataFrame()
        frame.attrs.update(
            {
                "reason": "pit_feature_history_unavailable",
                "mismatched_snapshot_count": 24,
            }
        )
        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "utils.self_evolution.local_data_status",
                    return_value={
                        "fresh": True,
                        "local_date": "2026-07-14",
                        "expected_date": "2026-07-14",
                    },
                )
            )
            stack.enter_context(
                patch(
                    "utils.self_evolution.read_snapshot_metadata",
                    side_effect=[
                        ({"600000": "浦发银行"}, self.SNAPSHOT_ID),
                        ({"600000": "银行"}, self.SNAPSHOT_ID),
                    ],
                )
            )
            stack.enter_context(
                patch(
                    "utils.self_evolution._coverage",
                    return_value={
                        "universe_count": 100,
                        "covered_count": 80,
                        "coverage_ratio": 0.8,
                    },
                )
            )
            stack.enter_context(
                patch(
                    "utils.self_evolution.update_decision_outcomes",
                    return_value={
                        "updated": 0,
                        "complete": 0,
                        "pending": 0,
                        "missing_data": 0,
                    },
                )
            )
            stack.enter_context(
                patch("utils.self_evolution.data_version", return_value="d1")
            )
            stack.enter_context(
                patch(
                    "utils.self_evolution.load_exchange_sessions",
                    return_value=sessions,
                )
            )
            stack.enter_context(
                patch("utils.self_evolution.save_evolution_run", return_value="e1")
            )
            stack.enter_context(
                patch(
                    "utils.reference_snapshots.capture_reference_snapshot",
                    return_value={
                        "available": True,
                        "as_of": "2026-07-14",
                        "market_snapshot_id": self.SNAPSHOT_ID,
                    },
                )
            )
            stack.enter_context(
                patch(
                    "utils.reference_snapshots.load_reference_snapshots",
                    return_value={date: {} for date in sessions},
                )
            )
            stack.enter_context(
                patch(
                    "tools.hierarchical_walk_forward.materialize_pit_feature_ledger",
                    return_value={"complete": True},
                )
            )
            stack.enter_context(
                patch(
                    "tools.hierarchical_walk_forward.build_dataset",
                    return_value=frame,
                )
            )
            train = stack.enter_context(
                patch("tools.hierarchical_walk_forward.train_and_register")
            )

            result = run_daily_evolution(manager)

        train.assert_not_called()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["promotion_status"], "kept_champion")
        self.assertEqual(result["reason_codes"], ["pit_feature_history_unavailable"])
        self.assertEqual(result["metrics"]["training_status"], "pit_evidence_failed")
        self.assertEqual(
            result["metrics"]["dataset_gate"]["mismatched_snapshot_count"], 24
        )

    def test_training_readiness_gap_is_warming_up_not_evolution_failure(self):
        manager = CSVManager(Path(self.tmp.name) / "data")
        manager.snapshot_id = self.SNAPSHOT_ID
        sessions = [
            value.strftime("%Y-%m-%d")
            for value in pd.bdate_range("2024-01-01", "2026-07-14")
        ]
        months = pd.date_range("2024-01-01", periods=21, freq="MS")
        frame = pd.DataFrame(
            {
                "date": [
                    (month + pd.Timedelta(days=4)).strftime("%Y-%m-%d")
                    for month in months
                ],
                "label_end_date": [
                    (month + pd.Timedelta(days=11)).strftime("%Y-%m-%d")
                    for month in months
                ],
                "label_snapshot_date": [
                    (month + pd.Timedelta(days=11)).strftime("%Y-%m-%d")
                    for month in months
                ],
                "code": ["600000"] * len(months),
                "return_label_mature": [1] * len(months),
                "net_return_5": [1.0] * len(months),
                "excess_5": [1.0] * len(months),
                "y_quality": [1] * len(months),
                "entry_label_mature": [1] * len(months),
                "entry_feasible": [1] * len(months),
                "y_entry_risk": [0] * len(months),
                "exit_label_mature": [1] * len(months),
                "y_exit_risk": [0] * len(months),
            }
        )
        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "utils.self_evolution.local_data_status",
                    return_value={
                        "fresh": True,
                        "local_date": "2026-07-14",
                        "expected_date": "2026-07-14",
                    },
                )
            )
            stack.enter_context(
                patch(
                    "utils.self_evolution.read_snapshot_metadata",
                    side_effect=[
                        ({"600000": "浦发银行"}, self.SNAPSHOT_ID),
                        ({"600000": "银行"}, self.SNAPSHOT_ID),
                    ],
                )
            )
            stack.enter_context(
                patch(
                    "utils.self_evolution._coverage",
                    return_value={
                        "universe_count": 100,
                        "covered_count": 80,
                        "coverage_ratio": 0.8,
                    },
                )
            )
            stack.enter_context(
                patch(
                    "utils.self_evolution.update_decision_outcomes",
                    return_value={
                        "updated": 0,
                        "complete": 0,
                        "pending": 0,
                        "missing_data": 0,
                    },
                )
            )
            stack.enter_context(
                patch(
                    "utils.paper_trading.get_paper_status",
                    return_value={"established": False},
                )
            )
            stack.enter_context(
                patch("utils.self_evolution.data_version", return_value="d1")
            )
            stack.enter_context(
                patch(
                    "utils.self_evolution.load_exchange_sessions",
                    return_value=sessions,
                )
            )
            stack.enter_context(
                patch("utils.self_evolution.save_evolution_run", return_value="e1")
            )
            stack.enter_context(
                patch(
                    "utils.reference_snapshots.capture_reference_snapshot",
                    return_value={
                        "available": True,
                        "as_of": "2026-07-14",
                        "market_snapshot_id": self.SNAPSHOT_ID,
                    },
                )
            )
            stack.enter_context(
                patch(
                    "utils.reference_snapshots.load_reference_snapshots",
                    return_value={date: {} for date in sessions},
                )
            )
            stack.enter_context(
                patch(
                    "tools.hierarchical_walk_forward.materialize_pit_feature_ledger",
                    return_value={"complete": True},
                )
            )
            stack.enter_context(
                patch(
                    "tools.hierarchical_walk_forward.build_dataset",
                    return_value=frame,
                )
            )
            stack.enter_context(
                patch(
                    "tools.hierarchical_walk_forward.training_readiness",
                    return_value={
                        "ready": False,
                        "reason": "walk_forward_sample_insufficient",
                        "eligible_folds": 0,
                    },
                )
            )
            train = stack.enter_context(
                patch("tools.hierarchical_walk_forward.train_and_register")
            )

            result = run_daily_evolution(manager)

        train.assert_not_called()
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["promotion_status"], "kept_champion")
        self.assertEqual(result["reason_codes"], ["walk_forward_sample_insufficient"])
        self.assertEqual(result["metrics"]["model_state"], "warming_up")
        self.assertFalse(result["metrics"]["trained"])

    def test_daily_training_registers_shadow_but_never_promotes(self):
        manager = CSVManager(Path(self.tmp.name) / "data")
        manager.snapshot_id = self.SNAPSHOT_ID
        sessions = [
            value.strftime("%Y-%m-%d")
            for value in pd.bdate_range("2024-01-01", "2026-07-14")
        ]
        frame = pd.DataFrame(
            {
                "date": [
                    f"202{year}-{month:02d}-05"
                    for year in (4, 5)
                    for month in range(1, 13)
                ],
                "label_end_date": [
                    f"202{year}-{month:02d}-10"
                    for year in (4, 5)
                    for month in range(1, 13)
                ],
                "label_snapshot_date": [
                    f"202{year}-{month:02d}-11"
                    for year in (4, 5)
                    for month in range(1, 13)
                ],
                "code": ["600000"] * 24,
                "return_label_mature": [1] * 24,
                "net_return_5": [1.0] * 24,
                "excess_5": [1.0] * 24,
                "y_quality": [1] * 24,
                "entry_label_mature": [1] * 24,
                "entry_feasible": [1] * 24,
                "y_entry_risk": [0] * 24,
                "exit_label_mature": [1] * 24,
                "y_exit_risk": [0] * 24,
            }
        )
        report = {
            "bundle": {"version": "challenger-1"},
            "status": {
                key: "active"
                for key in (
                    "market",
                    "sector",
                    "entry_risk",
                    "exit_risk",
                    "quality",
                )
            },
            "aggregate": {
                key: {"n": 100, "months": 6, "avg": 1.0, "cvar10": -2.0}
                for key in (
                    "market",
                    "sector",
                    "entry_risk",
                    "exit_risk",
                    "quality",
                )
            },
        }
        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "utils.self_evolution.local_data_status",
                    return_value={
                        "fresh": True,
                        "local_date": "2026-07-14",
                        "expected_date": "2026-07-14",
                    },
                )
            )
            stack.enter_context(
                patch(
                    "utils.self_evolution.read_snapshot_metadata",
                    side_effect=[
                        ({"600000": "浦发银行"}, self.SNAPSHOT_ID),
                        ({"600000": "银行"}, self.SNAPSHOT_ID),
                    ],
                )
            )
            stack.enter_context(
                patch(
                    "utils.self_evolution._coverage",
                    return_value={
                        "universe_count": 100,
                        "covered_count": 80,
                        "coverage_ratio": 0.8,
                    },
                )
            )
            stack.enter_context(
                patch(
                    "utils.self_evolution.update_decision_outcomes",
                    return_value={
                        "updated": 0,
                        "complete": 0,
                        "pending": 0,
                        "missing_data": 0,
                    },
                )
            )
            stack.enter_context(
                patch("utils.self_evolution.data_version", return_value="d1")
            )
            stack.enter_context(
                patch(
                    "utils.self_evolution.load_exchange_sessions",
                    return_value=sessions,
                )
            )
            stack.enter_context(
                patch("utils.self_evolution.save_evolution_run", return_value="e1")
            )
            stack.enter_context(
                patch(
                    "utils.reference_snapshots.capture_reference_snapshot",
                    return_value={
                        "available": True,
                        "as_of": "2026-07-14",
                        "market_snapshot_id": self.SNAPSHOT_ID,
                    },
                )
            )
            stack.enter_context(
                patch(
                    "utils.reference_snapshots.load_reference_snapshots",
                    return_value={date: {} for date in sessions},
                )
            )
            materialize_ledger = stack.enter_context(
                patch(
                    "tools.hierarchical_walk_forward.materialize_pit_feature_ledger",
                    return_value={"complete": True},
                )
            )
            build_dataset = stack.enter_context(
                patch(
                    "tools.hierarchical_walk_forward.build_dataset",
                    return_value=frame,
                )
            )
            stack.enter_context(
                patch(
                    "tools.hierarchical_walk_forward.training_readiness",
                    return_value={"ready": True, "reason": None},
                )
            )

            def train_and_write(_frame, output_path, **_kwargs):
                self.assertEqual(
                    _kwargs["trained_as_of"],
                    "2025-12-11T16:00:00+08:00",
                )
                Path(output_path).write_text("{}", encoding="utf-8")
                return report

            stack.enter_context(
                patch(
                    "tools.hierarchical_walk_forward.train_and_register",
                    side_effect=train_and_write,
                )
            )
            promote = stack.enter_context(
                patch("utils.decision_ledger.promote_model_bundle")
            )

            result = run_daily_evolution(manager)

        promote.assert_not_called()
        self.assertEqual(
            list(materialize_ledger.call_args.kwargs["snapshots"]),
            sessions,
        )
        self.assertIs(
            materialize_ledger.call_args.kwargs["snapshots"],
            build_dataset.call_args.kwargs["snapshots"],
        )
        self.assertEqual(result["promotion_status"], "shadow_registered")
        self.assertIn("release_review_required", result["reason_codes"])


if __name__ == "__main__":
    unittest.main()
