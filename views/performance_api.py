"""当前 Super B1 决策链的结果跟踪 API。"""

import logging

from flask import Blueprint, jsonify, request

from utils.api_security import require_role
from utils.decision_ledger import list_decision_outcomes, outcome_summary
from utils.execution_model import DEFAULT_EXECUTION_POLICY

logger = logging.getLogger(__name__)
perf_bp = Blueprint("performance", __name__)


@perf_bp.route("/api/performance/summary", methods=["GET"])
def api_performance_summary():
    """只汇总版本化 decision ledger，不混入旧 views/results 战绩。"""
    try:
        return jsonify(
            {
                "available": True,
                "strategy": "super-b1-canonical",
                "execution_policy_version": DEFAULT_EXECUTION_POLICY.version,
                "summary": outcome_summary(),
                "legacy_results_included": False,
            }
        )
    except Exception as exc:
        logger.error("战绩汇总失败: %s", exc, exc_info=True)
        return jsonify({"available": False, "reason": "performance_unavailable"}), 500


@perf_bp.route("/api/performance/records", methods=["GET"])
def api_performance_records():
    limit = min(max(request.args.get("limit", default=100, type=int) or 100, 1), 200)
    try:
        records = list_decision_outcomes(limit=limit)
        return jsonify(
            {
                "available": True,
                "execution_policy_version": DEFAULT_EXECUTION_POLICY.version,
                "total": len(records),
                "records": records,
                "legacy_results_included": False,
            }
        )
    except Exception as exc:
        logger.error("战绩明细失败: %s", exc, exc_info=True)
        return jsonify({"available": False, "reason": "performance_unavailable"}), 500


@perf_bp.route("/api/performance/refresh", methods=["POST"])
@require_role("publisher")
def api_performance_refresh():
    """由独立 worker 回填，Web 请求不直接跑全市场计算。"""
    from utils.task_submission import submit_task

    return submit_task("outcome_refresh")
