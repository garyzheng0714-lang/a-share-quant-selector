"""
Web 服务器 - A股量化选股系统

包含：
- 多视图管理 API
- 选股执行 API
- APScheduler 定时任务
"""
import gc
import json
import logging
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import numpy as np
import yaml
from flask import Flask, jsonify, render_template, request


def _to_python(val):
    """将 numpy 类型转为 Python 原生类型."""
    if isinstance(val, (np.integer,)):
        return int(val)
    if isinstance(val, (np.floating,)):
        return float(val)
    if isinstance(val, np.ndarray):
        return val.tolist()
    return val

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from utils.csv_manager import CSVManager
from strategy.strategy_registry import StrategyRegistry
from strategy.pattern_library import B1PatternLibrary
from views.view_manager import (
    create_view,
    delete_view,
    duplicate_view,
    get_result_by_date,
    get_results,
    get_view,
    init_db,
    list_views,
    save_result,
    update_view,
)

logger = logging.getLogger(__name__)

app = Flask(
    __name__,
    template_folder="web/templates",
    static_folder="web/static",
)

csv_manager = CSVManager("data")

# 全局调度器状态
scheduler_instance = None
scheduler_lock = threading.Lock()
running_tasks: dict[int, str] = {}  # view_id -> status

# 异步选股任务
selection_tasks: dict[str, dict] = {}
_executor = ThreadPoolExecutor(max_workers=2)

# B1 图形库单例（懒初始化）
_b1_library: B1PatternLibrary | None = None
_b1_library_lock = threading.Lock()

# 缓存
_stock_list_cache: list | None = None
_stock_list_cache_ts: float = 0
_stock_names_cache: dict | None = None
_stock_names_cache_ts: float = 0
_CACHE_TTL = 3600  # 1 小时


