"""A 股日频模拟账户。

委托、尝试、成交、持仓批次、现金和净值均只追加；当前状态由事件重建。
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import orjson
import pandas as pd

from utils.csv_manager import CSVManager
from utils.data_freshness import next_trade_date
from utils.execution_model import is_one_word_limit
from views.view_manager import _get_conn


TZ = ZoneInfo("Asia/Shanghai")
DEFAULT_ACCOUNT_ID = "paper-main-v1"


@dataclass(frozen=True)
class PaperRules:
    version: str = "a-share-paper-v1"
    commission_rate: float = 0.0003
    minimum_commission: float = 5.0
    stamp_duty_sell_rate: float = 0.0005
    transfer_fee_rate: float = 0.00001
    slippage_bps_each_side: float = 5.0
    board_lot: int = 100
    max_position_weight: float = 0.30
    hold_sessions: int = 5


RULES = PaperRules()


def _json(value: Any) -> str:
    return orjson.dumps(value if value is not None else {}).decode()


def _loads(value: str | None, fallback):
    if not value:
        return fallback
    try:
        return orjson.loads(value)
    except Exception:
        return fallback


def _now() -> str:
    return datetime.now(TZ).isoformat(timespec="microseconds")


def init_paper_ledger() -> None:
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS paper_accounts (
                account_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                initial_cash REAL NOT NULL,
                benchmark_code TEXT,
                rule_version TEXT NOT NULL,
                rule_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS paper_orders (
                order_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                decision_run_id TEXT,
                source_lot_id TEXT,
                code TEXT NOT NULL,
                side TEXT NOT NULL CHECK(side IN ('buy', 'sell')),
                signal_date TEXT NOT NULL,
                earliest_trade_date TEXT NOT NULL,
                target_weight REAL,
                requested_quantity INTEGER,
                reason_codes_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(account_id) REFERENCES paper_accounts(account_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS paper_fills (
                fill_id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                outcome TEXT NOT NULL CHECK(outcome IN ('filled', 'rejected', 'deferred')),
                reason_code TEXT NOT NULL,
                price REAL,
                quantity INTEGER NOT NULL DEFAULT 0,
                gross_amount REAL NOT NULL DEFAULT 0,
                fees REAL NOT NULL DEFAULT 0,
                evidence_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(order_id, trade_date),
                FOREIGN KEY(order_id) REFERENCES paper_orders(order_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS paper_position_lots (
                lot_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                buy_fill_id TEXT NOT NULL,
                code TEXT NOT NULL,
                opened_date TEXT NOT NULL,
                sellable_date TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                cost_amount REAL NOT NULL,
                hold_sessions INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(account_id) REFERENCES paper_accounts(account_id),
                FOREIGN KEY(buy_fill_id) REFERENCES paper_fills(fill_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS paper_lot_closures (
                closure_id TEXT PRIMARY KEY,
                lot_id TEXT NOT NULL,
                sell_fill_id TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                proceeds REAL NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(lot_id) REFERENCES paper_position_lots(lot_id),
                FOREIGN KEY(sell_fill_id) REFERENCES paper_fills(fill_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS paper_cash_events (
                cash_event_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                fill_id TEXT,
                trade_date TEXT NOT NULL,
                event_type TEXT NOT NULL,
                amount REAL NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(account_id) REFERENCES paper_accounts(account_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS paper_nav (
                nav_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                as_of TEXT NOT NULL,
                cash REAL NOT NULL,
                market_value REAL NOT NULL,
                total_equity REAL NOT NULL,
                exposure REAL NOT NULL,
                drawdown REAL NOT NULL,
                turnover REAL NOT NULL,
                benchmark_value REAL,
                pricing_status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(account_id) REFERENCES paper_accounts(account_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS paper_reconciliations (
                reconciliation_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                nav_id TEXT NOT NULL,
                balanced INTEGER NOT NULL,
                difference REAL NOT NULL,
                reason_codes_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(account_id) REFERENCES paper_accounts(account_id),
                FOREIGN KEY(nav_id) REFERENCES paper_nav(nav_id)
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_paper_orders_due "
            "ON paper_orders(account_id, earliest_trade_date, code)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_paper_nav_date "
            "ON paper_nav(account_id, trade_date, created_at)"
        )


def ensure_default_account(initial_cash: float = 1_000_000.0) -> dict:
    init_paper_ledger()
    created = _now()
    with _get_conn() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO paper_accounts
              (account_id, name, initial_cash, benchmark_code, rule_version,
               rule_json, created_at)
            VALUES (?, '主模拟账户', ?, NULL, ?, ?, ?)
        """, (DEFAULT_ACCOUNT_ID, float(initial_cash), RULES.version, _json(asdict(RULES)), created))
        conn.execute("""
            INSERT OR IGNORE INTO paper_cash_events
              (cash_event_id, account_id, fill_id, trade_date, event_type, amount, created_at)
            VALUES (?, ?, NULL, ?, 'initial_deposit', ?, ?)
        """, (
            f"initial-{DEFAULT_ACCOUNT_ID}", DEFAULT_ACCOUNT_ID, created[:10],
            float(initial_cash), created,
        ))
        row = conn.execute(
            "SELECT * FROM paper_accounts WHERE account_id = ?", (DEFAULT_ACCOUNT_ID,)
        ).fetchone()
    return dict(row)


