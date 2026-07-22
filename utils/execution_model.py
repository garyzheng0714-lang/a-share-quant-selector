"""生产、回放、训练和模拟盘共用的 A 股日频成交政策。

日线无法还原集合竞价排队和部分成交，因此结果始终标记
``approximate=True``。所有输出都绑定一个不可变的政策版本。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from decimal import Decimal, ROUND_HALF_UP
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
    version: str = "a-share-eod-open-open-v3"
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


DEFAULT_EXECUTION_POLICY = ExecutionPolicy()


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
    require_pit_status: bool = False,
    policy: ExecutionPolicy = DEFAULT_EXECUTION_POLICY,
) -> dict:
    """信号日收盘决策，次日开盘入场，完成持有期后的开盘退出。"""
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
    d = daily.sort_values("date").reset_index(drop=True).copy()
    dates = d["date"].astype(str).str[:10]
    hits = d.index[dates == run_date].tolist()
    if not hits:
        return {"available": False, "reason": "run_date_missing", **common}
    signal_i = hits[-1]
    entry_i = signal_i + 1
    if entry_i >= len(d):
        return {
            "available": False,
            "reason": "entry_not_available",
            "entry_label_mature": False,
            **common,
        }

    entry_date = str(dates.iloc[entry_i])
    entry_state = enrich_security_state_with_history(
        _state_for(security_states, entry_date),
        entry_i + 1,
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

    previous_close = float(d.iloc[signal_i]["close"])
    entry_row = d.iloc[entry_i]
    entry_price = float(entry_row.get("open", 0) or 0)
    volume = float(entry_row.get("volume", 0) or 0)
    entry_one_word_up = is_one_word_limit(
        entry_row,
        previous_close,
        "up",
        entry_regime["limit_up_pct"],
    )
    next_open_gap_pct = (
        (entry_price / previous_close - 1) * 100 if previous_close > 0 else None
    )
    one_word_down_next_open = is_one_word_limit(
        entry_row,
        previous_close,
        "down",
        entry_regime["limit_down_pct"],
    )
    entry_feasible = bool(
        entry_price > 0
        and volume > 0
        and entry_regime["can_trade"]
        and not entry_one_word_up
    )
    base = {
        "available": True,
        "entry_label_mature": True,
        "entry_date": entry_date,
        "entry_price": round(entry_price, 3),
        "entry_feasible": entry_feasible,
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

    target_i = entry_i + policy.holding_sessions
    if target_i >= len(d):
        return {
            **base,
            "reason": "holding_incomplete",
            "execution_status": "holding_incomplete",
            "exit_label_mature": False,
            "return_label_mature": False,
            "exit_feasible": None,
            "net_return": None,
            "label_end_date": str(dates.iloc[-1]),
        }

    exit_i = target_i
    delayed = 0
    exit_regime = None
    while exit_i < len(d):
        exit_date = str(dates.iloc[exit_i])
        exit_state = enrich_security_state_with_history(
            _state_for(security_states, exit_date),
            exit_i + 1,
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
        previous = float(d.iloc[exit_i - 1]["close"])
        exit_row = d.iloc[exit_i]
        exit_volume = float(exit_row.get("volume", 0) or 0)
        blocked = (
            not exit_regime["can_trade"]
            or exit_volume <= 0
            or is_one_word_limit(
                exit_row,
                previous,
                "down",
                exit_regime["limit_down_pct"],
            )
        )
        if not blocked:
            break
        exit_i += 1
        delayed += 1
        if delayed > policy.max_exit_delay_sessions:
            break
    exit_feasible = exit_i < len(d) and delayed <= policy.max_exit_delay_sessions
    observed_end = str(dates.iloc[min(exit_i, len(d) - 1)])
    if not exit_feasible:
        return {
            **base,
            "reason": "exit_unsellable",
            "execution_status": "exit_unsellable",
            "exit_label_mature": True,
            "return_label_mature": False,
            "exit_feasible": False,
            "exit_delay_days": delayed,
            "net_return": None,
            "label_end_date": observed_end,
            "exit_regime": exit_regime,
        }

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
        "exit_date": str(dates.iloc[exit_i]),
        "label_end_date": str(dates.iloc[exit_i]),
        "exit_price": round(exit_price, 3),
        "exit_price_field": "open",
        "exit_delay_days": delayed,
        "gross_return": round((exit_price / entry_price - 1) * 100, 2),
        "net_return": round(net_return, 2),
        "cost_evidence": cost_evidence,
        "exit_regime": exit_regime,
    }
    segment = d.iloc[entry_i : exit_i + 1]
    result["max_gain"] = round(
        (float(segment["high"].max()) / entry_price - 1) * 100, 2
    )
    result["max_drawdown"] = round(
        (float(segment["low"].min()) / entry_price - 1) * 100, 2
    )
    return result
