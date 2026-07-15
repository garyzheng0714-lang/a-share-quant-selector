"""量化今日一票 API - 今天买什么 / 明天盯什么

与 AI 荐票（/api/daily-pick）并存但完全独立：那个是模型主观发挥，
这个是 12 万条历史信号回测出来的规则，只认经双周期验证的短线因子。
"""
import json
import logging
import threading
import time
from pathlib import Path

from flask import Blueprint, jsonify

from utils.csv_manager import CSVManager

logger = logging.getLogger(__name__)

quant_pick_bp = Blueprint("quant_pick", __name__)

_csv_manager = CSVManager("data")
_CACHE_TTL = 3600
_names_box: dict = {}
_industry_box: dict = {}
_cap_box: dict = {}
_track_box: dict = {}
_pending_cache: dict = {}      # {trade_date: [...]}，预备队全市场扫一次约1分钟
_pending_lock = threading.Lock()


def _load_json_cached(path: str, box: dict) -> dict:
    now = time.time()
    if not box.get("data") or now - box.get("ts", 0) > _CACHE_TTL:
        f = Path(path)
        if f.exists():
            try:
                with open(f, encoding="utf-8") as fh:
                    box["data"] = json.load(fh)
            except Exception as e:
                logger.warning("%s 加载失败: %s", path, e)
        box["ts"] = now
    return box.get("data") or {}


def _names():
    return _load_json_cached("data/stock_names.json", _names_box)


def _industry():
    return _load_json_cached("data/stock_industry.json", _industry_box)


def _caps():
    return _load_json_cached("data/stock_market_cap.json", _cap_box)


def _track():
    return _load_json_cached("data/factor_track_record.json", _track_box)


def _cap_yi(code):
    v = _caps().get(code)
    if isinstance(v, dict):
        c = v.get("circ_mv") or v.get("total_mv")
        if isinstance(c, (int, float)) and c > 0:
            return round(c / 1e8, 1)
    return None


def _sector_heat() -> dict:
    """{行业: {score, delta3, stage, rank, total}}——全部 116 个行业的冷热.

    用 heat_map 而不是 hot/relay 榜：那两个榜只有前 8 名，冷门行业的票查不到分，
    界面上就是一片空白（用户看不出这只票顺不顺风）。

    注意：它**不参与**排序决策（板块热度对个股收益的增益未经回测验证，
    不能拿未验证的东西当买入依据）。只是把用户已经信任的那份情报贴到票旁边。
    """
    try:
        from utils.sector_rotation import get_sector_rotation
        s = get_sector_rotation(_csv_manager)
        if not s.get("available"):
            return {}
        return s.get("heat_map") or {}
    except Exception as e:
        logger.warning("板块热度读取失败: %s", e)
        return {}


def _enrich(rows):
    ind, heat = _industry(), _sector_heat()
    out = []
    for r in rows:
        code = r.get("code", "")
        industry = ind.get(code, "")
        out.append({**r, "industry": industry, "cap_yi": _cap_yi(code),
                    "sector": heat.get(industry)})
    return out


def _pending(trade_date):
    """预备队（全市场扫描，按日缓存）."""
    if trade_date in _pending_cache:
        return _pending_cache[trade_date]
    with _pending_lock:
        if trade_date in _pending_cache:
            return _pending_cache[trade_date]
        from utils.quant_pick import scan_pending
        rows = scan_pending(_csv_manager, _names(), trade_date)
        _pending_cache.clear()          # 只留当日
        _pending_cache[trade_date] = rows
        return rows


def _today_buy():
    """今天可以买的票（云阶命中，已做主板过滤和信息补全）。返回 (trade_date, rows) 或 (None, reason)."""
    from utils.factor_scan import get_factor_hits
    from utils.market_filter import is_main_board, main_board_only
    from utils.quant_pick import CORE_FACTOR

    scan = get_factor_hits(_csv_manager, _names(), [CORE_FACTOR])
    if not scan.get("available"):
        return None, scan.get("reason", "数据准备中")
    hits = scan["results"][CORE_FACTOR]["hits"]
    if main_board_only():
        hits = [h for h in hits if is_main_board(h.get("code", ""))]
    return scan["trade_date"], _enrich(hits)


@quant_pick_bp.route("/api/quant-comment", methods=["GET"])
def api_quant_comment():
    """AI 对今天选中的票的人话点评（慢，单独接口异步加载，不拖累 /api/quant-pick）."""
    try:
        from utils.daily_pick import generate_quant_comment

        trade_date, rows = _today_buy()
        if trade_date is None:
            return jsonify({"available": False, "reason": rows})
        return jsonify(generate_quant_comment(trade_date, rows))
    except Exception as e:
        logger.error("AI 点评失败: %s", e, exc_info=True)
        return jsonify({"available": False, "reason": "点评暂不可用"}), 500


@quant_pick_bp.route("/api/quant-pick", methods=["GET"])
def api_quant_pick():
    """兼容旧客户端；启用分层决策后只暴露通过四层闸门的可执行标的。"""
    try:
        from utils.decision_config import get_decision_config
        if get_decision_config()["enabled"]:
            from utils.decision_ledger import get_latest_decision
            from utils.data_freshness import local_data_status
            from utils.hierarchical_decision import run_close_decision

            freshness = local_data_status()
            if not freshness["fresh"]:
                return jsonify({
                    "available": False, "reason": "stale_market_data", "freshness": freshness,
                }), 503
            decision = get_latest_decision()
            if not decision or decision.get("trade_date") != freshness["local_date"]:
                decision = run_close_decision()
            if decision and decision.get("candidates") is not None:
                rows = []
                for item in decision["candidates"]:
                    base = item.get("baseline") or {}
                    rows.append({
                        "code": item["code"], "name": item.get("name"),
                        "industry": item.get("industry") or "", "sector": item.get("sector"),
                        "close": base.get("close") or 0, "J": base.get("J"),
                        "RSI": base.get("RSI"), "cap_yi": base.get("cap_yi"),
                        "action": item.get("action"), "reason_codes": item.get("reason_codes", []),
                    })
                return jsonify({
                    "available": True, "trade_date": decision["trade_date"],
                    "today_buy": [row for row in rows if row["action"] == "buy"],
                    "tomorrow_watch": [], "decision": decision,
                    "honest_note": "市场先于板块、板块先于个股；任一闸门未通过就不推荐。",
                })
        from utils.quant_pick import CORE_FACTOR

        trade_date, hits = _today_buy()
        if trade_date is None:
            return jsonify({"available": False, "reason": hits})

        track = _track().get("factors", {}).get(CORE_FACTOR, {})
        return jsonify({
            "available": True,
            "trade_date": trade_date,
            "core_factor": {
                "key": CORE_FACTOR,
                "name": "云阶",
                "plain": "第一波大涨 → 缩量横盘不破位 → 再次突破前高",
                "why": "28个公式里唯一在两段互不重叠的历史中、持有1天和5天都跑赢大盘的",
                "track": track.get("periods", {}).get("ret_5"),
            },
            "today_buy": hits,               # _today_buy() 已做主板过滤 + 信息补全
            "tomorrow_watch": _enrich(_pending(trade_date)),
            "honest_note": (
                "命中多只时无法区分优劣——J值/RSI/放量/距前高/乖离/涨幅/共振数 "
                "7个维度全部试过，样本外均失效。建议等权分散，或结合板块风向自行取舍。"
            ),
        })
    except Exception as e:
        logger.error("量化选票失败: %s", e, exc_info=True)
        return jsonify({"available": False, "reason": "量化选票暂不可用"}), 500
