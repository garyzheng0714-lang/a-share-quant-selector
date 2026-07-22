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
from pathlib import Path
from statistics import fmean
from typing import Any

from utils.artifact_integrity import artifact_is_valid, seal_artifact
from utils.decision_versions import cache_identity
from utils.execution_model import DEFAULT_EXECUTION_POLICY


logger = logging.getLogger(__name__)
DATA_DIR = Path(__file__).parent.parent / "data"
CACHE_FILE = DATA_DIR / "market_thermometer_cache.json"
CACHE_SCHEMA_VERSION = 3


def _strategy_fitness() -> dict:
    """只使用统一执行模型回填的 canonical outcome，绝不读旧战绩或回测。"""
    from utils.decision_ledger import outcome_summary

    buy = outcome_summary().get("buy") or {}
    samples = int(buy.get("count") or 0)
    if samples < 20 or buy.get("win_rate") is None:
        return {
            "available": False,
            "reason": f"canonical_samples_insufficient:{samples}<20",
            "samples": samples,
            "source": "decision_outcomes",
        }
    win_rate = round(float(buy["win_rate"]) * 100, 1)
    return {
        "available": True,
        "source": "decision_outcomes",
        "execution_policy_version": DEFAULT_EXECUTION_POLICY.version,
        "samples": samples,
        "win_rate_t5": win_rate,
        "avg_net_ret_5": buy.get("avg_net_ret_5"),
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
        return (
            "caution",
            f"策略近期失效：统一成交口径下最近 {fitness['samples']} 个买入样本，"
            f"T+5 胜率为 {fitness['win_rate_t5']}%。当前应轻仓或观望。",
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
