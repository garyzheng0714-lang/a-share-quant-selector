"""市场洞察 API - Flask Blueprint（温度计 + 每日荐一票）

独立于 web_server.py（该文件已超行数上限，新 API 一律走 Blueprint）。
"""

import logging

from flask import Blueprint, jsonify

logger = logging.getLogger(__name__)

insight_bp = Blueprint("insight", __name__)


@insight_bp.route("/api/thermometer", methods=["GET"])
def api_thermometer():
    """读取 worker 生成且与当前 snapshot 绑定的市场状态。"""
    try:
        from utils.csv_manager import CSVManager
        from utils.market_thermometer import read_thermometer

        manager = CSVManager("data", writable=False)
        if manager.snapshot_id is None:
            return jsonify({"available": False, "reason": "snapshot_unavailable"}), 503
        result = read_thermometer(manager)
        return jsonify(result), (200 if result.get("available") else 503)
    except Exception as e:
        logger.error("温度计获取失败: %s", e)
        return jsonify({"available": False, "reason": "温度计数据暂不可用"}), 500


@insight_bp.route("/api/sectors", methods=["GET"])
def api_sectors():
    """板块轮动：当前最热板块 + 潜在接力板块（自研量化模型，收盘口径）."""
    try:
        from utils.csv_manager import CSVManager
        from utils.sector_rotation import read_cached_sector_rotation

        manager = CSVManager("data", writable=False)
        if manager.snapshot_id is None:
            return jsonify({"available": False, "reason": "snapshot_unavailable"}), 503
        result = read_cached_sector_rotation(manager)
        if result.get("available"):
            ranking = []
            for name, item in sorted(
                (result.get("heat_map") or {}).items(),
                key=lambda pair: pair[1].get("rank", 9999),
            ):
                delta = item.get("delta3", 0)
                ranking.append(
                    {
                        "name": name,
                        **item,
                        "trend": "up"
                        if delta >= 8
                        else ("down" if delta <= -8 else "flat"),
                    }
                )
            result = {**result, "ranking": ranking}
        return jsonify({**result, "snapshot_id": manager.snapshot_id})
    except Exception as e:
        logger.error("板块轮动获取失败: %s", e)
        return jsonify({"available": False, "reason": "板块数据暂不可用"}), 500


