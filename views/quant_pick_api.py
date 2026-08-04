"""旧客户端的量化候选兼容 API。

这两个 GET 端点只读取 worker 已经落账的当前决策/点评，不执行扫描、
不调用 LLM，也不写入数据库。
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify

logger = logging.getLogger(__name__)
quant_pick_bp = Blueprint("quant_pick", __name__)


def _current_close_decision() -> tuple[dict | None, dict, str | None]:
    """读取与当前不可变快照严格绑定的收盘决策。"""
    from utils.data_freshness import local_data_status
    from utils.decision_ledger import get_latest_decision
    from utils.decision_versions import strategy_version

    freshness = local_data_status()
    if not freshness.get("fresh"):
        return None, freshness, "stale_market_data"

    snapshot_id = freshness.get("snapshot_id")
    decision = get_latest_decision("close")
    valid = bool(
        snapshot_id
        and decision
        and decision.get("trade_date") == freshness.get("local_date")
        and decision.get("trade_date") == freshness.get("expected_date")
        and decision.get("strategy_version") == strategy_version()
        and decision.get("data_version") == f"snapshot-{snapshot_id}"
        and (decision.get("market") or {}).get("snapshot_id") == snapshot_id
    )
    return (
        (decision, freshness, None)
        if valid
        else (None, freshness, "decision_not_ready")
    )


@quant_pick_bp.route("/api/quant-comment", methods=["GET"])
def api_quant_comment():
    """Get 已由 worker 生成且与当前决策绑定的 AI 解释。"""
    try:
        from utils.daily_pick import get_quant_comment

        decision, freshness, reason = _current_close_decision()
        if decision is None:
            return jsonify(
                {
                    "available": False,
                    "reason": reason,
                    "freshness": freshness,
                }
            ), 503

        comment = get_quant_comment(decision["trade_date"])
        if not comment or comment.get("decision_run_id") != decision.get("run_id"):
            return jsonify(
                {
                    "available": False,
                    "reason": "comment_not_ready",
                    "decision_run_id": decision.get("run_id"),
                }
            ), 404
        return jsonify({"available": True, "cached": True, **comment})
    except Exception as exc:
        logger.error("读取 AI 点评失败: %s", exc, exc_info=True)
        return jsonify({"available": False, "reason": "comment_unavailable"}), 500


@quant_pick_bp.route("/api/quant-pick", methods=["GET"])
def api_quant_pick():
    """兼容旧客户端；只暴露当前版本化收盘决策。"""
    try:
        decision, freshness, reason = _current_close_decision()
        if decision is None:
            return jsonify(
                {
                    "available": False,
                    "reason": reason,
                    "freshness": freshness,
                }
            ), 503

        rows = []
        for item in decision.get("candidates") or []:
            base = item.get("baseline") or {}
            rows.append(
                {
                    "code": item["code"],
                    "name": item.get("name"),
                    "industry": item.get("industry") or "",
                    "sector": item.get("sector"),
                    "close": base.get("close"),
                    "J": base.get("J"),
                    "RSI": base.get("RSI"),
                    "cap_yi": base.get("cap_yi"),
                    "action": item.get("action"),
                    "reason_codes": item.get("reason_codes", []),
                }
            )
        return jsonify(
            {
                "available": True,
                "trade_date": decision["trade_date"],
                "is_stale": False,
                "freshness": freshness,
                "today_buy": [row for row in rows if row["action"] == "buy"],
                "tomorrow_watch": [],
                "decision": decision,
                "honest_note": "只读取已落账、与当前快照绑定的版本化决策。",
            }
        )
    except Exception as exc:
        logger.error("读取量化决策失败: %s", exc, exc_info=True)
        return jsonify({"available": False, "reason": "decision_unavailable"}), 500


@quant_pick_bp.route("/api/recommend", methods=["GET"])
def api_recommend():
    """今日推荐（云阶 + 板块热度排序）——只读 worker 已预热的因子缓存。

    信息形态：今天推荐几只、买哪只、排名、为什么。
    排名依据 = 板块热度：2026-08-04 双周期研究（tools/sector_rank_research.py）
    证明信号日板块强弱是唯一能在样本外区分云阶命中票 T+5 收益的维度。
    """
    try:
        from utils.csv_manager import CSVManager
        from utils.factor_scan import read_cached_factor_hits
        from utils.market_filter import is_main_board, main_board_only
        from utils.quant_pick import CORE_FACTOR

        manager = CSVManager("data", writable=False)
        if manager.snapshot_id is None:
            return jsonify({"available": False, "reason": "snapshot_unavailable"}), 503

        result = read_cached_factor_hits(manager, [CORE_FACTOR])
        if not result.get("available"):
            return jsonify(
                {
                    "available": False,
                    "reason": result.get("reason", "factor_cache_unavailable"),
                }
            ), 503

        hits = result["results"][CORE_FACTOR]["hits"]
        if main_board_only():
            hits = [h for h in hits if is_main_board(h.get("code", ""))]

        # 行业 + 板块热度（只读展示）
        ind = _load_industry_map(manager)
        heat = _load_sector_heat(manager)
        rows = []
        for h in hits:
            industry = ind.get(h.get("code", ""), "")
            rows.append(
                {
                    **h,
                    "industry": industry,
                    "sector": heat.get(industry) or None,
                }
            )

        def _sector_key(r):
            s = r.get("sector") or {}
            return (
                s.get("score") if s.get("score") is not None else -1.0,
                s.get("relative_strength")
                if s.get("relative_strength") is not None
                else -1.0,
            )

        rows.sort(key=_sector_key, reverse=True)
        for i, r in enumerate(rows, 1):
            s = r.get("sector") or {}
            r["rank"] = i
            r["rank_total"] = len(rows)
            parts = ["云阶：突破确认（第一波大涨→缩量横盘→再次突破前高）"]
            if s:
                score = s.get("score")
                if score is not None:
                    parts.append(
                        f"板块热度 {score:.0f} 分（全市场第 {s.get('rank')}/{s.get('total')} 名）"
                    )
                if s.get("delta3") is not None and s["delta3"] >= 8:
                    parts.append(f"3日升温 +{s['delta3']:.0f}")
                elif s.get("delta3") is not None and s["delta3"] <= -8:
                    parts.append(f"3日降温 {s['delta3']:.0f}")
                if s.get("stage"):
                    parts.append(s["stage"])
            r["reason"] = "；".join(parts)

        return jsonify(
            {
                "available": True,
                "trade_date": result["trade_date"],
                "core_factor": {
                    "key": CORE_FACTOR,
                    "name": "云阶",
                    "plain": "第一波大涨 → 缩量横盘不破位 → 再次突破前高",
                    "why": "28个公式里唯一在两段互不重叠的历史中、持有1天和5天都跑赢大盘的",
                },
                "today_buy": rows,
                "honest_note": (
                    "按板块热度排序：信号日板块强弱是唯一通过双周期样本外验证的排序维度"
                    "（2025-12~2026-06，板块当日涨幅/热度越高，T+5 胜率与收益越好）。"
                    "排名只呈现事实，不做买卖建议。"
                ),
            }
        )
    except Exception as exc:
        logger.error("今日推荐失败: %s", exc, exc_info=True)
        return jsonify({"available": False, "reason": "recommend_unavailable"}), 500


def _load_industry_map(manager) -> dict:
    from utils.market_snapshot import read_snapshot_metadata

    value, _snapshot_id = read_snapshot_metadata(
        "stock_industry.json", manager.base_data_dir, snapshot_id=manager.snapshot_id
    )
    return value if isinstance(value, dict) else {}


def _load_sector_heat(manager) -> dict:
    try:
        from utils.sector_rotation import get_sector_rotation

        s = get_sector_rotation(manager)
        if not s.get("available"):
            return {}
        return s.get("heat_map") or {}
    except Exception as exc:
        logger.warning("板块热度读取失败: %s", exc)
        return {}