def create_paper_order(
    account_id: str,
    code: str,
    side: str,
    signal_date: str,
    earliest_trade_date: str,
    *,
    target_weight: float | None = None,
    requested_quantity: int | None = None,
    decision_run_id: str | None = None,
    source_lot_id: str | None = None,
    reason_codes: list[str] | None = None,
) -> str:
    if side not in {"buy", "sell"}:
        raise ValueError("side 必须是 buy 或 sell")
    init_paper_ledger()
    identity = "|".join(str(value or "") for value in (
        account_id, decision_run_id, source_lot_id, code, side, signal_date,
        earliest_trade_date, target_weight, requested_quantity,
    ))
    order_id = hashlib.sha256(identity.encode()).hexdigest()[:24]
    with _get_conn() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO paper_orders
              (order_id, account_id, decision_run_id, source_lot_id, code, side,
               signal_date, earliest_trade_date, target_weight, requested_quantity,
               reason_codes_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            order_id, account_id, decision_run_id, source_lot_id, code, side,
            signal_date, earliest_trade_date, target_weight, requested_quantity,
            _json(reason_codes or []), _now(),
        ))
    return order_id


def queue_orders_from_decision(decision: dict | None, account_id: str = DEFAULT_ACCOUNT_ID) -> dict:
    account = ensure_default_account()
    if account_id != account["account_id"]:
        raise ValueError("未知模拟账户")
    if not decision or not decision.get("run_id"):
        return {"queued": 0, "reason": "decision_not_ready"}
    approved = [row for row in decision.get("candidates", []) if row.get("action") == "buy"]
    if not approved:
        return {"queued": 0, "reason": "no_approved_candidates", "order_ids": []}
    earliest = (
        (decision.get("market") or {}).get("decision_for_date")
        or next_trade_date(decision["trade_date"])
    )
    target = min(RULES.max_position_weight, 0.90 / len(approved))
    order_ids = [
        create_paper_order(
            account_id, row["code"], "buy", decision["trade_date"], earliest,
            target_weight=target, decision_run_id=decision["run_id"],
            reason_codes=row.get("reason_codes", []),
        )
        for row in approved
    ]
    return {"queued": len(order_ids), "order_ids": order_ids, "earliest_trade_date": earliest}


def _cash_balance(conn, account_id: str) -> float:
    row = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS value FROM paper_cash_events WHERE account_id = ?",
        (account_id,),
    ).fetchone()
    return round(float(row["value"]), 2)


def _open_lots(conn, account_id: str, code: str | None = None) -> list[dict]:
    where = "AND l.code = ?" if code else ""
    params = (account_id, code) if code else (account_id,)
    rows = conn.execute(f"""
        SELECT l.*,
               l.quantity - COALESCE(SUM(c.quantity), 0) AS remaining_quantity
        FROM paper_position_lots l
        LEFT JOIN paper_lot_closures c ON c.lot_id = l.lot_id
        WHERE l.account_id = ? {where}
        GROUP BY l.lot_id
        HAVING remaining_quantity > 0
        ORDER BY l.opened_date, l.created_at, l.lot_id
    """, params).fetchall()
    return [dict(row) for row in rows]


