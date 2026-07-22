import unittest

import pandas as pd

from utils.execution_model import (
    CostModel,
    enrich_security_state_with_history,
    evaluate_trade,
    limit_price,
    resolve_price_limit_regime,
    security_state_from_name,
)


class ExecutionModelTest(unittest.TestCase):
    def _daily(self, rows):
        return pd.DataFrame(rows)

    def test_limit_price_uses_exchange_rounding(self):
        self.assertEqual(limit_price(10.05, "up"), 11.06)
        self.assertEqual(limit_price(10.05, "down"), 9.05)

    def test_one_word_limit_up_is_unbuyable(self):
        daily = self._daily(
            [
                {
                    "date": "2026-01-05",
                    "open": 10,
                    "high": 10.1,
                    "low": 9.9,
                    "close": 10,
                    "volume": 100,
                },
                {
                    "date": "2026-01-06",
                    "open": 11,
                    "high": 11,
                    "low": 11,
                    "close": 11,
                    "volume": 10,
                },
            ]
        )
        result = evaluate_trade(daily, "2026-01-05", hold_days=1)
        self.assertFalse(result["entry_feasible"])
        self.assertEqual(result["reason"], "entry_unbuyable")

    def test_limit_down_exit_is_delayed(self):
        daily = self._daily(
            [
                {
                    "date": "2026-01-05",
                    "open": 10,
                    "high": 10,
                    "low": 10,
                    "close": 10,
                    "volume": 100,
                },
                {
                    "date": "2026-01-06",
                    "open": 10,
                    "high": 10.2,
                    "low": 9.8,
                    "close": 10,
                    "volume": 100,
                },
                {
                    "date": "2026-01-07",
                    "open": 9,
                    "high": 9,
                    "low": 9,
                    "close": 9,
                    "volume": 10,
                },
                {
                    "date": "2026-01-08",
                    "open": 9.1,
                    "high": 9.3,
                    "low": 8.9,
                    "close": 9.2,
                    "volume": 100,
                },
            ]
        )
        result = evaluate_trade(
            daily,
            "2026-01-05",
            hold_days=1,
            costs=CostModel(
                commission_rate=0,
                stamp_duty_sell_rate=0,
                slippage_bps_each_side=0,
                minimum_commission=0,
                transfer_fee_rate=0,
            ),
        )
        self.assertTrue(result["exit_feasible"])
        self.assertEqual(result["exit_delay_days"], 1)
        self.assertEqual(result["exit_date"], "2026-01-08")
        self.assertEqual(result["net_return"], -9.0)
        self.assertEqual(result["exit_price_field"], "open")

    def test_pit_st_and_board_regimes_are_not_fixed_at_ten_percent(self):
        st = resolve_price_limit_regime(
            "600000",
            "2026-01-05",
            security_state_from_name("*ST测试", "2026-01-05"),
        )
        chinext = resolve_price_limit_regime(
            "300001",
            "2026-01-05",
            security_state_from_name("测试", "2026-01-05"),
        )

        self.assertEqual(st["limit_pct"], 0.05)
        self.assertEqual(chinext["limit_pct"], 0.20)
        self.assertFalse(st["point_in_time_verified"])
        verified = resolve_price_limit_regime(
            "600000",
            "2026-01-05",
            enrich_security_state_with_history(
                security_state_from_name("*ST测试", "2026-01-05"),
                6,
            ),
        )
        self.assertTrue(verified["point_in_time_verified"])

    def test_initial_listing_regimes_are_explicit_and_directional(self):
        star_state = {
            **security_state_from_name("测试", "2026-01-05"),
            "listing_rule_verified": True,
            "listing_session_number": 3,
        }
        star = resolve_price_limit_regime("688001", "2026-01-05", star_state)
        self.assertIsNone(star["limit_up_pct"])
        self.assertEqual(star["rule"], "star_first_five_sessions")

        legacy_state = {
            **security_state_from_name("测试", "2020-01-02"),
            "listing_rule_verified": True,
            "listing_session_number": 1,
        }
        legacy = resolve_price_limit_regime("600001", "2020-01-02", legacy_state)
        self.assertEqual(legacy["limit_up_pct"], 0.44)
        self.assertEqual(legacy["limit_down_pct"], 0.36)

    def test_required_pit_state_missing_fails_closed(self):
        daily = self._daily(
            [
                {
                    "date": "2026-01-05",
                    "open": 10,
                    "high": 10,
                    "low": 10,
                    "close": 10,
                    "volume": 100,
                },
                {
                    "date": "2026-01-06",
                    "open": 10,
                    "high": 10,
                    "low": 10,
                    "close": 10,
                    "volume": 100,
                },
            ]
        )

        result = evaluate_trade(
            daily,
            "2026-01-05",
            hold_days=1,
            code="600000",
            require_pit_status=True,
        )

        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "pit_security_state_missing")


if __name__ == "__main__":
    unittest.main()
