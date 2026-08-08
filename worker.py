"""独立任务 worker 与唯一调度 leader；Web 进程不运行长任务。"""

from __future__ import annotations

import hashlib
import logging
import os
import signal
import sqlite3
import socket
import threading
import time
import uuid
from datetime import datetime, time as wall_time
from zoneinfo import ZoneInfo

from utils.operations_store import (
    TaskQueueCapacityExceeded,
    acquire_scheduler_lease,
    claim_job_run,
    claim_next_task,
    enqueue_task,
    finish_job_run,
    finish_task,
    get_task,
    heartbeat_task,
    release_scheduler_lease,
    update_task_progress,
)
from utils.runtime_paths import market_data_dir


logger = logging.getLogger(__name__)
TZ = ZoneInfo("Asia/Shanghai")
OWNER_ID = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
STOP = threading.Event()
PREOPEN_RECONCILE_START = wall_time(8, 45)
PREOPEN_RECONCILE_END = wall_time(9, 25)
CLOSE_RECONCILE_START = wall_time(16, 0)
DATA_DIR = market_data_dir()
PIPELINE_STAGE_LABELS = {
    "market_ingestion": "采集并发布行情",
    "snapshot_validation": "确认正式快照",
    "outcome_refresh": "回填历史决策结果",
    "paper_pricing": "模拟盘估值",
    "decision_materialization": "计算指标并生成收盘决策",
}


def _new_pipeline(requested_trade_date: str) -> dict:
    now = _shanghai_time().isoformat(timespec="seconds")
    return {
        "state": "running",
        "current_stage": "market_ingestion",
        "requested_trade_date": requested_trade_date or None,
        "started_at": now,
        "updated_at": now,
        "stages": [],
    }


def _mark_pipeline_stage(
    pipeline: dict,
    task_id: str,
    key: str,
    status: str,
    *,
    detail: dict | None = None,
) -> None:
    now = _shanghai_time().isoformat(timespec="seconds")
    stages = pipeline.setdefault("stages", [])
    stage = next((item for item in stages if item.get("key") == key), None)
    if stage is None:
        stage = {
            "key": key,
            "label": PIPELINE_STAGE_LABELS[key],
            "status": status,
            "started_at": now,
        }
        stages.append(stage)
    else:
        stage["status"] = status
    if detail:
        stage["detail"] = detail
    if status in {"complete", "attention", "failed"}:
        stage["finished_at"] = now
    if status == "running":
        pipeline["current_stage"] = key
    elif status == "failed":
        pipeline["state"] = "failed"
        pipeline["current_stage"] = key
    pipeline["updated_at"] = now
    update_task_progress(task_id, OWNER_ID, {"pipeline": pipeline})


def _finish_pipeline(pipeline: dict, task_id: str, *, succeeded: bool) -> None:
    now = _shanghai_time().isoformat(timespec="seconds")
    pipeline["state"] = "complete" if succeeded else "failed"
    pipeline["current_stage"] = (
        "complete" if succeeded else pipeline.get("current_stage")
    )
    pipeline["finished_at"] = now
    pipeline["updated_at"] = now
    update_task_progress(task_id, OWNER_ID, {"pipeline": pipeline})


def _daily_ingestion(_payload: dict) -> dict:
    from utils.market_ingestion import run_daily_ingestion

    return run_daily_ingestion(DATA_DIR)


def _full_rebuild(payload: dict) -> dict:
    from utils.market_ingestion import run_full_rebuild

    return run_full_rebuild(
        DATA_DIR, years=min(max(int(payload.get("years", 6)), 1), 10)
    )


def _close_decision(_payload: dict) -> dict:
    from utils.hierarchical_decision import run_close_decision

    return run_close_decision()


def _preopen_decision(_payload: dict) -> dict:
    from utils.hierarchical_decision import run_preopen_decision

    current = _shanghai_time()
    requested_trade_date = str(_payload.get("trade_date") or "").strip()
    if requested_trade_date and requested_trade_date != current.date().isoformat():
        return {
            "available": False,
            "reason": "scheduled_trade_date_mismatch",
            "requested_trade_date": requested_trade_date,
            "current_trade_date": current.date().isoformat(),
        }
    if not PREOPEN_RECONCILE_START <= current.time() < PREOPEN_RECONCILE_END:
        return {
            "available": False,
            "reason": "outside_preopen_execution_window",
            "as_of": current.isoformat(),
        }
    result = run_preopen_decision()
    if result.get("available"):
        from utils.paper_trading import queue_orders_from_decision

        result = {**result, "paper_orders": queue_orders_from_decision(result)}
    return result


