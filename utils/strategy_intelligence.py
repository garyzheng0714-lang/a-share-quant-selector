"""全策略每日影子评分。

本模块只读取不可变因子证据账本、当日因子缓存和调用方已绑定的
不可变行情快照。它不读取旧 ``factor_track_record``，不写入文件或
数据库，也不调用 LLM。
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any

from strategy.factors import FACTOR_REGISTRY
from utils.execution_model import DEFAULT_EXECUTION_POLICY
from utils.factor_evidence import (
    factor_registry_version,
    get_latest_factor_signal_run,
    list_latest_factor_outcomes,
)
from utils.market_snapshot import load_market_snapshot


MODEL_VERSION = "strategy-shadow-score-v2"
HOLD_WINDOWS = (1, 5, 10, 20)
PRIMARY_WINDOW = 5
RECENT_SIGNAL_DAY_LIMIT = 60
RECENT_CALENDAR_DAY_LIMIT = 540
MIN_MATURE_SIGNAL_DAYS = 20
MIN_MATURE_RECORDS = 60
BAYES_PRIOR_ALPHA = 1.0
BAYES_PRIOR_BETA = 1.0
WILSON_Z = 1.959963984540054

METHOD = (
    "信号日 T 为因子命中收盘日，按 a-share-eod-open-open-v5 在 T+1 "
    "开盘近似买入，持有 n 个交易日后的开盘卖出，净收益已扣费用和"
    "双边滑点。每个 T+n 窗口只纳入 return_label_mature=true 的记录；"
    "先对同一信号日的全部可成交命中等权，再对信号日等权。胜率以当日"
    "等权组合净收益大于 0 计，只使用最近 60 个原始信号日，使用 "
    "Beta(1,1) 中性先验收缩，并报告 "
    "Wilson 95% 下界。T+5 是主评分窗口；至少 20 个成熟信号日且 "
    "60 条成熟记录才参与排名。若存在已确定买不到或卖不掉、"
    "但无可实现净收益的终局执行失败，或已超过最晚评估日仍"
    "缺证据，该策略不参与排名，避免尾部风险被静默剔除。排名完全由"
    "固定统计公式产生，AI 无权修改。"
)

SCORE_FORMULA = (
    "shadow_score = 35%×贝叶斯收缩胜率 + 25%×Wilson 95%下界 "
    "+ 25%×收益质量 + 15%×尾部风险质量。收益质量将日均净收益 "
    "[-5%, +5%] 线性映射到 [0, 100]；尾部风险质量为 CVaR10 与平均"
    "最大回撤各自按 [-10%, +10%] 线性映射后的等权平均。"
)


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _round(value: float | None, digits: int = 2) -> float | None:
    return round(value, digits) if value is not None else None


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return min(max(value, low), high)


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _wilson_lower_bound(wins: int, total: int) -> float | None:
    if total <= 0:
        return None
    observed = wins / total
    z2 = WILSON_Z**2
    denominator = 1 + z2 / total
    centre = observed + z2 / (2 * total)
    margin = WILSON_Z * math.sqrt(
        (observed * (1 - observed) + z2 / (4 * total)) / total
    )
    return max(0.0, (centre - margin) / denominator)


def _empty_window() -> dict:
    return {
        "sample_count": 0,
        "signal_days": 0,
        "observed_win_rate_pct": None,
        "bayesian_win_rate_pct": None,
        "wilson_lower_bound_pct": None,
        "daily_avg_net_return_pct": None,
        "median_net_return_pct": None,
        "worst_net_return_pct": None,
        "cvar10_net_return_pct": None,
        "avg_max_drawdown_pct": None,
        "terminal_execution_failure_count": 0,
        "pending_signal_day_count": 0,
        "overdue_pending_signal_day_count": 0,
        "pit_verified_sample_count": 0,
        "forward_approximation_sample_count": 0,
        "oldest_signal_day": None,
        "newest_signal_day": None,
        "lookback_signal_day_limit": RECENT_SIGNAL_DAY_LIMIT,
        "evidence_complete": True,
    }


def _summarize_window(
    records: list[dict],
    *,
    terminal_execution_failure_dates: list[str] | None = None,
    pending_dates: list[str] | None = None,
    overdue_pending_dates: list[str] | None = None,
) -> dict:
    """先日内等权，再跨日等权，避免宽策略靠单日大量命中投票。"""
    by_day: dict[str, list[dict]] = {}
    for record in records:
        by_day.setdefault(record["pick_date"], []).append(record)
    failure_dates = list(terminal_execution_failure_dates or [])
    pending_signal_dates = list(pending_dates or [])
    pending_set = set(pending_signal_dates)
    overdue_pending_set = set(overdue_pending_dates or []) & pending_set
    # 用最近 60 个“原始信号日”定义窗口，不允许缺证据的
    # 坏样本被跳过后，再用更早的成熟样本补足名额。
    all_signal_days = set(by_day) | set(failure_dates) | pending_set
    selected_days = sorted(all_signal_days)[-RECENT_SIGNAL_DAY_LIMIT:]
    selected_failures = sum(day in selected_days for day in failure_dates)
    selected_pending_days = sum(day in selected_days for day in pending_set)
    selected_overdue_days = sum(day in selected_days for day in overdue_pending_set)
    blocked_days = set(failure_dates) | pending_set
    if not records:
        empty = _empty_window()
        empty["terminal_execution_failure_count"] = selected_failures
        empty["pending_signal_day_count"] = selected_pending_days
        empty["overdue_pending_signal_day_count"] = selected_overdue_days
        empty["oldest_signal_day"] = selected_days[0] if selected_days else None
        empty["newest_signal_day"] = selected_days[-1] if selected_days else None
        empty["evidence_complete"] = (
            selected_failures == 0 and selected_overdue_days == 0
        )
        return empty

    daily_returns: list[float] = []
    daily_drawdowns: list[float] = []
    for pick_date in selected_days:
        if pick_date not in by_day or pick_date in blocked_days:
            continue
        bucket = by_day[pick_date]
        returns = [record["net_return"] for record in bucket]
        daily_return = _mean(returns)
        if daily_return is None:
            continue
        daily_returns.append(daily_return)
        drawdowns = [
            record["max_drawdown"]
            for record in bucket
            if record["max_drawdown"] is not None
        ]
        daily_drawdown = _mean(drawdowns)
        if daily_drawdown is not None:
            daily_drawdowns.append(daily_drawdown)

    if not daily_returns:
        empty = _empty_window()
        empty["terminal_execution_failure_count"] = selected_failures
        empty["pending_signal_day_count"] = selected_pending_days
        empty["overdue_pending_signal_day_count"] = selected_overdue_days
        empty["oldest_signal_day"] = selected_days[0] if selected_days else None
        empty["newest_signal_day"] = selected_days[-1] if selected_days else None
        empty["evidence_complete"] = (
            selected_failures == 0 and selected_overdue_days == 0
        )
        return empty

    wins = sum(value > 0 for value in daily_returns)
    signal_days = len(daily_returns)
    posterior_rate = (wins + BAYES_PRIOR_ALPHA) / (
        signal_days + BAYES_PRIOR_ALPHA + BAYES_PRIOR_BETA
    )
    wilson = _wilson_lower_bound(wins, signal_days)
    tail_count = max(1, math.ceil(signal_days * 0.10))
    cvar10 = _mean(sorted(daily_returns)[:tail_count])

    return {
        "sample_count": sum(
            len(by_day[day])
            for day in selected_days
            if day in by_day and day not in blocked_days
        ),
        "signal_days": signal_days,
        "observed_win_rate_pct": round(wins / signal_days * 100, 2),
        "bayesian_win_rate_pct": round(posterior_rate * 100, 2),
        "wilson_lower_bound_pct": _round(wilson * 100 if wilson is not None else None),
        "daily_avg_net_return_pct": _round(_mean(daily_returns)),
        "median_net_return_pct": round(median(daily_returns), 2),
        "worst_net_return_pct": round(min(daily_returns), 2),
        "cvar10_net_return_pct": _round(cvar10),
        "avg_max_drawdown_pct": _round(_mean(daily_drawdowns)),
        "terminal_execution_failure_count": selected_failures,
        "pending_signal_day_count": selected_pending_days,
        "overdue_pending_signal_day_count": selected_overdue_days,
        "pit_verified_sample_count": sum(
            record.get("evidence_tier") == "pit_verified"
            for day in selected_days
            for record in by_day.get(day, [])
            if day not in blocked_days
        ),
        "forward_approximation_sample_count": sum(
            record.get("evidence_tier") == "forward_approximation"
            for day in selected_days
            for record in by_day.get(day, [])
            if day not in blocked_days
        ),
        "oldest_signal_day": selected_days[0] if selected_days else None,
        "newest_signal_day": selected_days[-1] if selected_days else None,
        "lookback_signal_day_limit": RECENT_SIGNAL_DAY_LIMIT,
        "evidence_complete": selected_failures == 0 and selected_overdue_days == 0,
    }


def _quality(value: float | None, *, span: float) -> float:
    if value is None:
        return 0.0
    return _clamp(50.0 + 50.0 * value / span)


def _score(metrics: dict) -> tuple[float | None, dict]:
    if metrics["signal_days"] <= 0 or not metrics["evidence_complete"]:
        return None, {
            "bayesian_win": None,
            "wilson_confidence": None,
            "return_quality": None,
            "tail_risk_quality": None,
        }

    bayesian = float(metrics["bayesian_win_rate_pct"])
    wilson = float(metrics["wilson_lower_bound_pct"])
    return_quality = _quality(metrics["daily_avg_net_return_pct"], span=5.0)
    cvar_quality = _quality(metrics["cvar10_net_return_pct"], span=10.0)
    drawdown_quality = _quality(metrics["avg_max_drawdown_pct"], span=10.0)
    tail_risk_quality = (cvar_quality + drawdown_quality) / 2
    score = (
        0.35 * bayesian
        + 0.25 * wilson
        + 0.25 * return_quality
        + 0.15 * tail_risk_quality
    )
    return round(score, 2), {
        "bayesian_win": round(bayesian, 2),
        "wilson_confidence": round(wilson, 2),
        "return_quality": round(return_quality, 2),
        "tail_risk_quality": round(tail_risk_quality, 2),
    }


def _snapshot_trade_date(
    csv_manager, snapshot_id: str
) -> tuple[str | None, str | None]:
    loaded = load_market_snapshot(
        getattr(csv_manager, "base_data_dir", "data"),
        snapshot_id,
        verify_files=False,
    )
    if not loaded.get("available"):
        return None, str(loaded.get("reason") or "snapshot_unavailable")
    trade_date = str((loaded.get("manifest") or {}).get("trade_date") or "")
    try:
        parsed = datetime.strptime(trade_date, "%Y-%m-%d").date()
    except ValueError:
        return None, "snapshot_trade_date_missing"
    if parsed.isoformat() != trade_date:
        return None, "snapshot_trade_date_missing"
    return trade_date, None


def _unavailable(
    reason: str,
    trade_date: str,
    snapshot_id: str | None,
    *,
    snapshot_trade_date: str | None = None,
) -> dict:
    return {
        "available": False,
        "reason": reason,
        "status": "unavailable",
        "trade_date": trade_date or None,
        "snapshot_trade_date": snapshot_trade_date,
        "snapshot_id": snapshot_id,
        "feedback_mode": "shadow_only",
        "model_version": MODEL_VERSION,
        "primary_horizon": PRIMARY_WINDOW,
        "primary_window": f"T+{PRIMARY_WINDOW}",
        "eligibility": {
            "required_signal_days": MIN_MATURE_SIGNAL_DAYS,
            "required_sample_count": MIN_MATURE_RECORDS,
        },
        "leader": None,
        "strategies": [],
        "methodology": METHOD,
        "method": METHOD,
    }


def build_strategy_intelligence(csv_manager, trade_date: str) -> dict:
    """使用已绑定快照的 ``CSVManager`` 生成全策略影子报告。

    返回值只含 JSON 可序列化类型；本函数没有任何写入副作用。
    """
    date = str(trade_date or "").strip()
    snapshot_id = str(getattr(csv_manager, "snapshot_id", "") or "") or None
    try:
        parsed_date = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        return _unavailable("invalid_trade_date", date, snapshot_id)
    if parsed_date.isoformat() != date:
        return _unavailable("invalid_trade_date", date, snapshot_id)
    if snapshot_id is None:
        return _unavailable("pinned_snapshot_required", date, None)
    snapshot_trade_date, _snapshot_reason = _snapshot_trade_date(
        csv_manager, snapshot_id
    )
    if snapshot_trade_date is None:
        return _unavailable(
            "pinned_snapshot_unavailable",
            date,
            snapshot_id,
            snapshot_trade_date=None,
        )
    if date != snapshot_trade_date:
        return _unavailable(
            "snapshot_trade_date_mismatch",
            date,
            snapshot_id,
            snapshot_trade_date=snapshot_trade_date,
        )

    current_factor_run = get_latest_factor_signal_run(date)
    today_counts = {
        str(row.get("factor_key") or ""): int(row.get("hit_count") or 0)
        for row in ((current_factor_run or {}).get("stats") or [])
    }
    today_complete = bool(
        current_factor_run
        and current_factor_run.get("snapshot_id") == snapshot_id
        and current_factor_run.get("registry_version") == factor_registry_version()
        and int(current_factor_run.get("factor_count") or 0) == len(FACTOR_REGISTRY)
        and set(today_counts) == set(FACTOR_REGISTRY)
    )
    today_reason = None if today_complete else "factor_signal_run_not_ready"
    registry_version = str((current_factor_run or {}).get("registry_version") or "")
    from_trade_date = (
        parsed_date - timedelta(days=RECENT_CALENDAR_DAY_LIMIT)
    ).isoformat()
    all_outcomes = (
        list_latest_factor_outcomes(
            as_of=date,
            from_trade_date=from_trade_date,
            registry_version=registry_version,
            execution_policy_version=DEFAULT_EXECUTION_POLICY.version,
            limit=1_000_000,
        )
        if today_complete and registry_version
        else []
    )
    outcomes_by_factor: dict[str, list[dict]] = {}
    for outcome in all_outcomes:
        outcomes_by_factor.setdefault(str(outcome.get("factor_key") or ""), []).append(
            outcome
        )
    strategies: list[dict] = []

    for strategy, meta in FACTOR_REGISTRY.items():
        window_records: dict[int, list[dict]] = {hold: [] for hold in HOLD_WINDOWS}
        window_execution_failures: dict[int, list[str]] = {
            hold: [] for hold in HOLD_WINDOWS
        }
        window_pending_dates: dict[int, list[str]] = {hold: [] for hold in HOLD_WINDOWS}
        window_overdue_pending_dates: dict[int, list[str]] = {
            hold: [] for hold in HOLD_WINDOWS
        }
        for outcome in outcomes_by_factor.get(strategy, []):
            if outcome.get("signal_provenance") != "forward_live":
                continue
            try:
                raw_hold = outcome.get("horizon_sessions")
                if raw_hold is None:
                    continue
                hold = int(raw_hold)
            except (TypeError, ValueError):
                continue
            if hold not in HOLD_WINDOWS:
                continue
            net_return = _finite(outcome.get("net_return"))
            if outcome.get("status") == "complete" and net_return is not None:
                window_records[hold].append(
                    {
                        "pick_date": str(outcome.get("trade_date") or "")[:10],
                        "net_return": net_return,
                        "max_drawdown": _finite(outcome.get("max_drawdown")),
                        "evidence_tier": outcome.get("evidence_tier"),
                    }
                )
            elif outcome.get("status") == "invalid":
                window_execution_failures[hold].append(
                    str(outcome.get("trade_date") or "")[:10]
                )
            elif outcome.get("status") == "pending":
                pending_date = str(outcome.get("trade_date") or "")[:10]
                window_pending_dates[hold].append(pending_date)
                payload = outcome.get("payload") or {}
                execution = payload.get("execution") or {}
                if (
                    payload.get("evidence_overdue") is True
                    or execution.get("evidence_overdue") is True
                ):
                    window_overdue_pending_dates[hold].append(pending_date)

        windows = {
            f"T+{hold}": _summarize_window(
                window_records[hold],
                terminal_execution_failure_dates=window_execution_failures[hold],
                pending_dates=window_pending_dates[hold],
                overdue_pending_dates=window_overdue_pending_dates[hold],
            )
            for hold in HOLD_WINDOWS
        }
        primary = windows[f"T+{PRIMARY_WINDOW}"]
        eligible = (
            primary["signal_days"] >= MIN_MATURE_SIGNAL_DAYS
            and primary["sample_count"] >= MIN_MATURE_RECORDS
            and primary["evidence_complete"]
        )
        shadow_score, score_components = _score(primary)
        strategies.append(
            {
                "strategy": strategy,
                "strategy_name": str(meta.get("name") or strategy),
                "name": str(meta.get("name") or strategy),
                "group": str(meta.get("group") or ""),
                "today_hit_count": today_counts.get(strategy),
                "status": "eligible" if eligible else "warming_up",
                "eligible": eligible,
                "eligibility": {
                    "required_signal_days": MIN_MATURE_SIGNAL_DAYS,
                    "required_sample_count": MIN_MATURE_RECORDS,
                    "missing_signal_days": max(
                        0, MIN_MATURE_SIGNAL_DAYS - primary["signal_days"]
                    ),
                    "missing_sample_count": max(
                        0, MIN_MATURE_RECORDS - primary["sample_count"]
                    ),
                    "blocking_execution_failures": primary[
                        "terminal_execution_failure_count"
                    ],
                    "blocking_overdue_evidence_days": primary[
                        "overdue_pending_signal_day_count"
                    ],
                },
                "primary_window": f"T+{PRIMARY_WINDOW}",
                "shadow_score": shadow_score,
                "score_components": score_components,
                "shadow_weight": 0.0,
                "rank": None,
                "windows": windows,
                "evidence_quality": (
                    "pit_verified"
                    if primary["sample_count"] > 0
                    and primary["forward_approximation_sample_count"] == 0
                    else "forward_approximation"
                ),
            }
        )

    eligible_rows = [row for row in strategies if row["eligible"]]
    eligible_rows.sort(
        key=lambda row: (
            -(row["shadow_score"] or 0.0),
            -(row["windows"]["T+5"]["wilson_lower_bound_pct"] or 0.0),
            -(row["windows"]["T+5"]["daily_avg_net_return_pct"] or 0.0),
            row["strategy"],
        )
    )
    score_total = sum(
        max(float(row["shadow_score"] or 0.0), 0.0) for row in eligible_rows
    )
    for rank, row in enumerate(eligible_rows, start=1):
        row["rank"] = rank
        if score_total > 0:
            row["shadow_weight"] = round(
                max(float(row["shadow_score"] or 0.0), 0.0) / score_total,
                6,
            )
        else:
            row["shadow_weight"] = round(1 / len(eligible_rows), 6)

    strategies.sort(
        key=lambda row: (
            0 if row["eligible"] else 1,
            row["rank"] if row["rank"] is not None else 10_000,
            -(row["shadow_score"] or 0.0),
            row["strategy"],
        )
    )
    leader = None
    if eligible_rows:
        top = eligible_rows[0]
        leader = {
            "strategy": top["strategy"],
            "strategy_name": top["strategy_name"],
            "name": top["name"],
            "shadow_score": top["shadow_score"],
            "shadow_weight": top["shadow_weight"],
            "primary_window": top["primary_window"],
        }

    known_hit_count = sum(today_counts.values())
    if not today_complete:
        status = "factor_snapshot_not_ready"
    elif leader is None:
        status = "warming_up"
    else:
        status = "ready"

    return {
        "available": True,
        "reason": None,
        "status": status,
        "trade_date": date,
        "snapshot_trade_date": snapshot_trade_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "snapshot_id": snapshot_id,
        "feedback_mode": "shadow_only",
        "model_version": MODEL_VERSION,
        "execution_policy_version": DEFAULT_EXECUTION_POLICY.version,
        "source_refs": [
            "factor-evidence-v1",
            "factor-outcome-observation-v1",
            "a-share-eod-open-open-v5",
        ],
        "factor_registry_version": registry_version or None,
        "current_factor_registry_version": factor_registry_version(),
        "evidence_quality": "shadow_forward_approximation",
        "factor_run_ids": sorted(
            {
                str(row.get("run_id") or "")
                for row in all_outcomes
                if row.get("signal_provenance") == "forward_live" and row.get("run_id")
            }
        ),
        "lookback_signal_day_limit": RECENT_SIGNAL_DAY_LIMIT,
        "lookback_calendar_days": RECENT_CALENDAR_DAY_LIMIT,
        "primary_horizon": PRIMARY_WINDOW,
        "primary_window": f"T+{PRIMARY_WINDOW}",
        "eligibility": {
            "required_signal_days": MIN_MATURE_SIGNAL_DAYS,
            "required_sample_count": MIN_MATURE_RECORDS,
        },
        "today_hit_count": known_hit_count if today_complete else None,
        "today_known_hit_count": known_hit_count,
        "today_hits_complete": today_complete,
        "today_hits_reason": None if today_complete else today_reason,
        "strategy_count": len(strategies),
        "eligible_strategy_count": len(eligible_rows),
        "leader": leader,
        "strategies": strategies,
        "score_formula": SCORE_FORMULA,
        "methodology": METHOD,
        "method": METHOD,
    }
