"""A 股量化选股系统的只读 Web/API 进程。

Web 进程只读取已经发布的不可变快照和 worker 已落账的决策。行情抓取、
策略执行、结果回填和定时调度全部由独立 worker 负责。
"""

from __future__ import annotations

import logging
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import pandas as pd
from flask import Flask, g, jsonify, request, send_from_directory


project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from utils.api_security import require_role  # noqa: E402
from utils.csv_manager import CSVManager  # noqa: E402
from utils.market_snapshot import (  # noqa: E402
    load_current_market_snapshot,
    load_market_snapshot,
    read_snapshot_metadata,
)
from utils.stock_info import get_industry_summary  # noqa: E402
from views.decision_api import decision_bp  # noqa: E402
from views.factor_api import factor_bp  # noqa: E402
from views.insight_api import insight_bp  # noqa: E402
from views.operations_api import operations_bp  # noqa: E402
from views.performance_api import perf_bp  # noqa: E402
from views.quant_pick_api import quant_pick_bp  # noqa: E402
from views.super_b1_api import super_b1_bp  # noqa: E402
from views.universe_api import universe_bp  # noqa: E402


logger = logging.getLogger(__name__)
app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024

for blueprint in (
    perf_bp,
    insight_bp,
    super_b1_bp,
    factor_bp,
    quant_pick_bp,
    decision_bp,
    universe_bp,
    operations_bp,
):
    app.register_blueprint(blueprint)

_frontend_dist = Path(__file__).parent / "frontend" / "dist"
_CACHE_TTL = 3600
_industry_cache: dict[str, str] | None = None
_industry_cache_ts = 0.0
_industry_cache_snapshot: str | None = None
_STOCK_CODE_RE = re.compile(r"\d{6}")


@app.before_request
def _attach_request_id() -> None:
    supplied = request.headers.get("X-Request-ID", "").strip()
    g.request_id = (supplied or uuid.uuid4().hex)[:128]


@app.after_request
def _security_headers(response):
    response.headers["X-Request-ID"] = getattr(g, "request_id", "")
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; object-src 'none'; frame-ancestors 'none'"
    )
    return response


def _valid_stock_code(code: str) -> bool:
    return bool(_STOCK_CODE_RE.fullmatch(code))


def _snapshot_context() -> tuple[CSVManager, dict]:
    """为一次请求绑定单一快照，指针切换时不混读。"""
    manager = CSVManager("data", writable=False)
    if manager.snapshot_id is None:
        return manager, {"available": False, "reason": "snapshot_pointer_missing"}
    return manager, load_market_snapshot(
        manager.base_data_dir,
        manager.snapshot_id,
        verify_files=False,
    )


def _load_stock_names(manager: CSVManager) -> dict[str, str]:
    value, _ = read_snapshot_metadata(
        "stock_names.json",
        manager.base_data_dir,
        snapshot_id=manager.snapshot_id,
    )
    if not isinstance(value, dict):
        return {}
    return {
        str(code): str(name)
        for code, name in value.items()
        if not str(code).startswith("_")
    }


def _load_market_caps(manager: CSVManager) -> dict[str, dict]:
    value, _ = read_snapshot_metadata(
        "stock_market_cap.json",
        manager.base_data_dir,
        snapshot_id=manager.snapshot_id,
    )
    if not isinstance(value, dict):
        return {}
    return {
        str(code): item
        for code, item in value.items()
        if not str(code).startswith("_") and isinstance(item, dict)
    }


def _get_cached_industry(manager: CSVManager) -> dict[str, str]:
    """只读取当前快照中的行业映射；缓存键包含 snapshot_id。"""
    global _industry_cache, _industry_cache_ts, _industry_cache_snapshot
    now = time.monotonic()
    value, snapshot_id = read_snapshot_metadata(
        "stock_industry.json",
        manager.base_data_dir,
        snapshot_id=manager.snapshot_id,
    )
    if (
        _industry_cache is None
        or _industry_cache_snapshot != snapshot_id
        or now - _industry_cache_ts > _CACHE_TTL
    ):
        source = value if isinstance(value, dict) else {}
        _industry_cache = {
            str(code): str(industry)
            for code, industry in source.items()
            if not str(code).startswith("_")
        }
        _industry_cache_ts = now
        _industry_cache_snapshot = snapshot_id
    return _industry_cache


def _market_cap_yi(cap_item: dict | None) -> float | None:
    if not cap_item:
        return None
    value = cap_item.get("circ_mv") or cap_item.get("total_mv")
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    return round(float(value) / 1e8, 2)


