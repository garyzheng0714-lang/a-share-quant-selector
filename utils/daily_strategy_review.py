"""每日全策略复盘的 worker 编排层。"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import orjson

from utils.decision_ledger import (
    get_latest_strategy_review_run,
    get_previous_strategy_review_run,
    register_model,
    save_strategy_review_run,
)
from utils.strategy_intelligence import build_strategy_intelligence
from utils.strategy_review_ai import PROMPT_VERSION, run_strategy_review_ai


TZ = ZoneInfo("Asia/Shanghai")
REVIEW_PIPELINE_SCHEMA_VERSION = "strategy-review-pipeline-v2"


def review_pipeline_version() -> str:
    """复盘有自己的版本，不与正式买卖策略版本混在一起。"""
    root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    digest.update(REVIEW_PIPELINE_SCHEMA_VERSION.encode())
    digest.update(PROMPT_VERSION.encode())
    for name in (
        "daily_strategy_review.py",
        "strategy_intelligence.py",
        "strategy_review_ai.py",
        "factor_evidence.py",
    ):
        path = root / name
        digest.update(name.encode())
        digest.update(path.read_bytes())
    return f"{REVIEW_PIPELINE_SCHEMA_VERSION}-{digest.hexdigest()[:16]}"


def strategy_review_is_current(
    review: dict | None,
    decision: dict | None,
    snapshot_id: str,
) -> bool:
    decision = decision or {}
    report = (review or {}).get("report") or {}
    return bool(
        review
        and decision.get("run_id")
        and review.get("trade_date") == decision.get("trade_date")
        and review.get("snapshot_id") == snapshot_id
        and review.get("decision_run_id") == decision.get("run_id")
        and review.get("model_version") == review_pipeline_version()
        and review.get("ai_prompt_version") == PROMPT_VERSION
        and report.get("review_pipeline_version") == review_pipeline_version()
    )


def _content_hash(report: dict) -> str:
    stable = {key: value for key, value in report.items() if key != "generated_at"}
    return hashlib.sha256(orjson.dumps(stable, option=orjson.OPT_SORT_KEYS)).hexdigest()


def materialize_daily_strategy_review(
    csv_manager,
    decision: dict | None,
    *,
    task_id: str | None = None,
    execution_token: str | None = None,
) -> dict:
    """生成确定性评分、受控 AI 结论并一次性落账。"""
    decision = decision or {}
    trade_date = str(decision.get("trade_date") or "")
    snapshot_id = str(getattr(csv_manager, "snapshot_id", "") or "")
    decision_snapshot = str((decision.get("market") or {}).get("snapshot_id") or "")
    if not trade_date or len(snapshot_id) != 64:
        return {"available": False, "reason": "pinned_snapshot_required"}
    if decision_snapshot != snapshot_id:
        return {"available": False, "reason": "decision_snapshot_mismatch"}
    decision_run_id = str(decision.get("run_id") or "")
    if not decision_run_id:
        return {"available": False, "reason": "decision_run_required"}

    task_id = str(task_id or "")
    execution_token = str(execution_token or "")
    if not task_id or not execution_token:
        return {"available": False, "reason": "review_execution_claim_required"}
    model_version = review_pipeline_version()
    claim_version = f"{model_version}:{decision_run_id}"
    from utils.operations_store import (
        claim_job_run,
        execution_lease_is_current,
        finish_job_run,
    )

    def require_current_execution() -> None:
        if not execution_lease_is_current(task_id, execution_token):
            raise RuntimeError("task_execution_lease_lost")

    require_current_execution()
    claim = claim_job_run(
        "daily_strategy_review",
        trade_date,
        snapshot_id,
        claim_version,
        task_id,
        execution_token=execution_token,
    )
    if not claim.get("claimed"):
        existing = get_latest_strategy_review_run(trade_date)
        if claim.get("status") == "succeeded" and strategy_review_is_current(
            existing, decision, snapshot_id
        ):
            return {"available": True, "existing": True, **existing}
        return {
            "available": False,
            "reason": (
                "strategy_review_in_progress"
                if claim.get("status") == "running"
                else "strategy_review_claim_inconsistent"
            ),
        }

    succeeded = False
    try:
        existing = get_latest_strategy_review_run(trade_date)
        if strategy_review_is_current(existing, decision, snapshot_id):
            succeeded = True
            return {"available": True, "existing": True, **existing}

        report = build_strategy_intelligence(csv_manager, trade_date)
        require_current_execution()
        if not report.get("available"):
            return {
                "available": False,
                "reason": report.get("reason") or "strategy_review_unavailable",
                "report": report,
            }

        algorithm_version = str(report["model_version"])
        report["algorithm_version"] = algorithm_version
        report["model_version"] = model_version
        report["review_pipeline_version"] = model_version
        source_hash = _content_hash(report)
        report["source_hash"] = source_hash
        artifact_model_version = f"{algorithm_version}-{source_hash[:16]}"
        report["model_artifact_version"] = artifact_model_version

        require_current_execution()
        register_model(
            {
                "model_key": "strategy_fitness",
                "version": artifact_model_version,
                "status": "shadow",
                "trained_as_of": trade_date,
                "train_range": None,
                "test_range": None,
                "feature_names": [
                    str(row.get("strategy") or "")
                    for row in report.get("strategies") or []
                ],
                "params": {
                    "primary_horizon": int(report.get("primary_horizon") or 5),
                    "feedback_mode": "shadow_only",
                    "algorithm_version": algorithm_version,
                    "review_pipeline_version": model_version,
                    "ai_prompt_version": PROMPT_VERSION,
                },
                "metrics": {
                    "status": report.get("status"),
                    "strategy_count": report.get("strategy_count"),
                    "eligible_strategy_count": report.get("eligible_strategy_count"),
                    "today_hit_count": report.get("today_hit_count"),
                },
                "source_refs": report.get("source_refs") or [],
                "artifact": {
                    "score_formula": report.get("score_formula"),
                    "method": report.get("method"),
                    "weights": {
                        str(row.get("strategy")): row.get("shadow_weight")
                        for row in report.get("strategies") or []
                        if row.get("eligible")
                    },
                },
            }
        )

        previous = get_previous_strategy_review_run(trade_date)
        require_current_execution()
        ai = run_strategy_review_ai(
            report,
            previous_report=(previous or {}).get("report"),
        )
        require_current_execution()
        report_status = str(report.get("status") or "warming_up")
        status = "ready" if report_status == "ready" else "warming_up"
        reason_codes = []
        if status == "warming_up":
            reason_codes.append(report_status)
        reason_codes.extend(ai.get("reason_codes") or [])
        now = datetime.now(TZ).isoformat(timespec="seconds")
        run = {
            "trade_date": trade_date,
            "snapshot_id": snapshot_id,
            "decision_run_id": decision_run_id,
            "as_of": now,
            "status": status,
            "model_version": model_version,
            "primary_horizon": int(report.get("primary_horizon") or 5),
            "input_hash": source_hash,
            "report": report,
            "ai_status": ai.get("ai_status") or "not_called",
            "ai_model": ai.get("ai_model"),
            "ai_prompt_version": ai.get("ai_prompt_version"),
            "ai_payload": {
                **(ai.get("ai_payload") or {}),
                "evidence": {
                    "prompt_hash": ai.get("prompt_hash"),
                    "previous_review_id": (previous or {}).get("review_id"),
                },
            },
            "reason_codes": sorted(set(reason_codes)),
        }
        require_current_execution()
        run["review_id"] = save_strategy_review_run(run)
        succeeded = True
        return {"available": True, **run}
    finally:
        finish_job_run(
            "daily_strategy_review",
            trade_date,
            snapshot_id,
            claim_version,
            task_id,
            succeeded=succeeded,
            execution_token=execution_token,
        )
