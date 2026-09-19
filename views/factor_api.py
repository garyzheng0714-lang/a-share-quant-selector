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


def _sector_heat() -> dict:
    """全行业热度榜 {行业: {score, delta3, stage, rank, total}}（只读展示，不参与排序）."""
    try:
        from utils.sector_rotation import get_sector_rotation
        s = get_sector_rotation(_csv_manager)
        if not s.get("available"):
            return {}
        return s.get("heat_map") or {}
    except Exception as e:
        logger.warning("板块热度读取失败: %s", e)
        return {}


def _compose_codes(sets: list, join: str) -> set:
    """按 join 合并各因子命中集合：and=交集，or=并集."""
    if not sets:
        return set()
    out = set(sets[0])
    for s in sets[1:]:
        out = out & set(s) if join == "and" else out | set(s)
    return out


def _spark(code: str, n: int = 20) -> list:
    """最近 n 根收盘（旧→新），迷你走势图用；读不到返回空列表."""
    try:
        df = _csv_manager.read_stock(code, nrows=n)
        if df.empty or "close" not in df:
            return []
        closes = [float(v) for v in df["close"].tolist()]
        dates = df["date"].astype(str).tolist()
        if len(dates) > 1 and dates[0] > dates[-1]:
            closes.reverse()
        return [round(v, 2) for v in closes]
    except Exception:
        return []


def _win_rate(track: dict, keys: list):
    """命中因子的样本外 5 日胜率，取最高者；无战绩返回 None."""
    best = None
    for k in keys:
        rec = (track.get("factors") or {}).get(k) or {}
        oos = ((rec.get("periods") or {}).get("ret_5") or {}).get("oos") or {}
        win = oos.get("win")
        if isinstance(win, (int, float)) and (best is None or win > best):
            best = win
    return best


@factor_bp.route("/api/factor-compose", methods=["GET"])
def api_factor_compose():
    """多因子组合选股：keys 用逗号分隔，join=and（全部满足）| or（任一满足）.

    稳定性约束：任一因子结果不可用就整体阻断，不返回部分交集。
    附加列：matched（命中了哪几个因子）、streak（连续命中天数，只用已缓存的
    历史交易日推算，缓存断档即停止计数）、win_rate（样本外 5 日胜率）、spark（20 日收盘）。
    """
    try:
        from strategy.factors import FACTOR_REGISTRY
        from utils.factor_scan import (
            _load_cache, get_factor_hits, recent_trade_dates,
        )
        from utils.market_filter import is_main_board, main_board_only

        keys = [k for k in request.args.get("keys", "").split(",") if k.strip()]
        keys = list(dict.fromkeys(k.strip() for k in keys))
        join = request.args.get("join", "and").strip()
        date = request.args.get("date", "").strip()
        if not keys or any(k not in FACTOR_REGISTRY for k in keys):
            return jsonify({"available": False, "reason": "缺少或未知的因子 keys"}), 400
        if join not in ("and", "or"):
            return jsonify({"available": False, "reason": "join 只能是 and 或 or"}), 400
        if date and not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
            return jsonify({"available": False, "reason": "日期格式不合法"}), 400

        result = get_factor_hits(_csv_manager, _stock_names(), keys, date=date)
        if not result.get("available"):
            return jsonify(result)
        buckets = result["results"]
        if any(k not in buckets for k in keys):
            return jsonify({"available": False, "reason": "至少一个因子结果不可用，已停止计算"})

        mb_only = main_board_only()
        per_key = {}
        for k in keys:
            hits = buckets[k].get("hits", [])
            if mb_only:
                hits = [h for h in hits if is_main_board(h.get("code", ""))]
            per_key[k] = {h["code"]: h for h in hits}
        codes = _compose_codes([set(v) for v in per_key.values()], join)

        # 连续命中：往前逐个已缓存交易日看该股是否仍在组合结果里
        trade_date = result["trade_date"]
        dates = [d for d in recent_trade_dates(_csv_manager, limit=40) if d < trade_date]
        history = []
        for d in dates:
            cache = _load_cache(d)
            if any(k not in cache for k in keys):
                break
            sets = [{h.get("code") for h in cache[k].get("hits", [])} for k in keys]
            history.append(_compose_codes(sets, join))

        def _streak(code):
            n = 1
            for prev in history:
                if code not in prev:
                    break
                n += 1
            return n

        ind = _industry_map()
        heat = _sector_heat()
        track = _track_record()
        hits = []
        for code in codes:
            matched = [k for k in keys if code in per_key[k]]
            base = per_key[matched[0]][code]
            industry = ind.get(code, "")
            hits.append({
                **base,
                "matched": matched,
                "industry": industry,
                "cap_yi": _cap_yi(code),
                "sector": heat.get(industry) or None,
                "streak": _streak(code),
                "streak_depth": len(history) + 1,
                "win_rate": _win_rate(track, matched),
                "spark": _spark(code),
            })
        hits.sort(key=lambda h: (-len(h["matched"]), -h["streak"],
                                 h.get("J") if h.get("J") is not None else 999, h["code"]))
        return jsonify({
            "available": True,
            "keys": keys,
            "join": join,
            "trade_date": trade_date,
            "hits": hits,
            "per_key_counts": {k: len(v) for k, v in per_key.items()},
            "total_scanned": max((buckets[k].get("total_scanned", 0) for k in keys), default=0),
        })
    except Exception as e:
        logger.error("因子组合查询失败: %s", e, exc_info=True)
        return jsonify({"available": False, "reason": "因子组合选股暂不可用"}), 500


@factor_bp.route("/api/factors", methods=["GET"])
def api_list_factors():
    """策略因子清单（分组+白话说明+当日命中数）+ 最近交易日列表.

    today_hits 直接读当日扫描缓存（预热后秒回；某因子未算过则为 None），
    主板过滤与 /api/factor-scan 同口径——概览徽标和详情列表数字必须一致。
    """
    try:
        from strategy.factors import FACTOR_REGISTRY, GROUP_ORDER, PLAIN_DESC, PRESETS
        from utils.factor_scan import _latest_data_date, _load_cache, recent_trade_dates
        from utils.market_filter import is_main_board, main_board_only

        trade_date = _latest_data_date(_csv_manager)
        cache = _load_cache(trade_date) if trade_date else {}
        mb_only = main_board_only()

        def _codes(key):
            bucket = cache.get(key)
            if not bucket:
                return None
            codes = {h.get("code", "") for h in bucket.get("hits", [])}
            return {c for c in codes if is_main_board(c)} if mb_only else codes

        def _today_hits(key):
            codes = _codes(key)
            return None if codes is None else len(codes)

        def _preset_hits(preset):
            """常用组合当日命中数：只读缓存，任一因子未算过则 None，不触发扫描."""
            sets = [_codes(k) for k in preset["keys"]]
            if any(s is None for s in sets):
                return None
            return len(_compose_codes(sets, preset["join"]))

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
        presets = [{**p, "today_hits": _preset_hits(p)} for p in PRESETS
                   if all(k in FACTOR_REGISTRY for k in p["keys"])]
        return jsonify({
            "factors": factors,
            "presets": presets,
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
        heat = _sector_heat()
        hits = [{
            **h,
            "industry": ind.get(h.get("code", ""), ""),
            "cap_yi": _cap_yi(h.get("code", "")),
            "sector": heat.get(ind.get(h.get("code", ""), "")) or None,
        } for h in hits]
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
