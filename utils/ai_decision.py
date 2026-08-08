"""受控 AI 决策记录：解释、放弃或影子排序，不改变量化动作。"""

from __future__ import annotations

import hashlib
from datetime import datetime
from zoneinfo import ZoneInfo

import orjson

from utils.decision_ledger import save_ai_decision_run


TZ = ZoneInfo("Asia/Shanghai")
PROMPT_VERSION = "cloud-stair-explainer-v1"


def _input_hash(decision: dict | None, candidates: list[dict]) -> str:
    payload = {
        "decision_run_id": (decision or {}).get("run_id"),
        "strategy_version": (decision or {}).get("strategy_version"),
        "model_version": (decision or {}).get("model_version"),
        "data_version": (decision or {}).get("data_version"),
        "snapshot_id": ((decision or {}).get("market") or {}).get("snapshot_id"),
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
            cloud_candidates = cloud_result.get("candidates") or []
    base = {
        "trade_date": trade_date,
        "decision_run_id": decision.get("run_id"),
        "as_of": now,
        "role": "explanation",
        "prompt_version": PROMPT_VERSION,
        "input_hash": _input_hash(decision, cloud_candidates),
    }

    if not decision_ready:
        run = {**base, "status": "not_called", "reason_codes": ["decision_not_ready"]}
    elif not snapshot_pinned:
        run = {
            **base,
            "status": "not_called",
            "reason_codes": ["decision_snapshot_not_pinned"],
        }
    elif not cloud_result or not cloud_result.get("available"):
        run = {
            **base,
            "status": "not_called",
            "reason_codes": [
                str((cloud_result or {}).get("reason") or "cloud_stair_not_ready")
            ],
        }
    elif not cloud_candidates:
        run = {
            **base,
            "status": "not_called",
            "reason_codes": ["no_cloud_stair_signals"],
        }
    else:
        from utils.daily_pick import generate_quant_comment, get_api_key

        if not get_api_key():
            run = {**base, "status": "not_called", "reason_codes": ["llm_unconfigured"]}
        else:
            stocks = []
            for item in cloud_candidates:
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
                    "payload": result,
                }
            else:
                run = {
                    **base,
                    "status": "failed",
                    "payload": result,
                    "reason_codes": ["llm_call_failed"],
                }
    run["ai_run_id"] = save_ai_decision_run(run)
    return {"available": run["status"] in {"explained", "shadow_ranked"}, **run}
