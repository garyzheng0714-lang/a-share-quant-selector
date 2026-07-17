import unittest
from unittest.mock import patch

from flask import Flask

from views.decision_api import decision_bp
from utils.decision_versions import strategy_version


class DecisionApiTest(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.register_blueprint(decision_bp)
        self.client = self.app.test_client()

    @patch("views.decision_api.list_models", return_value=[])
    @patch("views.decision_api.get_latest_decision")
    @patch("utils.data_freshness.local_data_status")
    def test_latest_returns_versioned_run(self, freshness, latest, _models):
        freshness.return_value = {
            "fresh": True, "local_date": "2026-07-14", "expected_date": "2026-07-14",
        }
        latest.return_value = {
            "run_id": "run-1", "stage": "close", "trade_date": "2026-07-14",
            "as_of": "2026-07-14T15:00:00+08:00", "status": "complete",
            "final_action": "none", "candidates": [],
            "strategy_version": strategy_version(),
        }
        response = self.client.get("/api/decision/latest")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["available"])
        self.assertEqual(response.json["run_id"], "run-1")

    def test_invalid_stage_is_rejected(self):
        response = self.client.get("/api/decision/latest?stage=intraday")
        self.assertEqual(response.status_code, 400)

    @patch("views.decision_api.get_latest_evolution")
    def test_evolution_status_is_exposed(self, latest):
        latest.return_value = {
            "trade_date": "2026-07-14", "status": "complete",
            "promotion_status": "kept_champion",
            "metrics": {"strategy": "super-b1-original"},
        }
        response = self.client.get("/api/decision/evolution")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["available"])
        self.assertEqual(response.json["data"]["promotion_status"], "kept_champion")

    @patch("views.decision_api.list_models", return_value=[])
    @patch("views.decision_api.get_latest_decision", return_value={"run_id": "old"})
    @patch("utils.data_freshness.local_data_status")
    def test_stale_data_returns_last_decision_with_warning(self, freshness, _latest, _models):
        freshness.return_value = {
            "fresh": False, "local_date": "2026-07-10", "expected_date": "2026-07-14",
        }
        response = self.client.get("/api/decision/latest")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["available"])
        self.assertTrue(response.json["is_stale"])
        self.assertEqual(response.json["data_status"], "stale")
        self.assertEqual(response.json["run_id"], "old")

    @patch("views.decision_api.list_models", return_value=[])
    @patch("views.decision_api.get_decision", return_value={"run_id": "archived-run"})
    @patch("utils.data_freshness.local_data_status")
    def test_historical_detail_remains_replayable_when_market_data_is_stale(
        self, freshness, _decision, _models,
    ):
        freshness.return_value = {
            "fresh": False, "local_date": "2026-07-10", "expected_date": "2026-07-14",
        }

        response = self.client.get("/api/decision/archived-run")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["available"])
        self.assertTrue(response.json["is_stale"])


if __name__ == "__main__":
    unittest.main()
