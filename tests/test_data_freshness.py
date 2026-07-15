import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from utils.data_freshness import expected_completed_trade_date, next_trade_date


class DataFreshnessTest(unittest.TestCase):
    @patch("utils.data_freshness._trade_calendar")
    def test_intraday_requires_previous_completed_session(self, calendar):
        calendar.return_value = ["2026-07-13", "2026-07-14", "2026-07-15"]
        as_of = datetime(2026, 7, 15, 10, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
        self.assertEqual(expected_completed_trade_date(as_of), "2026-07-14")

    @patch("utils.data_freshness._trade_calendar")
    def test_after_close_accepts_current_session(self, calendar):
        calendar.return_value = ["2026-07-14", "2026-07-15"]
        as_of = datetime(2026, 7, 15, 15, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
        self.assertEqual(expected_completed_trade_date(as_of), "2026-07-15")

    @patch("utils.data_freshness._trade_calendar")
    def test_next_session_is_explicit(self, calendar):
        calendar.return_value = ["2026-07-14", "2026-07-15", "2026-07-16"]
        self.assertEqual(next_trade_date("2026-07-14"), "2026-07-15")


if __name__ == "__main__":
    unittest.main()
