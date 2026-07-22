"""基于不可变快照和决策证据的纯策略 replay。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from utils.decision_ledger import get_decision
from utils.market_snapshot import load_market_snapshot
from utils.policy_engine import MODEL_COMPONENTS, evaluate_policy


def replay_decision(
    run_id: str,
    snapshot_id: str,
    *,
    data_dir: str | Path = "data",
) -> dict:
    """只接受明确 snapshot_id；禁止用当前可变数据伪回放。"""
    snapshot = load_market_snapshot(data_dir, snapshot_id, verify_files=True)
    if not snapshot.get("available"):
        return {
            "available": False,
            "reason": snapshot.get("reason", "snapshot_unavailable"),
        }
    decision = get_decision(run_id)
    if not decision or decision.get("stage") != "close":
        return {"available": False, "reason": "close_decision_not_found"}
    manifest = snapshot["manifest"]
    market = decision.get("market") or {}
    if (
        market.get("snapshot_id") != snapshot_id
        or decision.get("trade_date") != manifest.get("trade_date")
        or decision.get("data_version") != f"snapshot-{snapshot_id}"
    ):
        return {"available": False, "reason": "decision_snapshot_mismatch"}
    try:
        decision_as_of = datetime.fromisoformat(decision["as_of"])
        snapshot_closed_at = datetime.fromisoformat(manifest["closed_at"])
    except (KeyError, TypeError, ValueError):
        return {"available": False, "reason": "decision_time_evidence_invalid"}
    if decision_as_of > snapshot_closed_at:
        return {"available": False, "reason": "decision_as_of_after_snapshot_close"}
    policy = market.get("policy_manifest")
    if not isinstance(policy, dict):
        return {"available": False, "reason": "policy_manifest_missing"}

    evidence = []
    for candidate in decision.get("candidates") or []:
        baseline = candidate.get("baseline") or {}
        stock = candidate.get("stock") or {}
        evidence.append(
            {
                "candidate_id": candidate["code"],
                "code": candidate["code"],
                "decision_date": decision["trade_date"],
                "weekly_passed": (baseline.get("weekly") or {}).get("passed") is True,
                "probabilities": {
                    "market": (candidate.get("market") or {}).get("probability"),
                    "sector": (candidate.get("sector") or {}).get("probability"),
                    "entry_risk": stock.get("entry_risk_probability"),
                    "exit_risk": stock.get("exit_risk_probability"),
                    "quality": stock.get("quality_probability"),
                },
            }
        )
    replayed = evaluate_policy(evidence, policy)
    recorded = {
        candidate["code"]: {
            "action": candidate.get("action"),
            "reason_codes": sorted(candidate.get("reason_codes") or []),
            "rank": candidate.get("rank"),
        }
        for candidate in decision.get("candidates") or []
    }
    replay_payload = {
        candidate["code"]: {
            "action": candidate["action"],
            "reason_codes": sorted(candidate.get("reason_codes") or []),
            "rank": candidate["rank"],
        }
        for candidate in replayed
    }
    parity = recorded == replay_payload
    return {
        "available": True,
        "parity": parity,
        "reason": None if parity else "live_replay_divergence",
        "run_id": run_id,
        "snapshot_id": snapshot_id,
        "trade_date": decision["trade_date"],
        "policy_version": policy.get("policy_version"),
        "component_keys": list(MODEL_COMPONENTS),
        "recorded": recorded,
        "replayed": replay_payload,
    }
