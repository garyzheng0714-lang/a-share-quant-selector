"""战绩追踪 API - Flask Blueprint

独立于 web_server.py（该文件已超行数上限，新 API 一律走 Blueprint）。
"""
import logging

from flask import Blueprint, jsonify, request

from utils.csv_manager import CSVManager
from utils import performance_tracker

logger = logging.getLogger(__name__)

perf_bp = Blueprint("performance", __name__)

_csv_manager = CSVManager("data")


@perf_bp.route("/api/performance/summary", methods=["GET"])
def api_performance_summary():
    """战绩汇总：总体/按分类/按B1相似度分桶的胜率与平均收益."""
    view_id = request.args.get("view_id", type=int)
    try:
        return jsonify(performance_tracker.get_summary(view_id=view_id))
    except Exception as e:
        logger.error("战绩汇总失败: %s", e)
        return jsonify({"error": "战绩数据暂不可用"}), 500


@perf_bp.route("/api/performance/records", methods=["GET"])
def api_performance_records():
    """追踪记录明细."""
    view_id = request.args.get("view_id", type=int)
    limit = request.args.get("limit", default=200, type=int)
    try:
        records = performance_tracker.get_records(view_id=view_id, limit=limit)
        return jsonify({"total": len(records), "records": records})
    except Exception as e:
        logger.error("战绩明细查询失败: %s", e)
        return jsonify({"error": "战绩数据暂不可用"}), 500


@perf_bp.route("/api/performance/refresh", methods=["POST"])
def api_performance_refresh():
    """手动触发战绩回填（用最新行情数据更新未完成的追踪记录）."""
    try:
        stats = performance_tracker.update_performance(_csv_manager)
        return jsonify({"success": True, **stats})
    except Exception as e:
        logger.error("战绩回填失败: %s", e)
        return jsonify({"error": "战绩回填失败"}), 500
