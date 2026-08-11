"""A 股日频模拟账户。

委托、尝试、成交、持仓批次、现金和净值均只追加；当前状态由事件重建。
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import asdict
from datetime import datetime
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import orjson
import pandas as pd

from utils.csv_manager import CSVManager
from utils.execution_model import (
    DEFAULT_EXECUTION_POLICY,
    calculate_fees,
    enrich_security_state_with_history,
    is_one_word_limit,
    load_exchange_calendar,
    resolve_price_limit_regime,
    security_state_from_name,
)
from views.view_manager import _get_conn, _get_migration_conn, _get_read_conn


TZ = ZoneInfo("Asia/Shanghai")
DEFAULT_ACCOUNT_ID = "paper-main-v5"


RULES = DEFAULT_EXECUTION_POLICY
MAX_POSITION_WEIGHT = 0.30


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


def _market_snapshot_reference(manager: CSVManager) -> str:
    snapshot_id = str(getattr(manager, "snapshot_id", "") or "").lower()
    if len(snapshot_id) == 64 and all(
        char in "0123456789abcdef" for char in snapshot_id
    ):
        return snapshot_id
    if (
        getattr(manager, "allow_unpublished_paper_snapshot_for_tests", False) is True
        and not manager.read_only
    ):
        # 显式的单元测试标记，不是可发布证据。
        return "unpublished-test-data"
    raise RuntimeError("paper_market_snapshot_unpinned")


def init_paper_ledger() -> None:
    with _get_migration_conn() as conn:
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
                snapshot_id TEXT NOT NULL CHECK(
                    snapshot_id = 'unpublished-test-data' OR length(snapshot_id) = 64
                ),
                execution_policy_version TEXT NOT NULL,
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
                snapshot_id TEXT NOT NULL CHECK(
                    snapshot_id = 'unpublished-test-data' OR length(snapshot_id) = 64
                ),
                execution_policy_version TEXT NOT NULL,
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
        for table in ("paper_fills", "paper_nav"):
            columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            for name in ("snapshot_id", "execution_policy_version"):
                if name not in columns:
                    # 历史行保留 NULL，不伪造当时不存在的来源证据。
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} TEXT")
        for table in (
            "paper_accounts",
            "paper_orders",
            "paper_fills",
            "paper_position_lots",
            "paper_lot_closures",
            "paper_cash_events",
            "paper_nav",
            "paper_reconciliations",
        ):
            conn.executescript(f"""
                CREATE TRIGGER IF NOT EXISTS {table}_no_update
                BEFORE UPDATE ON {table}
                BEGIN
                    SELECT RAISE(ABORT, 'immutable_paper_ledger');
                END;
                CREATE TRIGGER IF NOT EXISTS {table}_no_delete
                BEFORE DELETE ON {table}
                BEGIN
                    SELECT RAISE(ABORT, 'immutable_paper_ledger');
                END;
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
    created = _now()
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO paper_accounts
              (account_id, name, initial_cash, benchmark_code, rule_version,
               rule_json, created_at)
            VALUES (?, '主模拟账户', ?, NULL, ?, ?, ?)
        """,
            (
                DEFAULT_ACCOUNT_ID,
                float(initial_cash),
                RULES.version,
                _json(asdict(RULES)),
                created,
            ),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO paper_cash_events
              (cash_event_id, account_id, fill_id, trade_date, event_type, amount, created_at)
            VALUES (?, ?, NULL, ?, 'initial_deposit', ?, ?)
        """,
            (
                f"initial-{DEFAULT_ACCOUNT_ID}",
                DEFAULT_ACCOUNT_ID,
                created[:10],
                float(initial_cash),
                created,
            ),
        )
        row = conn.execute(
            "SELECT * FROM paper_accounts WHERE account_id = ?", (DEFAULT_ACCOUNT_ID,)
        ).fetchone()
    return dict(row)


def _require_account(account_id: str = DEFAULT_ACCOUNT_ID) -> dict:
    with _get_read_conn() as conn:
        row = conn.execute(
            "SELECT * FROM paper_accounts WHERE account_id = ?", (account_id,)
        ).fetchone()
    if row is None:
        raise RuntimeError(f"paper_account_not_initialized:{account_id}")
    account = dict(row)
    if account.get("rule_version") != RULES.version:
        raise RuntimeError(
            "paper_account_rule_version_mismatch:"
            f"{account.get('rule_version')}:{RULES.version}"
        )
    return account


def _paper_exchange_calendar(manager: CSVManager) -> list[str]:
    """生产只读 pinned payload；未发布根目录仅供显式测试开关。"""
    if getattr(manager, "snapshot_id", None):
        return load_exchange_calendar(manager.data_dir)
    if getattr(manager, "allow_unpublished_calendar", False) is True:
        return load_exchange_calendar(manager.base_data_dir)
    return []


