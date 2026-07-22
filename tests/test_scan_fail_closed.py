import unittest

from strategy.factors import FACTOR_REGISTRY
from utils.csv_manager import MarketDataReadError
from utils.factor_scan import compute_scan as compute_factor_scan
from utils.super_b1_scan import compute_scan as compute_super_b1_scan


class BrokenManager:
    base_data_dir = "data"
    snapshot_id = None

    @staticmethod
    def list_all_stocks():
        return ["600000"]

    @staticmethod
    def read_stock(_code, nrows=None):
        raise MarketDataReadError("unreadable_market_file:600000")


class ScanFailClosedTest(unittest.TestCase):
    def test_factor_scan_rejects_even_one_market_read_error(self):
        strategy = next(iter(FACTOR_REGISTRY))

        result = compute_factor_scan(
            BrokenManager(),
            {"600000": "浦发银行"},
            [strategy],
            trade_date="2026-07-14",
        )

        self.assertFalse(result["available"])
        self.assertIn("1/1", result["reason"])

    def test_super_b1_scan_rejects_even_one_market_read_error(self):
        result = compute_super_b1_scan(
            BrokenManager(),
            {"600000": "浦发银行"},
        )

        self.assertFalse(result["available"])
        self.assertIn("1/1", result["reason"])


if __name__ == "__main__":
    unittest.main()
