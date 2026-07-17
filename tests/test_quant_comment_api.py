import unittest
from unittest.mock import patch

from flask import Flask

from views.quant_pick_api import quant_pick_bp


class QuantCommentApiTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.register_blueprint(quant_pick_bp)
        self.client = app.test_client()

    @patch("utils.decision_versions.strategy_version", return_value="s1")
    @patch("utils.data_freshness.local_data_status", return_value={
        "fresh": True, "local_date": "2026-07-14", "expected_date": "2026-07-14",
    })
    @patch("utils.decision_ledger.get_latest_decision")
    @patch("utils.daily_pick.generate_quant_comment")
    def test_comment_uses_only_approved_candidates_from_versioned_decision(
        self, generate, latest, _freshness, _version,
    ):
        latest.return_value = {
            "run_id": "run-1", "trade_date": "2026-07-14", "strategy_version": "s1",
            "candidates": [
                {
                    "code": "600000", "name": "浦发银行", "industry": "银行",
                    "action": "buy", "sector": {"score": 80},
                    "baseline": {"close": 10.0, "J": 20.0, "RSI": 30.0},
                },
                {
                    "code": "600001", "name": "观察票", "industry": "银行",
                    "action": "observe", "baseline": {"close": 9.0},
                },
            ],
        }
        generate.return_value = {"available": True, "by_code": {"600000": {}}}

        response = self.client.get("/api/quant-comment")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["available"])
        args, kwargs = generate.call_args
        self.assertEqual(args[0], "2026-07-14")
        self.assertEqual([row["code"] for row in args[1]], ["600000"])
        self.assertEqual(kwargs["decision_run_id"], "run-1")


if __name__ == "__main__":
    unittest.main()