@insight_bp.route("/api/sectors/<path:sector_name>", methods=["GET"])
def api_sector_detail(sector_name):
    """板块详情：板块状态、成分股排名、B1主判和辅助确认。"""
    try:
        from strategy.factors import FACTOR_REGISTRY
        from utils.csv_manager import CSVManager
        from utils.data_freshness import local_data_status
        from utils.decision_ledger import get_latest_decision
        from utils.factor_scan import read_cached_factor_hits
        from utils.market_filter import is_main_board
        from utils.market_snapshot import read_snapshot_metadata
        from utils.sector_rotation import read_cached_sector_rotation
        from utils.super_b1_scan import read_cached_super_b1

        from views.decision_api import _matches_current_snapshot

        cm = CSVManager("data", writable=False)
        if cm.snapshot_id is None:
            return jsonify({"available": False, "reason": "snapshot_unavailable"}), 503
        names, _ = read_snapshot_metadata(
            "stock_names.json",
            cm.base_data_dir,
            snapshot_id=cm.snapshot_id,
        )
        industries, _ = read_snapshot_metadata(
            "stock_industry.json",
            cm.base_data_dir,
            snapshot_id=cm.snapshot_id,
        )
        if not isinstance(names, dict) or not isinstance(industries, dict):
            return jsonify(
                {"available": False, "reason": "snapshot_metadata_unavailable"}
            ), 503
        sectors = read_cached_sector_rotation(cm)
        if not sectors.get("available"):
            return jsonify(sectors), 503
        state = (sectors.get("heat_map") or {}).get(sector_name)
        members = sorted(
            code
            for code, industry in industries.items()
            if industry == sector_name and is_main_board(code)
        )
        if not members:
            return jsonify(
                {
                    "available": False,
                    "reason": "板块分类已更新，请返回板块榜刷新后重新选择",
                    "trade_date": sectors.get("trade_date"),
                    "sector": {"name": sector_name, **(state or {})},
                    "stocks": [],
                    "recommended": [],
                    "total": 0,
                }
            )

        try:
            b1 = read_cached_super_b1(cm)
        except Exception as e:
            logger.warning("板块详情读取B1缓存失败: %s", e)
            b1 = {"hits": []}
        b1_map = {row["code"]: row for row in b1.get("hits") or []}
        try:
            factors = read_cached_factor_hits(cm, list(FACTOR_REGISTRY))
        except Exception as e:
            logger.warning("板块详情读取因子缓存失败: %s", e)
            factors = {"available": False}
        confirmations: dict[str, list[str]] = {}
        if factors.get("available"):
            for key, payload in (factors.get("results") or {}).items():
                for row in payload.get("hits") or []:
                    confirmations.setdefault(row.get("code", ""), []).append(key)
        try:
            freshness = local_data_status(cm)
            possible_runs = (
                get_latest_decision("preopen"),
                get_latest_decision("close"),
            )
            decision = next(
                (
                    run
                    for run in possible_runs
                    if _matches_current_snapshot(run, freshness)
                ),
                {},
            )
        except Exception as e:
            logger.warning("板块详情读取决策账本失败: %s", e)
            decision = {}
        actions = {row["code"]: row for row in decision.get("candidates") or []}

        stocks = []
        read_errors = []
        for code in members:
            try:
                frame = cm.read_stock(code, nrows=6)
                if frame.empty:
                    continue
                close = float(frame.iloc[0]["close"])
                ret1 = (
                    (close / float(frame.iloc[1]["close"]) - 1) * 100
                    if len(frame) > 1
                    else None
                )
                ret5 = (
                    (close / float(frame.iloc[-1]["close"]) - 1) * 100
                    if len(frame) > 5
                    else None
                )
                hit = b1_map.get(code)
                aux = confirmations.get(code, [])
                decision_item = actions.get(code, {})
                action = decision_item.get("action", "none")
                baseline = decision_item.get("baseline") or {}
                stocks.append(
                    {
                        "code": code,
                        "name": names.get(code, code),
                        "close": round(close, 2),
                        "ret1": round(ret1, 2) if ret1 is not None else None,
                        "ret5": round(ret5, 2) if ret5 is not None else None,
                        "b1": bool(hit),
                        "b1_signals": (hit or {}).get("signal_labels") or [],
                        "confirmation_count": len(aux),
                        "confirmations": aux,
                        "action": action,
                        "reason_codes": decision_item.get("reason_codes", []),
                        "weekly": baseline.get("weekly") or (hit or {}).get("weekly"),
                        "decision_run_id": decision.get("run_id")
                        if decision_item
                        else None,
                        "decision_as_of": decision.get("as_of")
                        if decision_item
                        else None,
                        "data_status": "complete" if len(frame) >= 6 else "partial",
                        "risk_status": (
                            "blocked"
                            if action == "avoid"
                            else "passed"
                            if action == "buy"
                            else "not_evaluated"
                        ),
                    }
                )
            except Exception as e:
                logger.warning("板块详情跳过异常行情 %s: %s", code, e)
                read_errors.append(code)
        if read_errors:
            return jsonify(
                {
                    "available": False,
                    "reason": "snapshot_stock_read_failed",
                    "error_count": len(read_errors),
                }
            ), 503
        stocks.sort(
            key=lambda row: (
                not row["b1"],
                {"buy": 0, "observe": 1, "avoid": 2, "none": 3}.get(row["action"], 4),
                -row["confirmation_count"],
                -(row["ret5"] if row["ret5"] is not None else -999),
                row["code"],
            )
        )
        for rank, row in enumerate(stocks, start=1):
            row["rank"] = rank
        return jsonify(
            {
                "available": True,
                "trade_date": sectors.get("trade_date"),
                "sector": {"name": sector_name, **(state or {})},
                "stocks": stocks,
                "recommended": [row for row in stocks if row["b1"]],
                "total": len(stocks),
            }
        )
    except Exception as e:
        logger.error("板块详情获取失败: %s", e, exc_info=True)
        return jsonify({"available": False, "reason": "板块详情暂不可用"}), 500


@insight_bp.route("/api/daily-pick", methods=["GET"])
def api_get_daily_pick():
    """旧 LLM 自主荐票档案不再进入生产 API。"""
    return jsonify(
        {
            "available": False,
            "reason": "legacy_research_disabled",
            "replacement": "/api/decision/latest",
        }
    ), 410


@insight_bp.route("/api/daily-pick", methods=["POST"])
def api_generate_daily_pick():
    """旧版 LLM 自主荐股已停用；GET 仅保留只读历史档案。"""
    return jsonify(
        {
            "available": False,
            "reason": "legacy_generation_disabled",
            "message": "旧版 AI 自主荐股已停用，请使用策略决策接口。",
        }
    ), 410
