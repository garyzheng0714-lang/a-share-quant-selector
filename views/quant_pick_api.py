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
        from utils.daily_pick import COMMENT_PROMPT_VERSION, get_quant_comment

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
        if (
            not comment
            or comment.get("decision_run_id") != decision.get("run_id")
            or comment.get("prompt_version") != COMMENT_PROMPT_VERSION
        ):
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
    """云阶唯一决策首屏：信号、行业、买入结论与已固化 AI 解释。"""
    try:
        from utils.ai_decision import PROMPT_VERSION
        from utils.cloud_stair_decision import load_cloud_stair_decision
        from utils.cloud_stair_intelligence import METHODOLOGY
        from utils.csv_manager import CSVManager
        from utils.daily_pick import COMMENT_PROMPT_VERSION, get_quant_comment
        from utils.decision_ledger import get_latest_ai_decision_run

        manager = CSVManager("data", writable=False)
        result = load_cloud_stair_decision(manager)
        if not result.get("available"):
            return jsonify(result), 503

        decision, freshness, decision_reason = _current_close_decision()
        comment = None
        ai_run = None
        if decision:
            stored_comment = get_quant_comment(str(result.get("trade_date") or ""))
            if (
                stored_comment
                and stored_comment.get("decision_run_id") == decision.get("run_id")
                and stored_comment.get("prompt_version") == COMMENT_PROMPT_VERSION
            ):
                comment = stored_comment
            latest_ai = get_latest_ai_decision_run()
            if (
                latest_ai
                and latest_ai.get("decision_run_id") == decision.get("run_id")
                and latest_ai.get("prompt_version") == PROMPT_VERSION
            ):
                ai_run = latest_ai

        by_code = (comment or {}).get("by_code") or {}
        ai_payload = (ai_run or {}).get("payload") or {}
        intelligence = ai_payload.get("intelligence") or {}
        intelligence_valid = bool(
            intelligence.get("available")
            and intelligence.get("methodology") == METHODOLOGY
            and intelligence.get("trade_date") == result.get("trade_date")
            and intelligence.get("snapshot_id") == result.get("snapshot_id")
        )
        intelligence_by_code = {
            str(item.get("code") or ""): item
            for item in (intelligence.get("candidates") if intelligence_valid else [])
        }
        decision_by_code = {
            str(item.get("code") or ""): item
            for item in ((decision or {}).get("candidates") or [])
        }
        rows = []
        for candidate in result.get("candidates") or []:
            code = str(candidate.get("code") or "")
            decision_row = decision_by_code.get(code) or {}
            candidate_intelligence = intelligence_by_code.get(code) or {}
            rows.append(
                {
                    **candidate,
                    **{
                        key: candidate_intelligence.get(key)
                        for key in (
                            "priority_score",
                            "priority_rank",
                            "rank_label",
                            "structure_score",
                            "structure_detail",
                            "sector_score",
                            "evidence_grade",
                        )
                        if candidate_intelligence.get(key) is not None
                    },
                    "ai_analysis": by_code.get(code),
                    "decision_evidence": {
                        "reason_codes": decision_row.get("reason_codes") or [],
                        "explanation": decision_row.get("explanation"),
                        "baseline": decision_row.get("baseline") or {},
                    },
                }
            )
        if intelligence_valid:
            rows.sort(
                key=lambda row: (
                    int(row.get("priority_rank") or 10_000),
                    str(row.get("code") or ""),
                )
            )
        for index, row in enumerate(rows, 1):
            row["rank"] = index
            row["rank_total"] = len(rows)

        market_context = (
            intelligence.get("market_context") if intelligence_valid else None
        )
        if not market_context:
            from utils.cloud_stair_intelligence import build_market_context

            market_context = build_market_context(manager)

        ai_status = (ai_run or {}).get("status") or "not_called"
        ai_reasons = (ai_run or {}).get("reason_codes") or []
        if decision is None:
            ai_reasons = [decision_reason or "decision_not_ready"]
        elif comment:
            ai_status = "explained"

        return jsonify(
            {
                **result,
                "candidates": rows,
                # 保留旧字段，让已打开的旧客户端不会突然空白。
                "today_buy": rows,
                "honest_note": result.get("ranking_note"),
                "freshness": freshness,
                "market_context": market_context,
                "intelligence": {
                    "available": intelligence_valid,
                    "combination_codes": (
                        intelligence.get("combination_codes")
                        if intelligence_valid
                        else []
                    ),
                    "source_refs": (
                        intelligence.get("source_refs") if intelligence_valid else []
                    ),
                    "ranking_note": (
                        intelligence.get("ranking_note")
                        if intelligence_valid
                        else "云阶证据尚未生成，当前沿用板块热度排序。"
                    ),
                },
                "decision_run_id": (decision or {}).get("run_id"),
                "ai": {
                    "available": bool(comment),
                    "status": ai_status,
                    "reason_codes": ai_reasons,
                    "model": (comment or {}).get("model")
                    or (ai_run or {}).get("model"),
                    "created_at": (comment or {}).get("created_at")
                    or (ai_run or {}).get("created_at"),
                    "market_note": (comment or {}).get("market_note"),
                },
            }
        )
    except Exception as exc:
        logger.error("今日推荐失败: %s", exc, exc_info=True)
        return jsonify({"available": False, "reason": "recommend_unavailable"}), 500
