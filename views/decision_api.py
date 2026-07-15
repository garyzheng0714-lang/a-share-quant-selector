"""市场→板块→个股→执行的版本化决策 API。"""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from utils.decision_ledger import (
    get_decision, get_latest_decision, get_latest_evolution, list_models,
)

logger = logging.getLogger(__name__)
decision_bp = Blueprint("decision", __name__)


def _with_models(run: dict | None) -> dict:
    from utils.data_freshness import local_data_status
    freshness = local_data_status()
    if not freshness["fresh"]:
        return {
            "available": False, "reason": "stale_market_data",
            "freshness": freshness, "models": list_models(),
        }
    if not run:
        return {"available": False, "reason": "decision_not_ready", "models": list_models()}
    return {"available": True, **run, "freshness": freshness, "models": list_models()}


@decision_bp.route("/api/decision/latest", methods=["GET"])
def api_latest_decision():
    stage = request.args.get("stage")
    if stage not in {None, "close", "preopen"}:
        return jsonify({"available": False, "reason": "invalid_stage"}), 400
    try:
        run = get_latest_decision(stage)
        from utils.data_freshness import local_data_status
        from utils.decision_versions import strategy_version
        freshness = local_data_status()
        if run and freshness["fresh"] and (
            run.get("trade_date") != freshness["local_date"]
            or run.get("strategy_version") != strategy_version()
        ):
            run = None
        if run is None and stage != "preopen":
            from utils.hierarchical_decision import run_close_decision
            generated = run_close_decision()
            run = generated if generated.get("available") else None
        return jsonify(_with_models(run))
    except Exception as exc:
        logger.error("读取分层决策失败: %s", exc, exc_info=True)
        return jsonify({"available": False, "reason": "decision_unavailable"}), 500


@decision_bp.route("/api/decision/<run_id>", methods=["GET"])
def api_decision_detail(run_id: str):
    run = get_decision(run_id)
    return (jsonify(_with_models(run)), 200 if run else 404)


@decision_bp.route("/api/decision/close", methods=["POST"])
def api_run_close_decision():
    from utils.hierarchical_decision import run_close_decision
    return jsonify(run_close_decision())


@decision_bp.route("/api/decision/evolution", methods=["GET"])
def api_evolution_status():
    latest = get_latest_evolution()
    current = bool(latest and (latest.get("metrics") or {}).get("strategy") == "super-b1-original")
    return jsonify({"available": current, "data": latest if current else None})


@decision_bp.route("/api/decision/evolution", methods=["POST"])
def api_run_evolution():
    from utils.self_evolution import run_daily_evolution

    return jsonify(run_daily_evolution())


@decision_bp.route("/api/decision/preopen", methods=["POST"])
def api_run_preopen_decision():
    from utils.hierarchical_decision import run_preopen_decision
    return jsonify(run_preopen_decision())
