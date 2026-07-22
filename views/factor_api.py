"""策略因子选股 API - Flask Blueprint（第三期）

与 super_b1_api 同款模式：不 import web_server（__main__ 重复执行隐患），
Blueprint 自持 CSVManager 与 json 缓存。主板过滤与行业/市值附加都在这一层，
扫描缓存保持"全量原始"，以后放开板块权限不用重扫。
"""

import logging
import re
import time

from flask import Blueprint, jsonify, request

from utils.csv_manager import CSVManager
from utils.market_snapshot import read_snapshot_metadata

logger = logging.getLogger(__name__)

factor_bp = Blueprint("factor", __name__)

_CACHE_TTL = 3600
_industry_box: dict = {}
_cap_box: dict = {}


def _load_snapshot_json_cached(filename: str, box: dict, manager: CSVManager) -> dict:
    now = time.time()
    value, snapshot_id = read_snapshot_metadata(
        filename,
        manager.base_data_dir,
        snapshot_id=manager.snapshot_id,
    )
    if box.get("snapshot_id") != snapshot_id or now - box.get("ts", 0) > _CACHE_TTL:
        box.update(
            data=value if isinstance(value, dict) else {},
            ts=now,
            snapshot_id=snapshot_id,
        )
    return box.get("data") or {}


def _industry_map(manager: CSVManager) -> dict:
    return _load_snapshot_json_cached("stock_industry.json", _industry_box, manager)


def _cap_map(manager: CSVManager) -> dict:
    return _load_snapshot_json_cached("stock_market_cap.json", _cap_box, manager)


def _cap_yi(code: str, manager: CSVManager):
    """流通市值（亿），取不到返回 None."""
    v = _cap_map(manager).get(code)
    if isinstance(v, dict):
        cap = v.get("circ_mv") or v.get("total_mv")
        if isinstance(cap, (int, float)) and cap > 0:
            return round(cap / 1e8, 1)
    return None


@factor_bp.route("/api/factors", methods=["GET"])
def api_list_factors():
    """策略因子清单（分组+白话说明+当日命中数）+ 最近交易日列表.

    today_hits 直接读当日扫描缓存（预热后秒回；某因子未算过则为 None），
    主板过滤与 /api/factor-scan 同口径——概览徽标和详情列表数字必须一致。
    """
    try:
        from strategy.factors import FACTOR_REGISTRY, GROUP_ORDER, PLAIN_DESC
        from utils.factor_scan import _latest_data_date, _load_cache, recent_trade_dates
        from utils.market_filter import is_main_board, main_board_only

        manager = CSVManager("data", writable=False)
        if manager.snapshot_id is None:
            return jsonify({"available": False, "reason": "snapshot_unavailable"}), 503
        trade_date = _latest_data_date(manager)
        cache = _load_cache(trade_date, manager) if trade_date else {}
        mb_only = main_board_only()

        def _today_hits(key):
            bucket = cache.get(key)
            if not bucket:
                return None
            hits = bucket.get("hits", [])
            if mb_only:
                return sum(1 for h in hits if is_main_board(h.get("code", "")))
            return len(hits)

        factors = []
        for key, meta in FACTOR_REGISTRY.items():
            doc = (meta["fn"].__doc__ or "").strip().splitlines()
            desc = doc[0].split("：", 1)[-1].strip() if doc else ""
            factors.append(
                {
                    "key": key,
                    "name": meta["name"],
                    "group": meta["group"],
                    "desc": desc,
                    "plain": PLAIN_DESC.get(key, desc),
                    "today_hits": _today_hits(key),
                    # 旧 resonance_backtest 不是当前执行模型，不能冒充生产证据。
                    "track": None,
                    "research_only": True,
                }
            )
        factors.sort(
            key=lambda f: (
                GROUP_ORDER.index(f["group"]) if f["group"] in GROUP_ORDER else 99
            )
        )
        return jsonify(
            {
                "factors": factors,
                "groups": GROUP_ORDER,
                "trade_date": trade_date,
                "recent_dates": recent_trade_dates(manager, limit=40),
                "track_windows": None,
                "track_note": "旧回测口径已隔离；生产证据见 decision outcomes。",
                "source": "worker_snapshot",
            }
        )
    except Exception as e:
        logger.error("因子清单查询失败: %s", e, exc_info=True)
        return jsonify({"error": "因子清单暂不可用"}), 500


@factor_bp.route("/api/factor-scan", methods=["GET"])
def api_factor_scan():
    """只读 worker 已发布的单策略缓存；date 为空=最新交易日。

    Query:
        strategy: 因子 key（必填）
        date: YYYY-MM-DD（可选，只读已有研究缓存，不在 GET 中重扫）
    """
    try:
        from utils.factor_scan import read_cached_factor_hits
        from utils.market_filter import is_main_board, main_board_only

        manager = CSVManager("data", writable=False)
        if manager.snapshot_id is None:
            return jsonify({"available": False, "reason": "snapshot_unavailable"}), 503
        strategy = request.args.get("strategy", "").strip()
        date = request.args.get("date", "").strip()
        if not strategy:
            return jsonify({"available": False, "reason": "缺少 strategy 参数"}), 400
        # date 会参与缓存文件名拼接，必须是纯日期格式（引擎层另有兜底校验）
        if date and not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
            return jsonify({"available": False, "reason": "日期格式不合法"}), 400

        result = read_cached_factor_hits(
            manager,
            [strategy],
            date=date,
        )
        if not result.get("available"):
            return jsonify(result)

        bucket = result["results"].get(strategy, {})
        hits = bucket.get("hits", [])
        if main_board_only():
            hits = [h for h in hits if is_main_board(h.get("code", ""))]
        ind = _industry_map(manager)
        hits = [
            {
                **h,
                "industry": ind.get(h.get("code", ""), ""),
                "cap_yi": _cap_yi(h.get("code", ""), manager),
            }
            for h in hits
        ]
        return jsonify(
            {
                "available": True,
                "strategy": strategy,
                "trade_date": result["trade_date"],
                "hits": hits,
                "total_scanned": bucket.get("total_scanned", 0),
                "errors": bucket.get("errors", 0),
                "research_only": True,
                "source": "worker_snapshot",
            }
        )
    except Exception as e:
        logger.error("因子扫描查询失败: %s", e, exc_info=True)
        return jsonify({"available": False, "reason": "因子选股暂不可用"}), 500
