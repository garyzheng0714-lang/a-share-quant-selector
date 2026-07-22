"""超级B1 API - Flask Blueprint（独立模块，web_server.py 已超行数上限新 API 一律走 Blueprint）

注意：不 import web_server（生产以 `python web_server.py` 启动，模块名是 __main__，
运行时 from web_server import 会把整个文件重新执行一遍）。与 performance_api 同款：
Blueprint 自持 CSVManager 与名称缓存。
"""

import logging
import time

from flask import Blueprint, jsonify

from utils.csv_manager import CSVManager
from utils.api_security import require_role
from utils.market_snapshot import read_snapshot_metadata

logger = logging.getLogger(__name__)

super_b1_bp = Blueprint("super_b1", __name__)

_CACHE_TTL = 3600
_industry_box: dict = {}


def _load_json_cached(filename: str, box: dict, manager: CSVManager) -> dict:
    """按 snapshot ID 隔离的只读元数据缓存。"""
    now = time.time()
    value, snapshot_id = read_snapshot_metadata(
        filename,
        manager.base_data_dir,
        snapshot_id=manager.snapshot_id,
    )
    if box.get("snapshot_id") != snapshot_id or now - box.get("ts", 0) > _CACHE_TTL:
        box["data"] = value if isinstance(value, dict) else {}
        box["snapshot_id"] = snapshot_id
        box["ts"] = now
    return box.get("data") or {}


def _industry_map(manager: CSVManager) -> dict:
    return _load_json_cached("stock_industry.json", _industry_box, manager)


@super_b1_bp.route("/api/super-b1", methods=["GET"])
def api_get_super_b1():
    """只读 worker 已生成的当前快照信号；缓存缺失时不在 GET 重扫。"""
    try:
        from utils.market_filter import is_main_board, main_board_only
        from utils.super_b1_scan import read_cached_super_b1

        manager = CSVManager("data", writable=False)
        if manager.snapshot_id is None:
            return jsonify({"available": False, "reason": "snapshot_unavailable"}), 503
        result = read_cached_super_b1(manager)
        if result.get("available"):
            hits = result.get("hits", [])
            if main_board_only():
                hits = [h for h in hits if is_main_board(h.get("code", ""))]
            # 附所属行业（展示层拼装，不写进扫描缓存）
            ind = _industry_map(manager)
            hits = [{**h, "industry": ind.get(h.get("code", ""), "")} for h in hits]
            result = {**result, "hits": hits}
        return jsonify(result)
    except Exception as e:
        logger.error("超级B1查询失败: %s", e, exc_info=True)
        return jsonify({"available": False, "reason": "超级B1数据暂不可用"}), 500


@super_b1_bp.route("/api/super-b1/performance", methods=["GET"])
def api_super_b1_performance():
    """旧 tracker 口径已隔离；统一战绩见 canonical performance API。"""
    return jsonify(
        {
            "available": False,
            "reason": "legacy_research_disabled",
            "replacement": "/api/performance/records",
        }
    ), 410


@super_b1_bp.route("/api/super-b1/performance/refresh", methods=["POST"])
@require_role("admin")
def api_super_b1_performance_refresh():
    """旧 tracker 刷新入口永久停用。"""
    return jsonify(
        {
            "available": False,
            "reason": "legacy_research_disabled",
            "replacement": "/api/performance/refresh",
        }
    ), 410