def _board_name(code: str) -> str:
    if code.startswith(("688", "689")):
        return "科创板"
    if code.startswith(("300", "301")):
        return "创业板"
    if code.startswith(("8", "4")):
        return "北京证券交易所"
    if code.startswith("6"):
        return "沪市主板"
    if code.startswith(("000", "001", "002", "003")):
        return "深市主板"
    return "其他"


def _finite_number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if pd.notna(number) else default


def _legacy_disabled():
    return jsonify(
        {
            "success": False,
            "error": "legacy_research_disabled",
            "replacement": "/api/decision/latest",
        }
    ), 410


# -------------------- React SPA --------------------


@app.route("/")
def serve_frontend():
    return send_from_directory(_frontend_dist, "index.html")


@app.route("/<path:path>")
def serve_frontend_assets(path: str):
    if path.startswith("api/"):
        return jsonify({"success": False, "error": "not_found"}), 404
    file_path = _frontend_dist / path
    if file_path.is_file():
        return send_from_directory(_frontend_dist, path)
    return send_from_directory(_frontend_dist, "index.html")


# -------------------- 已隔离的旧视图 API --------------------


@app.get("/api/views")
def api_list_views():
    return _legacy_disabled()


@app.post("/api/views")
@require_role("admin")
def api_create_view():
    return _legacy_disabled()


@app.get("/api/views/<int:view_id>")
def api_get_view(view_id: int):
    return _legacy_disabled()


@app.put("/api/views/<int:view_id>")
@require_role("admin")
def api_update_view(view_id: int):
    return _legacy_disabled()


@app.delete("/api/views/<int:view_id>")
@require_role("admin")
def api_delete_view(view_id: int):
    return _legacy_disabled()


@app.post("/api/views/<int:view_id>/run")
@require_role("publisher")
def api_run_selection(view_id: int):
    return _legacy_disabled()


@app.get("/api/views/<int:view_id>/run/status")
def api_run_status(view_id: int):
    return _legacy_disabled()


@app.get("/api/views/<int:view_id>/results")
def api_get_results(view_id: int):
    return _legacy_disabled()


@app.get("/api/views/<int:view_id>/results/<run_date>")
def api_get_result_by_date(view_id: int, run_date: str):
    return _legacy_disabled()


# -------------------- 状态与只读行情 API --------------------


@app.get("/api/stats")
def api_get_stats():
    """常数级状态查询，不遍历行情文件。"""
    try:
        from utils.decision_ledger import get_latest_decision
        from utils.operations_store import scheduler_status

        current = load_current_market_snapshot("data", verify_files=False)
        manifest = current.get("manifest") or {}
        decision = get_latest_decision("close")
        return jsonify(
            {
                "success": True,
                "data": {
                    "total_stocks": manifest.get("valid_count", 0),
                    "latest_date": manifest.get("trade_date", "-"),
                    "snapshot_id": current.get("snapshot_id"),
                    "decision_run_id": decision.get("run_id") if decision else None,
                    "decision_trade_date": decision.get("trade_date")
                    if decision
                    else None,
                    "total_views": 0,
                    "active_views": 0,
                    "legacy_views_enabled": False,
                    "scheduler_running": scheduler_status().get("running", False),
                },
            }
        )
    except Exception as exc:
        logger.error("读取系统状态失败: %s", exc, exc_info=True)
        return jsonify({"success": False, "error": "status_unavailable"}), 500


@app.get("/healthz")
def healthz():
    """仅表示 Web 进程可响应，不触发磁盘扫描或外部请求。"""
    return jsonify({"status": "ok"})


@app.get("/api/version")
def api_version():
    from utils.decision_versions import git_commit_sha, strategy_version

    snapshot = load_current_market_snapshot("data", verify_files=False)
    return jsonify(
        {
            "git_commit_sha": git_commit_sha(),
            "strategy_version": strategy_version(),
            "snapshot_id": snapshot.get("snapshot_id"),
            "snapshot_available": bool(snapshot.get("available")),
        }
    )


@app.get("/readyz")
def readyz():
    from utils.data_freshness import local_data_status
    from utils.operations_store import alert_summary, scheduler_status

    freshness = local_data_status()
    scheduler = scheduler_status()
    ready = freshness.get("fresh") is True and scheduler.get("running") is True
    return jsonify(
        {
            "ready": ready,
            "market_data": freshness,
            "scheduler": scheduler,
            "alerts": alert_summary(),
        }
    ), (200 if ready else 503)


