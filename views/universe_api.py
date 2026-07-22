"""全量股票池覆盖率与后台历史回补 API。"""

from __future__ import annotations

import logging
from flask import Blueprint, jsonify

from utils.api_security import require_role

logger = logging.getLogger(__name__)
universe_bp = Blueprint("universe", __name__)


@universe_bp.route("/api/data/coverage", methods=["GET"])
def api_data_coverage():
    from utils.market_snapshot import load_current_market_snapshot

    current = load_current_market_snapshot("data", verify_files=False)
    if not current.get("available"):
        return jsonify({"success": False, "reason": current.get("reason")}), 503
    manifest = current["manifest"]
    status = {
        "snapshot_id": current["snapshot_id"],
        "trade_date": manifest.get("trade_date"),
        "universe_count": manifest.get("expected_count"),
        "covered_count": manifest.get("valid_count"),
        "coverage_ratio": manifest.get("coverage_ratio"),
        "reference_quality": manifest.get("reference_quality"),
    }
    return jsonify({"success": True, "data": status})


@universe_bp.route("/api/data/bootstrap", methods=["POST"])
@require_role("admin")
def api_data_bootstrap():
    from utils.task_submission import submit_task

    return submit_task("full_market_rebuild", {"years": 6})
