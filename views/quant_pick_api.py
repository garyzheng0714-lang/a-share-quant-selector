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
