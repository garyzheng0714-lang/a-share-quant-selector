import unittest
from unittest.mock import patch

from utils.ai_decision import run_ai_decision


class AiDecisionTest(unittest.TestCase):
    @patch("utils.ai_decision.save_ai_decision_run", return_value="ai-1")
    def test_no_approved_pool_is_visible_without_calling_llm(self, save):
        decision = {
            "run_id": "run-1", "trade_date": "2026-07-14",
            "strategy_version": "s1", "model_version": "baseline-only",
            "candidates": [{
                "code": "600000", "action": "observe",
                "reason_codes": ["market_model_unvalidated"],
            }],
        }

        result = run_ai_decision(decision)

        self.assertFalse(result["available"])
        self.assertEqual(result["status"], "not_called")
        self.assertEqual(result["reason_codes"], ["no_approved_candidates"])
        save.assert_called_once()


if __name__ == "__main__":
    unittest.main()