def _calendar_distance(
    sessions: list[str],
    start_date: str,
    end_date: str,
) -> int | None:
    try:
        return sessions.index(end_date) - sessions.index(start_date)
    except ValueError:
        return None


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
    _require_account(account_id)
    if side not in {"buy", "sell"}:
        raise ValueError("side 必须是 buy 或 sell")
    identity = "|".join(
        str(value or "")
        for value in (
            account_id,
            source_lot_id,
            code,
            side,
            signal_date,
            earliest_trade_date,
        )
    )
    order_id = hashlib.sha256(identity.encode()).hexdigest()[:24]
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO paper_orders
              (order_id, account_id, decision_run_id, source_lot_id, code, side,
               signal_date, earliest_trade_date, target_weight, requested_quantity,
               reason_codes_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                order_id,
                account_id,
                decision_run_id,
                source_lot_id,
                code,
                side,
                signal_date,
                earliest_trade_date,
                target_weight,
                requested_quantity,
                _json(reason_codes or []),
                _now(),
            ),
        )
    return order_id


def queue_orders_from_decision(
    decision: dict | None, account_id: str = DEFAULT_ACCOUNT_ID
) -> dict:
    account = _require_account()
    if account_id != account["account_id"]:
        raise ValueError("未知模拟账户")
    if not decision or not decision.get("run_id"):
        return {"queued": 0, "reason": "decision_not_ready"}
    approved = [
        row for row in decision.get("candidates", []) if row.get("action") == "buy"
    ]
    if not approved:
        return {"queued": 0, "reason": "no_approved_candidates", "order_ids": []}
    earliest = (decision.get("market") or {}).get("decision_for_date")
    if not earliest:
        return {
            "queued": 0,
            "reason": "decision_execution_date_missing",
            "order_ids": [],
        }
    target = min(MAX_POSITION_WEIGHT, 0.90 / len(approved))
    order_ids = [
        create_paper_order(
            account_id,
            row["code"],
            "buy",
            decision["trade_date"],
            earliest,
            target_weight=target,
            decision_run_id=decision["run_id"],
            reason_codes=row.get("reason_codes", []),
        )
        for row in approved
    ]
    return {
        "queued": len(order_ids),
        "order_ids": order_ids,
        "earliest_trade_date": earliest,
    }


def _cash_balance(conn, account_id: str) -> float:
    row = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS value FROM paper_cash_events WHERE account_id = ?",
        (account_id,),
    ).fetchone()
    return round(float(row["value"]), 2)


def _open_lots(conn, account_id: str, code: str | None = None) -> list[dict]:
    where = "AND l.code = ?" if code else ""
    params = (account_id, code) if code else (account_id,)
    rows = conn.execute(
        f"""
        SELECT l.*,
               l.quantity - COALESCE(SUM(c.quantity), 0) AS remaining_quantity
        FROM paper_position_lots l
        LEFT JOIN paper_lot_closures c ON c.lot_id = l.lot_id
        WHERE l.account_id = ? {where}
        GROUP BY l.lot_id
        HAVING remaining_quantity > 0
        ORDER BY l.opened_date, l.created_at, l.lot_id
    """,
        params,
    ).fetchall()
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
    return calculate_fees(gross, side, RULES)


def _security_state(manager: CSVManager, code: str, trade_date: str) -> dict | None:
    """只接受同一 pinned payload 内完整复验的官方证券状态。"""
    path = manager.data_dir / "stock_names.json"
    try:
        names = orjson.loads(path.read_bytes())
    except (OSError, orjson.JSONDecodeError):
        return None
    if not isinstance(names, dict) or code not in names:
        return None
    from utils.reference_snapshots import _security_states

    states = _security_states(manager.data_dir, trade_date, set(names))
    if states:
        return states.get(code)
    if getattr(
        manager, "allow_unpublished_paper_snapshot_for_tests", False
    ) is True and not getattr(manager, "snapshot_id", None):
        # 仅保留给明确标记的未发布单元测试；生产不得用名称伪造 active。
        return security_state_from_name(names.get(code), trade_date)
    return None


