import unittest

import pandas as pd

from utils.execution_model import CostModel, evaluate_trade, limit_price


class ExecutionModelTest(unittest.TestCase):
    def _daily(self, rows):
        return pd.DataFrame(rows)

    def test_limit_price_uses_exchange_rounding(self):
        self.assertEqual(limit_price(10.05, "up"), 11.06)
        self.assertEqual(limit_price(10.05, "down"), 9.05)

    def test_one_word_limit_up_is_unbuyable(self):
        daily = self._daily([
            {"date": "2026-01-05", "open": 10, "high": 10.1, "low": 9.9, "close": 10, "volume": 100},
            {"date": "2026-01-06", "open": 11, "high": 11, "low": 11, "close": 11, "volume": 10},
        ])
        result = evaluate_trade(daily, "2026-01-05", hold_days=1)
        self.assertFalse(result["entry_feasible"])
        self.assertEqual(result["reason"], "entry_unbuyable")

    def test_limit_down_exit_is_delayed(self):
        daily = self._daily([
            {"date": "2026-01-05", "open": 10, "high": 10, "low": 10, "close": 10, "volume": 100},
            {"date": "2026-01-06", "open": 10, "high": 10.2, "low": 9.8, "close": 10, "volume": 100},
            {"date": "2026-01-07", "open": 9, "high": 9, "low": 9, "close": 9, "volume": 10},
            {"date": "2026-01-08", "open": 9.1, "high": 9.3, "low": 8.9, "close": 9.2, "volume": 100},
        ])
        result = evaluate_trade(
            daily, "2026-01-05", hold_days=2,
            costs=CostModel(commission_rate=0, stamp_duty_sell_rate=0, slippage_bps_each_side=0),
        )
        self.assertTrue(result["exit_feasible"])
        self.assertEqual(result["exit_delay_days"], 1)
        self.assertEqual(result["exit_date"], "2026-01-08")
        self.assertEqual(result["net_return"], -8.0)


if __name__ == "__main__":
    unittest.main()