def _price_rows(manager: CSVManager, code: str, trade_date: str):
    frame = manager.read_stock(code)
    if frame is None or frame.empty:
        return None, None, None
    daily = frame.copy().sort_values("date").reset_index(drop=True)
    daily["date"] = pd.to_datetime(daily["date"]).dt.strftime("%Y-%m-%d")
    hits = daily.index[daily["date"] == trade_date].tolist()
    if not hits:
        return daily, None, None
    index = hits[-1]
    previous = daily.iloc[index - 1] if index > 0 else None
    return daily, daily.iloc[index], previous


def _fees(gross: float, side: str) -> float:
    commission = max(RULES.minimum_commission, gross * RULES.commission_rate)
    transfer = gross * RULES.transfer_fee_rate
    stamp = gross * RULES.stamp_duty_sell_rate if side == "sell" else 0.0
    return round(commission + transfer + stamp, 2)


def _record_attempt(conn, order: dict, trade_date: str, outcome: str, reason: str,
                    *, price: float | None = None, quantity: int = 0,
                    gross: float = 0.0, fees: float = 0.0,
                    evidence: dict | None = None) -> dict:
    fill_id = uuid4().hex[:24]
    conn.execute("""
        INSERT INTO paper_fills
          (fill_id, order_id, trade_date, outcome, reason_code, price, quantity,
           gross_amount, fees, evidence_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        fill_id, order["order_id"], trade_date, outcome, reason, price, quantity,
        round(gross, 2), round(fees, 2), _json(evidence or {}), _now(),
    ))
    return {
        "fill_id": fill_id, "order_id": order["order_id"], "code": order["code"],
        "side": order["side"], "trade_date": trade_date, "outcome": outcome,
        "reason_code": reason, "price": price, "quantity": quantity,
        "gross_amount": round(gross, 2), "fees": round(fees, 2),
    }


def _latest_equity(conn, account_id: str) -> float:
    row = conn.execute(
        "SELECT total_equity FROM paper_nav WHERE account_id = ? "
        "ORDER BY trade_date DESC, created_at DESC, rowid DESC LIMIT 1",
        (account_id,),
    ).fetchone()
    return float(row["total_equity"]) if row else _cash_balance(conn, account_id)


def execute_pending_orders(
    trade_date: str, manager: CSVManager, account_id: str = DEFAULT_ACCOUNT_ID,
) -> list[dict]:
    ensure_default_account()
    results = []
    with _get_conn() as conn:
        orders = [dict(row) for row in conn.execute("""
            SELECT o.* FROM paper_orders o
            WHERE o.account_id = ? AND o.earliest_trade_date <= ?
              AND NOT EXISTS (
                  SELECT 1 FROM paper_fills final
                  WHERE final.order_id = o.order_id
                    AND final.outcome IN ('filled', 'rejected')
              )
              AND NOT EXISTS (
                  SELECT 1 FROM paper_fills same_day
                  WHERE same_day.order_id = o.order_id AND same_day.trade_date = ?
              )
            ORDER BY o.earliest_trade_date, o.created_at, o.order_id
        """, (account_id, trade_date, trade_date)).fetchall()]
        for order in orders:
            _, row, previous = _price_rows(manager, order["code"], trade_date)
            if row is None or previous is None:
                results.append(_record_attempt(
                    conn, order, trade_date, "deferred", "market_data_missing",
                ))
                continue
            open_price = float(row.get("open", 0) or 0)
            previous_close = float(previous.get("close", 0) or 0)
            if open_price <= 0 or previous_close <= 0:
                results.append(_record_attempt(
                    conn, order, trade_date, "deferred", "invalid_open_price",
                ))
                continue

            slip = RULES.slippage_bps_each_side / 10_000
            if order["side"] == "buy":
                if is_one_word_limit(row, previous_close, "up"):
                    results.append(_record_attempt(
                        conn, order, trade_date, "rejected", "one_word_limit_up",
                        evidence={"open": open_price, "previous_close": previous_close},
                    ))
                    continue
                cash = _cash_balance(conn, account_id)
                equity = _latest_equity(conn, account_id)
                target = min(
                    cash, equity * min(float(order["target_weight"] or 0),
                                       RULES.max_position_weight),
                )
                price = round(open_price * (1 + slip), 4)
                quantity = math.floor(max(target - RULES.minimum_commission, 0)
                                      / price / RULES.board_lot) * RULES.board_lot
                while quantity > 0:
                    gross = price * quantity
                    fees = _fees(gross, "buy")
                    if gross + fees <= cash + 1e-6:
                        break
                    quantity -= RULES.board_lot
                if quantity < RULES.board_lot:
                    results.append(_record_attempt(
                        conn, order, trade_date, "rejected", "insufficient_cash",
                    ))
                    continue
                gross = round(price * quantity, 2)
                fees = _fees(gross, "buy")
                fill = _record_attempt(
                    conn, order, trade_date, "filled", "filled", price=price,
                    quantity=quantity, gross=gross, fees=fees,
                    evidence={"approximate": True, "rule_version": RULES.version},
                )
                conn.execute("""
                    INSERT INTO paper_cash_events VALUES (?, ?, ?, ?, 'buy_principal', ?, ?)
                """, (uuid4().hex[:24], account_id, fill["fill_id"], trade_date, -gross, _now()))
                conn.execute("""
                    INSERT INTO paper_cash_events VALUES (?, ?, ?, ?, 'trading_fee', ?, ?)
                """, (uuid4().hex[:24], account_id, fill["fill_id"], trade_date, -fees, _now()))
                conn.execute("""
                    INSERT INTO paper_position_lots
                      (lot_id, account_id, buy_fill_id, code, opened_date,
                       sellable_date, quantity, cost_amount, hold_sessions, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    uuid4().hex[:24], account_id, fill["fill_id"], order["code"],
                    trade_date, next_trade_date(trade_date), quantity, gross + fees,
                    RULES.hold_sessions, _now(),
                ))
                results.append(fill)
                continue

            lots = _open_lots(conn, account_id, order["code"])
            sellable = [lot for lot in lots if lot["sellable_date"] <= trade_date]
            available = sum(int(lot["remaining_quantity"]) for lot in sellable)
            requested = int(order["requested_quantity"] or available)
            quantity = min(requested, available)
            if quantity <= 0:
                reason = "t_plus_one_locked" if lots else "position_not_available"
                outcome = "deferred" if lots else "rejected"
                results.append(_record_attempt(conn, order, trade_date, outcome, reason))
                continue
            if is_one_word_limit(row, previous_close, "down"):
                results.append(_record_attempt(
                    conn, order, trade_date, "deferred", "one_word_limit_down",
                    evidence={"open": open_price, "previous_close": previous_close},
                ))
                continue
            price = round(open_price * (1 - slip), 4)
            gross = round(price * quantity, 2)
            fees = _fees(gross, "sell")
            fill = _record_attempt(
                conn, order, trade_date, "filled", "filled", price=price,
                quantity=quantity, gross=gross, fees=fees,
                evidence={"approximate": True, "rule_version": RULES.version},
            )
            conn.execute("""
                INSERT INTO paper_cash_events VALUES (?, ?, ?, ?, 'sell_proceeds', ?, ?)
            """, (uuid4().hex[:24], account_id, fill["fill_id"], trade_date, gross, _now()))
            conn.execute("""
                INSERT INTO paper_cash_events VALUES (?, ?, ?, ?, 'trading_fee', ?, ?)
            """, (uuid4().hex[:24], account_id, fill["fill_id"], trade_date, -fees, _now()))
            remaining = quantity
            for lot in sellable:
                close_quantity = min(remaining, int(lot["remaining_quantity"]))
                if close_quantity <= 0:
                    break
                conn.execute("""
                    INSERT INTO paper_lot_closures
                      (closure_id, lot_id, sell_fill_id, quantity, proceeds, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    uuid4().hex[:24], lot["lot_id"], fill["fill_id"], close_quantity,
                    round(gross * close_quantity / quantity, 2), _now(),
                ))
                remaining -= close_quantity
            results.append(fill)
    return results


def queue_due_exit_orders(
    trade_date: str, manager: CSVManager, account_id: str = DEFAULT_ACCOUNT_ID,
) -> list[str]:
    ensure_default_account()
    order_ids = []
    with _get_conn() as conn:
        lots = _open_lots(conn, account_id)
        for lot in lots:
            existing = conn.execute(
                "SELECT order_id FROM paper_orders WHERE source_lot_id = ? AND side = 'sell'",
                (lot["lot_id"],),
            ).fetchone()
            if existing:
                continue
            frame = manager.read_stock(lot["code"])
            if frame is None or frame.empty:
                continue
            dates = sorted(pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d").unique())
            completed = [date for date in dates if lot["opened_date"] < date < trade_date]
            if len(completed) < int(lot["hold_sessions"]) - 1:
                continue
            signal_date = completed[-1] if completed else lot["opened_date"]
            order_ids.append(create_paper_order(
                account_id, lot["code"], "sell", signal_date, trade_date,
                requested_quantity=int(lot["remaining_quantity"]),
                decision_run_id=f"fixed-exit:{lot['lot_id']}", source_lot_id=lot["lot_id"],
                reason_codes=["fixed_hold_sessions_reached"],
            ))
    return order_ids


def _position_snapshot(conn, account_id: str, manager: CSVManager,
                       as_of: str | None = None) -> tuple[list[dict], list[str]]:
    positions, missing = [], []
    for lot in _open_lots(conn, account_id):
        frame = manager.read_stock(lot["code"])
        price = None
        price_date = None
        if frame is not None and not frame.empty:
            daily = frame.copy()
            daily["date"] = pd.to_datetime(daily["date"]).dt.strftime("%Y-%m-%d")
            if as_of:
                daily = daily[daily["date"] <= as_of]
            if not daily.empty:
                latest = daily.sort_values("date").iloc[-1]
                price = float(latest.get("close", 0) or 0)
                price_date = latest["date"]
        if not price:
            missing.append(lot["code"])
            price = 0.0
        positions.append({
            "lot_id": lot["lot_id"], "code": lot["code"],
            "quantity": int(lot["remaining_quantity"]), "opened_date": lot["opened_date"],
            "sellable_date": lot["sellable_date"], "cost_amount": lot["cost_amount"],
            "last_price": round(price, 4), "price_date": price_date,
            "market_value": round(price * int(lot["remaining_quantity"]), 2),
        })
    return positions, sorted(set(missing))


def mark_paper_nav(
    trade_date: str, manager: CSVManager, account_id: str = DEFAULT_ACCOUNT_ID,
) -> dict:
    ensure_default_account()
    with _get_conn() as conn:
        cash = _cash_balance(conn, account_id)
        positions, missing = _position_snapshot(conn, account_id, manager, trade_date)
        market_value = round(sum(row["market_value"] for row in positions), 2)
        equity = round(cash + market_value, 2)
        peak = conn.execute(
            "SELECT MAX(total_equity) AS peak FROM paper_nav WHERE account_id = ?",
            (account_id,),
        ).fetchone()["peak"]
        peak = max(float(peak or equity), equity)
        drawdown = round(equity / peak - 1, 6) if peak > 0 else 0.0
        gross = conn.execute("""
            SELECT COALESCE(SUM(gross_amount), 0) AS gross
            FROM paper_fills f JOIN paper_orders o ON o.order_id = f.order_id
            WHERE o.account_id = ? AND f.trade_date = ? AND f.outcome = 'filled'
        """, (account_id, trade_date)).fetchone()["gross"]
        prior = conn.execute(
            "SELECT total_equity FROM paper_nav WHERE account_id = ? AND trade_date < ? "
            "ORDER BY trade_date DESC, created_at DESC LIMIT 1", (account_id, trade_date),
        ).fetchone()
        denominator = float(prior["total_equity"]) if prior else equity
        turnover = round(float(gross) / denominator, 6) if denominator > 0 else 0.0
        nav_id = uuid4().hex[:24]
        payload = {
            "nav_id": nav_id, "account_id": account_id, "trade_date": trade_date,
            "as_of": f"{trade_date}T15:00:00+08:00", "cash": cash,
            "market_value": market_value, "total_equity": equity,
            "exposure": round(market_value / equity, 6) if equity > 0 else 0.0,
            "drawdown": drawdown, "turnover": turnover, "benchmark_value": None,
            "pricing_status": "complete" if not missing else "missing_prices",
        }
        conn.execute("""
            INSERT INTO paper_nav
              (nav_id, account_id, trade_date, as_of, cash, market_value, total_equity,
               exposure, drawdown, turnover, benchmark_value, pricing_status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            payload["nav_id"], payload["account_id"], payload["trade_date"],
            payload["as_of"], payload["cash"], payload["market_value"],
            payload["total_equity"], payload["exposure"], payload["drawdown"],
            payload["turnover"], payload["benchmark_value"],
            payload["pricing_status"], _now(),
        ))
    return {**payload, "missing_price_codes": missing}