def _record_attempt(
    conn,
    order: dict,
    trade_date: str,
    outcome: str,
    reason: str,
    *,
    price: float | None = None,
    quantity: int = 0,
    gross: float = 0.0,
    fees: float = 0.0,
    evidence: dict | None = None,
) -> dict:
    fill_id = uuid4().hex[:24]
    snapshot_id = str(order["_execution_snapshot_id"])
    evidence_payload = {
        **(evidence or {}),
        "snapshot_id": snapshot_id,
        "execution_policy_version": RULES.version,
    }
    conn.execute(
        """
        INSERT INTO paper_fills
          (fill_id, order_id, trade_date, snapshot_id, execution_policy_version,
           outcome, reason_code, price, quantity, gross_amount, fees,
           evidence_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (
            fill_id,
            order["order_id"],
            trade_date,
            snapshot_id,
            RULES.version,
            outcome,
            reason,
            price,
            quantity,
            round(gross, 2),
            round(fees, 2),
            _json(evidence_payload),
            _now(),
        ),
    )
    return {
        "fill_id": fill_id,
        "order_id": order["order_id"],
        "code": order["code"],
        "side": order["side"],
        "trade_date": trade_date,
        "snapshot_id": snapshot_id,
        "execution_policy_version": RULES.version,
        "outcome": outcome,
        "reason_code": reason,
        "price": price,
        "quantity": quantity,
        "gross_amount": round(gross, 2),
        "fees": round(fees, 2),
    }


def _latest_equity(conn, account_id: str) -> float:
    row = conn.execute(
        "SELECT total_equity FROM paper_nav WHERE account_id = ? "
        "ORDER BY trade_date DESC, created_at DESC, rowid DESC LIMIT 1",
        (account_id,),
    ).fetchone()
    return float(row["total_equity"]) if row else _cash_balance(conn, account_id)


def _equity_at_open(
    conn,
    account_id: str,
    manager: CSVManager,
    trade_date: str,
) -> float | None:
    """用当日开盘价独立重建下单时权益，不依赖可能过期的 NAV。"""
    market_value = 0.0
    for lot in _open_lots(conn, account_id):
        _, row, _ = _price_rows(manager, lot["code"], trade_date)
        if row is None:
            return None
        price = float(row.get("open", 0) or 0)
        if price <= 0:
            return None
        market_value += price * int(lot["remaining_quantity"])
    return _cash_balance(conn, account_id) + market_value


def execute_pending_orders(
    trade_date: str,
    manager: CSVManager,
    account_id: str = DEFAULT_ACCOUNT_ID,
) -> list[dict]:
    _require_account(account_id)
    snapshot_id = _market_snapshot_reference(manager)
    trading_sessions = _paper_exchange_calendar(manager)
    results = []
    with _get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        orders = [
            dict(row)
            for row in conn.execute(
                """
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
        """,
                (account_id, trade_date, trade_date),
            ).fetchall()
        ]
        for order in orders:
            order["_execution_snapshot_id"] = snapshot_id
            if not trading_sessions:
                results.append(
                    _record_attempt(
                        conn,
                        order,
                        trade_date,
                        "rejected" if order["side"] == "buy" else "deferred",
                        "trading_calendar_unavailable",
                    )
                )
                continue
            entry_offset = _calendar_distance(
                trading_sessions,
                order["signal_date"],
                order["earliest_trade_date"],
            )
            if order["side"] == "buy" and entry_offset != 1:
                results.append(
                    _record_attempt(
                        conn,
                        order,
                        trade_date,
                        "rejected",
                        "invalid_entry_session",
                        evidence={"signal_to_entry_sessions": entry_offset},
                    )
                )
                continue
            session_delay = _calendar_distance(
                trading_sessions,
                order["earliest_trade_date"],
                trade_date,
            )
            if session_delay is None or session_delay < 0:
                results.append(
                    _record_attempt(
                        conn,
                        order,
                        trade_date,
                        "rejected" if order["side"] == "buy" else "deferred",
                        "trading_calendar_unavailable",
                    )
                )
                continue
            if order["side"] == "buy" and session_delay != 0:
                results.append(
                    _record_attempt(
                        conn,
                        order,
                        trade_date,
                        "rejected",
                        "entry_session_missed",
                        evidence={"entry_session_delay": session_delay},
                    )
                )
                continue
            if (
                order["side"] == "sell"
                and session_delay > RULES.max_exit_delay_sessions
            ):
                results.append(
                    _record_attempt(
                        conn,
                        order,
                        trade_date,
                        "rejected",
                        "max_exit_delay_exceeded",
                        evidence={"exit_delay_sessions": session_delay},
                    )
                )
                continue
            daily, row, previous = _price_rows(manager, order["code"], trade_date)
            if row is None or previous is None:
                results.append(
                    _record_attempt(
                        conn,
                        order,
                        trade_date,
                        (
                            "rejected"
                            if order["side"] == "buy"
                            or session_delay >= RULES.max_exit_delay_sessions
                            else "deferred"
                        ),
                        "market_data_missing",
                        evidence={"session_delay": session_delay},
                    )
                )
                continue
            open_price = float(row.get("open", 0) or 0)
            previous_close = float(previous.get("close", 0) or 0)
            if open_price <= 0 or previous_close <= 0:
                results.append(
                    _record_attempt(
                        conn,
                        order,
                        trade_date,
                        (
                            "rejected"
                            if order["side"] == "buy"
                            or session_delay >= RULES.max_exit_delay_sessions
                            else "deferred"
                        ),
                        "invalid_open_price",
                    )
                )
                continue

            slip = RULES.slippage_bps_each_side / 10_000
            state = _security_state(manager, order["code"], trade_date)
            observed_sessions = int((daily["date"] <= trade_date).sum())
            state = enrich_security_state_with_history(state, observed_sessions)
            regime = resolve_price_limit_regime(order["code"], trade_date, state)
            if not regime["point_in_time_verified"]:
                results.append(
                    _record_attempt(
                        conn,
                        order,
                        trade_date,
                        (
                            "rejected"
                            if order["side"] == "buy"
                            or session_delay >= RULES.max_exit_delay_sessions
                            else "deferred"
                        ),
                        "pit_security_state_missing",
                        evidence={"regime": regime},
                    )
                )
                continue
            volume = float(row.get("volume", 0) or 0)
            if not regime["can_trade"] or volume <= 0:
                results.append(
                    _record_attempt(
                        conn,
                        order,
                        trade_date,
                        (
                            "rejected"
                            if order["side"] == "buy"
                            or session_delay >= RULES.max_exit_delay_sessions
                            else "deferred"
                        ),
                        "security_suspended",
                        evidence={
                            "regime": regime,
                            "volume": volume,
                            "session_delay": session_delay,
                        },
                    )
                )
                continue
            if order["side"] == "buy":
                trade_session_i = trading_sessions.index(trade_date)
                sellable_date = (
                    trading_sessions[trade_session_i + 1]
                    if trade_session_i + 1 < len(trading_sessions)
                    else ""
                )
                if not sellable_date:
                    results.append(
                        _record_attempt(
                            conn,
                            order,
                            trade_date,
                            "rejected",
                            "trading_calendar_unavailable",
                        )
                    )
                    continue
                if is_one_word_limit(
                    row,
                    previous_close,
                    "up",
                    regime["limit_up_pct"],
                ):
                    results.append(
                        _record_attempt(
                            conn,
                            order,
                            trade_date,
                            "rejected",
                            "one_word_limit_up",
                            evidence={
                                "open": open_price,
                                "previous_close": previous_close,
                                "regime": regime,
                            },
                        )
                    )
                    continue
                cash = _cash_balance(conn, account_id)
                equity = _equity_at_open(conn, account_id, manager, trade_date)
                if equity is None:
                    results.append(
                        _record_attempt(
                            conn,
                            order,
                            trade_date,
                            "rejected",
                            "portfolio_price_missing",
                        )
                    )
                    continue
                existing_quantity = sum(
                    int(lot["remaining_quantity"])
                    for lot in _open_lots(conn, account_id, order["code"])
                )
                current_position_value = existing_quantity * open_price
                desired_position_value = equity * min(
                    float(order["target_weight"] or 0),
                    MAX_POSITION_WEIGHT,
                )
                incremental_budget = max(
                    desired_position_value - current_position_value,
                    0.0,
                )
                target = min(cash, incremental_budget)
                price = round(open_price * (1 + slip), 4)
                quantity = (
                    math.floor(
                        max(target - RULES.minimum_commission, 0)
                        / price
                        / RULES.board_lot
                    )
                    * RULES.board_lot
                )
                while quantity > 0:
                    gross = price * quantity
                    fees = _fees(gross, "buy")
                    if gross + fees <= cash + 1e-6:
                        break
                    quantity -= RULES.board_lot
                if quantity < RULES.board_lot:
                    reason = (
                        "position_limit_reached"
                        if incremental_budget < price * RULES.board_lot
                        else "insufficient_cash"
                    )
                    results.append(
                        _record_attempt(
                            conn,
                            order,
                            trade_date,
                            "rejected",
                            reason,
                            evidence={
                                "current_position_value": round(
                                    current_position_value, 2
                                ),
                                "desired_position_value": round(
                                    desired_position_value, 2
                                ),
                                "max_position_weight": MAX_POSITION_WEIGHT,
                            },
                        )
                    )
                    continue
                gross = round(price * quantity, 2)
                fees = _fees(gross, "buy")
                fill = _record_attempt(
                    conn,
                    order,
                    trade_date,
                    "filled",
                    "filled",
                    price=price,
                    quantity=quantity,
                    gross=gross,
                    fees=fees,
                    evidence={
                        "approximate": True,
                        "execution_policy_version": RULES.version,
                        "regime": regime,
                    },
                )
                conn.execute(
                    """
                    INSERT INTO paper_cash_events VALUES (?, ?, ?, ?, 'buy_principal', ?, ?)
                """,
                    (
                        uuid4().hex[:24],
                        account_id,
                        fill["fill_id"],
                        trade_date,
                        -gross,
                        _now(),
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO paper_cash_events VALUES (?, ?, ?, ?, 'trading_fee', ?, ?)
                """,
                    (
                        uuid4().hex[:24],
                        account_id,
                        fill["fill_id"],
                        trade_date,
                        -fees,
                        _now(),
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO paper_position_lots
                      (lot_id, account_id, buy_fill_id, code, opened_date,
                       sellable_date, quantity, cost_amount, hold_sessions, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        uuid4().hex[:24],
                        account_id,
                        fill["fill_id"],
                        order["code"],
                        trade_date,
                        sellable_date,
                        quantity,
                        gross + fees,
                        RULES.holding_sessions,
                        _now(),
                    ),
                )
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
                results.append(
                    _record_attempt(conn, order, trade_date, outcome, reason)
                )
                continue
            if is_one_word_limit(
                row,
                previous_close,
                "down",
                regime["limit_down_pct"],
            ):
                results.append(
                    _record_attempt(
                        conn,
                        order,
                        trade_date,
                        (
                            "rejected"
                            if session_delay >= RULES.max_exit_delay_sessions
                            else "deferred"
                        ),
                        "one_word_limit_down",
                        evidence={
                            "open": open_price,
                            "previous_close": previous_close,
                            "regime": regime,
                            "exit_delay_sessions": session_delay,
                        },
                    )
                )
                continue
            price = round(open_price * (1 - slip), 4)
            gross = round(price * quantity, 2)
            fees = _fees(gross, "sell")
            fill = _record_attempt(
                conn,
                order,
                trade_date,
                "filled",
                "filled",
                price=price,
                quantity=quantity,
                gross=gross,
                fees=fees,
                evidence={
                    "approximate": True,
                    "execution_policy_version": RULES.version,
                    "regime": regime,
                },
            )
            conn.execute(
                """
                INSERT INTO paper_cash_events VALUES (?, ?, ?, ?, 'sell_proceeds', ?, ?)
            """,
                (
                    uuid4().hex[:24],
                    account_id,
                    fill["fill_id"],
                    trade_date,
                    gross,
                    _now(),
                ),
            )
            conn.execute(
                """
                INSERT INTO paper_cash_events VALUES (?, ?, ?, ?, 'trading_fee', ?, ?)
            """,
                (
                    uuid4().hex[:24],
                    account_id,
                    fill["fill_id"],
                    trade_date,
                    -fees,
                    _now(),
                ),
            )
            remaining = quantity
            for lot in sellable:
                close_quantity = min(remaining, int(lot["remaining_quantity"]))
                if close_quantity <= 0:
                    break
                conn.execute(
                    """
                    INSERT INTO paper_lot_closures
                      (closure_id, lot_id, sell_fill_id, quantity, proceeds, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """,
                    (
                        uuid4().hex[:24],
                        lot["lot_id"],
                        fill["fill_id"],
                        close_quantity,
                        round(gross * close_quantity / quantity, 2),
                        _now(),
                    ),
                )
                remaining -= close_quantity
            results.append(fill)
    return results


def queue_due_exit_orders(
    trade_date: str,
    manager: CSVManager,
    account_id: str = DEFAULT_ACCOUNT_ID,
) -> list[str]:
    _require_account(account_id)
    _market_snapshot_reference(manager)
    trading_sessions = _paper_exchange_calendar(manager)
    if trade_date not in trading_sessions:
        raise RuntimeError("paper_trading_calendar_unavailable")
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
            try:
                opened_i = trading_sessions.index(lot["opened_date"])
            except ValueError:
                continue
            target_i = opened_i + int(lot["hold_sessions"])
            if target_i >= len(trading_sessions):
                continue
            target_date = trading_sessions[target_i]
            if target_date > trade_date:
                continue
            signal_date = trading_sessions[target_i - 1]
            order_ids.append(
                create_paper_order(
                    account_id,
                    lot["code"],
                    "sell",
                    signal_date,
                    target_date,
                    requested_quantity=int(lot["remaining_quantity"]),
                    decision_run_id=f"fixed-exit:{lot['lot_id']}",
                    source_lot_id=lot["lot_id"],
                    reason_codes=["fixed_hold_sessions_reached"],
                )
            )
    return order_ids


def _position_snapshot(
    conn, account_id: str, manager: CSVManager, as_of: str | None = None
) -> tuple[list[dict], list[str]]:
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
            price = None
        positions.append(
            {
                "lot_id": lot["lot_id"],
                "code": lot["code"],
                "quantity": int(lot["remaining_quantity"]),
                "opened_date": lot["opened_date"],
                "sellable_date": lot["sellable_date"],
                "cost_amount": lot["cost_amount"],
                "last_price": round(price, 4) if price is not None else None,
                "price_date": price_date,
                "market_value": round(price * int(lot["remaining_quantity"]), 2)
                if price is not None
                else None,
            }
        )
    return positions, sorted(set(missing))


def mark_paper_nav(
    trade_date: str,
    manager: CSVManager,
    account_id: str = DEFAULT_ACCOUNT_ID,
) -> dict:
    _require_account(account_id)
    snapshot_id = _market_snapshot_reference(manager)
    with _get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        cash = _cash_balance(conn, account_id)
        positions, missing = _position_snapshot(conn, account_id, manager, trade_date)
        if missing:
            return {
                "available": False,
                "reason": "missing_position_prices",
                "account_id": account_id,
                "trade_date": trade_date,
                "snapshot_id": snapshot_id,
                "execution_policy_version": RULES.version,
                "cash": cash,
                "positions": positions,
                "missing_price_codes": missing,
                "pricing_status": "missing_prices",
            }
        market_value = round(sum(row["market_value"] for row in positions), 2)
        equity = round(cash + market_value, 2)
        peak = conn.execute(
            "SELECT MAX(total_equity) AS peak FROM paper_nav WHERE account_id = ?",
            (account_id,),
        ).fetchone()["peak"]
        peak = max(float(peak or equity), equity)
        drawdown = round(equity / peak - 1, 6) if peak > 0 else 0.0
        gross = conn.execute(
            """
            SELECT COALESCE(SUM(gross_amount), 0) AS gross
            FROM paper_fills f JOIN paper_orders o ON o.order_id = f.order_id
            WHERE o.account_id = ? AND f.trade_date = ? AND f.outcome = 'filled'
        """,
            (account_id, trade_date),
        ).fetchone()["gross"]
        prior = conn.execute(
            "SELECT total_equity FROM paper_nav WHERE account_id = ? AND trade_date < ? "
            "ORDER BY trade_date DESC, created_at DESC LIMIT 1",
            (account_id, trade_date),
        ).fetchone()
        denominator = float(prior["total_equity"]) if prior else equity
        turnover = round(float(gross) / denominator, 6) if denominator > 0 else 0.0
        as_of = f"{trade_date}T15:00:00+08:00"
        nav_id = hashlib.sha256(
            f"{account_id}|{trade_date}|{snapshot_id}|{as_of}|{RULES.version}".encode()
        ).hexdigest()[:24]
        payload = {
            "nav_id": nav_id,
            "account_id": account_id,
            "trade_date": trade_date,
            "snapshot_id": snapshot_id,
            "execution_policy_version": RULES.version,
            "as_of": as_of,
            "cash": cash,
            "market_value": market_value,
            "total_equity": equity,
            "exposure": round(market_value / equity, 6) if equity > 0 else 0.0,
            "drawdown": drawdown,
            "turnover": turnover,
            "benchmark_value": None,
            "pricing_status": "complete" if not missing else "missing_prices",
        }
        existing = conn.execute(
            "SELECT * FROM paper_nav WHERE nav_id = ?",
            (nav_id,),
        ).fetchone()
        if existing is not None:
            comparable = (
                "cash",
                "market_value",
                "total_equity",
                "exposure",
                "drawdown",
                "turnover",
                "pricing_status",
                "snapshot_id",
                "execution_policy_version",
            )
            if any(existing[key] != payload[key] for key in comparable):
                raise RuntimeError("nav_conflict_requires_explicit_correction")
        else:
            conn.execute(
                """
                INSERT INTO paper_nav
              (nav_id, account_id, trade_date, snapshot_id, as_of, cash,
               execution_policy_version, market_value, total_equity, exposure,
               drawdown, turnover, benchmark_value, pricing_status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    payload["nav_id"],
                    payload["account_id"],
                    payload["trade_date"],
                    payload["snapshot_id"],
                    payload["as_of"],
                    payload["cash"],
                    payload["execution_policy_version"],
                    payload["market_value"],
                    payload["total_equity"],
                    payload["exposure"],
                    payload["drawdown"],
                    payload["turnover"],
                    payload["benchmark_value"],
                    payload["pricing_status"],
                    _now(),
                ),
            )
    return {
        "available": True,
        **payload,
        "positions": positions,
        "missing_price_codes": missing,
        "idempotent_replay": existing is not None,
    }


def reconcile_paper_account(nav: dict) -> dict:
    if not nav.get("available", True):
        return {
            "balanced": False,
            "reason_codes": ["missing_position_prices"],
            "difference": None,
        }
    with _get_conn() as conn:
        account_id = nav["account_id"]
        reasons: list[str] = []
        account = conn.execute(
            "SELECT initial_cash FROM paper_accounts WHERE account_id = ?",
            (account_id,),
        ).fetchone()
        initial_events = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS value FROM paper_cash_events "
            "WHERE account_id = ? AND event_type = 'initial_deposit'",
            (account_id,),
        ).fetchone()["value"]
        if (
            account is None
            or abs(float(initial_events) - float(account["initial_cash"])) > 0.01
        ):
            reasons.append("initial_cash_event_mismatch")

        fills = [
            dict(row)
            for row in conn.execute(
                """
            SELECT f.*, o.side FROM paper_fills f
            JOIN paper_orders o ON o.order_id = f.order_id
            WHERE o.account_id = ? AND f.outcome = 'filled'
        """,
                (account_id,),
            ).fetchall()
        ]
        independently_rebuilt_cash = float(initial_events)
        for fill in fills:
            fill_id = fill["fill_id"]
            events = [
                dict(row)
                for row in conn.execute(
                    "SELECT event_type, amount FROM paper_cash_events WHERE fill_id = ?",
                    (fill_id,),
                ).fetchall()
            ]
            by_type: dict[str, float] = {}
            for event in events:
                by_type[event["event_type"]] = by_type.get(
                    event["event_type"], 0.0
                ) + float(event["amount"])
            gross, fees = float(fill["gross_amount"]), float(fill["fees"])
            if fill["side"] == "buy":
                independently_rebuilt_cash -= gross + fees
                if (
                    abs(by_type.get("buy_principal", 0.0) + gross) > 0.01
                    or abs(by_type.get("trading_fee", 0.0) + fees) > 0.01
                ):
                    reasons.append("buy_cash_events_mismatch")
                lots = conn.execute(
                    "SELECT COALESCE(SUM(quantity), 0) AS quantity, "
                    "COALESCE(SUM(cost_amount), 0) AS cost FROM paper_position_lots "
                    "WHERE buy_fill_id = ?",
                    (fill_id,),
                ).fetchone()
                if (
                    int(lots["quantity"]) != int(fill["quantity"])
                    or abs(float(lots["cost"]) - gross - fees) > 0.01
                ):
                    reasons.append("buy_fill_lot_mismatch")
            else:
                independently_rebuilt_cash += gross - fees
                if (
                    abs(by_type.get("sell_proceeds", 0.0) - gross) > 0.01
                    or abs(by_type.get("trading_fee", 0.0) + fees) > 0.01
                ):
                    reasons.append("sell_cash_events_mismatch")
                closed = conn.execute(
                    "SELECT COALESCE(SUM(quantity), 0) AS quantity FROM paper_lot_closures "
                    "WHERE sell_fill_id = ?",
                    (fill_id,),
                ).fetchone()["quantity"]
                if int(closed) != int(fill["quantity"]):
                    reasons.append("sell_fill_closure_mismatch")

        invalid_lots = conn.execute("""
            SELECT l.lot_id FROM paper_position_lots l
            LEFT JOIN paper_lot_closures c ON c.lot_id = l.lot_id
            GROUP BY l.lot_id
            HAVING COALESCE(SUM(c.quantity), 0) > l.quantity
               OR l.quantity - COALESCE(SUM(c.quantity), 0) < 0
        """).fetchall()
        if invalid_lots:
            reasons.append("lot_quantity_invariant_broken")

        event_cash = _cash_balance(conn, account_id)
        if abs(event_cash - independently_rebuilt_cash) > 0.01:
            reasons.append("cash_event_sum_mismatch")
        position_market_value = round(
            sum(float(row["market_value"]) for row in nav.get("positions", [])),
            2,
        )
        if abs(position_market_value - float(nav["market_value"])) > 0.01:
            reasons.append("position_valuation_mismatch")
        independently_rebuilt_equity = round(
            independently_rebuilt_cash + position_market_value,
            2,
        )
        difference = round(independently_rebuilt_equity - float(nav["total_equity"]), 2)
        if abs(float(nav["cash"]) - independently_rebuilt_cash) > 0.01:
            reasons.append("nav_cash_mismatch")
        if abs(difference) > 0.01:
            reasons.append("cash_position_nav_mismatch")
        formal_nav_count = conn.execute(
            "SELECT COUNT(*) AS n FROM paper_nav WHERE account_id = ? "
            "AND trade_date = ? AND snapshot_id = ? AND as_of = ?",
            (
                account_id,
                nav["trade_date"],
                nav["snapshot_id"],
                nav["as_of"],
            ),
        ).fetchone()["n"]
        if int(formal_nav_count) != 1:
            reasons.append("formal_nav_not_unique")

        reasons = sorted(set(reasons))
        reconciliation_id = hashlib.sha256(
            f"{account_id}|{nav['nav_id']}|event-reconciliation-v2".encode()
        ).hexdigest()[:24]
        conn.execute(
            """
            INSERT OR IGNORE INTO paper_reconciliations
              (reconciliation_id, account_id, trade_date, nav_id, balanced,
               difference, reason_codes_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                reconciliation_id,
                account_id,
                nav["trade_date"],
                nav["nav_id"],
                int(not reasons),
                difference,
                _json(reasons),
                _now(),
            ),
        )
    return {
        "reconciliation_id": reconciliation_id,
        "balanced": not reasons,
        "difference": difference,
        "reason_codes": reasons,
        "event_cash": event_cash,
        "independently_rebuilt_cash": round(independently_rebuilt_cash, 2),
        "independently_rebuilt_market_value": position_market_value,
        "independently_rebuilt_equity": independently_rebuilt_equity,
        "formal_nav_count": int(formal_nav_count),
    }


def get_paper_status(
    account_id: str = DEFAULT_ACCOUNT_ID,
    manager: CSVManager | None = None,
) -> dict:
    manager = manager or CSVManager("data", writable=False)
    with _get_read_conn() as conn:
        account = conn.execute(
            "SELECT * FROM paper_accounts WHERE account_id = ?", (account_id,)
        ).fetchone()
        if account is None:
            return {"established": False, "reason": "paper_account_not_established"}
        cash = _cash_balance(conn, account_id)
        positions, missing = _position_snapshot(conn, account_id, manager)
        market_value = (
            round(sum(row["market_value"] for row in positions), 2)
            if not missing
            else None
        )
        latest_nav = conn.execute(
            "SELECT * FROM paper_nav WHERE account_id = ? "
            "ORDER BY trade_date DESC, created_at DESC, rowid DESC LIMIT 1",
            (account_id,),
        ).fetchone()
        nav_days = conn.execute(
            "SELECT COUNT(DISTINCT trade_date) AS n FROM paper_nav WHERE account_id = ?",
            (account_id,),
        ).fetchone()["n"]
        pending = conn.execute(
            """
            SELECT COUNT(*) AS n FROM paper_orders o
            WHERE o.account_id = ? AND NOT EXISTS (
                SELECT 1 FROM paper_fills f WHERE f.order_id = o.order_id
                  AND f.outcome IN ('filled', 'rejected')
            )
        """,
            (account_id,),
        ).fetchone()["n"]
    equity = round(cash + market_value, 2) if market_value is not None else None
    initial = float(account["initial_cash"])
    return {
        "established": True,
        "account_id": account_id,
        "rule_version": account["rule_version"],
        "cash": cash,
        "available": not missing,
        "reason": "missing_position_prices" if missing else None,
        "market_value": market_value,
        "total_equity": equity,
        "net_return": round(equity / initial - 1, 6)
        if equity is not None and initial > 0 and nav_days
        else None,
        "positions": positions,
        "pending_orders": int(pending),
        "nav_days": int(nav_days),
        "track_record_state": "collecting"
        if nav_days < 60
        else "operational_history_ready",
        "benchmark_state": "not_configured",
        "missing_price_codes": missing,
        "latest_nav_date": latest_nav["trade_date"] if latest_nav else None,
        "latest_drawdown": latest_nav["drawdown"] if latest_nav else None,
    }


def run_daily_paper_cycle(
    trade_date: str,
    manager: CSVManager | None = None,
    account_id: str = DEFAULT_ACCOUNT_ID,
) -> dict:
    manager = manager or CSVManager("data", writable=False)
    _require_account(account_id)
    _market_snapshot_reference(manager)
    exit_orders = queue_due_exit_orders(trade_date, manager, account_id)
    fills = execute_pending_orders(trade_date, manager, account_id)
    nav = mark_paper_nav(trade_date, manager, account_id)
    if not nav.get("available", True):
        return {
            "available": False,
            "reason": nav["reason"],
            "trade_date": trade_date,
            "exit_orders": exit_orders,
            "fills": fills,
            "nav": nav,
            "reconciliation": reconcile_paper_account(nav),
            "status": get_paper_status(account_id, manager),
        }
    reconciliation = reconcile_paper_account(nav)
    return {
        "available": True,
        "trade_date": trade_date,
        "exit_orders": exit_orders,
        "fills": fills,
        "nav": nav,
        "reconciliation": reconciliation,
        "status": get_paper_status(account_id, manager),
    }
