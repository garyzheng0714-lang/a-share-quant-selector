import unittest
from unittest.mock import patch

from utils.event_risk import HARD_PATTERNS, REVIEW_PATTERNS, _match, review_candidates


class EventRiskTest(unittest.TestCase):
    def test_hard_and_review_patterns_are_separate(self):
        self.assertIn("investigation", _match("关于收到立案调查告知书的公告", HARD_PATTERNS))
        self.assertEqual(_match("股东减持计划公告", HARD_PATTERNS), [])
        self.assertIn("reduction", _match("股东减持计划公告", REVIEW_PATTERNS))

    @patch("utils.event_risk._call_event_llm")
    @patch("utils.event_risk.fetch_notice_events")
    def test_llm_is_not_called_when_veto_switch_is_off(self, fetch, llm):
        fetch.return_value = {
            "available": True, "events": [], "errors": [], "source_refs": ["test-source"]
        }
        result = review_candidates(
            [{"code": "600000"}], "2026-07-14", "2026-07-15T08:45:00+08:00", False
        )
        llm.assert_not_called()
        self.assertTrue(result["available"])
        self.assertEqual(result["llm"]["reason"], "llm_veto_disabled")


if __name__ == "__main__":
    unittest.main()
