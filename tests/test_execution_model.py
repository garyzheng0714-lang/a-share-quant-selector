import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from utils.execution_model import (
    CostModel,
    enrich_security_state_with_history,
    evaluate_trade,
    load_exchange_sessions,
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
        result = evaluate_trade(
            daily,
            "2026-01-05",
            hold_days=1,
            trading_sessions=["2026-01-05", "2026-01-06"],
        )
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
            trading_sessions=[
                "2026-01-05",
                "2026-01-06",
                "2026-01-07",
                "2026-01-08",
            ],
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
            trading_sessions=["2026-01-05", "2026-01-06"],
            require_pit_status=True,
        )

        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "pit_security_state_missing")

    def test_missing_entry_bar_does_not_buy_on_reopen(self):
        daily = self._daily(
            [
                {
                    "date": "2026-01-05",
                    "open": 10,
                    "high": 10.2,
                    "low": 9.9,
                    "close": 10,
                    "volume": 100,
                },
                {
                    "date": "2026-01-07",
                    "open": 10.5,
                    "high": 10.7,
                    "low": 10.4,
                    "close": 10.6,
                    "volume": 100,
                },
            ]
        )

        result = evaluate_trade(
            daily,
            "2026-01-05",
            hold_days=1,
            trading_sessions=["2026-01-05", "2026-01-06", "2026-01-07"],
            security_states={
                "2026-01-06": {
                    "as_of": "2026-01-06",
                    "is_st": False,
                    "trading_status": "suspended",
                    "source": "test-pit-status",
                    "listing_rule_verified": True,
                    "listing_session_number": 100,
                }
            },
        )

        self.assertTrue(result["available"])
        self.assertEqual(result["entry_date"], "2026-01-06")
        self.assertFalse(result["entry_bar_available"])
        self.assertIsNone(result["entry_price"])
        self.assertEqual(result["reason"], "entry_suspended")

    def test_active_security_with_missing_entry_bar_is_pending_data_gap(self):
        daily = self._daily(
            [
                {
                    "date": "2026-01-05",
                    "open": 10,
                    "high": 10.2,
                    "low": 9.9,
                    "close": 10,
                    "volume": 100,
                },
                {
                    "date": "2026-01-07",
                    "open": 10.5,
                    "high": 10.7,
                    "low": 10.4,
                    "close": 10.6,
                    "volume": 100,
                },
            ]
        )
        active_state = {
            "as_of": "2026-01-06",
            "is_st": False,
            "trading_status": "active",
            "source": "test-pit-status",
            "listing_rule_verified": True,
            "listing_session_number": 100,
        }

        result = evaluate_trade(
            daily,
            "2026-01-05",
            hold_days=1,
            trading_sessions=["2026-01-05", "2026-01-06", "2026-01-07"],
            security_states={"2026-01-06": active_state},
        )

        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "market_bar_missing")
        self.assertFalse(result["entry_label_mature"])

    def test_missing_exit_bars_consume_exchange_session_delay(self):
        daily = self._daily(
            [
                {
                    "date": "2026-01-05",
                    "open": 10,
                    "high": 10.2,
                    "low": 9.9,
                    "close": 10,
                    "volume": 100,
                },
                {
                    "date": "2026-01-06",
                    "open": 10,
                    "high": 10.3,
                    "low": 9.9,
                    "close": 10.1,
                    "volume": 100,
                },
                {
                    "date": "2026-01-09",
                    "open": 10.4,
                    "high": 10.6,
                    "low": 10.3,
                    "close": 10.5,
                    "volume": 100,
                },
            ]
        )
        sessions = [
            "2026-01-05",
            "2026-01-06",
            "2026-01-07",
            "2026-01-08",
            "2026-01-09",
        ]
        suspended_states = {
            date: {
                "as_of": date,
                "is_st": False,
                "trading_status": "suspended",
                "source": "test-pit-status",
                "listing_rule_verified": True,
                "listing_session_number": 100,
            }
            for date in ("2026-01-07", "2026-01-08")
        }

        expired = evaluate_trade(
            daily,
            "2026-01-05",
            hold_days=1,
            max_exit_delay=1,
            trading_sessions=sessions,
            security_states=suspended_states,
        )
        resumed = evaluate_trade(
            daily,
            "2026-01-05",
            hold_days=1,
            max_exit_delay=2,
            trading_sessions=sessions,
            security_states=suspended_states,
        )

        self.assertEqual(expired["reason"], "exit_unsellable")
        self.assertEqual(expired["exit_delay_sessions"], 1)
        self.assertIsNone(expired["net_return"])
        self.assertEqual(resumed["exit_date"], "2026-01-09")
        self.assertEqual(resumed["exit_delay_sessions"], 2)

    def test_active_security_with_missing_exit_bar_is_pending_data_gap(self):
        daily = self._daily(
            [
                {
                    "date": "2026-01-05",
                    "open": 10,
                    "high": 10.2,
                    "low": 9.9,
                    "close": 10,
                    "volume": 100,
                },
                {
                    "date": "2026-01-06",
                    "open": 10,
                    "high": 10.3,
                    "low": 9.9,
                    "close": 10.1,
                    "volume": 100,
                },
                {
                    "date": "2026-01-08",
                    "open": 10.4,
                    "high": 10.6,
                    "low": 10.3,
                    "close": 10.5,
                    "volume": 100,
                },
            ]
        )
        active_state = {
            "as_of": "2026-01-07",
            "is_st": False,
            "trading_status": "active",
            "source": "test-pit-status",
            "listing_rule_verified": True,
            "listing_session_number": 100,
        }

        result = evaluate_trade(
            daily,
            "2026-01-05",
            hold_days=1,
            trading_sessions=[
                "2026-01-05",
                "2026-01-06",
                "2026-01-07",
                "2026-01-08",
            ],
            security_states={"2026-01-07": active_state},
        )

        self.assertEqual(result["reason"], "market_bar_missing")
        self.assertFalse(result["exit_label_mature"])
        self.assertEqual(result["exit_delay_sessions"], 0)

    def test_missing_trading_calendar_fails_closed(self):
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

        result = evaluate_trade(daily, "2026-01-05", hold_days=1)

        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "trading_calendar_missing")
        self.assertFalse(result["session_axis_verified"])

    def test_snapshot_calendar_is_capped_at_manifest_trade_date(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = root / "payload"
            payload.mkdir()
            (payload / "trade_calendar.json").write_text(
                json.dumps(["2026-01-05", "2026-01-06", "2026-01-07"]),
                encoding="utf-8",
            )
            (root / "manifest.json").write_text(
                json.dumps({"trade_date": "2026-01-06"}),
                encoding="utf-8",
            )

            sessions = load_exchange_sessions(payload)

        self.assertEqual(sessions, ["2026-01-05", "2026-01-06"])


if __name__ == "__main__":
    unittest.main()
