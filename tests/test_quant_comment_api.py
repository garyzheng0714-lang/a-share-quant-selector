import unittest
from unittest.mock import patch

from flask import Flask

from views.quant_pick_api import quant_pick_bp


CURRENT_DECISION = {
    "run_id": "run-1",
    "trade_date": "2026-07-14",
    "strategy_version": "s1",
    "data_version": "snapshot-snap-1",
    "market": {"snapshot_id": "snap-1"},
    "candidates": [
        {
            "code": "600000",
            "name": "浦发银行",
            "industry": "银行",
            "action": "buy",
            "sector": {"score": 80},
            "baseline": {"close": 10.0, "J": 20.0, "RSI": 30.0},
            "reason_codes": [],
        },
        {
            "code": "600001",
            "name": "观察票",
            "industry": "银行",
            "action": "observe",
            "baseline": {"close": 9.0},
            "reason_codes": ["market_gate"],
        },
    ],
}
FRESHNESS = {
    "fresh": True,
    "local_date": "2026-07-14",
    "expected_date": "2026-07-14",
    "snapshot_id": "snap-1",
}


class QuantCommentApiTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.register_blueprint(quant_pick_bp)
        self.client = app.test_client()

    @patch("utils.daily_pick.generate_quant_comment")
    @patch(
        "utils.daily_pick.get_quant_comment",
        return_value={
            "decision_run_id": "run-1",
            "prompt_version": "cloud-stair-explainer-v3",
            "market_note": "已记录",
            "by_code": {"600000": {"comment": "x", "risk": "y"}},
        },
    )
    @patch(
        "views.quant_pick_api._current_close_decision",
        return_value=(
            CURRENT_DECISION,
            FRESHNESS,
            None,
        ),
    )
    def test_comment_only_reads_persisted_result(
        self,
        _current,
        persisted,
        generate,
    ):
        response = self.client.get("/api/quant-comment")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["available"])
        self.assertEqual(response.json["decision_run_id"], "run-1")
        persisted.assert_called_once_with("2026-07-14")
        generate.assert_not_called()

    @patch(
        "utils.daily_pick.get_quant_comment",
        return_value={
            "decision_run_id": "old-run",
            "by_code": {},
        },
    )
    @patch(
        "views.quant_pick_api._current_close_decision",
        return_value=(
            CURRENT_DECISION,
            FRESHNESS,
            None,
        ),
    )
    def test_stale_comment_is_not_mixed_with_current_decision(
        self, _current, _persisted
    ):
        response = self.client.get("/api/quant-comment")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json["reason"], "comment_not_ready")

    @patch("utils.hierarchical_decision.run_close_decision")
    @patch(
        "views.quant_pick_api._current_close_decision",
        return_value=(
            CURRENT_DECISION,
            FRESHNESS,
            None,
        ),
    )
    def test_quant_pick_is_read_only_and_exposes_canonical_decision(
        self, _current, run_close
    ):
        response = self.client.get("/api/quant-pick")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [row["code"] for row in response.json["today_buy"]], ["600000"]
        )
        self.assertEqual(response.json["decision"]["run_id"], "run-1")
        run_close.assert_not_called()

    @patch(
        "views.quant_pick_api._current_close_decision",
        return_value=(
            None,
            {"fresh": False},
            "stale_market_data",
        ),
    )
    def test_quant_pick_fails_closed_when_snapshot_is_stale(self, _current):
        response = self.client.get("/api/quant-pick")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json["reason"], "stale_market_data")


if __name__ == "__main__":
    unittest.main()
