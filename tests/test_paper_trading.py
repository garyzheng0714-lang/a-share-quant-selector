import tempfile
import unittest
from pathlib import Path

import pandas as pd

import views.view_manager as view_manager
from utils.csv_manager import CSVManager
from utils.paper_trading import (
    create_paper_order, ensure_default_account, execute_pending_orders,
    get_paper_status, run_daily_paper_cycle,
)


class PaperTradingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original = view_manager.DB_PATH
        view_manager.DB_PATH = Path(self.tmp.name) / "test.db"
        self.manager = CSVManager(Path(self.tmp.name) / "data")

    def tearDown(self):
        view_manager.DB_PATH = self.original
        self.tmp.cleanup()

    def _write_prices(self, rows):
        self.manager.write_stock("600000", pd.DataFrame(rows))

    def test_empty_account_still_records_daily_nav_and_reconciles(self):
        result = run_daily_paper_cycle("2026-01-05", self.manager)

        self.assertTrue(result["reconciliation"]["balanced"])
        self.assertEqual(result["status"]["cash"], 1_000_000.0)
        self.assertEqual(result["status"]["market_value"], 0.0)
        self.assertEqual(result["status"]["total_equity"], 1_000_000.0)

    def test_buy_uses_board_lot_and_same_day_sell_is_t1_locked(self):
        self._write_prices([
            {"date": "2026-01-05", "open": 9.8, "high": 10.2, "low": 9.7,
             "close": 10.0, "volume": 1000},
            {"date": "2026-01-06", "open": 10.0, "high": 10.5, "low": 9.9,
             "close": 10.4, "volume": 1000},
            {"date": "2026-01-07", "open": 10.3, "high": 10.6, "low": 10.1,
             "close": 10.5, "volume": 1000},
        ])
        account = ensure_default_account(initial_cash=100_000)
        create_paper_order(
            account["account_id"], "600000", "buy", "2026-01-05", "2026-01-06",
            target_weight=0.5, decision_run_id="run-1",
        )

        fills = execute_pending_orders("2026-01-06", self.manager, account["account_id"])
        buy = next(row for row in fills if row["side"] == "buy")
        self.assertEqual(buy["outcome"], "filled")
        self.assertEqual(buy["quantity"] % 100, 0)
        self.assertGreater(buy["quantity"], 0)

        create_paper_order(
            account["account_id"], "600000", "sell", "2026-01-06", "2026-01-06",
            requested_quantity=buy["quantity"], decision_run_id="exit-1",
        )
        locked = execute_pending_orders("2026-01-06", self.manager, account["account_id"])
        self.assertEqual(locked[0]["outcome"], "deferred")
        self.assertEqual(locked[0]["reason_code"], "t_plus_one_locked")

        sold = execute_pending_orders("2026-01-07", self.manager, account["account_id"])
        self.assertEqual(sold[0]["outcome"], "filled")
        self.assertEqual(get_paper_status(account["account_id"], self.manager)["positions"], [])

    def test_one_word_limit_up_never_creates_fake_fill(self):
        self._write_prices([
            {"date": "2026-01-05", "open": 10.0, "high": 10.0, "low": 10.0,
             "close": 10.0, "volume": 1000},
            {"date": "2026-01-06", "open": 11.0, "high": 11.0, "low": 11.0,
             "close": 11.0, "volume": 1000},
        ])
        account = ensure_default_account(initial_cash=100_000)
        create_paper_order(
            account["account_id"], "600000", "buy", "2026-01-05", "2026-01-06",
            target_weight=0.5,
        )

        fills = execute_pending_orders("2026-01-06", self.manager, account["account_id"])

        self.assertEqual(fills[0]["outcome"], "rejected")
        self.assertEqual(fills[0]["reason_code"], "one_word_limit_up")
        status = get_paper_status(account["account_id"], self.manager)
        self.assertEqual(status["cash"], 100_000.0)
        self.assertEqual(status["positions"], [])


if __name__ == "__main__":
    unittest.main()