def _model_evolution(_payload: dict) -> dict:
    from utils.self_evolution import run_daily_evolution

    return run_daily_evolution()


def _outcome_refresh(_payload: dict) -> dict:
    from utils.csv_manager import CSVManager
    from utils.self_evolution import update_decision_outcomes

    result = update_decision_outcomes(CSVManager(DATA_DIR, writable=False))
    return {"available": True, **result}


def _run_decision_materialization(manager, freshness: dict) -> dict:
    """为已发布快照重建派生缓存并落账决策，不再次抓取行情。"""
    from utils.market_snapshot import read_snapshot_metadata

    names, _ = read_snapshot_metadata(
        "stock_names.json",
        manager.base_data_dir,
        snapshot_id=manager.snapshot_id,
    )
    from utils.sector_rotation import get_sector_rotation

    sectors = get_sector_rotation(manager, force=True)
    if not sectors.get("available"):
        return {"success": False, "stage": "sector_rotation", "result": sectors}
    from utils.market_thermometer import refresh_thermometer

    thermometer = refresh_thermometer(manager, sectors)
    if not thermometer.get("available"):
        return {"success": False, "stage": "market_thermometer", "result": thermometer}
    from utils.super_b1_scan import get_super_b1

    super_b1 = get_super_b1(manager, names, force=True)
    if not super_b1.get("available"):
        return {"success": False, "stage": "super_b1", "result": super_b1}
    from utils.factor_scan import prewarm_all

    factors = prewarm_all(manager, names)
    if not factors.get("available"):
        return {"success": False, "stage": "factor_scan", "result": factors}
    from utils.hierarchical_decision import run_close_decision

    decision = run_close_decision(manager)
    ai = None
    if decision.get("available"):
        from utils.ai_decision import run_ai_decision

        ai = run_ai_decision(decision, csv_manager=manager)
    return {
        "success": bool(decision.get("available")),
        "stage": "complete",
        "freshness": freshness,
        "sectors": sectors,
        "thermometer": thermometer,
        "super_b1": super_b1,
        "factor_trade_date": factors.get("trade_date"),
        "decision": decision,
        "ai": ai,
    }


def _run_daily_close_downstream(
    manager,
    freshness: dict,
    *,
    task_id: str,
    pipeline: dict,
) -> dict:
    """只消费已绑定快照；调用前业务幂等键已被占用。"""
    _mark_pipeline_stage(pipeline, task_id, "outcome_refresh", "running")
    try:
        outcomes = _outcome_refresh({})
    except Exception as exc:
        _mark_pipeline_stage(
            pipeline,
            task_id,
            "outcome_refresh",
            "failed",
            detail={"reason": type(exc).__name__},
        )
        raise
    outcome_status = "complete" if outcomes.get("available") else "attention"
    _mark_pipeline_stage(
        pipeline,
        task_id,
        "outcome_refresh",
        outcome_status,
        detail={
            "updated": int(outcomes.get("updated") or 0),
            "pending": int(outcomes.get("pending") or 0),
            "reason": outcomes.get("reason"),
        },
    )

    _mark_pipeline_stage(pipeline, task_id, "paper_pricing", "running")
    from utils.paper_trading import run_daily_paper_cycle

    paper = run_daily_paper_cycle(freshness["local_date"], manager)
    if not paper.get("available"):
        _mark_pipeline_stage(
            pipeline,
            task_id,
            "paper_pricing",
            "failed",
            detail={"reason": paper.get("reason")},
        )
        _finish_pipeline(pipeline, task_id, succeeded=False)
        return {
            "success": False,
            "stage": "paper_pricing",
            "result": paper,
            "outcome_refresh": outcomes,
            "pipeline": pipeline,
        }
    _mark_pipeline_stage(
        pipeline,
        task_id,
        "paper_pricing",
        "complete",
        detail={"trade_date": freshness["local_date"]},
    )

    _mark_pipeline_stage(pipeline, task_id, "decision_materialization", "running")
    result = _run_decision_materialization(manager, freshness)
    decision_succeeded = result.get("success") is True
    _mark_pipeline_stage(
        pipeline,
        task_id,
        "decision_materialization",
        "complete" if decision_succeeded else "failed",
        detail={
            "stage": result.get("stage"),
            "run_id": (result.get("decision") or {}).get("run_id"),
        },
    )
    _finish_pipeline(pipeline, task_id, succeeded=decision_succeeded)
    return {
        **result,
        "paper": paper,
        "outcome_refresh": outcomes,
        "pipeline": pipeline,
    }