@app.get("/api/stocks")
def api_get_stocks():
    """分页读取快照目录；每只股票最多读取一行。"""
    try:
        try:
            page = int(request.args.get("page", 1))
            per_page = int(request.args.get("per_page", 50))
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": "invalid_pagination"}), 400
        if page < 1 or per_page < 1 or per_page > 100:
            return jsonify({"success": False, "error": "invalid_pagination"}), 400

        manager, current = _snapshot_context()
        if not current.get("available"):
            return jsonify({"success": False, "error": "snapshot_unavailable"}), 503
        manifest = current.get("manifest") or {}
        files = manifest.get("files") or {}
        stocks = sorted(code for code in files if _valid_stock_code(str(code)))
        names = _load_stock_names(manager)
        caps = _load_market_caps(manager)
        start = (page - 1) * per_page
        selected = stocks[start : start + per_page]

        rows = []
        for code in selected:
            frame = manager.read_stock(code, nrows=1)
            if frame.empty:
                continue
            latest = frame.iloc[0]
            date = pd.to_datetime(latest.get("date"), errors="coerce")
            rows.append(
                {
                    "code": code,
                    "name": names.get(code, "未知"),
                    "latest_price": round(_finite_number(latest.get("close")), 2),
                    "latest_date": date.strftime("%Y-%m-%d")
                    if pd.notna(date)
                    else None,
                    "market_cap": _market_cap_yi(caps.get(code)),
                    "data_count": int((files.get(code) or {}).get("rows") or 0),
                    "snapshot_id": current.get("snapshot_id"),
                }
            )

        total = len(stocks)
        return jsonify(
            {
                "success": True,
                "data": rows,
                "total": total,
                "page": page,
                "per_page": per_page,
                "total_pages": (total + per_page - 1) // per_page,
                "snapshot_id": current.get("snapshot_id"),
            }
        )
    except Exception as exc:
        logger.error("读取股票列表失败: %s", exc, exc_info=True)
        return jsonify({"success": False, "error": "stock_list_unavailable"}), 500


@app.get("/api/stock/<code>")
def api_get_stock_detail(code: str):
    if not _valid_stock_code(code):
        return jsonify({"success": False, "error": "invalid_stock_code"}), 400
    try:
        from utils.technical import KDJ

        manager, current = _snapshot_context()
        if not current.get("available"):
            return jsonify({"success": False, "error": "snapshot_unavailable"}), 503
        frame = manager.read_stock(code, nrows=120)
        if frame.empty:
            return jsonify({"success": False, "error": "stock_not_found"}), 404
        kdj = KDJ(frame, n=9, m1=3, m2=3)
        cap_yi = _market_cap_yi(_load_market_caps(manager).get(code))
        rows = []
        for index, (_, row) in enumerate(frame.head(100).iterrows()):
            date = pd.to_datetime(row.get("date"), errors="coerce")
            rows.append(
                {
                    "date": date.strftime("%Y-%m-%d") if pd.notna(date) else None,
                    "open": round(_finite_number(row.get("open")), 2),
                    "high": round(_finite_number(row.get("high")), 2),
                    "low": round(_finite_number(row.get("low")), 2),
                    "close": round(_finite_number(row.get("close")), 2),
                    "volume": int(_finite_number(row.get("volume"))),
                    "amount": round(_finite_number(row.get("amount")) / 1e4, 2),
                    "turnover": round(_finite_number(row.get("turnover")), 2),
                    "market_cap": cap_yi,
                    "K": round(_finite_number(kdj.iloc[index].get("K")), 2),
                    "D": round(_finite_number(kdj.iloc[index].get("D")), 2),
                    "J": round(_finite_number(kdj.iloc[index].get("J")), 2),
                }
            )
        return jsonify({"success": True, "code": code, "data": rows})
    except Exception as exc:
        logger.error("读取股票详情失败 [%s]: %s", code, exc, exc_info=True)
        return jsonify({"success": False, "error": "stock_detail_unavailable"}), 500


