"""生产、回放、训练和模拟盘共用的 A 股日频成交政策。

日线无法还原集合竞价排队和部分成交，因此结果始终标记
``approximate=True``。所有输出都绑定一个不可变的政策版本。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass, replace
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Mapping

import pandas as pd


@dataclass(frozen=True)
class CostModel:
    """兼容旧调用的费率覆盖。"""

    commission_rate: float = 0.0003
    stamp_duty_sell_rate: float = 0.0005
    slippage_bps_each_side: float = 5.0
    minimum_commission: float = 5.0
    transfer_fee_rate: float = 0.00001


@dataclass(frozen=True)
class ExecutionPolicy:
    version: str = "a-share-eod-open-open-v5"
    decision_time: str = "signal_session_close"
    entry_rule: str = "next_session_open"
    exit_rule: str = "open_after_completed_holding_sessions"
    holding_sessions: int = 5
    max_exit_delay_sessions: int = 5
    commission_rate: float = 0.0003
    minimum_commission: float = 5.0
    stamp_duty_sell_rate: float = 0.0005
    transfer_fee_rate: float = 0.00001
    slippage_bps_each_side: float = 5.0
    board_lot: int = 100
    reference_notional: float = 100_000.0
    price_limit_regime: str = "cn-a-share-pit-v3"
    suspension_rule: str = "zero-volume-or-pit-suspended-no-fill"
    partial_fill_rule: str = "daily-bars-do-not-prove-liquidity;all-or-none"
    liquidity_cap: str = "not_available_in_daily_bar;approximate"
    session_axis_rule: str = "pinned_exchange_calendar;missing_bar_is_no_fill"


DEFAULT_EXECUTION_POLICY = ExecutionPolicy()


def load_exchange_sessions(
    payload_dir: str | Path,
    *,
    through_date: str | None = None,
) -> list[str]:
    """从已绑定的行情快照载入交易所会话轴。

    调用方必须传入 ``CSVManager.data_dir`` 这类已固定的 snapshot
    payload，不在成交计算期间跟随可变 CURRENT 指针。
    """
    payload = Path(payload_dir)
    calendar = load_exchange_calendar(payload)
    if not calendar:
        return []
    cutoff = str(through_date or "")[:10]
    if not cutoff:
        try:
            manifest = json.loads((payload.parent / "manifest.json").read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        cutoff = str(manifest.get("trade_date") or "")[:10]
    if not cutoff:
        return []
    return [date for date in calendar if date <= cutoff]


def load_exchange_calendar(payload_dir: str | Path) -> list[str]:
    """读取已绑定快照的完整交易所日历（含已公布的未来会话）。"""
    path = Path(payload_dir) / "trade_calendar.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return _normalize_sessions(document) if isinstance(document, list) else []


def _normalize_sessions(values: Iterable[object]) -> list[str]:
    sessions: set[str] = set()
    for value in values:
        try:
            timestamp = pd.Timestamp(value)
        except (TypeError, ValueError):
            continue
        if pd.isna(timestamp):
            continue
        sessions.add(timestamp.strftime("%Y-%m-%d"))
    return sorted(sessions)


def _session_axis_evidence(sessions: list[str], source: str) -> dict:
    canonical = json.dumps(sessions, separators=(",", ":")).encode()
    return {
        "session_axis_source": source,
        "session_axis_verified": source == "pinned_exchange_calendar",
        "session_axis_hash": hashlib.sha256(canonical).hexdigest(),
        "session_axis_count": len(sessions),
        "session_axis_end": sessions[-1] if sessions else None,
    }


def execution_policy_manifest(
    policy: ExecutionPolicy = DEFAULT_EXECUTION_POLICY,
) -> dict:
    return asdict(policy)


def security_state_from_name(name: str | None, as_of: str) -> dict:
    """从当日股票名称快照提取风险警示状态。

    名称只能证明当日 ST 标记，不能证明是否处于上市初期。后者必须由
    历史行情行数或独立上市日期快照补齐。
    """
    normalized = str(name or "").strip().upper().replace("＊", "*")
    return {
        "as_of": str(as_of)[:10],
        "is_st": "ST" in normalized,
        "trading_status": "active",
        "source": "immutable-stock-name-risk-marker-v1",
        "listing_rule_verified": False,
    }


def enrich_security_state_with_history(
    security_state: Mapping | None,
    observed_sessions: int,
) -> dict | None:
    """用截至当日已观察到的交易日数证明已离开上市初期。

    只要已有至少 6 根更早/当日交易日线，就能确定不再处于任何当前板块的
    前 5 日无涨跌幅阶段；这不依赖把截断数据首日误当成真实上市日。
    """
    if security_state is None:
        return None
    state = dict(security_state)
    sessions = max(int(observed_sessions), 0)
    state["observed_trading_sessions"] = sessions
    if isinstance(state.get("listing_session_number"), int):
        state["listing_rule_verified"] = True
    elif sessions >= 6:
        state["listing_rule_verified"] = True
        state["initial_listing_period"] = False
    return state


def _initial_regime(
    code: str, trade_date: str, session_number: int | None
) -> dict | None:
    if not session_number or session_number < 1:
        return None
    if code.startswith(("688", "689")) and trade_date >= "2019-07-22":
        return {"no_limit": session_number <= 5, "rule": "star_first_five_sessions"}
    if code.startswith(("300", "301")) and trade_date >= "2020-08-24":
        return {"no_limit": session_number <= 5, "rule": "chinext_first_five_sessions"}
    if code.startswith(("4", "8", "92")) and trade_date >= "2021-11-15":
        return {"no_limit": session_number == 1, "rule": "beijing_first_session"}
    if code.startswith(("600", "601", "603", "605", "000", "001", "002", "003")):
        if trade_date >= "2023-04-10":
            return {
                "no_limit": session_number <= 5,
                "rule": "registration_main_first_five",
            }
        if session_number == 1:
            return {
                "no_limit": False,
                "limit_up_pct": 0.44,
                "limit_down_pct": 0.36,
                "rule": "legacy_main_ipo_first_session_44_36",
            }
    return None


def limit_price(
    previous_close: float, direction: str, limit_pct: float = 0.10
) -> float:
    if direction not in {"up", "down"}:
        raise ValueError("direction 必须是 up 或 down")
    multiplier = 1 + limit_pct if direction == "up" else 1 - limit_pct
    return float(
        (Decimal(str(previous_close)) * Decimal(str(multiplier))).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
    )


def resolve_price_limit_regime(
    code: str,
    trade_date: str,
    security_state: Mapping | None = None,
) -> dict:
    """按当日证券状态和历史板块制度解析涨跌停。

    ``security_state`` 来自当日不可变快照；没有它时只能根据代码和
    制度日期推断，会明确标记为未完整 PIT 证据。
    """
    state = dict(security_state or {})
    status_verified = bool(
        state
        and str(state.get("as_of") or "")[:10] == str(trade_date)[:10]
        and state.get("source")
    )
    listing_verified = state.get("listing_rule_verified") is True
    verified = status_verified and listing_verified
    if state.get("trading_status") in {"suspended", "delisted"}:
        return {
            "limit_pct": None,
            "limit_up_pct": None,
            "limit_down_pct": None,
            "can_trade": False,
            "point_in_time_verified": verified,
            "status_verified": status_verified,
            "listing_rule_verified": listing_verified,
            "source": state.get("source") or "missing_pit_security_state",
            "rule": "security_not_tradable",
            "reason": str(state.get("trading_status")),
        }
    initial = (
        _initial_regime(
            code,
            str(trade_date)[:10],
            state.get("listing_session_number"),
        )
        if listing_verified
        else None
    )
    limit_up_pct = limit_down_pct = None
    rule = "regular_board_regime"
    if initial and initial.get("no_limit"):
        limit_pct = None
        rule = initial["rule"]
    elif initial and initial.get("limit_up_pct") is not None:
        limit_pct = None
        limit_up_pct = float(initial["limit_up_pct"])
        limit_down_pct = float(initial["limit_down_pct"])
        rule = initial["rule"]
    elif state.get("no_price_limit") is True:
        limit_pct = None
        rule = "explicit_no_price_limit"
    elif isinstance(state.get("limit_pct"), (int, float)):
        limit_pct = float(state["limit_pct"])
    elif bool(state.get("is_st")):
        limit_pct = 0.05
    elif code.startswith(("688", "689")) and trade_date >= "2019-07-22":
        limit_pct = 0.20
    elif code.startswith(("300", "301")) and trade_date >= "2020-08-24":
        limit_pct = 0.20
    elif code.startswith(("4", "8", "92")) and trade_date >= "2021-11-15":
        limit_pct = 0.30
    else:
        limit_pct = 0.10
    if limit_pct is not None:
        limit_up_pct = limit_down_pct = limit_pct
    return {
        "limit_pct": limit_pct,
        "limit_up_pct": limit_up_pct,
        "limit_down_pct": limit_down_pct,
        "can_trade": True,
        "point_in_time_verified": verified,
        "status_verified": status_verified,
        "listing_rule_verified": listing_verified,
        "source": state.get("source") or "board_code_and_regime_date_inference",
        "rule": rule,
        "reason": "ok" if verified else "listing_or_status_evidence_incomplete",
    }


def is_one_word_limit(
    row: pd.Series,
    previous_close: float,
    direction: str,
    limit_pct: float | None = 0.10,
) -> bool:
    if limit_pct is None:
        return False
    price = limit_price(previous_close, direction, limit_pct)
    tolerance = 0.011
    values = [float(row.get(key, 0) or 0) for key in ("open", "high", "low", "close")]
    if direction == "up":
        return min(values) >= price - tolerance
    return max(values) <= price + tolerance


def _fees(gross: float, side: str, policy: ExecutionPolicy) -> float:
    commission = max(policy.minimum_commission, gross * policy.commission_rate)
    transfer = gross * policy.transfer_fee_rate
    stamp = gross * policy.stamp_duty_sell_rate if side == "sell" else 0.0
    return commission + transfer + stamp


def calculate_fees(
    gross: float,
    side: str,
    policy: ExecutionPolicy = DEFAULT_EXECUTION_POLICY,
) -> float:
    """统一费用计算入口，供模拟盘和研究回放共用。"""
    if side not in {"buy", "sell"}:
        raise ValueError("side 必须是 buy 或 sell")
    return round(_fees(float(gross), side, policy), 2)


def _net_return(
    entry: float, exit_price: float, policy: ExecutionPolicy
) -> tuple[float, dict]:
    slip = policy.slippage_bps_each_side / 10_000
    paid_price = entry * (1 + slip)
    received_price = exit_price * (1 - slip)
    quantity = (
        int(policy.reference_notional / paid_price / policy.board_lot)
        * policy.board_lot
    )
    if quantity <= 0:
        return float("nan"), {"quantity": 0}
    buy_gross = paid_price * quantity
    sell_gross = received_price * quantity
    buy_fees = _fees(buy_gross, "buy", policy)
    sell_fees = _fees(sell_gross, "sell", policy)
    invested = buy_gross + buy_fees
    returned = sell_gross - sell_fees
    return (returned / invested - 1) * 100, {
        "reference_quantity": quantity,
        "buy_gross": round(buy_gross, 2),
        "sell_gross": round(sell_gross, 2),
        "buy_fees": round(buy_fees, 2),
        "sell_fees": round(sell_fees, 2),
    }


def _state_for(
    security_states: Mapping[str, Mapping] | None,
    trade_date: str,
) -> Mapping | None:
    return security_states.get(str(trade_date)[:10]) if security_states else None


def evaluate_trade(
    daily: pd.DataFrame,
    run_date: str,
    hold_days: int = 5,
    costs: CostModel | None = None,
    max_exit_delay: int = 5,
    *,
    code: str = "",
    security_states: Mapping[str, Mapping] | None = None,
    trading_sessions: Iterable[object] | None = None,
    require_pit_status: bool = False,
    policy: ExecutionPolicy = DEFAULT_EXECUTION_POLICY,
) -> dict:
    """信号日收盘决策，下一交易所会话开盘尝试入场。

    ``trading_sessions`` 必须是截止当前已发布快照日的不可变
    交易所会话轴。个股停牌时可以没有 bar，但会话仍然推进；
    缺 bar 的会话只能判定为不可成交，不得跳到复牌日代替执行。
    """
    policy = replace(
        policy,
        holding_sessions=int(hold_days),
        max_exit_delay_sessions=int(max_exit_delay),
    )
    if costs is not None:
        policy = replace(
            policy,
            commission_rate=costs.commission_rate,
            stamp_duty_sell_rate=costs.stamp_duty_sell_rate,
            slippage_bps_each_side=costs.slippage_bps_each_side,
            minimum_commission=costs.minimum_commission,
            transfer_fee_rate=costs.transfer_fee_rate,
        )
    common = {
        "approximate": True,
        "execution_policy_version": policy.version,
        "execution_policy": execution_policy_manifest(policy),
    }
    if daily is None or daily.empty:
        return {"available": False, "reason": "no_daily_data", **common}
    d = daily.copy()
    d["_session_date"] = pd.to_datetime(d["date"], errors="coerce")
    d = d.dropna(subset=["_session_date"])
    d["_session_date"] = d["_session_date"].dt.strftime("%Y-%m-%d")
    d = (
        d.sort_values("_session_date")
        .drop_duplicates(subset=["_session_date"], keep="last")
        .reset_index(drop=True)
    )
    if d.empty:
        return {"available": False, "reason": "no_daily_data", **common}
    dates = d["_session_date"]
    run_session = str(run_date)[:10]
    hits = d.index[dates == run_session].tolist()
    if not hits:
        return {"available": False, "reason": "run_date_missing", **common}

    sessions = _normalize_sessions(trading_sessions or [])
    if not sessions:
        return {
            "available": False,
            "reason": "trading_calendar_missing",
            **_session_axis_evidence([], "missing"),
            **common,
        }
    common = {
        **_session_axis_evidence(sessions, "pinned_exchange_calendar"),
        **common,
    }
    if run_session not in sessions:
        return {
            "available": False,
            "reason": "run_date_not_in_trading_calendar",
            **common,
        }

    bar_index_by_date = {str(date): int(i) for i, date in dates.items()}
    signal_i = hits[-1]
    signal_session_i = sessions.index(run_session)
    entry_session_i = signal_session_i + 1
    if entry_session_i >= len(sessions):
        return {
            "available": False,
            "reason": "entry_not_available",
            "entry_label_mature": False,
            "label_end_date": sessions[-1],
            **common,
        }

    entry_date = sessions[entry_session_i]
    entry_i = bar_index_by_date.get(entry_date)
    observed_entry_bars = int((dates <= entry_date).sum())
    entry_state = enrich_security_state_with_history(
        _state_for(security_states, entry_date),
        observed_entry_bars,
    )
    entry_regime = resolve_price_limit_regime(code, entry_date, entry_state)
    if require_pit_status and not entry_regime["point_in_time_verified"]:
        return {
            "available": False,
            "reason": "pit_security_state_missing",
            "entry_date": entry_date,
            "entry_label_mature": False,
            "entry_regime": entry_regime,
            **common,
        }
    entry_state_status = str((entry_state or {}).get("trading_status") or "")
    if entry_i is None and entry_state_status not in {"suspended", "delisted"}:
        return {
            "available": False,
            "reason": "market_bar_missing",
            "execution_status": "market_bar_missing",
            "entry_date": entry_date,
            "entry_bar_available": False,
            "entry_label_mature": False,
            "exit_label_mature": False,
            "return_label_mature": False,
            "entry_regime": entry_regime,
            "label_end_date": entry_date,
            **common,
        }

    previous_close = float(d.iloc[signal_i]["close"])
    entry_row = d.iloc[entry_i] if entry_i is not None else None
    entry_price = float(entry_row.get("open", 0) or 0) if entry_row is not None else 0
    volume = float(entry_row.get("volume", 0) or 0) if entry_row is not None else 0
    entry_one_word_up = bool(
        entry_row is not None
        and is_one_word_limit(
            entry_row,
            previous_close,
            "up",
            entry_regime["limit_up_pct"],
        )
    )
    next_open_gap_pct = (
        (entry_price / previous_close - 1) * 100
        if entry_row is not None and entry_price > 0 and previous_close > 0
        else None
    )
    one_word_down_next_open = bool(
        entry_row is not None
        and is_one_word_limit(
            entry_row,
            previous_close,
            "down",
            entry_regime["limit_down_pct"],
        )
    )
    entry_feasible = bool(
        entry_row is not None
        and entry_price > 0
        and volume > 0
        and entry_regime["can_trade"]
        and not entry_one_word_up
    )
    base = {
        "available": True,
        "entry_label_mature": True,
        "entry_date": entry_date,
        "entry_price": round(entry_price, 3) if entry_price > 0 else None,
        "entry_feasible": entry_feasible,
        "entry_bar_available": entry_row is not None,
        "entry_one_word_limit_up": entry_one_word_up,
        "one_word_limit_down_next_open": one_word_down_next_open,
        "next_open_gap_pct": round(next_open_gap_pct, 2)
        if next_open_gap_pct is not None
        else None,
        "entry_regime": entry_regime,
        **common,
    }
    if not entry_feasible:
        reason = (
            "entry_suspended"
            if not entry_regime["can_trade"] or volume <= 0
            else "entry_unbuyable"
        )
        return {
            **base,
            "reason": reason,
            "execution_status": reason,
            "exit_label_mature": False,
            "return_label_mature": False,
            "exit_feasible": None,
            "net_return": None,
            "label_end_date": entry_date,
        }

    target_session_i = entry_session_i + policy.holding_sessions
    if target_session_i >= len(sessions):
        return {
            **base,
            "reason": "holding_incomplete",
            "execution_status": "holding_incomplete",
            "exit_label_mature": False,
            "return_label_mature": False,
            "exit_feasible": None,
            "net_return": None,
            "label_end_date": sessions[-1],
        }

    exit_session_i = target_session_i
    exit_i: int | None = None
    blocked_attempts = 0
    session_delay = 0
    exit_regime = None
    observed_end = sessions[target_session_i]
    while exit_session_i < len(sessions):
        exit_date = sessions[exit_session_i]
        session_delay = exit_session_i - target_session_i
        observed_end = exit_date
        exit_i = bar_index_by_date.get(exit_date)
        observed_exit_bars = int((dates <= exit_date).sum())
        exit_state = enrich_security_state_with_history(
            _state_for(security_states, exit_date),
            observed_exit_bars,
        )
        exit_regime = resolve_price_limit_regime(code, exit_date, exit_state)
        if require_pit_status and not exit_regime["point_in_time_verified"]:
            return {
                **base,
                "reason": "pit_security_state_missing",
                "execution_status": "pit_security_state_missing",
                "exit_label_mature": False,
                "return_label_mature": False,
                "exit_feasible": None,
                "net_return": None,
                "label_end_date": exit_date,
                "exit_regime": exit_regime,
            }
        exit_state_status = str((exit_state or {}).get("trading_status") or "")
        if exit_i is None and exit_state_status not in {"suspended", "delisted"}:
            return {
                **base,
                "reason": "market_bar_missing",
                "execution_status": "market_bar_missing",
                "exit_date": exit_date,
                "exit_bar_available": False,
                "exit_label_mature": False,
                "return_label_mature": False,
                "exit_feasible": None,
                "exit_delay_days": session_delay,
                "exit_delay_sessions": session_delay,
                "net_return": None,
                "label_end_date": exit_date,
                "exit_regime": exit_regime,
            }
        exit_row = d.iloc[exit_i] if exit_i is not None else None
        prior = d[d["_session_date"] < exit_date]
        previous = float(prior.iloc[-1]["close"]) if not prior.empty else 0
        exit_volume = (
            float(exit_row.get("volume", 0) or 0) if exit_row is not None else 0
        )
        blocked = (
            exit_row is None
            or not exit_regime["can_trade"]
            or exit_volume <= 0
            or previous <= 0
            or bool(
                exit_row is not None
                and is_one_word_limit(
                    exit_row,
                    previous,
                    "down",
                    exit_regime["limit_down_pct"],
                )
            )
        )
        if not blocked:
            break
        blocked_attempts += 1
        if blocked_attempts > policy.max_exit_delay_sessions:
            break
        exit_session_i += 1
    if (
        exit_session_i >= len(sessions)
        and blocked_attempts <= policy.max_exit_delay_sessions
    ):
        return {
            **base,
            "reason": "exit_delay_incomplete",
            "execution_status": "exit_delay_incomplete",
            "exit_label_mature": False,
            "return_label_mature": False,
            "exit_feasible": None,
            "exit_delay_days": session_delay,
            "exit_delay_sessions": session_delay,
            "net_return": None,
            "label_end_date": observed_end,
            "exit_regime": exit_regime,
        }
    exit_feasible = bool(
        exit_i is not None
        and exit_session_i < len(sessions)
        and blocked_attempts <= policy.max_exit_delay_sessions
    )
    if not exit_feasible:
        return {
            **base,
            "reason": "exit_unsellable",
            "execution_status": "exit_unsellable",
            "exit_label_mature": True,
            "return_label_mature": False,
            "exit_feasible": False,
            "exit_delay_days": session_delay,
            "exit_delay_sessions": session_delay,
            "net_return": None,
            "label_end_date": observed_end,
            "exit_regime": exit_regime,
        }

    assert exit_i is not None
    exit_row = d.iloc[exit_i]
    exit_price = float(exit_row["open"])
    net_return, cost_evidence = _net_return(entry_price, exit_price, policy)
    result = {
        **base,
        "reason": "ok",
        "execution_status": "filled_round_trip",
        "exit_label_mature": True,
        "return_label_mature": True,
        "exit_feasible": True,
        "exit_date": sessions[exit_session_i],
        "label_end_date": sessions[exit_session_i],
        "exit_price": round(exit_price, 3),
        "exit_price_field": "open",
        "exit_delay_days": session_delay,
        "exit_delay_sessions": session_delay,
        "gross_return": round((exit_price / entry_price - 1) * 100, 2),
        "net_return": round(net_return, 2),
        "cost_evidence": cost_evidence,
        "exit_regime": exit_regime,
    }
    # 开盘卖出后已不再持仓，不能用退出日盘中 high/low。
    segment = d[
        (d["_session_date"] >= entry_date)
        & (d["_session_date"] < sessions[exit_session_i])
    ]
    observed_high = max(float(segment["high"].max()), exit_price)
    observed_low = min(float(segment["low"].min()), exit_price)
    result["max_gain"] = round((observed_high / entry_price - 1) * 100, 2)
    result["max_drawdown"] = round((observed_low / entry_price - 1) * 100, 2)
    return result