def _decision_matches_snapshot(
    decision: dict | None,
    freshness: dict,
    policy_version: str,
) -> bool:
    snapshot_id = freshness.get("snapshot_id")
    return bool(
        decision
        and freshness.get("fresh") is True
        and snapshot_id
        and decision.get("trade_date") == freshness.get("local_date")
        and decision.get("trade_date") == freshness.get("expected_date")
        and decision.get("strategy_version") == policy_version
        and decision.get("data_version") == f"snapshot-{snapshot_id}"
        and (decision.get("market") or {}).get("snapshot_id") == snapshot_id
    )


def _materialize_snapshot_decision(payload: dict) -> dict:
    """快照或代码版本切换后，为当前快照补齐决策产物。"""
    from utils.csv_manager import CSVManager
    from utils.data_freshness import local_data_status
    from utils.decision_ledger import get_latest_decision
    from utils.decision_versions import strategy_version

    manager = CSVManager(DATA_DIR, writable=False)
    freshness = local_data_status(manager)
    if not freshness.get("fresh"):
        return {"success": False, "stage": "freshness", "freshness": freshness}

    trade_date = str(freshness.get("local_date") or "")
    snapshot_id = str(freshness.get("snapshot_id") or "")
    policy_version = strategy_version()
    requested = {
        "trade_date": str(payload.get("trade_date") or ""),
        "snapshot_id": str(payload.get("snapshot_id") or ""),
        "strategy_version": str(payload.get("strategy_version") or ""),
    }
    current = {
        "trade_date": trade_date,
        "snapshot_id": snapshot_id,
        "strategy_version": policy_version,
    }
    if requested != current:
        return {
            "success": True,
            "stage": "superseded_snapshot_target",
            "requested": requested,
            "current": current,
        }

    decision = get_latest_decision("close")
    if _decision_matches_snapshot(decision, freshness, policy_version):
        return {
            "success": True,
            "stage": "idempotent_replay",
            "trade_date": trade_date,
            "snapshot_id": snapshot_id,
            "policy_version": policy_version,
            "run_id": decision.get("run_id"),
        }

    task_id = str(payload.get("task_id") or "").strip()
    if not task_id:
        return {"success": False, "stage": "business_task_identity_missing"}
    job_name = "snapshot_decision_materialization"
    claim = claim_job_run(
        job_name,
        trade_date,
        snapshot_id,
        policy_version,
        task_id,
    )
    if not claim["claimed"]:
        return {
            "success": False,
            "stage": (
                "decision_ledger_inconsistent"
                if claim["status"] == "succeeded"
                else "business_run_in_progress"
            ),
            "original_task_id": claim.get("task_id"),
        }

    succeeded = False
    try:
        result = _run_decision_materialization(manager, freshness)
        succeeded = result.get("success") is True
        return result
    finally:
        finish_job_run(
            job_name,
            trade_date,
            snapshot_id,
            policy_version,
            task_id,
            succeeded=succeeded,
        )


