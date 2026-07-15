import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from utils.akshare_fetcher import AKShareFetcher


class UniverseExpansionTest(unittest.TestCase):
    @staticmethod
    def _history(rows):
        dates = pd.date_range("2024-01-01", periods=rows, freq="B")
        return pd.DataFrame({
            "date": dates, "open": 10, "high": 11, "low": 9,
            "close": 10, "volume": 100,
        })

    @patch("utils.akshare_fetcher.time.sleep", return_value=None)
    def test_missing_main_board_stock_is_added_with_training_history(self, _sleep):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = AKShareFetcher(tmp)
            fetcher.get_all_stock_codes = lambda: {"002020": "京新药业", "300001": "特锐德"}
            dates = pd.date_range("2025-01-01", periods=220, freq="B")
            history = pd.DataFrame({
                "date": dates, "open": 10, "high": 11, "low": 9,
                "close": 10, "volume": 100,
            })
            fetcher.fetch_stock_history = lambda code, years: history.copy()

            result = fetcher.expand_universe(max_new=10, years=2)

            self.assertEqual(result["added"], 1)
            self.assertTrue(fetcher.csv_manager.stock_exists("002020"))
            self.assertFalse(fetcher.csv_manager.stock_exists("300001"))

    @patch("utils.akshare_fetcher.time.sleep", return_value=None)
    def test_checkpoint_resumes_without_redownloading_completed_stock(self, _sleep):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = AKShareFetcher(tmp)
            fetcher.get_all_stock_codes = lambda: {"002020": "京新药业", "600000": "浦发银行"}
            calls = []

            def first_pass(code, years):
                calls.append(code)
                return self._history(220) if code == "002020" else None

            fetcher.fetch_stock_history = first_pass
            first = fetcher.bootstrap_universe()
            self.assertEqual(first["added"], 1)
            self.assertEqual(first["failed"], 1)

            calls.clear()
            fetcher.fetch_stock_history = lambda code, years: calls.append(code) or self._history(220)
            second = fetcher.bootstrap_universe()
            self.assertEqual(calls, ["600000"])
            self.assertEqual(second["covered_count"], 2)
            self.assertEqual(second["remaining_count"], 0)

    def test_short_listing_is_covered_but_not_counted_as_training_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = AKShareFetcher(tmp)
            fetcher.get_all_stock_codes = lambda: {"001386": "雪祺电气"}
            fetcher.fetch_stock_history = lambda code, years: self._history(80)
            result = fetcher.bootstrap_universe()
            self.assertEqual(result["covered_count"], 1)
            self.assertEqual(result["trainable_count"], 0)
            self.assertEqual(result["trainable_eligible_count"], 0)
            self.assertEqual(result["short_history_count"], 1)


if __name__ == "__main__":
    unittest.main()
