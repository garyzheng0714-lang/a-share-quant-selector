"""分层决策功能开关；默认保守开启，环境变量可即时回退。"""
from __future__ import annotations

import os
from pathlib import Path

import yaml


DEFAULTS = {
    "enabled": True,
    "strict_unvalidated_gate": True,
    "preopen_event_check": True,
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
    return result