def _daily_close_pipeline(_payload: dict) -> dict:
    """同一快照上的收盘 DAG；上游失败立即停止。"""
    requested_trade_date = str(_payload.get("trade_date") or "").strip()
    task_id = str(_payload.get("task_id") or "").strip()
    if not task_id:
        return {"success": False, "stage": "business_task_identity_missing"}
    pipeline = _new_pipeline(requested_trade_date)
    _mark_pipeline_stage(pipeline, task_id, "market_ingestion", "running")
    if requested_trade_date:
        from utils.data_freshness import expected_completed_trade_date

        currently_expected = expected_completed_trade_date(data_dir=DATA_DIR)
        if currently_expected and currently_expected != requested_trade_date:
            _mark_pipeline_stage(
                pipeline,
                task_id,
                "market_ingestion",
                "failed",
                detail={"reason": "scheduled_trade_date_mismatch"},
            )
            _finish_pipeline(pipeline, task_id, succeeded=False)
            return {
                "success": False,
                "stage": "scheduled_trade_date_mismatch",
                "requested_trade_date": requested_trade_date,
                "expected_trade_date": currently_expected,
                "pipeline": pipeline,
            }
    ingestion = _daily_ingestion({})
    if not ingestion.get("success"):
        _mark_pipeline_stage(
            pipeline,
            task_id,
            "market_ingestion",
            "failed",
            detail={"reason": ingestion.get("reason")},
        )
        _finish_pipeline(pipeline, task_id, succeeded=False)
        return {
            "success": False,
            "stage": "ingestion",
            "ingestion": ingestion,
            "pipeline": pipeline,
        }
    _mark_pipeline_stage(
        pipeline,
        task_id,
        "market_ingestion",
        "complete",
        detail={
            "trade_date": ingestion.get("trade_date"),
            "snapshot_id": ingestion.get("snapshot_id"),
        },
    )

    from utils.csv_manager import CSVManager
    from utils.data_freshness import local_data_status
    from utils.decision_versions import strategy_version

    _mark_pipeline_stage(pipeline, task_id, "snapshot_validation", "running")
    manager = CSVManager(DATA_DIR, writable=False)
    freshness = local_data_status(manager)
    if not freshness.get("fresh"):
        _mark_pipeline_stage(
            pipeline,
            task_id,
            "snapshot_validation",
            "failed",
            detail={"reason": freshness.get("reason")},
        )
        _finish_pipeline(pipeline, task_id, succeeded=False)
        return {
            "success": False,
            "stage": "freshness",
            "freshness": freshness,
            "pipeline": pipeline,
        }
    if requested_trade_date and requested_trade_date != freshness.get("local_date"):
        _mark_pipeline_stage(
            pipeline,
            task_id,
            "snapshot_validation",
            "failed",
            detail={"reason": "scheduled_trade_date_mismatch"},
        )
        _finish_pipeline(pipeline, task_id, succeeded=False)
        return {
            "success": False,
            "stage": "scheduled_trade_date_mismatch",
            "requested_trade_date": requested_trade_date,
            "snapshot_trade_date": freshness.get("local_date"),
            "pipeline": pipeline,
        }
    _mark_pipeline_stage(
        pipeline,
        task_id,
        "snapshot_validation",
        "complete",
        detail={
            "trade_date": freshness.get("local_date"),
            "snapshot_id": freshness.get("snapshot_id"),
            "coverage_ratio": freshness.get("coverage_ratio"),
        },
    )
    job_name = "daily_close_pipeline"
    trade_date = freshness["local_date"]
    snapshot_id = freshness["snapshot_id"]
    policy_version = strategy_version()
    claim = claim_job_run(
        job_name,
        trade_date,
        snapshot_id,
        policy_version,
        task_id,
    )
    if not claim["claimed"]:
        if claim["status"] == "succeeded":
            _finish_pipeline(pipeline, task_id, succeeded=True)
            return {
                "success": True,
                "stage": "idempotent_replay",
                "trade_date": trade_date,
                "snapshot_id": snapshot_id,
                "policy_version": policy_version,
                "original_task_id": claim.get("task_id"),
                "pipeline": pipeline,
            }
        _finish_pipeline(pipeline, task_id, succeeded=False)
        return {
            "success": False,
            "stage": "business_run_in_progress",
            "original_task_id": claim.get("task_id"),
            "pipeline": pipeline,
        }

    succeeded = False
    try:
        result = _run_daily_close_downstream(
            manager,
            freshness,
            task_id=task_id,
            pipeline=pipeline,
        )
        succeeded = result.get("success") is True
        return result
    finally:
        finish_job_run(
            job_name,
            trade_date,
            snapshot_id,
            policy_version,
            task_id,
            succeeded=succeeded,
        )


