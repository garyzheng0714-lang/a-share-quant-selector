import json
import tempfile
from pathlib import Path

import orjson
import pandas as pd
from hypothesis import given, settings, strategies as st

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
)


@settings(max_examples=15, deadline=None)
@given(
    initial_cash=st.integers(min_value=50_000, max_value=500_000),
    price=st.integers(min_value=2, max_value=30),
    weight_percent=st.integers(min_value=10, max_value=30),
)
def test_buy_fill_cash_lot_and_nav_invariants(initial_cash, price, weight_percent):
    original = view_manager.DB_PATH
    with tempfile.TemporaryDirectory() as temporary:
        try:
            root = Path(temporary)
            view_manager.DB_PATH = root / "paper.db"
            init_paper_ledger()
            manager = CSVManager(root / "data")
            manager.allow_unpublished_paper_snapshot_for_tests = True
            manager.allow_unpublished_calendar = True
            (manager.base_data_dir / "trade_calendar.json").write_text(
                json.dumps(
                    pd.bdate_range("2025-12-01", "2026-02-28")
                    .strftime("%Y-%m-%d")
                    .tolist()
                ),
                encoding="utf-8",
            )
            (manager.data_dir / "stock_names.json").write_bytes(
                orjson.dumps({"600000": "浦发银行"})
            )
            dates = pd.bdate_range(end="2026-01-07", periods=10)
            manager.write_stock(
                "600000",
                pd.DataFrame(
                    {
                        "date": dates,
                        "open": float(price),
                        "high": float(price) * 1.01,
                        "low": float(price) * 0.99,
                        "close": float(price),
                        "volume": 10_000,
                    }
                ),
            )
            account = ensure_default_account(initial_cash=float(initial_cash))
            create_paper_order(
                account["account_id"],
                "600000",
                "buy",
                "2026-01-05",
                "2026-01-06",
                target_weight=weight_percent / 100,
                decision_run_id="property-run",
            )
            fill = execute_pending_orders(
                "2026-01-06",
                manager,
                account["account_id"],
            )[0]
            assert fill["outcome"] == "filled"
            assert fill["quantity"] > 0
            assert fill["quantity"] % 100 == 0

            nav = mark_paper_nav("2026-01-06", manager, account["account_id"])
            reconciliation = reconcile_paper_account(nav)
            assert reconciliation["balanced"]

            with view_manager._get_conn() as connection:
                lot = connection.execute(
                    "SELECT quantity, buy_fill_id FROM paper_position_lots",
                ).fetchone()
                cash_sum = connection.execute(
                    "SELECT SUM(amount) FROM paper_cash_events WHERE account_id = ?",
                    (account["account_id"],),
                ).fetchone()[0]
            status = get_paper_status(account["account_id"], manager)
            assert lot["quantity"] == fill["quantity"]
            assert lot["buy_fill_id"] == fill["fill_id"]
            assert abs(float(cash_sum) - float(status["cash"])) < 0.01
            assert (
                abs(
                    float(nav["total_equity"])
                    - float(nav["cash"])
                    - float(nav["market_value"])
                )
                < 0.01
            )

            cash_before_sell = float(status["cash"])
            create_paper_order(
                account["account_id"],
                "600000",
                "sell",
                "2026-01-06",
                "2026-01-07",
                requested_quantity=fill["quantity"],
                decision_run_id="property-exit",
            )
            sell = execute_pending_orders(
                "2026-01-07",
                manager,
                account["account_id"],
            )[0]
            assert sell["outcome"] == "filled"
            sold_status = get_paper_status(account["account_id"], manager)
            assert (
                abs(
                    float(sold_status["cash"])
                    - cash_before_sell
                    - float(sell["gross_amount"])
                    + float(sell["fees"])
                )
                < 0.01
            )
            with view_manager._get_conn() as connection:
                closed = connection.execute(
                    "SELECT SUM(quantity) FROM paper_lot_closures"
                ).fetchone()[0]
                cash_sum = connection.execute(
                    "SELECT SUM(amount) FROM paper_cash_events WHERE account_id = ?",
                    (account["account_id"],),
                ).fetchone()[0]
            assert 0 <= int(closed) <= int(lot["quantity"])
            assert sold_status["positions"] == []
            assert abs(float(cash_sum) - float(sold_status["cash"])) < 0.01

            sold_nav = mark_paper_nav("2026-01-07", manager, account["account_id"])
            assert reconcile_paper_account(sold_nav)["balanced"]
        finally:
            view_manager.DB_PATH = original
