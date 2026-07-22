import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

import views.view_manager as view_manager
from utils.decision_ledger import init_decision_ledger, save_decision_run
from utils.hierarchical_decision import (
    _active_model_bundle,
    _baseline_candidates,
    run_close_decision,
    run_preopen_decision,
)


def _candidate(weekly_passed: bool = True) -> dict:
    return {
        "code": "600000",
        "name": "浦发银行",
        "industry": "银行",
        "signals": ["原始B1"],
        "signal_labels": ["原始B1"],
        "close": 10.0,
        "J": 10.0,
        "RSI": 15.0,
        "weekly": {
            "passed": weekly_passed,
            "aligned": weekly_passed,
            "rising": weekly_passed,
            "rising_count": 4 if weekly_passed else 2,
            "directions": {},
            "ma_values": {},
        },
    }


class HierarchicalDecisionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original = view_manager.DB_PATH
        view_manager.DB_PATH = Path(self.tmp.name) / "test.db"
        init_decision_ledger()
        self.common = [
            patch(
                "utils.hierarchical_decision.local_data_status",
                return_value={
                    "fresh": True,
                    "local_date": "2026-07-14",
                    "expected_date": "2026-07-14",
                    "snapshot_id": "a" * 64,
                    "closed_at": "2026-07-14T15:05:00+08:00",
                },
            ),
            patch(
                "utils.hierarchical_decision.next_trade_date", return_value="2026-07-15"
            ),
            patch("utils.hierarchical_decision.strategy_version", return_value="s1"),
            patch(
                "utils.hierarchical_decision.data_version",
                return_value=f"snapshot-{'a' * 64}",
            ),
            patch(
                "utils.hierarchical_decision._verify_manager_snapshot",
                return_value={"available": True},
            ),
        ]
        for item in self.common:
            item.start()

    def tearDown(self):
        for item in reversed(self.common):
            item.stop()
        view_manager.DB_PATH = self.original
        self.tmp.cleanup()

    def _save_close(self, *, snapshot_id="a" * 64, trade_date="2026-07-14"):
        run = {
            "trade_date": trade_date,
            "stage": "close",
            "as_of": f"{trade_date}T15:05:00+08:00",
            "status": "complete",
            "final_action": "buy",
            "strategy_version": "s1",
            "feature_version": "f1",
            "model_version": "baseline-only",
            "data_version": f"snapshot-{snapshot_id}",
            "market": {
                "snapshot_id": snapshot_id,
                "decision_for_date": "2026-07-15",
            },
        }
        candidate = {
            "code": "600000",
            "name": "浦发银行",
            "action": "buy",
            "reason_codes": [],
        }
        return save_decision_run(run, [candidate])

    @patch(
        "utils.hierarchical_decision._active_model_bundle",
        return_value=({}, "baseline-only"),
    )
    @patch("utils.hierarchical_decision._baseline_candidates")
    @patch("utils.hierarchical_decision.get_decision_config")
    def test_weekly_gate_is_recorded_in_shadow_mode(self, config, baseline, _models):
        config.return_value = {
            "enabled": True,
            "strict_unvalidated_gate": True,
            "preopen_event_check": True,
            "weekly_gate_mode": "shadow",
        }
        artifact = {
            "namespace": "super_b1",
            "cache_key": "cache-key",
            "content_hash": "sha256:" + "b" * 64,
            "trade_date": "2026-07-14",
        }
        baseline.return_value = (
            "2026-07-14",
            [_candidate(False)],
            {"super_b1": artifact},
        )

        result = run_close_decision()

        self.assertEqual(result["candidates"][0]["action"], "observe")
        self.assertIn(
            "weekly_four_ma_shadow_fail", result["candidates"][0]["reason_codes"]
        )
        self.assertEqual(result["market"]["layer_modes"]["weekly_four_ma"], "shadow")
        self.assertEqual(result["market"]["derived_artifacts"]["super_b1"], artifact)
        self.assertIn(
            f"derived-artifact:super_b1:{artifact['content_hash']}",
            result["source_refs"],
        )

    @patch("utils.hierarchical_decision.get_active_policy_models")
    def test_no_released_atomic_policy_means_baseline_only(self, active_policy):
        active_policy.return_value = ({}, "baseline-only")

        models, version = _active_model_bundle()

        self.assertEqual(models, {})
        self.assertEqual(version, "baseline-only")

    @patch("utils.hierarchical_decision.local_data_status")
    @patch(
        "utils.hierarchical_decision._verify_manager_snapshot",
        return_value={"available": False, "reason": "snapshot_file_hash_mismatch"},
    )
    @patch("utils.hierarchical_decision.get_decision_config")
    def test_tampered_snapshot_is_rejected_before_decision(
        self, config, _verified, freshness
    ):
        config.return_value = {
            "enabled": True,
            "strict_unvalidated_gate": True,
            "preopen_event_check": True,
            "weekly_gate_mode": "shadow",
        }

        result = run_close_decision()

        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "market_snapshot_integrity_failed")
        freshness.assert_not_called()

    @patch("utils.hierarchical_decision.save_decision_run")
    @patch(
        "utils.hierarchical_decision._active_model_bundle",
        return_value=({}, "baseline-only"),
    )
    @patch("utils.hierarchical_decision._baseline_candidates")
    @patch("utils.hierarchical_decision.get_decision_config")
    def test_snapshot_changed_during_close_is_rejected_before_ledger_commit(
        self,
        config,
        baseline,
        _models,
        save_run,
    ):
        config.return_value = {
            "enabled": True,
            "strict_unvalidated_gate": True,
            "preopen_event_check": True,
            "weekly_gate_mode": "shadow",
        }
        baseline.return_value = ("2026-07-14", [_candidate(True)], {})
        with patch(
            "utils.hierarchical_decision._verify_manager_snapshot",
            side_effect=[
                {"available": True},
                {"available": False, "reason": "snapshot_file_hash_mismatch"},
            ],
        ):
            result = run_close_decision()

        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "market_snapshot_integrity_failed")
        self.assertEqual(result["phase"], "before_ledger_commit")
        save_run.assert_not_called()

    @patch("utils.hierarchical_decision._predict")
    @patch("utils.hierarchical_decision._live_feature_rows")
    @patch("utils.hierarchical_decision._active_model_bundle")
    @patch("utils.hierarchical_decision._baseline_candidates")
    @patch("utils.hierarchical_decision.get_decision_config")
    def test_incomplete_model_bundle_fails_closed(
        self,
        config,
        baseline,
        models,
        live_rows,
        predict,
    ):
        config.return_value = {
            "enabled": True,
            "strict_unvalidated_gate": True,
            "preopen_event_check": True,
            "weekly_gate_mode": "shadow",
        }
        baseline.return_value = ("2026-07-14", [_candidate(True)], {})
        models.return_value = ({"market": {"version": "market-v1"}}, "market@market-v1")
        live_rows.return_value = pd.DataFrame(
            [{"code": "600000", "feature_missing": False}]
        )
        predict.return_value = {
            "600000": {"market": 0.8, "market_threshold": 0.5},
        }

        result = run_close_decision()

        self.assertEqual(result["candidates"][0]["action"], "avoid")
        self.assertIn("market_gate", result["candidates"][0]["reason_codes"])
        self.assertNotIn("hierarchy_models_unvalidated", result["reason_codes"])

    def test_missing_market_cap_remains_missing_instead_of_becoming_fake_value(self):
        metadata = {
            "stock_names.json": ({"600000": "浦发银行"}, "snapshot-1"),
            "stock_industry.json": ({"600000": "银行"}, "snapshot-1"),
            "stock_market_cap.json": ({}, "snapshot-1"),
        }
        with (
            patch(
                "utils.hierarchical_decision.read_snapshot_metadata",
                side_effect=lambda name, *_args, **_kwargs: metadata[name],
            ),
            patch(
                "utils.super_b1_scan.read_cached_super_b1",
                return_value={
                    "available": True,
                    "trade_date": "2026-07-14",
                    "hits": [_candidate()],
                },
            ),
            patch(
                "utils.sector_rotation.read_cached_sector_rotation",
                return_value={"available": True, "heat_map": {"bank": {}}},
            ),
            patch(
                "utils.factor_scan.read_cached_factor_hits",
                return_value={"available": False},
            ),
            patch("utils.market_filter.main_board_only", return_value=False),
        ):
            manager = MagicMock()
            manager.base_data_dir = Path("data")
            manager.snapshot_id = "a" * 64
            trade_date, rows, artifacts = _baseline_candidates(manager)

        self.assertEqual(trade_date, "2026-07-14")
        self.assertIsNone(rows[0]["cap_yi"])
        self.assertEqual(set(artifacts), {"super_b1", "sector_rotation"})

    @patch("utils.event_risk.review_candidates")
    @patch("utils.hierarchical_decision.get_decision_config")
    def test_old_close_run_cannot_enter_current_preopen(self, config, review):
        config.return_value = {
            "enabled": True,
            "preopen_event_check": True,
            "weekly_gate_mode": "shadow",
            "strict_unvalidated_gate": True,
        }
        self._save_close(trade_date="2026-07-13")

        result = run_preopen_decision("2026-07-15T08:45:00+08:00")

        self.assertFalse(result["available"])
        self.assertEqual(
            result["reason"], "close_decision_missing_for_previous_session"
        )
        review.assert_not_called()

    @patch("utils.hierarchical_decision.get_active_models", return_value={})
    @patch("utils.event_risk.review_candidates")
    @patch("utils.hierarchical_decision.get_decision_config")
    def test_preopen_idempotency_is_bound_to_exact_close_run(
        self,
        config,
        review,
        _models,
    ):
        config.return_value = {
            "enabled": True,
            "preopen_event_check": True,
            "weekly_gate_mode": "shadow",
            "strict_unvalidated_gate": True,
        }
        close_run_id = self._save_close()
        save_decision_run(
            {
                "trade_date": "2026-07-14",
                "stage": "preopen",
                "as_of": "2026-07-15T08:44:00+08:00",
                "status": "complete",
                "final_action": "buy",
                "strategy_version": "s1",
                "feature_version": "f1",
                "model_version": "baseline-only",
                "data_version": f"snapshot-{'a' * 64}",
                "market": {
                    "snapshot_id": "a" * 64,
                    "decision_for_date": "2026-07-15",
                },
                "evaluation": {"close_run_id": "superseded-close"},
            },
            [{"code": "600000", "action": "buy", "reason_codes": []}],
        )
        review.return_value = {
            "available": True,
            "events_by_code": {},
            "veto_codes": [],
            "review_codes": [],
            "source_refs": [],
            "llm": {},
        }

        result = run_preopen_decision("2026-07-15T08:45:00+08:00")

        self.assertTrue(result["available"])
        self.assertNotIn("idempotent_replay", result)
        self.assertEqual(result["evaluation"]["close_run_id"], close_run_id)
        review.assert_called_once()

        repeated = run_preopen_decision("2026-07-15T08:45:00+08:00")
        self.assertTrue(repeated["idempotent_replay"])
        self.assertEqual(review.call_count, 1)

    @patch("utils.hierarchical_decision.get_active_models", return_value={})
    @patch("utils.event_risk.review_candidates")
    @patch("utils.hierarchical_decision.get_decision_config")
    def test_snapshot_changed_during_preopen_is_rejected_before_ledger_commit(
        self,
        config,
        review,
        _models,
    ):
        config.return_value = {
            "enabled": True,
            "preopen_event_check": True,
            "weekly_gate_mode": "shadow",
            "strict_unvalidated_gate": True,
        }
        self._save_close()
        review.return_value = {
            "available": True,
            "events_by_code": {},
            "veto_codes": [],
            "review_codes": [],
            "source_refs": [],
            "llm": {},
        }
        with (
            patch(
                "utils.hierarchical_decision._verify_manager_snapshot",
                side_effect=[
                    {"available": True},
                    {"available": False, "reason": "snapshot_file_hash_mismatch"},
                ],
            ),
            patch("utils.hierarchical_decision.save_decision_run") as save_run,
        ):
            result = run_preopen_decision("2026-07-15T08:45:00+08:00")

        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "market_snapshot_integrity_failed")
        self.assertEqual(result["phase"], "before_ledger_commit")
        save_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
