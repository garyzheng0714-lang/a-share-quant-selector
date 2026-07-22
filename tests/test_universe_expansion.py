import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from utils.akshare_fetcher import AKShareFetcher
from utils.data_contracts import FetchResult


class UniverseExpansionTest(unittest.TestCase):
    TARGET_DATE = "2026-07-14"

    @staticmethod
    def _calendar(root):
        Path(root, "trade_calendar.json").write_text(
            json.dumps([UniverseExpansionTest.TARGET_DATE]),
            encoding="utf-8",
        )

    @staticmethod
    def _history(rows):
        dates = pd.date_range(
            end=UniverseExpansionTest.TARGET_DATE, periods=rows, freq="B"
        )
        return pd.DataFrame(
            {
                "date": dates,
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10,
                "volume": 100,
            }
        )

    @patch(
        "utils.data_freshness.expected_completed_trade_date",
        return_value=TARGET_DATE,
    )
    @patch("utils.akshare_fetcher.time.sleep", return_value=None)
    def test_missing_main_board_stock_is_added_with_training_history(
        self, _sleep, _cutoff
    ):
        with tempfile.TemporaryDirectory() as tmp:
            self._calendar(tmp)
            fetcher = AKShareFetcher(tmp)
            fetcher.get_all_stock_codes = lambda: {
                "002020": "京新药业",
                "300001": "特锐德",
            }
            dates = pd.date_range(end=self.TARGET_DATE, periods=220, freq="B")
            history = pd.DataFrame(
                {
                    "date": dates,
                    "open": 10,
                    "high": 11,
                    "low": 9,
                    "close": 10,
                    "volume": 100,
                }
            )
            fetcher.fetch_stock_history = lambda code, years: FetchResult.ok(
                history,
                source="test",
            )

            result = fetcher.expand_universe(max_new=10, years=2)

            self.assertEqual(result["added"], 1)
            self.assertTrue(fetcher.csv_manager.stock_exists("002020"))
            self.assertFalse(fetcher.csv_manager.stock_exists("300001"))

    @patch(
        "utils.data_freshness.expected_completed_trade_date",
        return_value=TARGET_DATE,
    )
    @patch("utils.akshare_fetcher.time.sleep", return_value=None)
    def test_checkpoint_resumes_without_redownloading_completed_stock(
        self, _sleep, _cutoff
    ):
        with tempfile.TemporaryDirectory() as tmp:
            self._calendar(tmp)
            fetcher = AKShareFetcher(tmp)
            fetcher.get_all_stock_codes = lambda: {
                "002020": "京新药业",
                "600000": "浦发银行",
            }
            calls = []

            def first_pass(code, years):
                calls.append(code)
                if code == "002020":
                    return FetchResult.ok(self._history(220), source="test")
                return FetchResult.failure(source="test", reason="source_failed")

            fetcher.fetch_stock_history = first_pass
            first = fetcher.bootstrap_universe()
            self.assertEqual(first["added"], 1)
            self.assertEqual(first["failed"], 1)

            calls.clear()
            fetcher.fetch_stock_history = lambda code, years: (
                calls.append(code) or FetchResult.ok(self._history(220), source="test")
            )
            second = fetcher.bootstrap_universe()
            self.assertEqual(calls, ["600000"])
            self.assertEqual(second["covered_count"], 2)
            self.assertEqual(second["remaining_count"], 0)

    @patch(
        "utils.data_freshness.expected_completed_trade_date",
        return_value=TARGET_DATE,
    )
    def test_short_listing_is_covered_but_not_counted_as_training_failure(
        self, _cutoff
    ):
        with tempfile.TemporaryDirectory() as tmp:
            self._calendar(tmp)
            fetcher = AKShareFetcher(tmp)
            fetcher.get_all_stock_codes = lambda: {"001386": "雪祺电气"}
            fetcher.fetch_stock_history = lambda code, years: FetchResult.ok(
                self._history(80),
                source="test",
            )
            result = fetcher.bootstrap_universe()
            self.assertEqual(result["covered_count"], 1)
            self.assertEqual(result["trainable_count"], 0)
            self.assertEqual(result["trainable_eligible_count"], 0)
            self.assertEqual(result["short_history_count"], 1)

    @patch(
        "utils.data_freshness.expected_completed_trade_date",
        return_value=TARGET_DATE,
    )
    def test_one_session_new_listing_is_kept_but_not_trainable(self, _cutoff):
        with tempfile.TemporaryDirectory() as tmp:
            self._calendar(tmp)
            fetcher = AKShareFetcher(tmp)
            fetcher.get_all_stock_codes = lambda: {"001399": "新上市股"}
            fetcher.fetch_stock_history = lambda code, years: FetchResult.ok(
                self._history(1),
                source="test",
            )

            result = fetcher.bootstrap_universe()

            self.assertEqual(result["failed"], 0)
            self.assertEqual(result["covered_count"], 1)
            self.assertEqual(result["trainable_count"], 0)
            self.assertEqual(result["short_history_count"], 1)

    @patch(
        "utils.data_freshness.expected_completed_trade_date", return_value="2026-07-14"
    )
    def test_bootstrap_drops_unfinished_intraday_bar(self, _cutoff):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = AKShareFetcher(tmp)
            fetcher.get_all_stock_codes = lambda: {"600000": "浦发银行"}
            history = self._history(220)
            history["date"] = pd.date_range(end="2026-07-14", periods=220, freq="B")
            unfinished = history.iloc[[-1]].copy()
            unfinished["date"] = pd.Timestamp("2026-07-15")
            fetcher.fetch_stock_history = lambda code, years: FetchResult.ok(
                pd.concat([history, unfinished], ignore_index=True),
                source="test",
            )

            result = fetcher.bootstrap_universe()
            saved = fetcher.csv_manager.read_stock("600000")
            self.assertEqual(result["trainable_count"], 1)
            self.assertEqual(str(saved.iloc[0]["date"])[:10], "2026-07-14")


if __name__ == "__main__":
    unittest.main()
