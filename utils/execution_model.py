"""主板短线交易的保守成交模型。

日线无法精确还原集合竞价和排队，因此本模块只给出可审计的
保守近似，并显式返回 approximate=True。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_HALF_UP

import pandas as pd


@dataclass(frozen=True)
class CostModel:
    commission_rate: float = 0.0003
    stamp_duty_sell_rate: float = 0.0005
    slippage_bps_each_side: float = 5.0


def limit_price(previous_close: float, direction: str, limit_pct: float = 0.10) -> float:
    multiplier = 1 + limit_pct if direction == "up" else 1 - limit_pct
    return float((Decimal(str(previous_close)) * Decimal(str(multiplier))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    ))


def is_one_word_limit(row: pd.Series, previous_close: float, direction: str,
                      limit_pct: float = 0.10) -> bool:
    price = limit_price(previous_close, direction, limit_pct)
    tolerance = 0.011
    values = [float(row.get(k, 0) or 0) for k in ("open", "high", "low", "close")]
    if direction == "up":
        return min(values) >= price - tolerance
    return max(values) <= price + tolerance


def _net_return(entry: float, exit_price: float, costs: CostModel) -> float:
    slip = costs.slippage_bps_each_side / 10_000
    paid = entry * (1 + slip + costs.commission_rate)
    received = exit_price * (1 - slip - costs.commission_rate - costs.stamp_duty_sell_rate)
    return (received / paid - 1) * 100


def evaluate_trade(daily: pd.DataFrame, run_date: str, hold_days: int = 5,
                   costs: CostModel | None = None, max_exit_delay: int = 5) -> dict:
    """信号日收盘决策，次日开盘买入，持有 hold_days 个交易日。"""
    costs = costs or CostModel()
    if daily is None or daily.empty:
        return {"available": False, "reason": "no_daily_data", "approximate": True}
    d = daily.sort_values("date").reset_index(drop=True).copy()
    dates = d["date"].astype(str).str[:10]
    hits = d.index[dates == run_date].tolist()
    if not hits:
        return {"available": False, "reason": "run_date_missing", "approximate": True}
    signal_i = hits[-1]
    entry_i = signal_i + 1
    if entry_i >= len(d):
        return {"available": False, "reason": "entry_not_available", "approximate": True}

    previous_close = float(d.iloc[signal_i]["close"])
    entry_row = d.iloc[entry_i]
    entry_price = float(entry_row.get("open", 0) or 0)
    entry_one_word_up = is_one_word_limit(entry_row, previous_close, "up")
    next_open_gap_pct = (entry_price / previous_close - 1) * 100 if previous_close > 0 else None
    one_word_down_next_open = is_one_word_limit(entry_row, previous_close, "down")
    entry_feasible = bool(entry_price > 0 and not entry_one_word_up)
    base = {
        "available": True,
        "approximate": True,
        "entry_date": dates.iloc[entry_i],
        "entry_price": round(entry_price, 3),
        "entry_feasible": entry_feasible,
        "entry_one_word_limit_up": entry_one_word_up,
        "one_word_limit_down_next_open": one_word_down_next_open,
        "next_open_gap_pct": round(next_open_gap_pct, 2) if next_open_gap_pct is not None else None,
    }
    if not entry_feasible:
        return {**base, "reason": "entry_unbuyable", "exit_feasible": None, "net_return": None}

    target_i = signal_i + hold_days
    if target_i >= len(d):
        return {**base, "reason": "holding_incomplete", "exit_feasible": None, "net_return": None}

    exit_i = target_i
    delayed = 0
    while exit_i < len(d):
        prev_close = float(d.iloc[exit_i - 1]["close"])
        if not is_one_word_limit(d.iloc[exit_i], prev_close, "down"):
            break
        exit_i += 1
        delayed += 1
        if delayed > max_exit_delay:
            break
    exit_feasible = exit_i < len(d) and delayed <= max_exit_delay
    if not exit_feasible:
        return {
            **base, "reason": "exit_unsellable", "exit_feasible": False,
            "exit_delay_days": delayed, "net_return": None,
        }
    exit_price = float(d.iloc[exit_i]["close"])
    result = {
        **base,
        "reason": "ok",
        "exit_feasible": True,
        "exit_date": dates.iloc[exit_i],
        "exit_price": round(exit_price, 3),
        "exit_delay_days": delayed,
        "gross_return": round((exit_price / entry_price - 1) * 100, 2),
        "net_return": round(_net_return(entry_price, exit_price, costs), 2),
        "cost_model": asdict(costs),
    }
    segment = d.iloc[entry_i: exit_i + 1]
    result["max_gain"] = round((float(segment["high"].max()) / entry_price - 1) * 100, 2)
    result["max_drawdown"] = round((float(segment["low"].min()) / entry_price - 1) * 100, 2)
    return result
