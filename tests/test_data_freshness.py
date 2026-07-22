import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from utils.data_freshness import (
    expected_completed_trade_date,
    local_data_status,
    next_trade_date,
)


class DataFreshnessTest(unittest.TestCase):
    @staticmethod
    def _snapshot(**overrides):
        manifest = {
            "trade_date": "2026-07-14",
            "future_rows": 0,
            "coverage_ratio": 0.99,
            "anchor_dates": {
                "000001": "2026-07-14",
                "600030": "2026-07-14",
                "600036": "2026-07-14",
                "600519": "2026-07-14",
            },
            "anchor_quorum": 4,
            "source_quorum_passed": True,
            "schema_errors": 0,
            "synthetic_rows": 0,
            "source_set": ["akshare", "tencent"],
        }
        manifest.update(overrides)
        return {
            "available": True,
            "snapshot_id": "a" * 64,
            "manifest": manifest,
            "payload_dir": "/tmp/not-used",
        }

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
    def test_cutoff_is_exactly_1505(self, calendar):
        calendar.return_value = ["2026-07-14", "2026-07-15"]
        zone = ZoneInfo("Asia/Shanghai")
        self.assertEqual(
            expected_completed_trade_date(
                datetime(2026, 7, 15, 15, 4, 59, tzinfo=zone)
            ),
            "2026-07-14",
        )
        self.assertEqual(
            expected_completed_trade_date(datetime(2026, 7, 15, 15, 5, tzinfo=zone)),
            "2026-07-15",
        )

    @patch("utils.data_freshness._trade_calendar", return_value=[])
    def test_calendar_failure_does_not_guess_weekdays(self, _calendar):
        as_of = datetime(2026, 7, 15, 15, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
        self.assertEqual(expected_completed_trade_date(as_of), "")

    def test_unpublished_root_calendar_requires_explicit_ingestion_opt_in(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "trade_calendar.json").write_text(
                json.dumps(["2026-07-15"]), encoding="utf-8"
            )
            as_of = datetime(2026, 7, 15, 16, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
            with patch(
                "utils.data_freshness.load_current_market_snapshot",
                return_value={"available": False},
            ):
                production = expected_completed_trade_date(as_of, data_dir=root)
                staging = expected_completed_trade_date(
                    as_of,
                    data_dir=root,
                    allow_unpublished_calendar=True,
                )

        self.assertEqual(production, "")
        self.assertEqual(staging, "2026-07-15")

    def test_pinned_snapshot_never_falls_back_to_mutable_root_calendar(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = root / "market_snapshots" / ("a" * 64) / "payload"
            payload.mkdir(parents=True)
            (root / "trade_calendar.json").write_text(
                json.dumps(["2026-07-15"]), encoding="utf-8"
            )
            with patch(
                "utils.data_freshness.load_market_snapshot",
                return_value={"available": True, "payload_dir": str(payload)},
            ):
                result = expected_completed_trade_date(
                    datetime(
                        2026,
                        7,
                        15,
                        16,
                        0,
                        tzinfo=ZoneInfo("Asia/Shanghai"),
                    ),
                    data_dir=root,
                    snapshot_id="a" * 64,
                )

        self.assertEqual(result, "")

    @patch("utils.data_freshness._trade_calendar")
    def test_next_session_is_explicit(self, calendar):
        calendar.return_value = ["2026-07-14", "2026-07-15", "2026-07-16"]
        self.assertEqual(next_trade_date("2026-07-14"), "2026-07-15")

    @patch(
        "utils.data_freshness.expected_completed_trade_date", return_value="2026-07-14"
    )
    @patch("utils.data_freshness.load_current_market_snapshot")
    def test_validated_exact_date_snapshot_is_fresh(self, load, _expected):
        load.return_value = self._snapshot()
        status = local_data_status()
        self.assertTrue(status["fresh"])
        self.assertEqual(status["snapshot_id"], "a" * 64)

    @patch(
        "utils.data_freshness.expected_completed_trade_date", return_value="2026-07-14"
    )
    @patch("utils.data_freshness.load_current_market_snapshot")
    def test_future_date_does_not_pass_exact_date_gate(self, load, _expected):
        load.return_value = self._snapshot(trade_date="2026-07-15")
        status = local_data_status()
        self.assertFalse(status["fresh"])
        self.assertIn("trade_date_mismatch", status["reason_codes"])

    @patch(
        "utils.data_freshness.expected_completed_trade_date", return_value="2026-07-14"
    )
    @patch("utils.data_freshness.load_current_market_snapshot")
    def test_one_anchor_cannot_report_fresh(self, load, _expected):
        load.return_value = self._snapshot(anchor_quorum=1)
        status = local_data_status()
        self.assertFalse(status["fresh"])
        self.assertIn("anchor_quorum_failed", status["reason_codes"])

    @patch(
        "utils.data_freshness.expected_completed_trade_date", return_value="2026-07-14"
    )
    @patch("utils.data_freshness.load_current_market_snapshot")
    def test_anchor_quorum_matrix(self, load, _expected):
        for quorum, should_pass in (
            (0, False),
            (1, False),
            (2, False),
            (3, True),
            (4, True),
        ):
            with self.subTest(quorum=quorum):
                load.return_value = self._snapshot(anchor_quorum=quorum)
                self.assertEqual(local_data_status()["fresh"], should_pass)

    @patch(
        "utils.data_freshness.expected_completed_trade_date", return_value="2026-07-14"
    )
    @patch("utils.data_freshness.load_current_market_snapshot")
    def test_quality_failures_are_never_reported_fresh(self, load, _expected):
        cases = (
            ({"future_rows": 1}, "future_market_data"),
            ({"source_quorum_passed": False}, "source_quorum_failed"),
            ({"schema_errors": 1}, "schema_validation_failed"),
            ({"synthetic_rows": 1}, "synthetic_market_data"),
        )
        for override, reason in cases:
            with self.subTest(reason=reason):
                load.return_value = self._snapshot(**override)
                status = local_data_status()
                self.assertFalse(status["fresh"])
                self.assertIn(reason, status["reason_codes"])

    @patch(
        "utils.data_freshness.expected_completed_trade_date", return_value="2026-07-14"
    )
    @patch("utils.data_freshness.load_current_market_snapshot")
    def test_low_coverage_cannot_report_fresh(self, load, _expected):
        load.return_value = self._snapshot(coverage_ratio=0.5)
        status = local_data_status()
        self.assertFalse(status["fresh"])
        self.assertIn("coverage_below_threshold", status["reason_codes"])

    @patch(
        "utils.data_freshness.expected_completed_trade_date", return_value="2026-07-14"
    )
    @patch("utils.data_freshness.load_current_market_snapshot")
    def test_missing_snapshot_fails_closed(self, load, _expected):
        load.return_value = {"available": False, "reason": "snapshot_pointer_missing"}
        status = local_data_status()
        self.assertFalse(status["fresh"])
        self.assertEqual(status["reason"], "snapshot_pointer_missing")


if __name__ == "__main__":
    unittest.main()
