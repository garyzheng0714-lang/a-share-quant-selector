"""面向研究台的数据管线只读状态。"""

import logging

from flask import Blueprint, jsonify


logger = logging.getLogger(__name__)
pipeline_bp = Blueprint("pipeline", __name__)


@pipeline_bp.get("/api/data-pipeline/status")
def api_data_pipeline_status():
    try:
        from utils.pipeline_status import build_pipeline_status

        return jsonify(build_pipeline_status())
    except Exception as exc:
        logger.error("读取数据管线状态失败: %s", exc, exc_info=True)
        return jsonify(
            {
                "available": False,
                "state": "unavailable",
                "reason": "pipeline_status_unavailable",
            }
        ), 500
