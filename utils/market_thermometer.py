"""版本化市场状态快照。

旧实现会在 GET 中临时请求外部指数并混入 legacy performance/backtest。
当前实现只允许 worker 基于同一不可变行情快照和 canonical decision outcomes
生成缓存；Web 端只能校验并读取该缓存。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from statistics import fmean
from typing import Any

from utils.artifact_integrity import artifact_is_valid, seal_artifact
from utils.decision_versions import cache_identity
from utils.execution_model import DEFAULT_EXECUTION_POLICY
from utils.runtime_paths import market_data_dir


logger = logging.getLogger(__name__)
DATA_DIR = market_data_dir()
CACHE_FILE = DATA_DIR / "market_thermometer_cache.json"
CACHE_SCHEMA_VERSION = 4
MIN_NUMERIC_RETURN_COVERAGE = 0.8
MIN_TRACKING_COMPLETION_RATIO = 0.8


def _strategy_fitness() -> dict:
    """只使用统一执行模型回填的 canonical outcome，绝不读旧战绩或回测。"""
    from utils.decision_ledger import outcome_summary

    buy = outcome_summary().get("buy") or {}
    samples = int(buy.get("numeric_return_count") or buy.get("count") or 0)
    terminal_samples = int(buy.get("terminal_outcome_count") or samples)
    coverage = buy.get("return_coverage_ratio")
    tracking_completion = buy.get("tracking_completion_ratio")
    evidence = {
        "samples": samples,
        "numeric_return_samples": samples,
        "terminal_samples": terminal_samples,
        "return_coverage_ratio": coverage,
        "tracking_completion_ratio": tracking_completion,
        "entry_failure_count": int(buy.get("entry_failure_count") or 0),
        "exit_failure_count": int(buy.get("exit_failure_count") or 0),
        "universe_removal_count": int(buy.get("universe_removal_count") or 0),
        "universe_removal_with_entry_unknown_count": int(
            buy.get("universe_removal_with_entry_unknown_count") or 0
        ),
        "missing_return_count": int(buy.get("missing_return_count") or 0),
        "win_rate_scope": "numeric_return_subset_only",
    }
    numeric_win_rate = buy.get("numeric_return_win_rate", buy.get("win_rate"))
    if samples < 20 or numeric_win_rate is None:
        return {
            "available": False,
            "reason": f"canonical_samples_insufficient:{samples}<20",
            "source": "decision_outcomes",
            **evidence,
        }
    if coverage is None or float(coverage) < MIN_NUMERIC_RETURN_COVERAGE:
        return {
            "available": False,
            "reason": "canonical_return_coverage_insufficient",
            "minimum_return_coverage_ratio": MIN_NUMERIC_RETURN_COVERAGE,
            "source": "decision_outcomes",
            **evidence,
        }
    if (
        tracking_completion is None
        or float(tracking_completion) < MIN_TRACKING_COMPLETION_RATIO
    ):
        return {
            "available": False,
            "reason": "canonical_tracking_completion_insufficient",
            "minimum_tracking_completion_ratio": MIN_TRACKING_COMPLETION_RATIO,
            "source": "decision_outcomes",
            **evidence,
        }
    win_rate = round(float(numeric_win_rate) * 100, 1)
    return {
        "available": True,
        "source": "decision_outcomes",
        "execution_policy_version": DEFAULT_EXECUTION_POLICY.version,
        **evidence,
        "win_rate_t5": win_rate,
        "avg_net_ret_5": buy.get(
            "numeric_return_avg_net_ret_5", buy.get("avg_net_ret_5")
        ),
        "status": (
            "failing" if win_rate < 40 else "weak" if win_rate < 50 else "healthy"
        ),
    }


def _market_heat(sectors: dict) -> dict:
    heat_map = sectors.get("heat_map") or {}
    scores = [
        float(item["score"])
        for item in heat_map.values()
        if isinstance(item, dict) and isinstance(item.get("score"), (int, float))
    ]
    changes = [
        float(item["delta3"])
        for item in heat_map.values()
        if isinstance(item, dict) and isinstance(item.get("delta3"), (int, float))
    ]
    if not scores:
        raise ValueError("sector_heat_map_empty")
    breadth_score = round(fmean(scores), 1)
    warming_ratio = (
        round(sum(value >= 8 for value in changes) / len(changes), 4)
        if changes
        else 0.0
    )
    cooling_ratio = (
        round(sum(value <= -8 for value in changes) / len(changes), 4)
        if changes
        else 0.0
    )
    delta3_mean = round(fmean(changes), 1) if changes else 0.0
    if delta3_mean >= 3:
        trend = "bull"
    elif delta3_mean <= -3:
        trend = "bear"
    else:
        trend = "sideways"
    if breadth_score >= 70 and warming_ratio >= cooling_ratio:
        level = "hot"
    elif breadth_score <= 35:
        level = "cold"
    else:
        level = "normal"
    return {
        "methodology": "cross_sectional_sector_heat_v1",
        "breadth_score": breadth_score,
        "warming_sector_ratio": warming_ratio,
        "cooling_sector_ratio": cooling_ratio,
        "delta3_mean": delta3_mean,
        "trend": trend,
        "level": level,
        "sector_count": len(scores),
        "as_of": sectors.get("trade_date"),
    }


def _conclusion(heat: dict, fitness: dict) -> tuple[str, str]:
    if fitness.get("available") and fitness.get("status") == "failing":
        coverage = fitness.get("return_coverage_ratio")
        coverage_text = (
            f"，数值收益覆盖率为 {float(coverage) * 100:.1f}%"
            if coverage is not None
            else ""
        )
        return (
            "caution",
            f"策略近期偏弱：统一成交口径下 "
            f"{fitness['terminal_samples']} 个已终局买入结果中，"
            f"{fitness['numeric_return_samples']} 个可评估数值收益{coverage_text}；"
            f"该子集 T+5 胜率为 {fitness['win_rate_t5']}%。当前应轻仓或观望。",
        )
    if heat["level"] == "hot":
        return (
            "caution",
            f"市场板块广度偏热（{heat['breadth_score']} 分），追高风险上升。",
        )
    if heat["level"] == "cold":
        return (
            "opportunity",
            f"市场板块广度处于低位（{heat['breadth_score']} 分），只观察已转强标的。",
        )
    if fitness.get("available") and fitness.get("status") == "weak":
        return (
            "neutral",
            f"市场广度正常，但策略 T+5 胜率仅 {fitness['win_rate_t5']}%，需控制仓位。",
        )
    if not fitness.get("available"):
        if fitness.get("terminal_samples"):
            coverage = fitness.get("return_coverage_ratio")
            coverage_text = (
                f"，覆盖率 {float(coverage) * 100:.1f}%" if coverage is not None else ""
            )
            failures = (
                int(fitness.get("entry_failure_count") or 0)
                + int(fitness.get("exit_failure_count") or 0)
                + int(fitness.get("universe_removal_count") or 0)
            )
            tracking = fitness.get("tracking_completion_ratio")
            tracking_text = (
                f"，跟踪完成率 {float(tracking) * 100:.1f}%"
                if tracking is not None
                else ""
            )
            return (
                "neutral",
                f"canonical 实盘已有 {fitness['terminal_samples']} 个终局结果，"
                f"其中 {fitness['numeric_return_samples']} 个具备数值收益"
                f"{coverage_text}{tracking_text}，另有 {failures} 个成交或移除失败；"
                "证据覆盖不足，暂不输出策略健康结论。",
            )
        return (
            "neutral",
            "市场广度正常；canonical 实盘样本尚不足，暂不把历史胜率当作放行证据。",
        )
    return "normal", "市场广度与策略实盘状态正常，可按已发布策略执行。"


def build_thermometer(csv_manager, sectors: dict) -> dict:
    """纯计算：把已生成的板块快照与 canonical outcome 合成为展示快照。"""
    if not sectors.get("available"):
        return {"available": False, "reason": "sector_snapshot_not_ready"}
    try:
        heat = _market_heat(sectors)
        fitness = _strategy_fitness()
        signal, conclusion = _conclusion(heat, fitness)
        identity = cache_identity(
            csv_manager,
            "market_thermometer",
            CACHE_SCHEMA_VERSION,
        )
        return {
            "available": True,
            "cache_schema_version": CACHE_SCHEMA_VERSION,
            **identity,
            "trade_date": sectors.get("trade_date"),
            "sector_cache_key": sectors.get("cache_key"),
            "computed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "heat": heat,
            "fitness": fitness,
            "signal": signal,
            "conclusion": conclusion,
            "source_refs": [
                "immutable_market_snapshot",
                "sector_rotation_cache_v3",
                "canonical_decision_outcomes",
                DEFAULT_EXECUTION_POLICY.version,
            ],
        }
    except Exception as exc:
        logger.error("市场状态计算失败: %s", exc, exc_info=True)
        return {"available": False, "reason": "thermometer_build_failed"}


def refresh_thermometer(csv_manager, sectors: dict) -> dict:
    """仅供 worker 调用：原子写入当前 snapshot 的市场状态产物。"""
    result = build_thermometer(csv_manager, sectors)
    if not result.get("available"):
        return result
    result = seal_artifact(result)
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = CACHE_FILE.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(CACHE_FILE)
    return result


def read_thermometer(csv_manager) -> dict:
    """只读当前 snapshot 的缓存；缺失/过期时 fail closed。"""
    if not CACHE_FILE.is_file():
        return {"available": False, "reason": "thermometer_snapshot_not_ready"}
    try:
        value: Any = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        value = {}
    identity = cache_identity(csv_manager, "market_thermometer", CACHE_SCHEMA_VERSION)
    valid = bool(
        isinstance(value, dict)
        and value.get("available")
        and artifact_is_valid(value)
        and value.get("cache_schema_version") == CACHE_SCHEMA_VERSION
        and identity.get("cache_key")
        and value.get("cache_key") == identity.get("cache_key")
    )
    if valid:
        return value
    return {"available": False, "reason": "thermometer_snapshot_not_ready"}


def get_thermometer(csv_manager=None) -> dict:
    """兼容名称；语义已变为严格只读。"""
    if csv_manager is None:
        from utils.csv_manager import CSVManager

        csv_manager = CSVManager("data", writable=False)
    return read_thermometer(csv_manager)
