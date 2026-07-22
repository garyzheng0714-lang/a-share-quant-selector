import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import orjson
import pandas as pd

import views.view_manager as view_manager
from utils.csv_manager import CSVManager
from utils.paper_trading import (
    create_paper_order,
    ensure_default_account,
    execute_pending_orders,
    get_paper_status,
    init_paper_ledger,
    mark_paper_nav,
    reconcile_paper_account,
    run_daily_paper_cycle,
)


class PaperTradingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original = view_manager.DB_PATH
        view_manager.DB_PATH = Path(self.tmp.name) / "test.db"
        init_paper_ledger()
        self.manager = CSVManager(Path(self.tmp.name) / "data")
        self.manager.allow_unpublished_paper_snapshot_for_tests = True
        self.manager.allow_unpublished_calendar = True
        (self.manager.base_data_dir / "trade_calendar.json").write_text(
            json.dumps(
                pd.bdate_range("2025-12-01", "2026-02-28").strftime("%Y-%m-%d").tolist()
            ),
            encoding="utf-8",
        )
        (self.manager.data_dir / "stock_names.json").write_bytes(
            orjson.dumps({"600000": "浦发银行"})
        )

    def tearDown(self):
        view_manager.DB_PATH = self.original
        self.tmp.cleanup()

    def _write_prices(self, rows, *, established=True):
        values = list(rows)
        if established and values:
            first_date = pd.Timestamp(min(row["date"] for row in values))
            template = values[0]
            prior = [
                {
                    **template,
                    "date": date.strftime("%Y-%m-%d"),
                    "open": float(template["close"]),
                    "high": float(template["close"]),
                    "low": float(template["close"]),
                    "close": float(template["close"]),
                }
                for date in pd.bdate_range(
                    end=first_date - pd.Timedelta(days=1), periods=6
                )
            ]
            values = [*prior, *values]
        self.manager.write_stock("600000", pd.DataFrame(values))

    def test_empty_account_still_records_daily_nav_and_reconciles(self):
        ensure_default_account()
        result = run_daily_paper_cycle("2026-01-05", self.manager)

        self.assertTrue(result["reconciliation"]["balanced"])
        self.assertEqual(result["nav"]["snapshot_id"], "unpublished-test-data")
        self.assertEqual(result["status"]["cash"], 1_000_000.0)
        self.assertEqual(result["status"]["market_value"], 0.0)
        self.assertEqual(result["status"]["total_equity"], 1_000_000.0)

    def test_buy_is_deferred_when_next_session_cannot_be_proven(self):
        self._write_prices(
            [
                {
                    "date": "2026-01-05",
                    "open": 10,
                    "high": 10.2,
                    "low": 9.8,
                    "close": 10,
                    "volume": 1000,
                },
                {
                    "date": "2026-01-06",
                    "open": 10,
                    "high": 10.2,
                    "low": 9.8,
                    "close": 10,
                    "volume": 1000,
                },
            ]
        )
        self.manager.allow_unpublished_calendar = False
        account = ensure_default_account(initial_cash=100_000)
        create_paper_order(
            account["account_id"],
            "600000",
            "buy",
            "2026-01-05",
            "2026-01-06",
            target_weight=0.2,
        )

        result = execute_pending_orders(
            "2026-01-06", self.manager, account["account_id"]
        )

        self.assertEqual(result[0]["outcome"], "deferred")
        self.assertEqual(result[0]["reason_code"], "trading_calendar_unavailable")

    def test_buy_uses_board_lot_and_same_day_sell_is_t1_locked(self):
        self._write_prices(
            [
                {
                    "date": "2026-01-05",
                    "open": 9.8,
                    "high": 10.2,
                    "low": 9.7,
                    "close": 10.0,
                    "volume": 1000,
                },
                {
                    "date": "2026-01-06",
                    "open": 10.0,
                    "high": 10.5,
                    "low": 9.9,
                    "close": 10.4,
                    "volume": 1000,
                },
                {
                    "date": "2026-01-07",
                    "open": 10.3,
                    "high": 10.6,
                    "low": 10.1,
                    "close": 10.5,
                    "volume": 1000,
                },
            ]
        )
        account = ensure_default_account(initial_cash=100_000)
        create_paper_order(
            account["account_id"],
            "600000",
            "buy",
            "2026-01-05",
            "2026-01-06",
            target_weight=0.5,
            decision_run_id="run-1",
        )

        fills = execute_pending_orders(
            "2026-01-06", self.manager, account["account_id"]
        )
        buy = next(row for row in fills if row["side"] == "buy")
        self.assertEqual(buy["outcome"], "filled")
        self.assertEqual(buy["snapshot_id"], "unpublished-test-data")
        self.assertEqual(buy["quantity"] % 100, 0)
        self.assertGreater(buy["quantity"], 0)
        with view_manager._get_read_conn() as conn:
            stored_fill = conn.execute(
                "SELECT snapshot_id, execution_policy_version, evidence_json "
                "FROM paper_fills WHERE fill_id = ?",
                (buy["fill_id"],),
            ).fetchone()
        self.assertEqual(stored_fill["snapshot_id"], "unpublished-test-data")
        self.assertEqual(
            stored_fill["execution_policy_version"],
            "a-share-eod-open-open-v3",
        )
        self.assertEqual(
            json.loads(stored_fill["evidence_json"])["snapshot_id"],
            "unpublished-test-data",
        )

        create_paper_order(
            account["account_id"],
            "600000",
            "sell",
            "2026-01-06",
            "2026-01-06",
            requested_quantity=buy["quantity"],
            decision_run_id="exit-1",
        )
        locked = execute_pending_orders(
            "2026-01-06", self.manager, account["account_id"]
        )
        self.assertEqual(locked[0]["outcome"], "deferred")
        self.assertEqual(locked[0]["reason_code"], "t_plus_one_locked")

        sold = execute_pending_orders("2026-01-07", self.manager, account["account_id"])
        self.assertEqual(sold[0]["outcome"], "filled")
        self.assertEqual(
            get_paper_status(account["account_id"], self.manager)["positions"], []
        )

    def test_read_only_unpinned_market_data_cannot_create_paper_evidence(self):
        ensure_default_account()
        unpinned = CSVManager(
            Path(self.tmp.name) / "unpublished",
            resolve_snapshot=False,
            writable=False,
        )

        with self.assertRaisesRegex(RuntimeError, "paper_market_snapshot_unpinned"):
            mark_paper_nav("2026-01-05", unpinned)

    def test_one_word_limit_up_never_creates_fake_fill(self):
        self._write_prices(
            [
                {
                    "date": "2026-01-05",
                    "open": 10.0,
                    "high": 10.0,
                    "low": 10.0,
                    "close": 10.0,
                    "volume": 1000,
                },
                {
                    "date": "2026-01-06",
                    "open": 11.0,
                    "high": 11.0,
                    "low": 11.0,
                    "close": 11.0,
                    "volume": 1000,
                },
            ]
        )
        account = ensure_default_account(initial_cash=100_000)
        create_paper_order(
            account["account_id"],
            "600000",
            "buy",
            "2026-01-05",
            "2026-01-06",
            target_weight=0.5,
        )

        fills = execute_pending_orders(
            "2026-01-06", self.manager, account["account_id"]
        )

        self.assertEqual(fills[0]["outcome"], "rejected")
        self.assertEqual(fills[0]["reason_code"], "one_word_limit_up")
        status = get_paper_status(account["account_id"], self.manager)
        self.assertEqual(status["cash"], 100_000.0)
        self.assertEqual(status["positions"], [])

    def test_zero_volume_session_is_treated_as_suspension(self):
        self._write_prices(
            [
                {
                    "date": "2026-01-05",
                    "open": 10,
                    "high": 10.1,
                    "low": 9.9,
                    "close": 10,
                    "volume": 1000,
                },
                {
                    "date": "2026-01-06",
                    "open": 10,
                    "high": 10,
                    "low": 10,
                    "close": 10,
                    "volume": 0,
                },
            ]
        )
        account = ensure_default_account(initial_cash=100_000)
        create_paper_order(
            account["account_id"],
            "600000",
            "buy",
            "2026-01-05",
            "2026-01-06",
            target_weight=0.2,
        )

        fill = execute_pending_orders(
            "2026-01-06", self.manager, account["account_id"]
        )[0]

        self.assertEqual(fill["outcome"], "deferred")
        self.assertEqual(fill["reason_code"], "security_suspended")

    def test_st_stock_uses_five_percent_limit(self):
        (self.manager.data_dir / "stock_names.json").write_bytes(
            orjson.dumps({"600000": "*ST测试"})
        )
        self._write_prices(
            [
                {
                    "date": "2026-01-05",
                    "open": 10,
                    "high": 10,
                    "low": 10,
                    "close": 10,
                    "volume": 1000,
                },
                {
                    "date": "2026-01-06",
                    "open": 10.5,
                    "high": 10.5,
                    "low": 10.5,
                    "close": 10.5,
                    "volume": 1000,
                },
            ]
        )
        account = ensure_default_account(initial_cash=100_000)
        create_paper_order(
            account["account_id"],
            "600000",
            "buy",
            "2026-01-05",
            "2026-01-06",
            target_weight=0.2,
        )

        fill = execute_pending_orders(
            "2026-01-06", self.manager, account["account_id"]
        )[0]

        self.assertEqual(fill["outcome"], "rejected")
        self.assertEqual(fill["reason_code"], "one_word_limit_up")

    def test_repeated_one_word_limit_down_defers_sell_until_tradable_day(self):
        self._write_prices(
            [
                {
                    "date": "2026-01-05",
                    "open": 10,
                    "high": 10.1,
                    "low": 9.9,
                    "close": 10,
                    "volume": 1000,
                },
                {
                    "date": "2026-01-06",
                    "open": 10,
                    "high": 10.1,
                    "low": 9.9,
                    "close": 10,
                    "volume": 1000,
                },
                {
                    "date": "2026-01-07",
                    "open": 9,
                    "high": 9,
                    "low": 9,
                    "close": 9,
                    "volume": 1000,
                },
                {
                    "date": "2026-01-08",
                    "open": 8.1,
                    "high": 8.1,
                    "low": 8.1,
                    "close": 8.1,
                    "volume": 1000,
                },
                {
                    "date": "2026-01-09",
                    "open": 8.2,
                    "high": 8.3,
                    "low": 8.0,
                    "close": 8.2,
                    "volume": 1000,
                },
            ]
        )
        account = ensure_default_account(initial_cash=100_000)
        create_paper_order(
            account["account_id"],
            "600000",
            "buy",
            "2026-01-05",
            "2026-01-06",
            target_weight=0.2,
        )
        buy = execute_pending_orders("2026-01-06", self.manager, account["account_id"])[
            0
        ]
        create_paper_order(
            account["account_id"],
            "600000",
            "sell",
            "2026-01-06",
            "2026-01-07",
            requested_quantity=buy["quantity"],
        )

        first = execute_pending_orders(
            "2026-01-07", self.manager, account["account_id"]
        )[0]
        second = execute_pending_orders(
            "2026-01-08", self.manager, account["account_id"]
        )[0]
        third = execute_pending_orders(
            "2026-01-09", self.manager, account["account_id"]
        )[0]

        self.assertEqual(first["reason_code"], "one_word_limit_down")
        self.assertEqual(second["reason_code"], "one_word_limit_down")
        self.assertEqual(third["outcome"], "filled")

    def test_unknown_initial_listing_status_fails_closed(self):
        self._write_prices(
            [
                {
                    "date": "2026-01-05",
                    "open": 10,
                    "high": 10,
                    "low": 10,
                    "close": 10,
                    "volume": 1000,
                },
                {
                    "date": "2026-01-06",
                    "open": 10,
                    "high": 10.2,
                    "low": 9.8,
                    "close": 10,
                    "volume": 1000,
                },
            ],
            established=False,
        )
        account = ensure_default_account(initial_cash=100_000)
        create_paper_order(
            account["account_id"],
            "600000",
            "buy",
            "2026-01-05",
            "2026-01-06",
            target_weight=0.5,
        )

        fill = execute_pending_orders(
            "2026-01-06",
            self.manager,
            account["account_id"],
        )[0]

        self.assertEqual(fill["outcome"], "deferred")
        self.assertEqual(fill["reason_code"], "pit_security_state_missing")

    def test_existing_position_is_subtracted_from_single_stock_cap(self):
        self._write_prices(
            [
                {
                    "date": "2026-01-05",
                    "open": 10,
                    "high": 10.2,
                    "low": 9.8,
                    "close": 10,
                    "volume": 1000,
                },
                {
                    "date": "2026-01-06",
                    "open": 10,
                    "high": 10.2,
                    "low": 9.8,
                    "close": 10,
                    "volume": 1000,
                },
                {
                    "date": "2026-01-07",
                    "open": 10,
                    "high": 10.2,
                    "low": 9.8,
                    "close": 10,
                    "volume": 1000,
                },
            ]
        )
        account = ensure_default_account(initial_cash=100_000)
        create_paper_order(
            account["account_id"],
            "600000",
            "buy",
            "2026-01-05",
            "2026-01-06",
            target_weight=0.30,
            decision_run_id="run-1",
        )
        first = execute_pending_orders(
            "2026-01-06", self.manager, account["account_id"]
        )[0]
        create_paper_order(
            account["account_id"],
            "600000",
            "buy",
            "2026-01-06",
            "2026-01-07",
            target_weight=0.30,
            decision_run_id="run-2",
        )
        second = execute_pending_orders(
            "2026-01-07", self.manager, account["account_id"]
        )[0]

        self.assertEqual(first["outcome"], "filled")
        self.assertLessEqual(first["gross_amount"], 30_000)
        self.assertEqual(second["outcome"], "rejected")
        self.assertEqual(second["reason_code"], "position_limit_reached")

    def test_reconciliation_independently_detects_tampered_cash_event(self):
        self._write_prices(
            [
                {
                    "date": "2026-01-05",
                    "open": 10,
                    "high": 10.2,
                    "low": 9.8,
                    "close": 10,
                    "volume": 1000,
                },
                {
                    "date": "2026-01-06",
                    "open": 10,
                    "high": 10.2,
                    "low": 9.8,
                    "close": 10,
                    "volume": 1000,
                },
            ]
        )
        account = ensure_default_account(initial_cash=100_000)
        create_paper_order(
            account["account_id"],
            "600000",
            "buy",
            "2026-01-05",
            "2026-01-06",
            target_weight=0.20,
            decision_run_id="run-1",
        )
        execute_pending_orders("2026-01-06", self.manager, account["account_id"])
        nav = mark_paper_nav("2026-01-06", self.manager, account["account_id"])
        with view_manager._get_conn() as conn:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
                conn.execute(
                    "UPDATE paper_cash_events SET amount = amount + 100 "
                    "WHERE event_type = 'trading_fee'"
                )
            conn.execute("DROP TRIGGER paper_cash_events_no_update")
            conn.execute(
                "UPDATE paper_cash_events SET amount = amount + 100 "
                "WHERE event_type = 'trading_fee'"
            )

        result = reconcile_paper_account(nav)

        self.assertFalse(result["balanced"])
        self.assertIn("buy_cash_events_mismatch", result["reason_codes"])
        self.assertIn("cash_event_sum_mismatch", result["reason_codes"])

    def test_daily_nav_is_idempotent(self):
        ensure_default_account()
        first = run_daily_paper_cycle("2026-01-05", self.manager)
        second = run_daily_paper_cycle("2026-01-05", self.manager)

        self.assertEqual(first["nav"]["nav_id"], second["nav"]["nav_id"])
        self.assertTrue(second["nav"]["idempotent_replay"])
        with view_manager._get_conn() as conn:
            count = conn.execute("SELECT COUNT(*) FROM paper_nav").fetchone()[0]
        self.assertEqual(count, 1)

    def test_same_day_multiple_preopen_runs_create_one_business_order(self):
        from utils.paper_trading import queue_orders_from_decision

        ensure_default_account()
        base = {
            "trade_date": "2026-01-05",
            "market": {"decision_for_date": "2026-01-06"},
            "candidates": [{"code": "600000", "action": "buy"}],
        }

        first = queue_orders_from_decision({**base, "run_id": "preopen-1"})
        second = queue_orders_from_decision({**base, "run_id": "preopen-2"})

        self.assertEqual(first["order_ids"], second["order_ids"])
        with view_manager._get_conn() as conn:
            count = conn.execute("SELECT COUNT(*) FROM paper_orders").fetchone()[0]
        self.assertEqual(count, 1)

    def test_same_date_price_correction_requires_explicit_nav_correction(self):
        self._write_prices(
            [
                {
                    "date": "2026-01-05",
                    "open": 10,
                    "high": 10.2,
                    "low": 9.8,
                    "close": 10,
                    "volume": 1000,
                },
                {
                    "date": "2026-01-06",
                    "open": 10,
                    "high": 10.2,
                    "low": 9.8,
                    "close": 10,
                    "volume": 1000,
                },
            ]
        )
        account = ensure_default_account(initial_cash=100_000)
        create_paper_order(
            account["account_id"],
            "600000",
            "buy",
            "2026-01-05",
            "2026-01-06",
            target_weight=0.2,
        )
        execute_pending_orders("2026-01-06", self.manager, account["account_id"])
        mark_paper_nav("2026-01-06", self.manager, account["account_id"])
        corrected = self.manager.read_stock("600000")
        mask = corrected["date"].dt.strftime("%Y-%m-%d") == "2026-01-06"
        corrected.loc[mask, ["high", "close"]] = 11.0
        self.manager.write_stock("600000", corrected)

        with self.assertRaisesRegex(
            RuntimeError, "nav_conflict_requires_explicit_correction"
        ):
            mark_paper_nav("2026-01-06", self.manager, account["account_id"])

    def test_account_state_survives_database_and_manager_reopen(self):
        self._write_prices(
            [
                {
                    "date": "2026-01-05",
                    "open": 10,
                    "high": 10.2,
                    "low": 9.8,
                    "close": 10,
                    "volume": 1000,
                },
                {
                    "date": "2026-01-06",
                    "open": 10,
                    "high": 10.2,
                    "low": 9.8,
                    "close": 10,
                    "volume": 1000,
                },
            ]
        )
        account = ensure_default_account(initial_cash=100_000)
        create_paper_order(
            account["account_id"],
            "600000",
            "buy",
            "2026-01-05",
            "2026-01-06",
            target_weight=0.2,
        )
        execute_pending_orders("2026-01-06", self.manager, account["account_id"])
        before = get_paper_status(account["account_id"], self.manager)

        reopened = CSVManager(self.manager.base_data_dir, resolve_snapshot=False)
        after = get_paper_status(account["account_id"], reopened)

        self.assertEqual(after["cash"], before["cash"])
        self.assertEqual(after["positions"], before["positions"])

    def test_missing_position_price_blocks_nav_and_reconciliation(self):
        self._write_prices(
            [
                {
                    "date": "2026-01-05",
                    "open": 10,
                    "high": 10.2,
                    "low": 9.8,
                    "close": 10,
                    "volume": 1000,
                },
                {
                    "date": "2026-01-06",
                    "open": 10,
                    "high": 10.2,
                    "low": 9.8,
                    "close": 10,
                    "volume": 1000,
                },
            ]
        )
        account = ensure_default_account(initial_cash=100_000)
        create_paper_order(
            account["account_id"],
            "600000",
            "buy",
            "2026-01-05",
            "2026-01-06",
            target_weight=0.20,
        )
        fill = execute_pending_orders(
            "2026-01-06", self.manager, account["account_id"]
        )[0]
        self.assertEqual(fill["outcome"], "filled")
        self.manager.get_stock_path("600000").unlink()

        result = run_daily_paper_cycle(
            "2026-01-07", self.manager, account["account_id"]
        )
        status = get_paper_status(account["account_id"], self.manager)

        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "missing_position_prices")
        self.assertFalse(result["reconciliation"]["balanced"])
        self.assertIsNone(status["total_equity"])
        self.assertEqual(status["missing_price_codes"], ["600000"])
        with view_manager._get_conn() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM paper_nav WHERE trade_date = '2026-01-07'"
            ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_two_workers_cannot_create_duplicate_daily_nav(self):
        for attempt in range(10):
            view_manager.DB_PATH = Path(self.tmp.name) / f"nav-race-{attempt}.db"
            init_paper_ledger()
            ensure_default_account()
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(
                    executor.map(
                        lambda _: run_daily_paper_cycle("2026-01-05", self.manager),
                        range(2),
                    )
                )

            self.assertEqual(
                {result["nav"]["nav_id"] for result in results},
                {results[0]["nav"]["nav_id"]},
            )
            self.assertTrue(
                all(result["reconciliation"]["balanced"] for result in results)
            )
            with view_manager._get_conn() as conn:
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM paper_nav").fetchone()[0], 1
                )

    def test_decision_without_explicit_execution_date_does_not_queue_order(self):
        from utils.paper_trading import queue_orders_from_decision

        ensure_default_account()
        result = queue_orders_from_decision(
            {
                "run_id": "missing-execution-date",
                "trade_date": "2026-01-05",
                "market": {},
                "candidates": [{"code": "600000", "action": "buy"}],
            }
        )

        self.assertEqual(result["queued"], 0)
        self.assertEqual(result["reason"], "decision_execution_date_missing")


if __name__ == "__main__":
    unittest.main()
