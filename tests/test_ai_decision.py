import unittest
from unittest.mock import MagicMock, patch

from utils.ai_decision import run_ai_decision
from utils.daily_pick import generate_daily_pick, generate_quant_comment


class AiDecisionTest(unittest.TestCase):
    @patch("utils.daily_pick._call_ark")
    def test_legacy_llm_stock_selection_is_disabled_inside_service(self, call):
        result = generate_daily_pick(
            force=True,
            candidates=[{"code": "600000"}],
            run_date="2026-07-14",
        )

        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "legacy_generation_disabled")
        call.assert_not_called()

    @patch("utils.daily_pick._verify_comment_snapshot", return_value=(True, None))
    @patch("utils.daily_pick._build_comment_prompt", return_value="prompt")
    @patch(
        "utils.daily_pick._call_ark_comment",
        return_value=(
            {
                "market_note": "仅供研究",
                "comments": [{"code": "600000", "comment": "原因", "risk": "风险"}],
            },
            "model-1",
        ),
    )
    @patch("utils.daily_pick.get_api_key", return_value="secret")
    @patch(
        "utils.daily_pick._load_llm_config",
        return_value={"provider": "ark", "model": "model-1"},
    )
    @patch("utils.daily_pick.get_quant_comment", return_value=None)
    def test_llm_explanation_must_cover_every_canonical_candidate(
        self,
        _cached,
        _config,
        _key,
        _call,
        _prompt,
        _verify,
    ):
        manager = MagicMock(snapshot_id="a" * 64)

        result = generate_quant_comment(
            "2026-07-14",
            [{"code": "600000"}, {"code": "600001"}],
            decision_run_id="run-1",
            csv_manager=manager,
        )

        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "llm_output_incomplete")

    @patch(
        "utils.cloud_stair_decision.load_cloud_stair_decision",
        return_value={"available": True, "candidates": []},
    )
    @patch("utils.ai_decision.save_ai_decision_run", return_value="ai-1")
    def test_no_cloud_stair_signal_is_visible_without_calling_llm(self, save, _load):
        decision = {
            "run_id": "run-1",
            "trade_date": "2026-07-14",
            "strategy_version": "s1",
            "model_version": "baseline-only",
            "market": {"snapshot_id": "a" * 64},
            "candidates": [
                {
                    "code": "600000",
                    "action": "observe",
                    "reason_codes": ["market_model_unvalidated"],
                }
            ],
        }
        manager = MagicMock(snapshot_id="a" * 64)

        result = run_ai_decision(decision, csv_manager=manager)

        self.assertFalse(result["available"])
        self.assertEqual(result["status"], "not_called")
        self.assertEqual(result["reason_codes"], ["no_cloud_stair_signals"])
        save.assert_called_once()

    @patch(
        "utils.cloud_stair_decision.load_cloud_stair_decision",
        return_value={
            "available": True,
            "candidates": [
                {
                    "code": "600000",
                    "name": "云阶票",
                    "industry": "机械设备",
                    "action": "buy",
                }
            ],
        },
    )
    @patch(
        "utils.cloud_stair_intelligence.build_cloud_stair_intelligence",
        return_value={
            "available": True,
            "content_hash": "intelligence-1",
            "candidates": [{"code": "600000", "priority_score": 88.0}],
        },
    )
    @patch("utils.daily_pick.get_api_key", return_value="secret")
    @patch(
        "utils.daily_pick.generate_quant_comment",
        return_value={"available": True, "model": "ark-model", "by_code": {}},
    )
    @patch("utils.ai_decision.save_ai_decision_run", return_value="ai-3")
    def test_cloud_stair_signal_calls_ai_even_when_broad_decision_observes(
        self, _save, comment, _key, _intelligence, _load
    ):
        decision = {
            "run_id": "run-3",
            "trade_date": "2026-07-14",
            "strategy_version": "s1",
            "market": {"snapshot_id": "a" * 64},
            "candidates": [{"code": "600000", "action": "observe"}],
        }
        manager = MagicMock(snapshot_id="a" * 64)

        result = run_ai_decision(decision, csv_manager=manager)

        self.assertTrue(result["available"])
        self.assertEqual(result["status"], "explained")
        self.assertEqual(comment.call_args.args[1][0]["code"], "600000")

    @patch(
        "utils.cloud_stair_decision.load_cloud_stair_decision",
        return_value={
            "available": True,
            "candidates": [{"code": "600000", "action": "buy"}],
        },
    )
    @patch(
        "utils.cloud_stair_intelligence.build_cloud_stair_intelligence",
        return_value={
            "available": True,
            "content_hash": "intelligence-2",
            "candidates": [{"code": "600000", "priority_score": 80.0}],
        },
    )
    @patch("utils.daily_pick.get_api_key", return_value="secret")
    @patch(
        "utils.daily_pick.generate_quant_comment",
        return_value={"available": False, "reason": "llm_http_401"},
    )
    @patch("utils.ai_decision.save_ai_decision_run", return_value="ai-4")
    def test_ai_failure_preserves_safe_provider_reason(
        self, _save, _comment, _key, _intelligence, _load
    ):
        decision = {
            "run_id": "run-4",
            "trade_date": "2026-07-14",
            "market": {"snapshot_id": "a" * 64},
            "candidates": [{"code": "600000", "action": "buy"}],
        }
        manager = MagicMock(snapshot_id="a" * 64)

        result = run_ai_decision(decision, csv_manager=manager)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["reason_codes"], ["llm_http_401"])

    @patch("utils.ai_decision.save_ai_decision_run", return_value="ai-2")
    @patch("utils.daily_pick.generate_quant_comment")
    def test_approved_pool_requires_same_pinned_snapshot(self, comment, _save):
        decision = {
            "run_id": "run-2",
            "trade_date": "2026-07-14",
            "strategy_version": "s1",
            "model_version": "m1",
            "data_version": f"snapshot-{'a' * 64}",
            "market": {"snapshot_id": "a" * 64},
            "candidates": [{"code": "600000", "action": "buy"}],
        }
        manager = MagicMock(snapshot_id="b" * 64)

        result = run_ai_decision(decision, csv_manager=manager)

        self.assertEqual(result["status"], "not_called")
        self.assertEqual(result["reason_codes"], ["decision_snapshot_not_pinned"])
        comment.assert_not_called()


if __name__ == "__main__":
    unittest.main()
