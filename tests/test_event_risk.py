import unittest
from unittest.mock import patch

from utils.event_risk import HARD_PATTERNS, REVIEW_PATTERNS, _match, review_candidates


class EventRiskTest(unittest.TestCase):
    def test_hard_and_review_patterns_are_separate(self):
        self.assertIn(
            "investigation", _match("关于收到立案调查告知书的公告", HARD_PATTERNS)
        )
        self.assertEqual(_match("股东减持计划公告", HARD_PATTERNS), [])
        self.assertIn("reduction", _match("股东减持计划公告", REVIEW_PATTERNS))

    def test_negated_risk_title_is_not_treated_as_hard_event(self):
        self.assertEqual(_match("公司无重大诉讼事项的说明", HARD_PATTERNS), [])

    @patch("utils.event_risk._call_event_llm")
    @patch("utils.event_risk.fetch_notice_events")
    def test_llm_is_not_called_when_veto_switch_is_off(self, fetch, llm):
        fetch.return_value = {
            "available": True,
            "events": [],
            "errors": [],
            "source_refs": ["test-source"],
        }
        result = review_candidates(
            [{"code": "600000"}], "2026-07-14", "2026-07-15T08:45:00+08:00", False
        )
        llm.assert_not_called()
        self.assertTrue(result["available"])
        self.assertEqual(result["llm"]["reason"], "llm_label_disabled")

    @patch("utils.event_risk.fetch_notice_events")
    def test_date_precision_event_requires_review_instead_of_auto_veto(self, fetch):
        fetch.return_value = {
            "available": True,
            "events": [
                {
                    "event_id": "event-1",
                    "code": "600000",
                    "title": "重大诉讼公告",
                    "published_at": "2026-07-14T00:00:00+08:00",
                    "published_at_precision": "date",
                    "hard_tags": ["debt_or_fraud"],
                    "review_tags": [],
                }
            ],
            "errors": [],
            "source_refs": ["test-source"],
        }

        result = review_candidates(
            [{"code": "600000"}], "2026-07-14", "2026-07-15T08:45:00+08:00", False
        )

        self.assertEqual(result["veto_codes"], [])
        self.assertEqual(result["review_codes"], ["600000"])

    @patch("utils.event_risk._call_event_llm")
    @patch("utils.event_risk.fetch_notice_events")
    def test_llm_veto_label_never_changes_candidate_action(self, fetch, llm):
        fetch.return_value = {
            "available": True,
            "events": [
                {
                    "event_id": "event-2",
                    "code": "600000",
                    "title": "普通经营公告",
                    "published_at": "2026-07-14T20:00:00+08:00",
                    "published_at_precision": "second",
                    "hard_tags": [],
                    "review_tags": [],
                }
            ],
            "errors": [],
            "source_refs": ["test-source"],
        }
        llm.return_value = {
            "available": True,
            "decisions": [
                {
                    "event_id": "event-2",
                    "code": "600000",
                    "action": "veto",
                    "confidence": 1.0,
                }
            ],
        }

        result = review_candidates(
            [{"code": "600000"}],
            "2026-07-14",
            "2026-07-15T08:45:00+08:00",
            True,
        )

        self.assertEqual(result["veto_codes"], [])
        self.assertFalse(result["llm_action_applied"])


if __name__ == "__main__":
    unittest.main()