def reconcile_paper_account(nav: dict) -> dict:
    with _get_conn() as conn:
        cash = _cash_balance(conn, nav["account_id"])
        difference = round(cash + float(nav["market_value"]) - float(nav["total_equity"]), 2)
        reasons = [] if abs(difference) < 0.01 else ["cash_position_nav_mismatch"]
        reconciliation_id = uuid4().hex[:24]
        conn.execute("""
            INSERT INTO paper_reconciliations
              (reconciliation_id, account_id, trade_date, nav_id, balanced,
               difference, reason_codes_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            reconciliation_id, nav["account_id"], nav["trade_date"], nav["nav_id"],
            int(not reasons), difference, _json(reasons), _now(),
        ))
    return {
        "reconciliation_id": reconciliation_id, "balanced": not reasons,
        "difference": difference, "reason_codes": reasons,
    }


def get_paper_status(
    account_id: str = DEFAULT_ACCOUNT_ID, manager: CSVManager | None = None,
) -> dict:
    manager = manager or CSVManager("data")
    init_paper_ledger()
    with _get_conn() as conn:
        account = conn.execute(
            "SELECT * FROM paper_accounts WHERE account_id = ?", (account_id,)
        ).fetchone()
        if account is None:
            return {"established": False, "reason": "paper_account_not_established"}
        cash = _cash_balance(conn, account_id)
        positions, missing = _position_snapshot(conn, account_id, manager)
        market_value = round(sum(row["market_value"] for row in positions), 2)
        latest_nav = conn.execute(
            "SELECT * FROM paper_nav WHERE account_id = ? "
            "ORDER BY trade_date DESC, created_at DESC, rowid DESC LIMIT 1", (account_id,),
        ).fetchone()
        nav_days = conn.execute(
            "SELECT COUNT(DISTINCT trade_date) AS n FROM paper_nav WHERE account_id = ?",
            (account_id,),
        ).fetchone()["n"]
        pending = conn.execute("""
            SELECT COUNT(*) AS n FROM paper_orders o
            WHERE o.account_id = ? AND NOT EXISTS (
                SELECT 1 FROM paper_fills f WHERE f.order_id = o.order_id
                  AND f.outcome IN ('filled', 'rejected')
            )
        """, (account_id,)).fetchone()["n"]
    equity = round(cash + market_value, 2)
    initial = float(account["initial_cash"])
    return {
        "established": True, "account_id": account_id, "rule_version": account["rule_version"],
        "cash": cash, "market_value": market_value, "total_equity": equity,
        "net_return": round(equity / initial - 1, 6) if initial > 0 and nav_days else None,
        "positions": positions, "pending_orders": int(pending), "nav_days": int(nav_days),
        "track_record_state": "collecting" if nav_days < 60 else "operational_history_ready",
        "benchmark_state": "not_configured", "missing_price_codes": missing,
        "latest_nav_date": latest_nav["trade_date"] if latest_nav else None,
        "latest_drawdown": latest_nav["drawdown"] if latest_nav else None,
    }


def run_daily_paper_cycle(
    trade_date: str, manager: CSVManager | None = None,
    account_id: str = DEFAULT_ACCOUNT_ID,
) -> dict:
    manager = manager or CSVManager("data")
    ensure_default_account()
    exit_orders = queue_due_exit_orders(trade_date, manager, account_id)
    fills = execute_pending_orders(trade_date, manager, account_id)
    nav = mark_paper_nav(trade_date, manager, account_id)
    reconciliation = reconcile_paper_account(nav)
    return {
        "available": True, "trade_date": trade_date, "exit_orders": exit_orders,
        "fills": fills, "nav": nav, "reconciliation": reconciliation,
        "status": get_paper_status(account_id, manager),
    }
