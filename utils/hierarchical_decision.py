"""分层推荐决策引擎：收盘候选 + 盘前风险复核。"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from strategy.factor_lib import FactorContext
from utils.artifact_integrity import ARTIFACT_HASH_FIELD
from utils.csv_manager import CSVManager
from utils.decision_config import get_decision_config
from utils.decision_ledger import (
    get_active_models,
    get_active_policy_models,
    get_latest_decision,
    list_models,
    save_decision_run,
)
from utils.decision_versions import (
    FEATURE_VERSION,
    VALIDATED_MODEL_SOURCE_REFS,
    data_version,
    strategy_version,
)
from utils.data_freshness import local_data_status, next_trade_date
from utils.probability_model import BinaryLogit
from utils.market_snapshot import load_market_snapshot, read_snapshot_metadata
from utils.policy_engine import MODEL_COMPONENTS, evaluate_policy, policy_manifest

logger = logging.getLogger(__name__)
TZ = ZoneInfo("Asia/Shanghai")


def _metadata(manager: CSVManager, filename: str) -> dict:
    value, _ = read_snapshot_metadata(
        filename,
        manager.base_data_dir,
        snapshot_id=manager.snapshot_id,
    )
    return value if isinstance(value, dict) else {}


def _verify_manager_snapshot(manager: CSVManager) -> dict:
    if manager.snapshot_id is None:
        return {"available": False, "reason": "snapshot_pointer_missing"}
    return load_market_snapshot(
        manager.base_data_dir,
        manager.snapshot_id,
        verify_files=True,
    )


def _artifact_reference(namespace: str, payload: dict) -> dict:
    """将已校验缓存的精确身份收入不可变决策证据。"""
    return {
        "namespace": namespace,
        "cache_key": payload.get("cache_key"),
        "content_hash": payload.get(ARTIFACT_HASH_FIELD),
        "trade_date": payload.get("trade_date"),
    }


def _baseline_candidates(
    manager: CSVManager,
) -> tuple[str | None, list[dict], dict[str, dict]]:
    from strategy.factors import FACTOR_REGISTRY
    from utils.factor_scan import read_cached_factor_hits
    from utils.market_filter import is_main_board, main_board_only
    from utils.sector_rotation import read_cached_sector_rotation
    from utils.super_b1_scan import read_cached_super_b1

    names = _metadata(manager, "stock_names.json")
    industries = _metadata(manager, "stock_industry.json")
    caps = _metadata(manager, "stock_market_cap.json")
    scan = read_cached_super_b1(manager)
    if not scan.get("available"):
        return None, [], {}
    hits = scan.get("hits") or []
    if main_board_only():
        hits = [h for h in hits if is_main_board(h.get("code", ""))]
    sectors = read_cached_sector_rotation(manager)
    if not sectors.get("available"):
        return None, [], {}
    heat = sectors.get("heat_map") or {}
    auxiliary = read_cached_factor_hits(manager, list(FACTOR_REGISTRY))
    artifacts = {
        "super_b1": _artifact_reference("super_b1", scan),
        "sector_rotation": _artifact_reference("sector_rotation", sectors),
    }
    if auxiliary.get("available"):
        artifacts["factor_scan"] = _artifact_reference("factor_scan", auxiliary)
    confirmations: dict[str, list[str]] = {}
    if auxiliary.get("available"):
        for key, result in (auxiliary.get("results") or {}).items():
            for item in result.get("hits") or []:
                confirmations.setdefault(item.get("code", ""), []).append(key)
    rows = []
    for hit in hits:
        code = hit.get("code", "")
        industry = industries.get(code, "")
        cap = caps.get(code, {})
        cap_value = (
            (cap.get("circ_mv") or cap.get("total_mv"))
            if isinstance(cap, dict)
            else None
        )
        rows.append(
            {
                **hit,
                "name": hit.get("name") or names.get(code, code),
                "industry": industry,
                "cap_yi": round(cap_value / 1e8, 1)
                if isinstance(cap_value, (int, float)) and cap_value > 0
                else None,
                "sector": heat.get(industry),
                "confirmations": confirmations.get(code, []),
            }
        )
    return scan["trade_date"], rows, artifacts


def _active_model_bundle() -> tuple[dict, str]:
    models, policy_version = get_active_policy_models()
    if not models:
        return {}, "baseline-only"
    valid = all(
        VALIDATED_MODEL_SOURCE_REFS.issubset(set(model.get("source_refs") or []))
        for model in models.values()
    )
    return (models, policy_version) if valid else ({}, "baseline-only")


def _layer_modes(models: dict, weekly_gate_mode: str) -> dict[str, str]:
    latest = {item["model_key"]: item for item in list_models()}
    modes = {"weekly_four_ma": weekly_gate_mode}
    for key in MODEL_COMPONENTS:
        if key in models:
            modes[key] = "active"
        elif (latest.get(key) or {}).get("status") == "shadow":
            modes[key] = "shadow"
        else:
            modes[key] = "off"
    return modes


def _live_feature_rows(
    candidates: list[dict], trade_date: str, manager: CSVManager
) -> pd.DataFrame:
    """与训练工具共用特征定义。仅在存在 active 模型时计算。"""
    from tools.hierarchical_walk_forward import (
        MARKET_FEATURES,
        SECTOR_FEATURES,
        _stock_features,
        build_panels,
    )

    industries = _metadata(manager, "stock_industry.json")
    codes = [
        code for code in manager.list_all_stocks() if code.isdigit() and len(code) == 6
    ]
    market, sector, stock_frames = build_panels(manager, codes, industries)
    rows = []
    for candidate in candidates:
        code, industry = candidate["code"], candidate.get("industry") or "未知"
        frame = stock_frames.get(code)
        if (
            frame is None
            or trade_date not in market.index
            or (trade_date, industry) not in sector.index
        ):
            rows.append({"code": code, "feature_missing": True})
            continue
        sub = frame[frame["date"] <= trade_date]
        if len(sub) < 60:
            rows.append({"code": code, "feature_missing": True})
            continue
        record = {"code": code, "feature_missing": False}
        record.update(
            {k: float(market.loc[trade_date].get(k)) for k in MARKET_FEATURES}
        )
        record.update(
            {
                k: float(sector.loc[(trade_date, industry)].get(k))
                for k in SECTOR_FEATURES
            }
        )
        record.update(_stock_features(FactorContext(sub)))
        rows.append(record)
    return pd.DataFrame(rows)


def _predict(models: dict, features: pd.DataFrame) -> dict[str, dict[str, float]]:
    out = {code: {} for code in features["code"]}
    valid = features[~features["feature_missing"]]
    for key, registration in models.items():
        model = BinaryLogit.from_dict(registration["artifact"])
        values = model.predict_proba(valid)
        for code, value in zip(valid["code"], values):
            out[code][key] = round(float(value), 4)
            out[code][f"{key}_threshold"] = registration.get("params", {}).get(
                "threshold"
            )
    return out


def run_close_decision(csv_manager: CSVManager | None = None) -> dict:
    manager = csv_manager or CSVManager("data", writable=False)
    config = get_decision_config()
    if not config["enabled"]:
        return {"available": False, "reason": "hierarchy_disabled"}
    verified = _verify_manager_snapshot(manager)
    if not verified.get("available"):
        return {
            "available": False,
            "reason": "market_snapshot_integrity_failed",
            "integrity": verified,
        }
    freshness = local_data_status(manager)
    if not freshness["fresh"]:
        return {
            "available": False,
            "reason": "stale_market_data",
            "freshness": freshness,
        }
    trade_date, baseline, derived_artifacts = _baseline_candidates(manager)
    if not trade_date:
        return {"available": False, "reason": "baseline_unavailable"}
    if (
        trade_date != freshness.get("local_date")
        or trade_date != freshness.get("expected_date")
        or not freshness.get("snapshot_id")
        or data_version(manager.data_dir) != f"snapshot-{freshness.get('snapshot_id')}"
    ):
        return {
            "available": False,
            "reason": "market_snapshot_date_mismatch",
            "baseline_trade_date": trade_date,
            "freshness": freshness,
        }
    as_of = freshness.get("closed_at") or f"{trade_date}T15:05:00+08:00"
    models, model_version = _active_model_bundle()
    predictions = {}
    if models and baseline:
        try:
            predictions = _predict(
                models,
                _live_feature_rows(baseline, trade_date, manager),
            )
        except Exception as exc:
            logger.exception("实时分层特征计算失败: %s", exc)
            models = {}
            model_version = "baseline-only"

    weekly_gate_mode = config["weekly_gate_mode"]
    layer_modes = _layer_modes(models, weekly_gate_mode)
    runtime_manifest = policy_manifest(
        policy_version=model_version,
        weekly_gate_mode=weekly_gate_mode,
        strict_unvalidated_market=config["strict_unvalidated_gate"],
        top_n=3,
        components={
            key: {
                "mode": layer_modes.get(key, "off"),
                "threshold": (models.get(key) or {}).get("params", {}).get("threshold"),
                "version": (models.get(key) or {}).get("version"),
            }
            for key in MODEL_COMPONENTS
        },
    )
    evidence = []
    for row in baseline:
        probability = predictions.get(row["code"], {})
        evidence.append(
            {
                "candidate_id": row["code"],
                "code": row["code"],
                "decision_date": trade_date,
                "weekly_passed": (row.get("weekly") or {}).get("passed") is True,
                "probabilities": {
                    key: probability.get(key) for key in MODEL_COMPONENTS
                },
            }
        )
    evaluated = evaluate_policy(evidence, runtime_manifest)
    by_code = {row["code"]: row for row in baseline}
    candidates = []
    for result in evaluated:
        row = by_code[result["code"]]
        probability = predictions.get(row["code"], {})
        weekly = row.get("weekly") or {}
        candidates.append(
            {
                "code": row["code"],
                "name": row.get("name"),
                "industry": row.get("industry"),
                "rank": result["rank"],
                "tie_group": result["tie_group"],
                "action": result["action"],
                "baseline": {
                    "signal": "super_b1",
                    "signals": row.get("signals") or [],
                    "signal_labels": row.get("signal_labels") or [],
                    "confirmations": row.get("confirmations") or [],
                    "confirmation_count": len(row.get("confirmations") or []),
                    "close": row.get("close"),
                    "J": row.get("J"),
                    "RSI": row.get("RSI"),
                    "cap_yi": row.get("cap_yi"),
                    "weekly": {**weekly, "gate_mode": weekly_gate_mode},
                },
                "market": {
                    "probability": probability.get("market"),
                    "threshold": probability.get("market_threshold"),
                    "semantic_name": "b1_signal_day_candidate_quality_gate",
                },
                "sector": {
                    **(row.get("sector") or {}),
                    "probability": probability.get("sector"),
                    "threshold": probability.get("sector_threshold"),
                },
                "stock": {
                    "entry_risk_probability": probability.get("entry_risk"),
                    "entry_risk_threshold": probability.get("entry_risk_threshold"),
                    "exit_risk_probability": probability.get("exit_risk"),
                    "exit_risk_threshold": probability.get("exit_risk_threshold"),
                    "quality_probability": probability.get("quality"),
                },
                "events": [],
                "reason_codes": result["reason_codes"],
            }
        )
    candidates.sort(key=lambda item: item["rank"])
    reason_codes = []
    if not baseline:
        final_action, status = "none", "complete"
        reason_codes.append("no_rule_hits")
    elif any(candidate["action"] == "buy" for candidate in candidates):
        final_action, status = "buy", "complete"
    else:
        final_action = "observe"
        status = "degraded" if "market" not in models else "complete"
        reason_codes.append("all_candidates_downgraded")
        if config["strict_unvalidated_gate"] and "market" not in models:
            reason_codes.append("market_model_unvalidated")
    run = {
        "trade_date": trade_date,
        "stage": "close",
        "as_of": as_of,
        "status": status,
        "final_action": final_action,
        "strategy_version": strategy_version(),
        "feature_version": FEATURE_VERSION,
        "model_version": model_version,
        "data_version": f"snapshot-{freshness['snapshot_id']}",
        "source_refs": [
            f"market-snapshot:{freshness['snapshot_id']}",
            "factor:super-b1-original",
            *[
                f"derived-artifact:{item['namespace']}:{item['content_hash']}"
                for item in derived_artifacts.values()
            ],
        ],
        "market": {
            "snapshot_id": freshness["snapshot_id"],
            "models_active": sorted(models),
            "layer_modes": layer_modes,
            "gate_order": runtime_manifest["gate_order"],
            "policy_manifest": runtime_manifest,
            "derived_artifacts": derived_artifacts,
            "decision_for_date": next_trade_date(
                trade_date,
                data_dir=manager.base_data_dir,
                snapshot_id=manager.snapshot_id,
            ),
        },
        "evaluation": {k: v.get("metrics", {}) for k, v in models.items()},
        "reason_codes": reason_codes,
    }
    final_verification = _verify_manager_snapshot(manager)
    if not final_verification.get("available"):
        return {
            "available": False,
            "reason": "market_snapshot_integrity_failed",
            "phase": "before_ledger_commit",
            "integrity": final_verification,
        }
    run_id = save_decision_run(run, candidates)
    from utils.decision_ledger import get_decision

    return {"available": True, **get_decision(run_id)}


def run_preopen_decision(
    as_of: str | None = None,
    csv_manager: CSVManager | None = None,
) -> dict:
    from utils.event_risk import review_candidates

    config = get_decision_config()
    if not config["enabled"] or not config["preopen_event_check"]:
        return {"available": False, "reason": "preopen_review_disabled"}
    manager = csv_manager or CSVManager("data", writable=False)
    verified = _verify_manager_snapshot(manager)
    if not verified.get("available"):
        return {
            "available": False,
            "reason": "market_snapshot_integrity_failed",
            "integrity": verified,
        }
    now = datetime.fromisoformat(as_of) if as_of else datetime.now(TZ)
    if now.tzinfo is None:
        now = now.replace(tzinfo=TZ)
    today = now.astimezone(TZ).date().isoformat()
    freshness = local_data_status(manager, as_of=now)
    if not freshness.get("fresh"):
        return {
            "available": False,
            "reason": "stale_market_data",
            "freshness": freshness,
        }
    previous_trade_date = freshness["local_date"]
    if (
        next_trade_date(
            previous_trade_date,
            data_dir=manager.base_data_dir,
            snapshot_id=manager.snapshot_id,
        )
        != today
    ):
        return {"available": False, "reason": "preopen_not_a_trading_session"}
    close_run = get_latest_decision("close")
    if not close_run or not close_run.get("candidates"):
        return {
            "available": False,
            "reason": "close_decision_missing_for_previous_session",
        }
    current_model_version = _active_model_bundle()[1]
    valid_close = (
        close_run.get("trade_date") == previous_trade_date
        and (close_run.get("market") or {}).get("decision_for_date") == today
        and close_run.get("strategy_version") == strategy_version()
        and close_run.get("model_version") == current_model_version
        and (close_run.get("market") or {}).get("snapshot_id")
        == freshness.get("snapshot_id")
        and close_run.get("data_version") == data_version(manager.data_dir)
    )
    if not valid_close:
        return {
            "available": False,
            "reason": "close_decision_missing_for_previous_session",
        }
    existing = get_latest_decision("preopen")
    existing_matches_close = bool(
        existing
        and (existing.get("market") or {}).get("decision_for_date") == today
        and (existing.get("evaluation") or {}).get("close_run_id")
        == close_run.get("run_id")
        and existing.get("strategy_version") == close_run.get("strategy_version")
        and existing.get("model_version") == close_run.get("model_version")
        and existing.get("data_version") == close_run.get("data_version")
    )
    if existing_matches_close:
        return {"available": True, **existing, "idempotent_replay": True}
    as_of = now.replace(hour=8, minute=45, second=0, microsecond=0).isoformat()
    llm_label_active = "event_llm" in get_active_models()
    review = review_candidates(
        close_run["candidates"], close_run["trade_date"], as_of, llm_label_active
    )
    candidates = []
    for item in close_run["candidates"]:
        candidate = {**item, "events": review["events_by_code"].get(item["code"], [])}
        reasons = list(candidate.get("reason_codes", []))
        if item["code"] in review["veto_codes"]:
            candidate["action"] = "avoid"
            reasons.append("overnight_event_veto")
        elif not review["available"]:
            candidate["action"] = "observe"
            reasons.append("overnight_source_missing")
        elif item["code"] in review["review_codes"] and candidate["action"] == "buy":
            candidate["action"] = "observe"
            reasons.append("overnight_event_review")
        candidate["reason_codes"] = sorted(set(reasons))
        candidates.append(candidate)
    buy_count = sum(c["action"] == "buy" for c in candidates)
    final_action = "buy" if buy_count else ("observe" if candidates else "none")
    run = {
        "trade_date": close_run["trade_date"],
        "stage": "preopen",
        "as_of": as_of,
        "status": "complete" if review["available"] else "degraded",
        "final_action": final_action,
        "strategy_version": close_run["strategy_version"],
        "feature_version": close_run["feature_version"],
        "model_version": close_run["model_version"],
        "data_version": close_run["data_version"],
        "source_refs": close_run["source_refs"] + review["source_refs"],
        "market": close_run["market"],
        "evaluation": {"close_run_id": close_run["run_id"], "event_llm": review["llm"]},
        "reason_codes": [] if review["available"] else ["overnight_source_missing"],
    }
    final_verification = _verify_manager_snapshot(manager)
    if not final_verification.get("available"):
        return {
            "available": False,
            "reason": "market_snapshot_integrity_failed",
            "phase": "before_ledger_commit",
            "integrity": final_verification,
        }
    run_id = save_decision_run(run, candidates)
    from utils.decision_ledger import get_decision

    return {"available": True, **get_decision(run_id)}
