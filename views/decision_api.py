"""市场→板块→个股→执行的版本化决策 API。"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from utils.api_security import require_role

from utils.decision_ledger import (
    get_active_policy,
    get_decision,
    get_latest_ai_decision_run,
    get_latest_decision,
    get_latest_evolution,
    list_models,
)

logger = logging.getLogger(__name__)
decision_bp = Blueprint("decision", __name__)


def _matches_current_snapshot(run: dict | None, freshness: dict) -> bool:
    if not run or freshness.get("fresh") is not True:
        return False
    from utils.decision_versions import strategy_version

    snapshot_id = freshness.get("snapshot_id")
    return bool(
        snapshot_id
        and run.get("trade_date") == freshness.get("local_date")
        and run.get("trade_date") == freshness.get("expected_date")
        and run.get("strategy_version") == strategy_version()
        and run.get("data_version") == f"snapshot-{snapshot_id}"
        and (run.get("market") or {}).get("snapshot_id") == snapshot_id
    )


def _with_models(run: dict | None) -> dict:
    from utils.data_freshness import local_data_status

    freshness = local_data_status()
    if not run:
        reason = "stale_market_data" if not freshness["fresh"] else "decision_not_ready"
        return {
            "available": False,
            "reason": reason,
            "freshness": freshness,
            "data_status": "stale" if not freshness["fresh"] else "fresh",
            "models": list_models(),
        }
    current = _matches_current_snapshot(run, freshness)
    return {
        "available": True,
        **run,
        "freshness": freshness,
        "is_stale": not current,
        "data_status": "current" if current else "historical",
        "warning_reason": (
            None
            if current
            else (
                "stale_market_data"
                if freshness.get("fresh") is not True
                else "historical_decision"
            )
        ),
        "models": list_models(),
    }


@decision_bp.route("/api/decision/latest", methods=["GET"])
def api_latest_decision():
    stage = request.args.get("stage")
    if stage not in {None, "close", "preopen"}:
        return jsonify({"available": False, "reason": "invalid_stage"}), 400
    try:
        run = get_latest_decision(stage)
        from utils.data_freshness import local_data_status

        freshness = local_data_status()
        if not _matches_current_snapshot(run, freshness):
            run = None
        return jsonify(_with_models(run))
    except Exception as exc:
        logger.error("读取分层决策失败: %s", exc, exc_info=True)
        return jsonify({"available": False, "reason": "decision_unavailable"}), 500


@decision_bp.route("/api/decision/<run_id>", methods=["GET"])
def api_decision_detail(run_id: str):
    run = get_decision(run_id)
    return (jsonify(_with_models(run)), 200 if run else 404)


@decision_bp.route("/api/decision/close", methods=["POST"])
@require_role("publisher")
def api_run_close_decision():
    from utils.task_submission import submit_task

    return submit_task("close_decision")


@decision_bp.route("/api/decision/evolution", methods=["GET"])
def api_evolution_status():
    latest = get_latest_evolution()
    current = bool(
        latest and (latest.get("metrics") or {}).get("strategy") == "super-b1-original"
    )
    return jsonify({"available": current, "data": latest if current else None})


@decision_bp.route("/api/decision/system-status", methods=["GET"])
def api_system_status():
    """一次返回决策、AI、模拟账户和研究发布状态，供工作台诚实展示。"""
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from utils.data_freshness import local_data_status
        from utils.paper_trading import get_paper_status

        freshness = local_data_status()
        latest_decision = get_latest_decision("close")
        decision = (
            latest_decision
            if _matches_current_snapshot(latest_decision, freshness)
            else None
        )
        evolution = get_latest_evolution()
        latest_ai = get_latest_ai_decision_run()
        ai = (
            latest_ai
            if decision
            and latest_ai
            and latest_ai.get("decision_run_id") == decision.get("run_id")
            else None
        )
        policy = get_active_policy()
        candidates = (decision or {}).get("candidates") or []
        counts = {
            action: sum(row.get("action") == action for row in candidates)
            for action in ("buy", "observe", "avoid")
        }
        paper = get_paper_status()
        return jsonify(
            {
                "available": True,
                "as_of": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(
                    timespec="seconds"
                ),
                "market_data": freshness,
                "decision": {
                    "available": bool(decision),
                    "run_id": (decision or {}).get("run_id"),
                    "trade_date": (decision or {}).get("trade_date"),
                    "status": (decision or {}).get("status"),
                    "final_action": (decision or {}).get("final_action"),
                    "model_version": (decision or {}).get(
                        "model_version", "baseline-only"
                    ),
                    "candidate_counts": counts,
                    "reason_codes": (decision or {}).get("reason_codes", []),
                    "reason": None
                    if decision
                    else (
                        "stale_market_data"
                        if freshness.get("fresh") is not True
                        else "decision_not_ready"
                    ),
                },
                "ai": ai
                or {
                    "status": "not_called",
                    "reason_codes": ["ai_run_not_current"],
                },
                "evolution": evolution
                or {
                    "status": "not_started",
                    "promotion_status": "not_evaluated",
                    "reason_codes": ["evolution_run_not_recorded"],
                },
                "paper": paper,
                "policy": {
                    "active_policy_version": (policy or {}).get(
                        "policy_version", "baseline-only"
                    ),
                    "release_id": (policy or {}).get("release_id"),
                    "state": "active" if policy else "baseline_only",
                    "daily_auto_promotion": False,
                },
            }
        )
    except Exception as exc:
        logger.error("读取系统状态失败: %s", exc, exc_info=True)
        return jsonify({"available": False, "reason": "system_status_unavailable"}), 500


@decision_bp.route("/api/decision/evolution", methods=["POST"])
@require_role("publisher")
def api_run_evolution():
    from utils.task_submission import submit_task

    return submit_task("model_evolution")


@decision_bp.route("/api/decision/preopen", methods=["POST"])
@require_role("publisher")
def api_run_preopen_decision():
    from utils.task_submission import submit_task

    return submit_task("preopen_decision")


@decision_bp.route("/api/decision/replay", methods=["POST"])
@require_role("admin")
def api_replay_decision():
    """显式 snapshot replay；不写账本。"""
    payload = request.get_json(silent=True) or {}
    run_id = str(payload.get("run_id") or "").strip()
    snapshot_id = str(payload.get("snapshot_id") or "").strip()
    if not run_id or not snapshot_id:
        return jsonify({"available": False, "reason": "run_and_snapshot_required"}), 400
    from utils.decision_replay import replay_decision

    result = replay_decision(run_id, snapshot_id)
    return jsonify(result), (200 if result.get("available") else 409)
