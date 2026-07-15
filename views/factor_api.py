"""策略因子选股 API - Flask Blueprint（第三期）

与 super_b1_api 同款模式：不 import web_server（__main__ 重复执行隐患），
Blueprint 自持 CSVManager 与 json 缓存。主板过滤与行业/市值附加都在这一层，
扫描缓存保持"全量原始"，以后放开板块权限不用重扫。
"""
import json
import logging
import re
import time
from pathlib import Path

from flask import Blueprint, jsonify, request

from utils.csv_manager import CSVManager

logger = logging.getLogger(__name__)

factor_bp = Blueprint("factor", __name__)

_csv_manager = CSVManager("data")
_CACHE_TTL = 3600
_names_box: dict = {}
_industry_box: dict = {}
_cap_box: dict = {}
_track_box: dict = {}


def _load_json_cached(path: str, box: dict) -> dict:
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


def _cap_map() -> dict:
    return _load_json_cached("data/stock_market_cap.json", _cap_box)


def _track_record() -> dict:
    """因子双周期真实战绩（tools/resonance_backtest.py 产出）.

    两段互不重叠的历史窗口各自回测：只在两段都跑赢基准的才算 robust——
    单段有效大概率是那段行情的运气（共振假设就是这么被证伪的）。
    """
    return _load_json_cached("data/factor_track_record.json", _track_box)


def _cap_yi(code: str):
    """流通市值（亿），取不到返回 None."""
    v = _cap_map().get(code)
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

        trade_date = _latest_data_date(_csv_manager)
        cache = _load_cache(trade_date) if trade_date else {}
        mb_only = main_board_only()

        def _today_hits(key):
            bucket = cache.get(key)
            if not bucket:
                return None
            hits = bucket.get("hits", [])
            if mb_only:
                return sum(1 for h in hits if is_main_board(h.get("code", "")))
            return len(hits)

        track = _track_record()
        records = track.get("factors", {})

        factors = []
        for key, meta in FACTOR_REGISTRY.items():
            doc = (meta["fn"].__doc__ or "").strip().splitlines()
            desc = doc[0].split("：", 1)[-1].strip() if doc else ""
            factors.append({
                "key": key,
                "name": meta["name"],
                "group": meta["group"],
                "desc": desc,
                "plain": PLAIN_DESC.get(key, desc),
                "today_hits": _today_hits(key),
                "track": records.get(key),   # 双周期真实战绩，无数据则 None
            })
        factors.sort(key=lambda f: (GROUP_ORDER.index(f["group"])
                                    if f["group"] in GROUP_ORDER else 99))
        return jsonify({
            "factors": factors,
            "groups": GROUP_ORDER,
            "trade_date": trade_date,
            "recent_dates": recent_trade_dates(_csv_manager, limit=40),
            "track_windows": track.get("windows"),
            "track_note": track.get("note"),
        })
    except Exception as e:
        logger.error("因子清单查询失败: %s", e, exc_info=True)
        return jsonify({"error": "因子清单暂不可用"}), 500


@factor_bp.route("/api/factor-scan", methods=["GET"])
def api_factor_scan():
    """单策略选股结果（带缓存；date 为空=最新交易日）.

    Query:
        strategy: 因子 key（必填）
        date: YYYY-MM-DD（可选，历史回看）
        force: 1 强制重扫
    """
    try:
        from utils.factor_scan import get_factor_hits
        from utils.market_filter import is_main_board, main_board_only

        strategy = request.args.get("strategy", "").strip()
        date = request.args.get("date", "").strip()
        force = request.args.get("force") == "1"
        if not strategy:
            return jsonify({"available": False, "reason": "缺少 strategy 参数"}), 400
        # date 会参与缓存文件名拼接，必须是纯日期格式（引擎层另有兜底校验）
        if date and not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
            return jsonify({"available": False, "reason": "日期格式不合法"}), 400

        result = get_factor_hits(_csv_manager, _stock_names(), [strategy],
                                 date=date, force=force)
        if not result.get("available"):
            return jsonify(result)

        bucket = result["results"].get(strategy, {})
        hits = bucket.get("hits", [])
        if main_board_only():
            hits = [h for h in hits if is_main_board(h.get("code", ""))]
        ind = _industry_map()
        hits = [{**h,
                 "industry": ind.get(h.get("code", ""), ""),
                 "cap_yi": _cap_yi(h.get("code", ""))} for h in hits]
        return jsonify({
            "available": True,
            "strategy": strategy,
            "trade_date": result["trade_date"],
            "hits": hits,
            "total_scanned": bucket.get("total_scanned", 0),
            "errors": bucket.get("errors", 0),
        })
    except Exception as e:
        logger.error("因子扫描查询失败: %s", e, exc_info=True)
        return jsonify({"available": False, "reason": "因子选股暂不可用"}), 500