HANDLERS = {
    "daily_market_ingestion": _daily_ingestion,
    "full_market_rebuild": _full_rebuild,
    "close_decision": _close_decision,
    "preopen_decision": _preopen_decision,
    "model_evolution": _model_evolution,
    "outcome_refresh": _outcome_refresh,
    "daily_close_pipeline": _daily_close_pipeline,
    "materialize_snapshot_decision": _materialize_snapshot_decision,
}


def _heartbeat_loop(task_id: str, done: threading.Event) -> None:
    while not done.wait(30):
        if not heartbeat_task(task_id, OWNER_ID, lease_seconds=180):
            logger.error("任务租约已丢失: %s", task_id)
            return


def _process_one() -> bool:
    task = claim_next_task(OWNER_ID, lease_seconds=180)
    if task is None:
        return False
    handler = HANDLERS.get(task["task_type"])
    if handler is None:
        finish_task(
            task["task_id"],
            OWNER_ID,
            error_code="unknown_task_type",
            retryable=False,
        )
        return True
    done = threading.Event()
    heartbeat = threading.Thread(
        target=_heartbeat_loop,
        args=(task["task_id"], done),
        daemon=True,
    )
    heartbeat.start()
    try:
        payload = {**task["payload"], "task_id": task["task_id"]}
        result = handler(payload)
        error = (
            None
            if result.get("success", result.get("available", False))
            else str(result.get("reason") or result.get("stage") or "task_failed")
        )
        finish_task(task["task_id"], OWNER_ID, result=result, error_code=error)
    except Exception as exc:
        logger.exception("任务执行失败 %s: %s", task["task_id"], exc)
        current = get_task(task["task_id"]) or {}
        finish_task(
            task["task_id"],
            OWNER_ID,
            result={
                **(current.get("result") or {}),
                "error_type": type(exc).__name__,
            },
            error_code="unhandled_exception",
        )
    finally:
        done.set()
        heartbeat.join(timeout=1)
    return True


def process_one() -> bool:
    """SQLite 短暂锁竞争不应让 worker 进程退出；租约过期后可重试。"""
    try:
        return _process_one()
    except sqlite3.OperationalError as exc:
        logger.warning("任务库暂时不可用，稍后重试: %s", exc)
        return False


def _shanghai_time(value: datetime | None = None) -> datetime:
    current = value or datetime.now(TZ)
    if current.tzinfo is None:
        return current.replace(tzinfo=TZ)
    return current.astimezone(TZ)


def _enqueue_completed_close(current: datetime) -> dict:
    from utils.data_freshness import expected_completed_trade_date

    today = current.date().isoformat()
    completed = expected_completed_trade_date(as_of=current, data_dir=DATA_DIR)
    due = bool(
        completed and (completed < today or current.time() >= CLOSE_RECONCILE_START)
    )
    if not due:
        return {"eligible": False, "trade_date": completed or None, "created": False}
    task, created = enqueue_task(
        "daily_close_pipeline",
        f"scheduled-close:{completed}",
        payload={"trade_date": completed},
        requested_by=f"scheduler:{OWNER_ID}",
        change_reason="scheduled close pipeline",
        max_attempts=32,
    )
    return {
        "eligible": True,
        "trade_date": completed,
        "created": created,
        "task_id": task["task_id"],
    }


def _enqueue_current_snapshot_decision(current: datetime) -> dict:
    """新快照或新策略版本必须拥有自己的当前决策。"""
    from utils.data_freshness import local_data_status
    from utils.decision_ledger import get_latest_decision
    from utils.decision_versions import strategy_version

    freshness = local_data_status(as_of=current)
    if not freshness.get("fresh"):
        return {
            "eligible": False,
            "ready": False,
            "created": False,
            "reason": freshness.get("reason") or "market_snapshot_not_ready",
        }
    snapshot_id = str(freshness["snapshot_id"])
    trade_date = str(freshness["local_date"])
    policy_version = strategy_version()
    decision = get_latest_decision("close")
    if _decision_matches_snapshot(decision, freshness, policy_version):
        return {
            "eligible": False,
            "ready": True,
            "created": False,
            "trade_date": trade_date,
            "snapshot_id": snapshot_id,
            "run_id": decision.get("run_id"),
        }
    policy_hash = hashlib.sha256(policy_version.encode()).hexdigest()[:16]
    task, created = enqueue_task(
        "materialize_snapshot_decision",
        f"snapshot-decision:{snapshot_id}:{policy_hash}",
        payload={
            "trade_date": trade_date,
            "snapshot_id": snapshot_id,
            "strategy_version": policy_version,
        },
        requested_by=f"scheduler:{OWNER_ID}",
        change_reason="materialize current snapshot decision",
        max_attempts=32,
    )
    return {
        "eligible": True,
        "ready": False,
        "created": created,
        "trade_date": trade_date,
        "snapshot_id": snapshot_id,
        "task_id": task["task_id"],
    }


