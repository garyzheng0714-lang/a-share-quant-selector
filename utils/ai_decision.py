"""受控 AI 决策记录：解释、放弃或影子排序，不改变量化动作。"""

from __future__ import annotations

import hashlib
from datetime import datetime
from zoneinfo import ZoneInfo

import orjson

from utils.decision_ledger import save_ai_decision_run


TZ = ZoneInfo("Asia/Shanghai")
PROMPT_VERSION = "cloud-stair-explainer-v6"


def _input_hash(
    decision: dict | None,
    candidates: list[dict],
    intelligence: dict | None = None,
) -> str:
    payload = {
        "decision_run_id": (decision or {}).get("run_id"),
        "strategy_version": (decision or {}).get("strategy_version"),
        "model_version": (decision or {}).get("model_version"),
        "data_version": (decision or {}).get("data_version"),
        "snapshot_id": ((decision or {}).get("market") or {}).get("snapshot_id"),
        "intelligence_hash": (intelligence or {}).get("content_hash"),
        "candidates": [
            {
                "code": row.get("code"),
                "action": row.get("action"),
                "reason_codes": row.get("reason_codes", []),
            }
            for row in candidates
        ],
    }
    return hashlib.sha256(
        orjson.dumps(payload, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()


def run_ai_decision(decision: dict | None, *, csv_manager=None) -> dict:
    """为当日云阶候选生成 AI 解释；没有信号也必须留下原因。"""
    now = datetime.now(TZ).isoformat(timespec="seconds")
    decision = decision or {}
    trade_date = decision.get("trade_date") or now[:10]
    cloud_result = None
    cloud_candidates = []
    intelligence = {
        "available": False,
        "reason": "cloud_stair_intelligence_not_ready",
        "candidates": [],
    }
    decision_ready = bool(decision.get("run_id"))
    snapshot_pinned = bool(
        csv_manager is not None
        and getattr(csv_manager, "snapshot_id", None)
        == (decision.get("market") or {}).get("snapshot_id")
    )
    if decision_ready and snapshot_pinned:
        from utils.cloud_stair_decision import load_cloud_stair_decision

        cloud_result = load_cloud_stair_decision(csv_manager)
        if cloud_result.get("available"):
            decision_by_code = {
                str(row.get("code") or ""): row
                for row in (decision.get("candidates") or [])
            }
            cloud_candidates = [
                {
                    **row,
                    "action": (
                        decision_by_code.get(str(row.get("code") or ""), {}).get(
                            "action"
                        )
                        if decision_by_code.get(str(row.get("code") or ""), {}).get(
                            "action"
                        )
                        in {"buy", "observe", "avoid", "none"}
                        else None
                    ),
                    "decision_evaluated": str(row.get("code") or "")
                    in decision_by_code,
                    "action_source": (
                        "canonical_candidate"
                        if str(row.get("code") or "") in decision_by_code
                        else "not_evaluated"
                    ),
                }
                for row in (cloud_result.get("candidates") or [])
            ]
            try:
                from utils.cloud_stair_intelligence import (
                    build_cloud_stair_intelligence,
                )

                intelligence = build_cloud_stair_intelligence(
                    cloud_candidates,
                    trade_date=str(cloud_result.get("trade_date") or trade_date),
                    as_of=now,
                    csv_manager=csv_manager,
                )
            except Exception as exc:
                intelligence = {
                    "available": False,
                    "reason": "cloud_stair_intelligence_failed",
                    "error_type": type(exc).__name__,
                    "candidates": [],
                }
    intelligence_by_code = {
        str(row.get("code") or ""): row
        for row in (intelligence.get("candidates") or [])
    }
    base = {
        "trade_date": trade_date,
        "decision_run_id": decision.get("run_id"),
        "as_of": now,
        "role": "explanation",
        "prompt_version": PROMPT_VERSION,
        "input_hash": _input_hash(decision, cloud_candidates, intelligence),
    }

    if not decision_ready:
        run = {
            **base,
            "status": "not_called",
            "payload": {"intelligence": intelligence},
            "reason_codes": ["decision_not_ready"],
        }
    elif not snapshot_pinned:
        run = {
            **base,
            "status": "not_called",
            "payload": {"intelligence": intelligence},
            "reason_codes": ["decision_snapshot_not_pinned"],
        }
    elif not cloud_result or not cloud_result.get("available"):
        run = {
            **base,
            "status": "not_called",
            "payload": {"intelligence": intelligence},
            "reason_codes": [
                str((cloud_result or {}).get("reason") or "cloud_stair_not_ready")
            ],
        }
    elif not cloud_candidates:
        run = {
            **base,
            "status": "not_called",
            "payload": {"intelligence": intelligence},
            "reason_codes": ["no_cloud_stair_signals"],
        }
    else:
        from utils.daily_pick import generate_quant_comment, get_api_key

        explainable_candidates = [
            item for item in cloud_candidates if item.get("decision_evaluated") is True
        ]
        if not explainable_candidates:
            run = {
                **base,
                "status": "shadow_ranked",
                "payload": {"intelligence": intelligence},
                "reason_codes": ["no_canonical_cloud_candidates"],
            }
        elif not get_api_key():
            run = {
                **base,
                "status": "not_called",
                "payload": {"intelligence": intelligence},
                "reason_codes": ["llm_unconfigured"],
            }
        else:
            stocks = []
            for item in explainable_candidates:
                stocks.append(
                    {
                        "code": item["code"],
                        "name": item.get("name"),
                        "industry": item.get("industry"),
                        "sector": item.get("sector"),
                        "close": item.get("close"),
                        "J": item.get("J"),
                        "RSI": item.get("RSI"),
                        "pct_change": item.get("pct_change"),
                        "peak_date": item.get("peak_date"),
                        "wave_gain_pct": item.get("wave_gain_pct"),
                        "action": item.get("action"),
                        "decision_evaluated": item.get("decision_evaluated") is True,
                        "action_source": item.get("action_source"),
                        "intelligence": intelligence_by_code.get(str(item["code"]))
                        or {},
                    }
                )
            result = generate_quant_comment(
                trade_date,
                stocks,
                decision_run_id=decision.get("run_id"),
                csv_manager=csv_manager,
            )
            if result.get("available"):
                run = {
                    **base,
                    "status": "explained",
                    "model": result.get("model"),
                    "payload": {
                        "intelligence": intelligence,
                        "comment": result,
                    },
                }
            else:
                failure_reason = str(result.get("reason") or "llm_call_failed")
                run = {
                    **base,
                    "status": "failed",
                    "payload": {
                        "intelligence": intelligence,
                        "comment": result,
                    },
                    "reason_codes": [failure_reason],
                }
    run["ai_run_id"] = save_ai_decision_run(run)
    return {"available": run["status"] in {"explained", "shadow_ranked"}, **run}
