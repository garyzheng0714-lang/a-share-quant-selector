"""市场洞察 API - Flask Blueprint（温度计 + 每日荐一票）

独立于 web_server.py（该文件已超行数上限，新 API 一律走 Blueprint）。
"""
import logging

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

insight_bp = Blueprint("insight", __name__)


@insight_bp.route("/api/thermometer", methods=["GET"])
def api_thermometer():
    """市场温度计：成交热度分位、大盘趋势、策略适应度、人话结论."""
    try:
        from utils.market_thermometer import get_thermometer
        return jsonify(get_thermometer())
    except Exception as e:
        logger.error("温度计获取失败: %s", e)
        return jsonify({"available": False, "reason": "温度计数据暂不可用"}), 500


@insight_bp.route("/api/sectors", methods=["GET"])
def api_sectors():
    """板块轮动：当前最热板块 + 潜在接力板块（自研量化模型，收盘口径）."""
    try:
        from utils.csv_manager import CSVManager
        from utils.sector_rotation import get_sector_rotation
        return jsonify(get_sector_rotation(CSVManager("data")))
    except Exception as e:
        logger.error("板块轮动获取失败: %s", e)
        return jsonify({"available": False, "reason": "板块数据暂不可用"}), 500


@insight_bp.route("/api/daily-pick", methods=["GET"])
def api_get_daily_pick():
    """最新一次推荐（含后续真实表现考核）；history=1 时返回推荐历史."""
    try:
        from utils.daily_pick import get_api_key, get_pick_history
        history = get_pick_history(limit=30)
        if request.args.get("history"):
            return jsonify({"configured": bool(get_api_key()), "picks": history})
        return jsonify({
            "configured": bool(get_api_key()),
            "pick": history[0] if history else None,
        })
    except Exception as e:
        logger.error("获取推荐失败: %s", e)
        return jsonify({"error": "推荐数据暂不可用"}), 500


@insight_bp.route("/api/daily-pick", methods=["POST"])
def api_generate_daily_pick():
    """基于最新选股结果生成今日推荐（已有当日推荐则复用，body 传 force 重新生成）."""
    try:
        from utils.daily_pick import generate_daily_pick
        body = request.get_json(silent=True) or {}
        result = generate_daily_pick(force=bool(body.get("force")))
        return jsonify(result)
    except Exception as e:
        logger.error("生成推荐失败: %s", e)
        return jsonify({"available": False, "reason": "生成推荐失败"}), 500