@app.get("/api/stock/<code>/kline")
def api_get_stock_kline(code: str):
    """读取有上限的日线或周线；历史信号只取 canonical outcome。"""
    if not _valid_stock_code(code):
        return jsonify({"success": False, "error": "invalid_stock_code"}), 400
    period = request.args.get("period", "daily")
    if period not in {"daily", "weekly"}:
        return jsonify({"success": False, "error": "invalid_period"}), 400
    default_days = 200 if period == "daily" else 2000
    try:
        days = int(request.args.get("days", default_days))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "invalid_days"}), 400
    if days < 1 or days > 5000:
        return jsonify({"success": False, "error": "invalid_days"}), 400

    try:
        from utils.technical import KDJ

        manager, current = _snapshot_context()
        if not current.get("available"):
            return jsonify({"success": False, "error": "snapshot_unavailable"}), 503
        names = _load_stock_names(manager)
        frame = manager.read_stock(code, nrows=days)
        if frame.empty:
            return jsonify({"success": False, "error": "stock_not_found"}), 404
        data_frame = frame.iloc[::-1].reset_index(drop=True)
        as_of = pd.to_datetime(data_frame["date"], errors="coerce").max()
        week_end = None
        current_week_partial = False

        if period == "weekly":
            data_frame["date"] = pd.to_datetime(data_frame["date"], errors="coerce")
            weekly = (
                data_frame.dropna(subset=["date"])
                .resample("W-FRI", on="date")
                .agg(
                    open=("open", "first"),
                    high=("high", "max"),
                    low=("low", "min"),
                    close=("close", "last"),
                    volume=("volume", "sum"),
                )
                .dropna(subset=["open"])
            )
            if not weekly.empty:
                week_end = weekly.index[-1]
                current_week_partial = bool(as_of.normalize() < week_end.normalize())
            for window in (5, 10, 20, 60):
                weekly[f"MA{window}"] = weekly["close"].rolling(window).mean()
            close = weekly["close"].astype(float)
            weekly["trend_line"] = (
                close.ewm(span=10, adjust=False)
                .mean()
                .ewm(
                    span=10,
                    adjust=False,
                )
                .mean()
            )
            weekly["dk_line"] = (
                sum(close.rolling(window).mean() for window in (14, 28, 57, 114)) / 4
            )
            data = [
                [
                    date.strftime("%Y-%m-%d"),
                    round(_finite_number(row["open"]), 2),
                    round(_finite_number(row["close"]), 2),
                    round(_finite_number(row["low"]), 2),
                    round(_finite_number(row["high"]), 2),
                    int(_finite_number(row["volume"])),
                    *[
                        round(float(row[key]), 2) if pd.notna(row[key]) else None
                        for key in (
                            "MA5",
                            "MA10",
                            "MA20",
                            "MA60",
                            "trend_line",
                            "dk_line",
                        )
                    ],
                ]
                for date, row in weekly.iterrows()
            ]
        else:
            kdj = KDJ(data_frame, n=9, m1=3, m2=3)
            close = data_frame["close"].astype(float)
            trend = (
                close.ewm(span=10, adjust=False)
                .mean()
                .ewm(
                    span=10,
                    adjust=False,
                )
                .mean()
            )
            dk_line = (
                sum(close.rolling(window).mean() for window in (14, 28, 57, 114)) / 4
            )
            data = []
            for index, (_, row) in enumerate(data_frame.iterrows()):
                date = pd.to_datetime(row.get("date"), errors="coerce")
                data.append(
                    [
                        date.strftime("%Y-%m-%d") if pd.notna(date) else None,
                        round(_finite_number(row.get("open")), 2),
                        round(_finite_number(row.get("close")), 2),
                        round(_finite_number(row.get("low")), 2),
                        round(_finite_number(row.get("high")), 2),
                        int(_finite_number(row.get("volume"))),
                        round(_finite_number(kdj.iloc[index].get("K")), 2),
                        round(_finite_number(kdj.iloc[index].get("D")), 2),
                        round(_finite_number(kdj.iloc[index].get("J")), 2),
                        round(float(trend.iloc[index]), 2)
                        if pd.notna(trend.iloc[index])
                        else None,
                        round(float(dk_line.iloc[index]), 2)
                        if pd.notna(dk_line.iloc[index])
                        else None,
                    ]
                )

        signals = []
        try:
            from utils.decision_ledger import list_decision_outcomes

            signals = [
                {
                    "date": item["trade_date"],
                    "category": item["action"],
                    "status": item["status"],
                }
                for item in list_decision_outcomes(limit=200)
                if item.get("code") == code
            ]
        except Exception as exc:
            logger.debug("读取 canonical 历史信号失败 [%s]: %s", code, exc)

        return jsonify(
            {
                "success": True,
                "code": code,
                "name": names.get(code, "未知"),
                "period": period,
                "as_of": as_of.strftime("%Y-%m-%d"),
                "week_end": week_end.strftime("%Y-%m-%d")
                if week_end is not None
                else None,
                "current_week_partial": current_week_partial,
                "change_label": "本周涨跌" if period == "weekly" else "今日涨跌",
                "data": data,
                "signals": signals,
            }
        )
    except Exception as exc:
        logger.error("读取 K 线失败 [%s]: %s", code, exc, exc_info=True)
        return jsonify({"success": False, "error": "kline_unavailable"}), 500


