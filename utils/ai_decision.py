"""受控 AI 决策记录：解释、放弃或影子排序，不改变量化动作。"""
from __future__ import annotations

import hashlib
from datetime import datetime
from zoneinfo import ZoneInfo

import orjson

from utils.decision_ledger import save_ai_decision_run


TZ = ZoneInfo("Asia/Shanghai")
PROMPT_VERSION = "quant-explainer-v1"


def _input_hash(decision: dict | None, candidates: list[dict]) -> str:
    payload = {
        "decision_run_id": (decision or {}).get("run_id"),
        "strategy_version": (decision or {}).get("strategy_version"),
        "model_version": (decision or {}).get("model_version"),
        "candidates": [
            {"code": row.get("code"), "action": row.get("action"),
             "reason_codes": row.get("reason_codes", [])}
            for row in candidates
        ],
    }
    return hashlib.sha256(orjson.dumps(payload, option=orjson.OPT_SORT_KEYS)).hexdigest()


def run_ai_decision(decision: dict | None) -> dict:
    """为一次量化决策生成可见状态；没有合格池也必须留下原因。"""
    now = datetime.now(TZ).isoformat(timespec="seconds")
    decision = decision or {}
    trade_date = decision.get("trade_date") or now[:10]
    all_candidates = decision.get("candidates") or []
    approved = [row for row in all_candidates if row.get("action") == "buy"]
    base = {
        "trade_date": trade_date,
        "decision_run_id": decision.get("run_id"),
        "as_of": now,
        "role": "explanation",
        "prompt_version": PROMPT_VERSION,
        "input_hash": _input_hash(decision, all_candidates),
    }

    if not decision.get("run_id"):
        run = {**base, "status": "not_called", "reason_codes": ["decision_not_ready"]}
    elif not approved:
        run = {**base, "status": "not_called", "reason_codes": ["no_approved_candidates"]}
    else:
        from utils.daily_pick import generate_quant_comment, get_api_key

        if not get_api_key():
            run = {**base, "status": "not_called", "reason_codes": ["llm_unconfigured"]}
        else:
            stocks = []
            for item in approved:
                baseline = item.get("baseline") or {}
                stocks.append({
                    "code": item["code"], "name": item.get("name"),
                    "industry": item.get("industry"), "sector": item.get("sector"),
                    "close": baseline.get("close"), "J": baseline.get("J"),
                    "RSI": baseline.get("RSI"), "weekly": baseline.get("weekly"),
                })
            result = generate_quant_comment(
                trade_date, stocks, decision_run_id=decision.get("run_id"),
            )
            if result.get("available"):
                run = {
                    **base, "status": "explained", "model": result.get("model"),
                    "payload": result,
                }
            else:
                run = {
                    **base, "status": "failed", "payload": result,
                    "reason_codes": ["llm_call_failed"],
                }
    run["ai_run_id"] = save_ai_decision_run(run)
    return {"available": run["status"] in {"explained", "shadow_ranked"}, **run}