def _load_stock_names() -> dict:
    """加载股票名称映射."""
    names_file = Path("data/stock_names.json")
    if names_file.exists():
        with open(names_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _get_cached_stock_list() -> list:
    """获取缓存的股票列表."""
    global _stock_list_cache, _stock_list_cache_ts
    now = time.time()
    if _stock_list_cache is None or now - _stock_list_cache_ts > _CACHE_TTL:
        _stock_list_cache = csv_manager.list_all_stocks()
        _stock_list_cache_ts = now
    return _stock_list_cache


def _get_cached_stock_names() -> dict:
    """获取缓存的股票名称映射."""
    global _stock_names_cache, _stock_names_cache_ts
    now = time.time()
    if _stock_names_cache is None or now - _stock_names_cache_ts > _CACHE_TTL:
        _stock_names_cache = _load_stock_names()
        _stock_names_cache_ts = now
    return _stock_names_cache


def _get_b1_library() -> B1PatternLibrary:
    """获取 B1 图形库单例（线程安全懒初始化）.

    Returns:
        B1PatternLibrary 实例
    """
    global _b1_library
    if _b1_library is None:
        with _b1_library_lock:
            if _b1_library is None:
                cache_path = Path("data") / "b1_pattern_library_cache.json"
                B1PatternLibrary.CACHE_FILE = cache_path
                _b1_library = B1PatternLibrary(csv_manager)
                logger.info(
                    "B1 图形库初始化完成，案例数: %d", len(_b1_library.cases)
                )
    return _b1_library


def _build_registry(params: dict) -> StrategyRegistry:
    """根据视图参数构建策略注册器.

    Args:
        params: BowlReboundStrategy 参数字典

    Returns:
        配置好的策略注册器
    """
    registry = StrategyRegistry.__new__(StrategyRegistry)
    registry.strategies = {}
    registry.params_file = Path("config/strategy_params.yaml")
    registry.params = {"BowlReboundStrategy": params}
    registry.auto_register_from_directory("strategy")
    return registry


def _run_selection_core(view_id: int, progress_cb=None) -> dict:
    """核心选股逻辑（同时供同步和异步调用）.

    Args:
        view_id: 视图 ID
        progress_cb: 进度回调 (current, total, phase) -> None

    Returns:
        选股结果字典
    """
    view = get_view(view_id)
    if view is None:
        return {"error": "视图不存在"}

    params = view["params"]
    b1_enabled = view.get("b1_enabled", False)
    registry = _build_registry(params)

    stock_codes = _get_cached_stock_list()
    stock_names = _get_cached_stock_names()

    invalid_keywords = ["退", "未知", "退市", "已退"]
    valid_stocks = []
    for code in stock_codes:
        name = stock_names.get(code, "未知")
        if not any(kw in name for kw in invalid_keywords):
            valid_stocks.append((code, name))

    total = len(valid_stocks)
    cap_threshold = params.get("CAP", 4000000000)

    results_list = []
    category_count = {
        "bowl_center": 0,
        "near_duokong": 0,
        "near_short_trend": 0,
    }

    # ---- Phase 1: 扫描股票 ----
    for strategy_name, strategy in registry.strategies.items():
        for i, (code, name) in enumerate(valid_stocks, 1):
            if progress_cb:
                progress_cb(i, total, "扫描股票")

            df = csv_manager.read_stock(code, nrows=200)
            if df.empty or len(df) < 60:
                continue

            latest_cap = df.iloc[0].get("market_cap", 0)
            if latest_cap <= cap_threshold:
                del df
                continue

            df_with_indicators = strategy.calculate_indicators(df)
            signal_list = strategy.select_stocks(df_with_indicators, name)

            if signal_list:
                for s in signal_list:
                    cat = s.get("category", "unknown")
                    category_count[cat] = category_count.get(cat, 0) + 1
                    results_list.append({
                        "code": code,
                        "name": name,
                        "strategy": strategy_name,
                        "category": cat,
                        "close": _to_python(s.get("close")),
                        "J": _to_python(s.get("J")),
                        "volume_ratio": _to_python(s.get("volume_ratio")),
                        "market_cap": _to_python(s.get("market_cap")),
                        "short_term_trend": _to_python(s.get("short_term_trend")),
                        "bull_bear_line": _to_python(s.get("bull_bear_line")),
                        "reasons": s.get("reasons", []),
                        "similarity_score": None,
                        "matched_case": None,
                        "match_breakdown": None,
                    })

            del df, df_with_indicators
            if i % 500 == 0:
                gc.collect()

    # ---- Phase 2: B1 图形拟合 ----
    if b1_enabled and results_list:
        try:
            library = _get_b1_library()
            b1_total = len(results_list)

            for idx, stock in enumerate(results_list, 1):
                if progress_cb:
                    progress_cb(idx, b1_total, "图形拟合")

                try:
                    df = csv_manager.read_stock(stock["code"], nrows=200)
                    if df.empty or len(df) < 25:
                        continue

                    match_result = library.find_best_match(
                        stock["code"], df, lookback_days=25
                    )
                    best = match_result.get("best_match")

                    if best is not None:
                        stock["similarity_score"] = _to_python(
                            best["similarity_score"]
                        )
                        stock["matched_case"] = best["case_name"]
                        stock["match_breakdown"] = {
                            k: _to_python(v)
                            for k, v in best["breakdown"].items()
                        }

                    del df
                except Exception as e:
                    logger.error(
                        "B1 匹配失败 [%s]: %s", stock["code"], e
                    )

        except Exception as e:
            logger.error("B1 图形库初始化失败: %s", e)

    run_date = datetime.now().strftime("%Y-%m-%d")
    save_result(view_id, run_date, results_list, params)

    return {
        "view_id": view_id,
        "view_name": view["name"],
        "run_date": run_date,
        "total": len(results_list),
        "category_count": category_count,
        "stocks": results_list,
    }


def _run_selection_for_view(view_id: int) -> dict:
    """同步选股（调度器使用）."""
    return _run_selection_core(view_id)


def _run_selection_async(view_id: int, task_id: str) -> None:
    """异步选股后台线程."""
    def progress_cb(current: int, total: int, phase: str = "扫描股票") -> None:
        selection_tasks[task_id]["progress"] = current
        selection_tasks[task_id]["total"] = total
        selection_tasks[task_id]["phase"] = phase

    try:
        selection_tasks[task_id]["status"] = "running"
        result = _run_selection_core(view_id, progress_cb=progress_cb)

        if "error" in result:
            selection_tasks[task_id]["status"] = "error"
            selection_tasks[task_id]["error"] = result["error"]
        else:
            selection_tasks[task_id]["status"] = "done"
            selection_tasks[task_id]["result"] = result
    except Exception as e:
        selection_tasks[task_id]["status"] = "error"
        selection_tasks[task_id]["error"] = str(e)
        logger.error("异步选股失败: %s", e)


# ==================== 页面路由 ====================


@app.route("/")
def index():
    """主页."""
    return render_template("index.html")


# ==================== 视图管理 API ====================


@app.route("/api/views", methods=["GET"])
def api_list_views():
    """获取所有视图."""
    try:
        views = list_views()
        return jsonify({"success": True, "data": views})
    except Exception as e:
        logger.error("获取视图列表失败: %s", e)
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/views", methods=["POST"])
def api_create_view():
    """创建新视图."""
    try:
        body = request.json or {}
        name = body.get("name", "").strip()
        if not name:
            return jsonify({"success": False, "error": "名称不能为空"})

        source_id = body.get("source_id")
        if source_id:
            view = duplicate_view(int(source_id), name)
        else:
            view = create_view(
                name=name,
                params=body.get("params"),
                b1_params=body.get("b1_params"),
                b1_enabled=body.get("b1_enabled", False),
            )
        if view is None:
            return jsonify({"success": False, "error": "创建失败"})
        return jsonify({"success": True, "data": view})
    except Exception as e:
        logger.error("创建视图失败: %s", e)
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/views/<int:view_id>", methods=["GET"])
def api_get_view(view_id):
    """获取视图详情."""
    try:
        view = get_view(view_id)
        if view is None:
            return jsonify({"success": False, "error": "视图不存在"})
        return jsonify({"success": True, "data": view})
    except Exception as e:
        logger.error("获取视图详情失败: %s", e)
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/views/<int:view_id>", methods=["PUT"])
def api_update_view(view_id):
    """更新视图."""
    try:
        body = request.json or {}
        view = update_view(
            view_id,
            name=body.get("name"),
            params=body.get("params"),
            b1_params=body.get("b1_params"),
            b1_enabled=body.get("b1_enabled"),
            is_active=body.get("is_active"),
        )
        if view is None:
            return jsonify({"success": False, "error": "视图不存在"})
        return jsonify({"success": True, "data": view})
    except Exception as e:
        logger.error("更新视图失败: %s", e)
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/views/<int:view_id>", methods=["DELETE"])
def api_delete_view(view_id):
    """删除视图."""
    try:
        view = get_view(view_id)
        if view and view["name"] == "默认策略":
            return jsonify({"success": False, "error": "不能删除默认策略"})
        ok = delete_view(view_id)
        return jsonify({"success": ok})
    except Exception as e:
        logger.error("删除视图失败: %s", e)
        return jsonify({"success": False, "error": str(e)})


# ==================== 选股执行 API ====================


@app.route("/api/views/<int:view_id>/run", methods=["POST"])
def api_run_selection(view_id):
    """异步触发选股，立即返回 task_id."""
    try:
        # 检查是否已有该视图的运行任务
        for tid, task in selection_tasks.items():
            if (
                task.get("view_id") == view_id
                and task["status"] == "running"
            ):
                return jsonify({
                    "success": True,
                    "task_id": tid,
                    "status": "running",
                })

        task_id = uuid.uuid4().hex[:8]
        selection_tasks[task_id] = {
            "view_id": view_id,
            "status": "starting",
            "progress": 0,
            "total": 0,
            "phase": "扫描股票",
            "result": None,
            "error": None,
        }

        _executor.submit(_run_selection_async, view_id, task_id)

        return jsonify({
            "success": True,
            "task_id": task_id,
            "status": "starting",
        })
    except Exception as e:
        logger.error("启动选股任务失败: %s", e)
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/views/<int:view_id>/run/status", methods=["GET"])
def api_run_status(view_id):
    """轮询选股任务进度."""
    task_id = request.args.get("task_id")
    task = selection_tasks.get(task_id)
    if not task:
        return jsonify({"success": False, "error": "任务不存在"})

    response = {
        "success": True,
        "status": task["status"],
        "progress": task["progress"],
        "total": task["total"],
        "phase": task.get("phase", "扫描股票"),
    }

    if task["status"] == "done":
        response["data"] = task["result"]
        selection_tasks.pop(task_id, None)
    elif task["status"] == "error":
        response["error"] = task["error"]
        selection_tasks.pop(task_id, None)

    return jsonify(response)


@app.route("/api/views/<int:view_id>/results", methods=["GET"])
def api_get_results(view_id):
    """获取某视图的历史结果."""
    try:
        limit = int(request.args.get("limit", 30))
        results = get_results(view_id, limit=limit)
        return jsonify({"success": True, "data": results})
    except Exception as e:
        logger.error("获取结果失败: %s", e)
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/views/<int:view_id>/results/<run_date>", methods=["GET"])
def api_get_result_by_date(view_id, run_date):
    """获取某日选股详情."""
    try:
        result = get_result_by_date(view_id, run_date)
        if result is None:
            return jsonify({"success": False, "error": "无该日结果"})
        return jsonify({"success": True, "data": result})
    except Exception as e:
        logger.error("获取结果详情失败: %s", e)
        return jsonify({"success": False, "error": str(e)})


# ==================== 系统状态 API ====================


@app.route("/api/stats", methods=["GET"])
def api_get_stats():
    """获取系统统计."""
    try:
        stocks = csv_manager.list_all_stocks()
        import pandas as pd

        dates = []
        for code in stocks[:50]:
            df = csv_manager.read_stock(code)
            if not df.empty:
                dates.append(df.iloc[0]["date"])

        latest_date = max(dates).strftime("%Y-%m-%d") if dates else "-"
        views = list_views()

        return jsonify({
            "success": True,
            "data": {
                "total_stocks": len(stocks),
                "latest_date": latest_date,
                "total_views": len(views),
                "active_views": sum(1 for v in views if v["is_active"]),
                "scheduler_running": scheduler_instance is not None,
            },
        })
    except Exception as e:
        logger.error("获取统计信息失败: %s", e)
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/stocks", methods=["GET"])
def api_get_stocks():
    """获取股票列表."""
    try:
        stocks = csv_manager.list_all_stocks()
        stock_names = _load_stock_names()

        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 500))

        start_idx = (page - 1) * per_page
        paginated = stocks[start_idx : start_idx + per_page]

        stock_list = []
        for code in paginated:
            df = csv_manager.read_stock(code)
            if not df.empty:
                latest = df.iloc[0]
                stock_list.append({
                    "code": code,
                    "name": stock_names.get(code, "未知"),
                    "latest_price": round(latest["close"], 2),
                    "latest_date": latest["date"].strftime("%Y-%m-%d"),
                    "market_cap": round(
                        latest.get("market_cap", 0) / 1e8, 2
                    ),
                    "data_count": len(df),
                })

        return jsonify({
            "success": True,
            "data": stock_list,
            "total": len(stocks),
            "page": page,
            "per_page": per_page,
            "total_pages": (len(stocks) + per_page - 1) // per_page,
        })
    except Exception as e:
        logger.error("获取股票列表失败: %s", e)
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/stock/<code>", methods=["GET"])
def api_get_stock_detail(code):
    """获取单只股票详情."""
    try:
        df = csv_manager.read_stock(code)
        if df.empty:
            return jsonify({"success": False, "error": "股票不存在"})

        from utils.technical import KDJ

        kdj_df = KDJ(df, n=9, m1=3, m2=3)

        data = []
        for i, (_, row) in enumerate(df.head(100).iterrows()):
            data.append({
                "date": row["date"].strftime("%Y-%m-%d"),
                "open": round(row["open"], 2),
                "high": round(row["high"], 2),
                "low": round(row["low"], 2),
                "close": round(row["close"], 2),
                "volume": int(row["volume"]),
                "amount": round(row["amount"] / 1e4, 2),
                "turnover": round(row.get("turnover", 0), 2),
                "market_cap": round(row.get("market_cap", 0) / 1e8, 2),
                "K": round(kdj_df.iloc[i]["K"], 2),
                "D": round(kdj_df.iloc[i]["D"], 2),
                "J": round(kdj_df.iloc[i]["J"], 2),
            })

        return jsonify({"success": True, "code": code, "data": data})
    except Exception as e:
        logger.error("获取股票详情失败: %s", e)
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/stock/<code>/kline", methods=["GET"])
def api_get_stock_kline(code):
    """获取股票K线数据（日线或周线）.

    Query params:
        period: "daily" (default) or "weekly"
        days: number of daily data points (default 200 for daily, 500 for weekly)
    """
    try:
        import pandas as pd
        from utils.technical import KDJ

        period = request.args.get("period", "daily")
        stock_names = _load_stock_names()
        stock_name = stock_names.get(code, "未知")

        df = csv_manager.read_stock(code)
        if df.empty:
            return jsonify({"success": False, "error": "股票不存在"})

        default_days = 200 if period == "daily" else 500
        days = int(request.args.get("days", default_days))

        # CSV is stored newest-first; take top N rows then reverse to chronological
        df_slice = df.head(days).iloc[::-1].reset_index(drop=True)

        if period == "weekly":
            df_slice["date"] = pd.to_datetime(df_slice["date"])
            weekly = df_slice.resample("W", on="date").agg(
                open=("open", "first"),
                high=("high", "max"),
                low=("low", "min"),
                close=("close", "last"),
                volume=("volume", "sum"),
            ).dropna(subset=["open"])

            weekly["MA5"] = weekly["close"].rolling(window=5).mean()
            weekly["MA10"] = weekly["close"].rolling(window=10).mean()
            weekly["MA20"] = weekly["close"].rolling(window=20).mean()
            weekly["MA60"] = weekly["close"].rolling(window=60).mean()

            w_close = weekly["close"].astype(float)
            w_ema10 = w_close.ewm(span=10, adjust=False).mean()
            weekly["trend_line"] = w_ema10.ewm(span=10, adjust=False).mean()

            w_ma14 = w_close.rolling(window=14).mean()
            w_ma28 = w_close.rolling(window=28).mean()
            w_ma57 = w_close.rolling(window=57).mean()
            w_ma114 = w_close.rolling(window=114).mean()
            weekly["dk_line"] = (w_ma14 + w_ma28 + w_ma57 + w_ma114) / 4

            data = []
            for date_idx, row in weekly.iterrows():
                data.append([
                    date_idx.strftime("%Y-%m-%d"),
                    round(float(row["open"]), 2),
                    round(float(row["close"]), 2),
                    round(float(row["low"]), 2),
                    round(float(row["high"]), 2),
                    int(row["volume"]),
                    round(float(row["MA5"]), 2) if pd.notna(row["MA5"]) else None,
                    round(float(row["MA10"]), 2) if pd.notna(row["MA10"]) else None,
                    round(float(row["MA20"]), 2) if pd.notna(row["MA20"]) else None,
                    round(float(row["MA60"]), 2) if pd.notna(row["MA60"]) else None,
                    round(float(row["trend_line"]), 2) if pd.notna(row["trend_line"]) else None,
                    round(float(row["dk_line"]), 2) if pd.notna(row["dk_line"]) else None,
                ])
        else:
            kdj_df = KDJ(df_slice, n=9, m1=3, m2=3)

            close_s = df_slice["close"].astype(float)
            ema10 = close_s.ewm(span=10, adjust=False).mean()
            trend_line = ema10.ewm(span=10, adjust=False).mean()

            ma14 = close_s.rolling(window=14).mean()
            ma28 = close_s.rolling(window=28).mean()
            ma57 = close_s.rolling(window=57).mean()
            ma114 = close_s.rolling(window=114).mean()
            dk_line = (ma14 + ma28 + ma57 + ma114) / 4

            data = []
            for i, (_, row) in enumerate(df_slice.iterrows()):
                tl = trend_line.iloc[i]
                dk = dk_line.iloc[i]
                data.append([
                    row["date"].strftime("%Y-%m-%d")
                    if hasattr(row["date"], "strftime")
                    else str(row["date"])[:10],
                    round(float(row["open"]), 2),
                    round(float(row["close"]), 2),
                    round(float(row["low"]), 2),
                    round(float(row["high"]), 2),
                    int(row["volume"]),
                    round(float(kdj_df.iloc[i]["K"]), 2),
                    round(float(kdj_df.iloc[i]["D"]), 2),
                    round(float(kdj_df.iloc[i]["J"]), 2),
                    round(float(tl), 2) if pd.notna(tl) else None,
                    round(float(dk), 2) if pd.notna(dk) else None,
                ])

        return jsonify({
            "success": True,
            "code": code,
            "name": stock_name,
            "period": period,
            "data": data,
        })
    except Exception as e:
        logger.error("获取K线数据失败: %s", e)
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/ranking", methods=["GET"])
def api_get_ranking():
    """获取综合排名（合并所有活跃视图最新结果）."""
    try:
        views = list_views()
        active_views = [v for v in views if v["is_active"]]

        category_priority = {
            "bowl_center": 0,
            "near_duokong": 1,
            "near_short_trend": 2,
        }

        stock_map: dict[str, dict] = {}
        run_date = ""

        for view in active_views:
            results = get_results(view["id"], limit=1)
            if not results:
                continue
            latest = results[0]
            if latest["run_date"] > run_date:
                run_date = latest["run_date"]

            for stock in latest.get("stocks", []):
                sc = stock.get("code", "")
                if sc in stock_map:
                    existing_views = stock_map[sc]["views"]
                    if view["name"] not in existing_views:
                        existing_views.append(view["name"])
                else:
                    bd = stock.get("match_breakdown")
                    stock_map[sc] = {
                        "code": sc,
                        "name": stock.get("name", ""),
                        "category": stock.get("category", "unknown"),
                        "close": _to_python(stock.get("close")),
                        "J": _to_python(stock.get("J")),
                        "volume_ratio": _to_python(
                            stock.get("volume_ratio")
                        ),
                        "market_cap": _to_python(
                            stock.get("market_cap")
                        ),
                        "similarity_score": _to_python(
                            stock.get("similarity_score")
                        ),
                        "matched_case": stock.get("matched_case"),
                        "match_breakdown": {
                            k: _to_python(v)
                            for k, v in bd.items()
                        } if isinstance(bd, dict) else None,
                        "views": [view["name"]],
                        "run_date": latest["run_date"],
                    }

        ranked = sorted(
            stock_map.values(),
            key=lambda s: (
                category_priority.get(s["category"], 99),
                s.get("J") if s.get("J") is not None else float("inf"),
            ),
        )

        return jsonify({
            "success": True,
            "data": ranked,
            "total": len(ranked),
            "run_date": run_date,
        })
    except Exception as e:
        logger.error("获取综合排名失败: %s", e)
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/data/update", methods=["POST"])
def api_update_data():
    """手动触发数据更新."""
    try:
        from utils.akshare_fetcher import AKShareFetcher

        fetcher = AKShareFetcher("data")
        fetcher.daily_update()
        return jsonify({
            "success": True,
            "message": "数据更新完成",
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
    except Exception as e:
        logger.error("数据更新失败: %s", e)
        return jsonify({"success": False, "error": str(e)})


# ==================== 调度器 API ====================


@app.route("/api/scheduler/status", methods=["GET"])
def api_scheduler_status():
    """获取调度器状态."""
    return jsonify({
        "success": True,
        "data": {
            "running": scheduler_instance is not None,
            "running_tasks": dict(running_tasks),
        },
    })


@app.route("/api/scheduler/start", methods=["POST"])
def api_start_scheduler():
    """启动调度器."""
    try:
        _start_scheduler()
        return jsonify({"success": True, "message": "调度器已启动"})
    except Exception as e:
        logger.error("启动调度器失败: %s", e)
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/scheduler/stop", methods=["POST"])
def api_stop_scheduler():
    """停止调度器."""
    try:
        _stop_scheduler()
        return jsonify({"success": True, "message": "调度器已停止"})
    except Exception as e:
        logger.error("停止调度器失败: %s", e)
        return jsonify({"success": False, "error": str(e)})


# ==================== 调度器管理 ====================


def _scheduled_job():
    """定时执行的选股任务."""
    logger.info("定时任务开始执行")

    # 先更新数据
    try:
        from utils.akshare_fetcher import AKShareFetcher

        fetcher = AKShareFetcher("data")
        fetcher.daily_update()
        logger.info("数据更新完成")
    except Exception as e:
        logger.error("定时数据更新失败: %s", e)

    # 遍历所有活跃视图
    views = list_views()
    for view in views:
        if not view["is_active"]:
            continue
        try:
            logger.info("执行视图 [%s] 选股", view["name"])
            _run_selection_for_view(view["id"])
            logger.info("视图 [%s] 选股完成", view["name"])
        except Exception as e:
            logger.error("视图 [%s] 选股失败: %s", view["name"], e)

    logger.info("定时任务执行完毕")


def _start_scheduler():
    """启动 APScheduler."""
    global scheduler_instance
    with scheduler_lock:
        if scheduler_instance is not None:
            return

        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger

        scheduler_instance = BackgroundScheduler(
            timezone="Asia/Shanghai"
        )
        scheduler_instance.add_job(
            _scheduled_job,
            CronTrigger(
                hour=16, minute=0, day_of_week="mon-fri"
            ),
            id="daily_selection",
            name="每日选股",
            replace_existing=True,
        )
        scheduler_instance.start()
        logger.info("调度器已启动: 每个交易日 16:00 执行")


def _stop_scheduler():
    """停止调度器."""
    global scheduler_instance
    with scheduler_lock:
        if scheduler_instance is not None:
            scheduler_instance.shutdown(wait=False)
            scheduler_instance = None
            logger.info("调度器已停止")


# ==================== 启动入口 ====================


def run_web_server(
    host: str = "0.0.0.0",
    port: int = 5000,
    debug: bool = False,
    auto_schedule: bool = True,
) -> None:
    """启动 Web 服务器.

    Args:
        host: 监听地址
        port: 端口
        debug: 调试模式
        auto_schedule: 是否自动启动调度器
    """
    init_db()

    if auto_schedule and not debug:
        _start_scheduler()

    print(f"Web 服务器启动: http://{host}:{port}")
    app.run(host=host, port=port, debug=debug)


def create_app():
    """Factory function for gunicorn.

    Usage: gunicorn -b 0.0.0.0:5000 web_server:create_app()
    """
    init_db()
    _start_scheduler()
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_web_server(debug=False, auto_schedule=True)