@app.get("/api/ranking")
def api_get_ranking():
    """只返回与当前快照、日期和策略版本严格绑定的收盘决策。"""
    from views.quant_pick_api import _current_close_decision

    decision, freshness, reason = _current_close_decision()
    if decision is None:
        return jsonify(
            {
                "success": False,
                "error": reason,
                "data": [],
                "total": 0,
                "run_date": freshness.get("local_date"),
            }
        ), 503
    candidates = []
    for item in decision.get("candidates") or []:
        baseline = item.get("baseline") or {}
        candidates.append(
            {
                "code": item.get("code"),
                "name": item.get("name"),
                "category": "canonical_policy",
                "close": baseline.get("close"),
                "J": baseline.get("J"),
                "volume_ratio": None,
                "market_cap": baseline.get("cap_yi"),
                "industry": item.get("industry"),
                "similarity_score": None,
                "matched_case": None,
                "match_breakdown": None,
                "views": ["canonical-policy"],
                "run_date": decision["trade_date"],
                "action": item.get("action"),
                "reason_codes": item.get("reason_codes") or [],
                "decision_run_id": decision.get("run_id"),
            }
        )
    return jsonify(
        {
            "success": True,
            "data": candidates,
            "total": len(candidates),
            "run_date": decision["trade_date"],
            "snapshot_id": freshness.get("snapshot_id"),
        }
    )


@app.get("/api/stock/<code>/profile")
def api_get_stock_profile(code: str):
    """只组合当前快照中的名称、行业和市值；GET 不联网、不写缓存。"""
    if not _valid_stock_code(code):
        return jsonify({"success": False, "error": "invalid_stock_code"}), 400
    try:
        manager, current = _snapshot_context()
        files = (current.get("manifest") or {}).get("files") or {}
        if not current.get("available") or code not in files:
            return jsonify({"success": False, "error": "stock_not_found"}), 404
        profile = {
            "code": code,
            "name": _load_stock_names(manager).get(code, "未知"),
            "industry": _get_cached_industry(manager).get(code, "未知"),
            "board": _board_name(code),
            "market_cap": _market_cap_yi(_load_market_caps(manager).get(code)),
            "business": "",
            "listing_date": None,
            "profile_source": "immutable_market_snapshot",
            "snapshot_id": current.get("snapshot_id"),
            "as_of": (current.get("manifest") or {}).get("trade_date"),
        }
        return jsonify({"success": True, "data": profile})
    except Exception as exc:
        logger.error("读取股票资料失败 [%s]: %s", code, exc, exc_info=True)
        return jsonify({"success": False, "error": "stock_profile_unavailable"}), 500


@app.get("/api/industries")
def api_get_industries():
    try:
        manager, current = _snapshot_context()
        if not current.get("available"):
            return jsonify({"success": False, "error": "snapshot_unavailable"}), 503
        summary = get_industry_summary(_get_cached_industry(manager))
        return jsonify({"success": True, "data": summary, "total": len(summary)})
    except Exception as exc:
        logger.error("读取行业统计失败: %s", exc, exc_info=True)
        return jsonify({"success": False, "error": "industries_unavailable"}), 500


@app.post("/api/data/update")
@require_role("admin")
def api_update_data():
    """提交持久任务；Web 请求内不抓行情。"""
    from utils.task_submission import submit_task

    return submit_task("daily_market_ingestion")


def _initialize_app_state() -> None:
    """只读校验生产账本；迁移必须由独立命令先完成。"""
    from utils.runtime_schema import verify_runtime_schema

    verify_runtime_schema()


def run_web_server(
    host: str = "127.0.0.1",
    port: int = 5000,
    debug: bool = False,
    auto_schedule: bool = False,
) -> None:
    if auto_schedule:
        raise RuntimeError("scheduler_must_run_in_dedicated_worker")
    _initialize_app_state()
    logger.info("Web 服务器启动: http://%s:%d", host, port)
    app.run(host=host, port=port, debug=debug)


def create_app():
    """Gunicorn factory；调度器只允许在独立 worker 中启动。"""
    _initialize_app_state()
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_web_server(debug=False, auto_schedule=False)
