"""旧客户端量化候选兼容 API；主入口统一使用版本化策略决策。"""
import json
import logging
import threading
import time
from pathlib import Path

from flask import Blueprint, jsonify

from utils.csv_manager import CSVManager
from utils.decision_config import get_decision_config

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

    它不参与版本化分层决策。旧兼容接口 /api/quant-pick 会用当前综合热度分做
    展示排序，但该运行时分数尚未完成同口径治理验证，不能当成买入依据。
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
    from utils.cloud_stair_stock_history import stock_history

    ind, heat = _industry(), _sector_heat()
    out = []
    for r in rows:
        code = r.get("code", "")
        industry = ind.get(code, "")
        out.append({
            **r,
            "industry": industry,
            "cap_yi": _cap_yi(code),
            "sector": heat.get(industry),
            "history": stock_history(code),
        })
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
    """云阶兼容候选：主板过滤、信息补全，并按板块综合热度展示排序。

    tools/sector_rank_research.py 支持的是信号日行业平均涨幅 ind_ret1 这一代理量；
    当前 sector_rotation 综合分并非同一特征，因此这里只能提供展示顺序。
    """
    from utils.factor_scan import get_factor_hits
    from utils.market_filter import is_main_board, main_board_only
    from utils.quant_pick import CORE_FACTOR

    scan = get_factor_hits(_csv_manager, _names(), [CORE_FACTOR])
    if not scan.get("available"):
        return None, scan.get("reason", "数据准备中")
    hits = scan["results"][CORE_FACTOR]["hits"]
    if main_board_only():
        hits = [h for h in hits if is_main_board(h.get("code", ""))]
    rows = _enrich(hits)

    def _sector_key(r):
        s = r.get("sector") or {}
        return (s.get("score") if s.get("score") is not None else -1.0,
                s.get("relative_strength") if s.get("relative_strength") is not None else -1.0)
    rows.sort(key=_sector_key, reverse=True)
    for i, r in enumerate(rows, 1):
        s = r.get("sector") or {}
        r["rank"] = i
        r["rank_total"] = len(rows)
        parts = ["云阶：回到前高附近（第一波大涨→缩量横盘→收盘达到前峰至少95%）"]
        if s:
            score = s.get("score")
            if score is not None:
                parts.append(f"板块热度 {score:.0f} 分（全市场第 {s.get('rank')}/{s.get('total')} 名）")
            if s.get("delta3") is not None and s["delta3"] >= 8:
                parts.append(f"3日升温 +{s['delta3']:.0f}")
            elif s.get("delta3") is not None and s["delta3"] <= -8:
                parts.append(f"3日降温 {s['delta3']:.0f}")
            if s.get("stage"):
                parts.append(s["stage"])
        r["reason"] = "；".join(parts)
    return scan["trade_date"], rows


@quant_pick_bp.route("/api/quant-comment", methods=["GET"])
def api_quant_comment():
    """AI 只解释当前版本化决策已通过复核的候选，不自主选票."""
    try:
        from utils.daily_pick import generate_quant_comment
        from utils.data_freshness import local_data_status
        from utils.decision_ledger import get_latest_decision
        from utils.decision_versions import strategy_version
        from utils.hierarchical_decision import run_close_decision

        freshness = local_data_status()
        if not freshness["fresh"]:
            return jsonify({
                "available": False, "reason": "stale_market_data", "freshness": freshness,
            })
        decision = get_latest_decision("close")
        if (
            not decision
            or decision.get("trade_date") != freshness["local_date"]
            or decision.get("strategy_version") != strategy_version()
        ):
            decision = run_close_decision()
        if not decision or not decision.get("available", True):
            return jsonify({"available": False, "reason": "decision_not_ready"})

        rows = []
        for item in decision.get("candidates", []):
            if item.get("action") != "buy":
                continue
            base = item.get("baseline") or {}
            rows.append({
                "code": item["code"], "name": item.get("name"),
                "industry": item.get("industry"), "sector": item.get("sector"),
                "close": base.get("close"), "J": base.get("J"), "RSI": base.get("RSI"),
                "weekly": base.get("weekly"),
            })
        if not rows:
            return jsonify({"available": False, "reason": "no_approved_candidates"})
        return jsonify(generate_quant_comment(
            decision["trade_date"], rows, decision_run_id=decision.get("run_id"),
        ))
    except Exception as e:
        logger.error("AI 点评失败: %s", e, exc_info=True)
        return jsonify({"available": False, "reason": "点评暂不可用"}), 500


@quant_pick_bp.route("/api/quant-pick", methods=["GET"])
def api_quant_pick():
    """沿用旧响应形状的研究候选（云阶 + 板块综合热度展示顺序）。

    today_buy 当前承载全部云阶命中，已不保持旧版“已批准买入”的字段语义。
    分层决策启用时，其结果作为 decision 参考字段附带；权威动作仍以版本化
    decision 为准。
    """
    try:
        from utils.quant_pick import CORE_FACTOR

        # 分层决策结果（参考字段；获取失败不影响云阶兼容候选）
        decision = None
        if get_decision_config()["enabled"]:
            try:
                from utils.decision_ledger import get_latest_decision
                from utils.data_freshness import local_data_status
                from utils.hierarchical_decision import run_close_decision

                freshness = local_data_status()
                decision = get_latest_decision()
                if freshness["fresh"] and (
                    not decision or decision.get("trade_date") != freshness["local_date"]
                ):
                    decision = run_close_decision()
            except Exception:
                decision = None

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
                "plain": "第一波大涨 → 缩量横盘不破位 → 收盘回到前峰至少95%",
                "why": "28个公式里唯一在两段互不重叠的历史中、持有1天和5天都跑赢大盘的",
                "track": track.get("periods", {}).get("ret_5"),
            },
            "today_buy": hits,               # 旧字段名：云阶候选，按板块热度展示排序
            "tomorrow_watch": _enrich(_pending(trade_date)),
            "decision": decision,
            "honest_note": (
                "候选按当前板块综合热度展示排序。历史分段研究只支持信号日行业强弱"
                "这一代理特征；当前综合分尚未完成同口径 point-in-time / purged walk-forward 验证。"
                "today_buy 只是沿用的字段名，该顺序不是版本化 buy 动作；旧客户端仍可能"
                "把它显示为今日推荐，完成字段迁移前不可发布，也不构成买卖建议。"
            ),
        })
    except Exception as e:
        logger.error("量化选票失败: %s", e, exc_info=True)
        return jsonify({"available": False, "reason": "量化选票暂不可用"}), 500