def _enqueue_current_preopen(current: datetime) -> dict:
    from utils.data_freshness import expected_completed_trade_date, next_trade_date

    today = current.date().isoformat()
    within_window = PREOPEN_RECONCILE_START <= current.time() < PREOPEN_RECONCILE_END
    previous = expected_completed_trade_date(as_of=current, data_dir=DATA_DIR)
    eligible = bool(
        within_window
        and previous
        and next_trade_date(previous, data_dir=DATA_DIR) == today
    )
    if not eligible:
        return {"eligible": False, "trade_date": today, "created": False}
    task, created = enqueue_task(
        "preopen_decision",
        f"scheduled-preopen:{today}",
        payload={"trade_date": today},
        requested_by=f"scheduler:{OWNER_ID}",
        change_reason="scheduled preopen review",
    )
    return {
        "eligible": True,
        "trade_date": today,
        "created": created,
        "task_id": task["task_id"],
    }


def reconcile_scheduled_tasks(as_of: datetime | None = None) -> dict:
    """Leader 周期性补齐当日任务，接管时不依赖已错过的 cron 瞬间。"""
    current = _shanghai_time(as_of)
    if not acquire_scheduler_lease("production-scheduler", OWNER_ID):
        return {"leader": False, "as_of": current.isoformat()}
    # 先补收盘和当前快照决策，再入队盘前复核。
    return {
        "leader": True,
        "as_of": current.isoformat(),
        "close": _enqueue_completed_close(current),
        "decision": _enqueue_current_snapshot_decision(current),
        "preopen": _enqueue_current_preopen(current),
    }


def enqueue_scheduled_close() -> dict:
    current = _shanghai_time()
    if not acquire_scheduler_lease("production-scheduler", OWNER_ID):
        return {"leader": False, "as_of": current.isoformat()}
    return {"leader": True, **_enqueue_completed_close(current)}


def enqueue_scheduled_preopen() -> dict:
    current = _shanghai_time()
    if not acquire_scheduler_lease("production-scheduler", OWNER_ID):
        return {"leader": False, "as_of": current.isoformat()}
    return {"leader": True, **_enqueue_current_preopen(current)}


def _initialize_worker_state() -> None:
    """只读校验账本；worker 不承担迁移职责。"""
    from utils.runtime_schema import verify_runtime_schema

    verify_runtime_schema()


def run_worker() -> None:
    _initialize_worker_state()
    logger.info("worker 已启动: %s", OWNER_ID)
    last_reconciliation = 0.0
    try:
        while not STOP.is_set():
            now = time.monotonic()
            if now - last_reconciliation >= 30:
                try:
                    reconcile_scheduled_tasks()
                except TaskQueueCapacityExceeded as exc:
                    logger.error(
                        "任务队列已满，调度任务未入队: pending=%d limit=%d",
                        exc.pending,
                        exc.limit,
                    )
                except sqlite3.OperationalError as exc:
                    logger.warning("调度账本暂时不可用，稍后重试: %s", exc)
                last_reconciliation = now
            if not process_one():
                STOP.wait(1)
    finally:
        try:
            release_scheduler_lease("production-scheduler", OWNER_ID)
        except (OSError, sqlite3.Error) as exc:
            logger.warning("退出时无法释放调度租约，将等待租约自然过期: %s", exc)


def _stop(_signum, _frame) -> None:
    STOP.set()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    run_worker()
