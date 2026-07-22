"""分层决策功能开关；默认保守开启，环境变量可即时回退。"""

from __future__ import annotations

import os
from pathlib import Path

import yaml


DEFAULTS = {
    "enabled": True,
    "strict_unvalidated_gate": True,
    "preopen_event_check": True,
    # 周线四均线是目标硬门槛，但在历史口径重建通过前只记录影子结果。
    "weekly_gate_mode": "shadow",
}


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def get_decision_config() -> dict:
    result = dict(DEFAULTS)
    path = Path("config/config.yaml")
    if path.exists():
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            result.update(payload.get("decision") or {})
        except Exception:
            pass
    result["enabled"] = _env_bool("DECISION_HIERARCHY_ENABLED", bool(result["enabled"]))
    result["strict_unvalidated_gate"] = _env_bool(
        "DECISION_STRICT_GATE", bool(result["strict_unvalidated_gate"])
    )
    result["preopen_event_check"] = _env_bool(
        "DECISION_PREOPEN_EVENTS", bool(result["preopen_event_check"])
    )
    weekly_mode = os.getenv("DECISION_WEEKLY_GATE_MODE", result["weekly_gate_mode"])
    weekly_mode = str(weekly_mode).strip().lower()
    result["weekly_gate_mode"] = (
        weekly_mode if weekly_mode in {"off", "shadow", "active"} else "shadow"
    )
    return result
