"""管理 API 提交持久任务的统一入口。"""

from __future__ import annotations

import re

from flask import g, jsonify, request

from utils.operations_store import TaskQueueCapacityExceeded, enqueue_task


_KEY_RE = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")


def valid_idempotency_key(value: str) -> bool:
    return bool(_KEY_RE.fullmatch(str(value).strip()))


def submit_task(task_type: str, payload: dict | None = None):
    key = request.headers.get("Idempotency-Key", "").strip()
    if not valid_idempotency_key(key):
        return jsonify(
            {
                "success": False,
                "error": "valid_idempotency_key_required",
            }
        ), 400
    reason = request.headers.get("X-Change-Reason", "").strip()
    if len(reason) < 3 or len(reason) > 500:
        return jsonify({"success": False, "error": "change_reason_required"}), 400
    principal = g.auth_principal
    try:
        task, created = enqueue_task(
            task_type,
            key,
            payload=payload or {},
            requested_by=principal.principal_id,
            request_id=getattr(g, "request_id", None),
            requested_ip=request.remote_addr,
            change_reason=reason,
        )
    except TaskQueueCapacityExceeded as exc:
        return jsonify(
            {
                "success": False,
                "error": "task_queue_capacity_exceeded",
                "pending": exc.pending,
                "limit": exc.limit,
            }
        ), 503
    return jsonify(
        {
            "success": True,
            "created": created,
            "task": task,
        }
    ), 202
