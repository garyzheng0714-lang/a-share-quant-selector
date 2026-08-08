"""面向用户的数据管线只读聚合状态。"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, time as wall_time
from pathlib import Path
from zoneinfo import ZoneInfo

from utils.data_freshness import local_data_status, next_trade_date
from utils.csv_manager import CSVManager
from utils.market_snapshot import load_current_market_snapshot
from utils.operations_store import (
    alert_summary,
    get_latest_task,
    list_alerts,
    scheduler_status,
)
from utils.runtime_paths import market_data_dir, runtime_state_dir


TZ = ZoneInfo("Asia/Shanghai")
CLOSE_TIME = wall_time(16, 0)
REASON_TEXT = {
    "validated_snapshot_missing": "还没有可用的正式行情快照",
    "trading_calendar_unavailable": "交易日历暂不可用",
    "trade_date_mismatch": "行情尚未更新到最近完成的交易日",
    "future_market_data": "行情中出现了未来日期",
    "coverage_below_threshold": "行情覆盖率低于发布门槛",
    "anchor_quorum_failed": "关键锚点股票没有全部更新",
    "source_quorum_failed": "可信行情来源数量不足",
    "schema_validation_failed": "行情结构校验没有通过",
    "synthetic_market_data": "行情中出现了不允许的合成数据",
}


PIPELINE_TASK_LABELS = {
    "full_market_rebuild": "全量基线重建",
    "daily_market_ingestion": "每日行情采集",
    "daily_close_pipeline": "每日收盘闭环",
}


def _read_operations_state() -> tuple[dict, dict | None, list[dict], dict]:
    try:
        tasks = [
            task
            for task_type in PIPELINE_TASK_LABELS
            if (task := get_latest_task(task_type)) is not None
        ]
        latest_task = max(
            tasks,
            key=lambda item: (str(item.get("created_at") or ""), item["task_id"]),
            default=None,
        )
        return (
            scheduler_status(),
            latest_task,
            list_alerts(limit=3),
            alert_summary(),
        )
    except (FileNotFoundError, sqlite3.Error):
        return (
            {"running": False, "leader": None},
            None,
            [],
            {"window_hours": 24, "warning": 0, "critical": 0, "total": 0},
        )


def _read_decision(freshness: dict) -> dict:
    try:
        from utils.decision_ledger import get_latest_decision
        from utils.decision_versions import strategy_version

        decision = get_latest_decision("close")
        policy_version = strategy_version()
    except (FileNotFoundError, sqlite3.Error):
        decision = None
        policy_version = None
    snapshot_id = freshness.get("snapshot_id")
    current = bool(
        decision
        and freshness.get("fresh") is True
        and decision.get("trade_date") == freshness.get("local_date")
        and decision.get("strategy_version") == policy_version
        and decision.get("data_version") == f"snapshot-{snapshot_id}"
        and (decision.get("market") or {}).get("snapshot_id") == snapshot_id
    )
    candidates = (decision or {}).get("candidates") or []
    counts = {
        action: sum(row.get("action") == action for row in candidates)
        for action in ("buy", "observe", "avoid")
    }
    return {
        "available": current,
        "run_id": decision.get("run_id") if current else None,
        "trade_date": decision.get("trade_date") if current else None,
        "final_action": decision.get("final_action") if current else None,
        "candidate_counts": counts if current else {"buy": 0, "observe": 0, "avoid": 0},
    }


def _next_close_at(freshness: dict, data_root: Path) -> str | None:
    expected = str(freshness.get("expected_date") or "")
    local_date = str(freshness.get("local_date") or "")
    if expected and freshness.get("fresh") is not True:
        target = expected
    else:
        base = local_date or expected
        target = next_trade_date(base, data_dir=data_root) if base else ""
    if not target:
        return None
    scheduled = datetime.combine(
        datetime.strptime(target, "%Y-%m-%d").date(), CLOSE_TIME, tzinfo=TZ
    )
    return scheduled.isoformat(timespec="minutes")


def _storage_status(data_root: Path) -> dict:
    snapshot_root = data_root / "market_snapshots"
    staging_root = data_root / ".snapshot_staging"
    snapshots = (
        sum(path.is_dir() for path in snapshot_root.iterdir())
        if snapshot_root.is_dir()
        else 0
    )
    staging = (
        sum(path.is_dir() for path in staging_root.iterdir())
        if staging_root.is_dir()
        else 0
    )
    return {
        "data_root": str(data_root),
        "state_root": str(runtime_state_dir()),
        "snapshot_directory": str(snapshot_root),
        "snapshot_count": snapshots,
        "staging_count": staging,
        "retention_state": "configured",
        "retention_policy": "indefinite",
        "retention_days": None,
        "retention_summary": "长期保留；系统不自动删除正式快照或失败暂存",
    }


def _rebuild_progress(data_root: Path) -> dict | None:
    path = data_root / ".ingestion_state" / "universe_bootstrap.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    total = int(value.get("universe_count") or 0)
    processed = int(value.get("processed_this_run") or 0)
    return {
        "status": value.get("status"),
        "processed": processed,
        "total": total,
        "remaining": max(total - processed, 0),
        "current": value.get("current"),
        "updated_at": value.get("updated_at"),
    }


def _task_summary(task: dict | None, data_root: Path) -> dict | None:
    if task is None:
        return None
    result = task.get("result") or {}
    pipeline = result.get("pipeline") or {}
    task_type = str(task.get("task_type") or "")
    stages = pipeline.get("stages") or []
    progress = None
    current_stage = pipeline.get("current_stage") or result.get("stage")
    if task_type == "full_market_rebuild" and task.get("status") == "running":
        progress = _rebuild_progress(data_root)
        if progress:
            current_stage = "historical_kline"
            stages = [
                {
                    "key": "historical_kline",
                    "label": "回补历史 K 线",
                    "status": "running",
                    "started_at": task.get("started_at"),
                    "detail": {
                        "processed": progress["processed"],
                        "total": progress["total"],
                        "pending": progress["remaining"],
                    },
                }
            ]
    return {
        "task_id": task.get("task_id"),
        "task_type": task_type,
        "task_label": PIPELINE_TASK_LABELS.get(task_type, task_type or "数据任务"),
        "status": task.get("status"),
        "trade_date": (task.get("payload") or {}).get("trade_date"),
        "current_stage": current_stage,
        "progress": progress,
        "attempt_count": task.get("attempt_count", 0),
        "max_attempts": task.get("max_attempts", 0),
        "created_at": task.get("created_at"),
        "started_at": task.get("started_at"),
        "finished_at": task.get("finished_at"),
        "next_attempt_at": task.get("next_attempt_at"),
        "error_code": task.get("error_code"),
        "stages": stages,
    }


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _source_status(snapshot: dict) -> dict:
    payload_value = snapshot.get("payload_dir")
    payload = Path(payload_value) if payload_value else None
    universe = _read_json(payload / "universe_manifest.json") if payload else {}
    reference = _read_json(payload / "reference_data_manifest.json") if payload else {}
    security = _read_json(payload / "security_status.json") if payload else {}
    verification = universe.get("verification") or {}
    return {
        "kline": {
            "primary": "tencent:qfqday",
            "fallback": "akshare:stock_zh_a_hist",
            "validation_fallback": "sina:stock_zh_a_daily",
            "adjustment": "qfq",
        },
        "universe": {
            "source_id": universe.get("source"),
            "discovery_source_id": verification.get("discovery_source_id"),
            "verification_source_id": verification.get("quote_source_id"),
            "count": int(universe.get("count") or 0),
        },
        "industry": reference.get("industry") or {},
        "market_cap": reference.get("market_cap") or {},
        "security_status": {
            "source_id": security.get("source_id"),
            "count": int(security.get("count") or 0),
            "suspended_count": int(security.get("suspended_count") or 0),
        },
    }


def build_pipeline_status(data_dir: str | Path = "data") -> dict:
    data_root = market_data_dir(data_dir)
    now = datetime.now(TZ)
    freshness = local_data_status(CSVManager(data_root, writable=False))
    snapshot = load_current_market_snapshot(data_root, verify_files=False)
    manifest = snapshot.get("manifest") or {}
    scheduler, latest_task, latest_alerts, alerts = _read_operations_state()
    run = _task_summary(latest_task, data_root)
    decision = _read_decision(freshness)
    storage = _storage_status(data_root)

    attention = []
    if freshness.get("fresh") is not True:
        reason = str(freshness.get("reason") or "validated_snapshot_missing")
        attention.append(
            {
                "code": reason,
                "level": "critical" if not snapshot.get("available") else "warning",
                "message": REASON_TEXT.get(reason, "行情数据当前不可用"),
            }
        )
    if scheduler.get("running") is not True:
        attention.append(
            {
                "code": "scheduler_not_running",
                "level": "critical",
                "message": "每日调度器当前没有运行",
            }
        )
    if run and run.get("status") == "failed":
        attention.append(
            {
                "code": "latest_data_task_failed",
                "level": "critical",
                "message": (
                    f"最近一次{run.get('task_label')}失败："
                    f"{run.get('error_code') or '原因待查看'}"
                ),
            }
        )
    elif run and run.get("status") == "queued" and run.get("error_code"):
        attention.append(
            {
                "code": "data_task_retry_scheduled",
                "level": "warning",
                "message": f"{run.get('task_label')}失败，系统已安排自动重试",
            }
        )
    if freshness.get("fresh") is True and not decision.get("available"):
        attention.append(
            {
                "code": "decision_not_ready",
                "level": "warning",
                "message": "行情已经就绪，但当前快照的收盘决策尚未生成",
            }
        )
    if storage["retention_state"] != "configured":
        attention.append(
            {
                "code": "retention_not_configured",
                "level": "warning",
                "message": "行情快照和失败暂存还没有自动保留期限",
            }
        )

    running = bool(run and run.get("status") in {"queued", "running"})
    if running:
        state = "updating"
    elif not snapshot.get("available"):
        state = "unavailable"
    elif attention:
        state = "attention"
    else:
        state = "healthy"

    return {
        "available": True,
        "state": state,
        "as_of": now.isoformat(timespec="seconds"),
        "market": {
            **freshness,
            "stock_count": int(manifest.get("valid_count") or 0),
            "captured_at": manifest.get("captured_at"),
        },
        "scheduler": {
            "running": scheduler.get("running") is True,
            "heartbeat_at": scheduler.get("heartbeat_at"),
            "next_close_at": _next_close_at(freshness, data_root),
            "close_schedule": "交易日 16:00 后",
            "preopen_schedule": "交易日 08:45–09:25",
        },
        "run": run,
        "decision": decision,
        "sources": _source_status(snapshot),
        "attention": attention,
        "alerts": {
            "summary": alerts,
            "latest": [
                {
                    "alert_id": item.get("alert_id"),
                    "occurred_at": item.get("occurred_at"),
                    "severity": item.get("severity"),
                    "message": item.get("message"),
                }
                for item in latest_alerts
            ],
        },
        "storage": storage,
    }
