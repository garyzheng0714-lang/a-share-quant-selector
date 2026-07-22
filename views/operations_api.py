"""持久后台任务查询 API。"""

from flask import Blueprint, g, jsonify, request

from utils.api_security import require_role
from utils.operations_store import (
    alert_summary,
    cancel_task,
    get_task,
    list_alerts,
    scheduler_status,
)
from utils.task_submission import valid_idempotency_key


operations_bp = Blueprint("operations", __name__)


@operations_bp.get("/api/tasks/<task_id>")
@require_role("viewer")
def api_task_status(task_id: str):
    task = get_task(task_id)
    if task is None:
        return jsonify({"success": False, "error": "task_not_found"}), 404
    return jsonify({"success": True, "task": task})


@operations_bp.get("/api/scheduler/status")
@require_role("viewer")
def api_scheduler_status():
    return jsonify({"success": True, "data": scheduler_status()})


@operations_bp.get("/api/alerts")
@require_role("viewer")
def api_alerts():
    try:
        limit = int(request.args.get("limit", 50))
        severity = request.args.get("severity") or None
        alerts = list_alerts(limit=limit, severity=severity)
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "invalid_alert_query"}), 400
    return jsonify(
        {
            "success": True,
            "data": {
                "alerts": alerts,
                "summary": alert_summary(),
            },
        }
    )


@operations_bp.post("/api/tasks/<task_id>/cancel")
@require_role("admin")
def api_cancel_task(task_id: str):
    if not valid_idempotency_key(request.headers.get("Idempotency-Key", "")):
        return jsonify(
            {"success": False, "error": "valid_idempotency_key_required"}
        ), 400
    reason = request.headers.get("X-Change-Reason", "").strip()
    if not 3 <= len(reason) <= 500:
        return jsonify({"success": False, "error": "change_reason_required"}), 400
    result = cancel_task(
        task_id,
        requested_by=g.auth_principal.principal_id,
        change_reason=reason,
    )
    if result["reason"] == "task_not_found":
        return jsonify({"success": False, **result}), 404
    if not result["cancelled"]:
        return jsonify({"success": False, **result}), 409
    return jsonify({"success": True, **result})
