import unittest
from unittest.mock import patch

from flask import Flask

from views.decision_api import decision_bp
from views.insight_api import insight_bp
from utils.decision_versions import strategy_version


class DecisionApiTest(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.register_blueprint(decision_bp)
        self.app.register_blueprint(insight_bp)
        self.client = self.app.test_client()

    def test_legacy_daily_pick_generation_stays_disabled(self):
        response = self.client.post("/api/daily-pick")

        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.json["reason"], "legacy_generation_disabled")

    @patch("views.decision_api.list_models", return_value=[])
    @patch("views.decision_api.get_latest_decision")
    @patch("utils.data_freshness.local_data_status")
    def test_latest_returns_versioned_run(self, freshness, latest, _models):
        freshness.return_value = {
            "fresh": True,
            "local_date": "2026-07-14",
            "expected_date": "2026-07-14",
            "snapshot_id": "snap-1",
        }
        latest.return_value = {
            "run_id": "run-1",
            "stage": "close",
            "trade_date": "2026-07-14",
            "as_of": "2026-07-14T15:00:00+08:00",
            "status": "complete",
            "final_action": "none",
            "candidates": [],
            "strategy_version": strategy_version(),
            "data_version": "snapshot-snap-1",
            "market": {"snapshot_id": "snap-1"},
        }
        response = self.client.get("/api/decision/latest")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["available"])
        self.assertEqual(response.json["run_id"], "run-1")

    def test_invalid_stage_is_rejected(self):
        response = self.client.get("/api/decision/latest?stage=intraday")
        self.assertEqual(response.status_code, 400)

    @patch("views.decision_api._current_evolution")
    def test_evolution_status_is_exposed(self, latest):
        latest.return_value = {
            "trade_date": "2026-07-14",
            "status": "complete",
            "promotion_status": "kept_champion",
            "metrics": {"strategy": "super-b1-original"},
        }
        response = self.client.get("/api/decision/evolution")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["available"])
        self.assertEqual(response.json["data"]["promotion_status"], "kept_champion")

    @patch(
        "utils.paper_trading.get_paper_status",
        return_value={
            "established": True,
            "track_record_state": "collecting",
            "nav_days": 2,
        },
    )
    @patch("views.decision_api.get_active_policy", return_value=None)
    @patch(
        "views.decision_api.get_latest_ai_decision_run",
        return_value={
            "status": "not_called",
            "decision_run_id": "run-1",
            "reason_codes": ["no_cloud_stair_signals"],
        },
    )
    @patch(
        "views.decision_api._current_evolution",
        return_value={
            "status": "complete",
            "promotion_status": "shadow_registered",
        },
    )
    @patch(
        "views.decision_api.get_latest_decision",
        return_value={
            "run_id": "run-1",
            "trade_date": "2026-07-14",
            "status": "degraded",
            "final_action": "observe",
            "model_version": "baseline-only",
            "strategy_version": strategy_version(),
            "data_version": "snapshot-snap-1",
            "market": {"snapshot_id": "snap-1"},
            "reason_codes": ["market_model_unvalidated"],
            "candidates": [{"action": "observe"}, {"action": "observe"}],
        },
    )
    @patch(
        "utils.data_freshness.local_data_status",
        return_value={
            "fresh": True,
            "local_date": "2026-07-14",
            "expected_date": "2026-07-14",
            "snapshot_id": "snap-1",
        },
    )
    def test_system_status_exposes_truthful_end_to_end_state(
        self,
        _freshness,
        _decision,
        _evolution,
        _ai,
        _policy,
        _paper,
    ):
        response = self.client.get("/api/decision/system-status")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["decision"]["candidate_counts"]["observe"], 2)
        self.assertEqual(response.json["ai"]["status"], "not_called")
        self.assertEqual(
            response.json["policy"]["active_policy_version"], "baseline-only"
        )
        self.assertFalse(response.json["policy"]["daily_auto_promotion"])

    @patch("views.decision_api.list_models", return_value=[])
    @patch("views.decision_api.get_latest_decision", return_value={"run_id": "old"})
    @patch("utils.data_freshness.local_data_status")
    def test_stale_data_never_exposes_old_decision_as_current(
        self, freshness, _latest, _models
    ):
        freshness.return_value = {
            "fresh": False,
            "local_date": "2026-07-10",
            "expected_date": "2026-07-14",
        }
        response = self.client.get("/api/decision/latest")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json["available"])
        self.assertEqual(response.json["data_status"], "stale")
        self.assertEqual(response.json["reason"], "stale_market_data")

    @patch("views.decision_api.list_models", return_value=[])
    @patch("views.decision_api.get_decision", return_value={"run_id": "archived-run"})
    @patch("utils.data_freshness.local_data_status")
    def test_historical_detail_remains_replayable_when_market_data_is_stale(
        self,
        freshness,
        _decision,
        _models,
    ):
        freshness.return_value = {
            "fresh": False,
            "local_date": "2026-07-10",
            "expected_date": "2026-07-14",
        }

        response = self.client.get("/api/decision/archived-run")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["available"])
        self.assertTrue(response.json["is_stale"])

    @patch("views.decision_api.list_models", return_value=[])
    @patch("views.decision_api.get_decision", return_value={"run_id": "archived-run"})
    @patch(
        "utils.data_freshness.local_data_status",
        return_value={
            "fresh": True,
            "local_date": "2026-07-14",
            "expected_date": "2026-07-14",
            "snapshot_id": "snap-1",
        },
    )
    def test_historical_detail_is_labeled_even_when_current_data_is_fresh(
        self,
        _freshness,
        _decision,
        _models,
    ):
        response = self.client.get("/api/decision/archived-run")

        self.assertTrue(response.json["available"])
        self.assertTrue(response.json["is_stale"])
        self.assertEqual(response.json["data_status"], "historical")
        self.assertEqual(response.json["warning_reason"], "historical_decision")


if __name__ == "__main__":
    unittest.main()
