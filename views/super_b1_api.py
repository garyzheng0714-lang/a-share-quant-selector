"""超级B1 API - Flask Blueprint（独立模块，web_server.py 已超行数上限新 API 一律走 Blueprint）

注意：不 import web_server（生产以 `python web_server.py` 启动，模块名是 __main__，
运行时 from web_server import 会把整个文件重新执行一遍）。与 performance_api 同款：
Blueprint 自持 CSVManager 与名称缓存。
"""
import json
import logging
import time
from pathlib import Path

from flask import Blueprint, jsonify, request

from utils.csv_manager import CSVManager

logger = logging.getLogger(__name__)

super_b1_bp = Blueprint("super_b1", __name__)

_csv_manager = CSVManager("data")
_CACHE_TTL = 3600
_names_box: dict = {}
_industry_box: dict = {}


def _load_json_cached(path: str, box: dict) -> dict:
    """带 TTL 的 json 文件缓存（names / industry 共用）."""
    now = time.time()
    if not box.get("data") or now - box.get("ts", 0) > _CACHE_TTL:
        f = Path(path)
        if f.exists():
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    box["data"] = json.load(fh)
            except Exception as e:
                logger.warning("%s 加载失败: %s", path, e)
        box["ts"] = now
    return box.get("data") or {}


def _stock_names() -> dict:
    return _load_json_cached("data/stock_names.json", _names_box)


def _industry_map() -> dict:
    return _load_json_cached("data/stock_industry.json", _industry_box)


@super_b1_bp.route("/api/super-b1", methods=["GET"])
def api_get_super_b1():
    """超级B1信号清单（文件缓存，数据日期变化时自动重算）.

    Query:
        force=1 强制重扫
    """
    try:
        from utils.market_filter import is_main_board, main_board_only
        from utils.super_b1_scan import get_super_b1

        force = request.args.get("force") == "1"
        result = get_super_b1(_csv_manager, _stock_names(), force=force)
        if result.get("available"):
            hits = result.get("hits", [])
            if main_board_only():
                hits = [h for h in hits if is_main_board(h.get("code", ""))]
            # 附所属行业（展示层拼装，不写进扫描缓存）
            ind = _industry_map()
            hits = [{**h, "industry": ind.get(h.get("code", ""), "")} for h in hits]
            result = {**result, "hits": hits}
        return jsonify(result)
    except Exception as e:
        logger.error("超级B1查询失败: %s", e, exc_info=True)
        return jsonify({"available": False, "reason": "超级B1数据暂不可用"}), 500


@super_b1_bp.route("/api/super-b1/performance", methods=["GET"])
def api_super_b1_performance():
    """超级B1独立战绩：总体/按信号类型的胜率与平均收益 + 明细."""
    try:
        from utils.super_b1_tracker import get_records, get_summary

        limit = request.args.get("limit", default=200, type=int)
        summary = get_summary()
        summary["records"] = get_records(limit=limit)
        return jsonify(summary)
    except Exception as e:
        logger.error("超级B1战绩查询失败: %s", e, exc_info=True)
        return jsonify({"error": "超级B1战绩暂不可用"}), 500


@super_b1_bp.route("/api/super-b1/performance/refresh", methods=["POST"])
def api_super_b1_performance_refresh():
    """手动触发：把当前扫描缓存的命中录入追踪表 + 回填后续表现."""
    try:
        from utils.super_b1_scan import get_super_b1
        from utils.super_b1_tracker import record_hits, update_performance

        scan = get_super_b1(_csv_manager, _stock_names())
        added = 0
        if scan.get("available"):
            added = record_hits(scan.get("hits", []), scan.get("trade_date", ""))
        stats = update_performance(_csv_manager)
        return jsonify({"success": True, "recorded": added, **stats})
    except Exception as e:
        logger.error("超级B1战绩刷新失败: %s", e, exc_info=True)
        return jsonify({"error": "超级B1战绩刷新失败"}), 500
