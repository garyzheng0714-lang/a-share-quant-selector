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

    @patch("utils.ai_decision.save_ai_decision_run", return_value="ai-1")
    def test_no_approved_pool_is_visible_without_calling_llm(self, save):
        decision = {
            "run_id": "run-1",
            "trade_date": "2026-07-14",
            "strategy_version": "s1",
            "model_version": "baseline-only",
            "candidates": [
                {
                    "code": "600000",
                    "action": "observe",
                    "reason_codes": ["market_model_unvalidated"],
                }
            ],
        }

        result = run_ai_decision(decision)

        self.assertFalse(result["available"])
        self.assertEqual(result["status"], "not_called")
        self.assertEqual(result["reason_codes"], ["no_approved_candidates"])
        save.assert_called_once()

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
