"""战绩追踪模块 - 对历史选股结果回填后续真实表现（自学习闭环的地基）

口径（与 WORKLOG.md 一致）：
- 选出日 T 收盘后出信号，按 T+1（下一个交易日）开盘价模拟买入
- ret_n = (T+n 收盘 - T+1 开盘) / T+1 开盘 * 100，n 为 run_date 之后第 n 个交易日
- max_gain / max_drawdown = T+1..T+20 区间内最高价/最低价相对买入价的涨跌幅
- status: pending(尚无 T+1 数据) / partial(不足 20 个交易日) / complete(满 20 个交易日)
          / invalid(T+1 开盘价<=0，无法计算收益的终态，不再重复追踪)

数据来源：
- 选股记录：views.db 的 results 表（Web 和 CLI 选股都会写入）
- 行情：data/ 目录下各股票 CSV（前复权日线）
"""
import logging
from datetime import datetime

import orjson
import pandas as pd

from views.view_manager import _get_conn

logger = logging.getLogger(__name__)

WINDOWS = (1, 5, 10, 20)
MAX_WINDOW = max(WINDOWS)

# 指数基准的失败时间戳（负缓存，见 _benchmark_aggregate）
_benchmark_fail_ts = 0.0


def init_performance_table() -> None:
    """初始化 performance 表（幂等）."""
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS performance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                view_id INTEGER NOT NULL,
                run_date TEXT NOT NULL,
                code TEXT NOT NULL,
                name TEXT,
                category TEXT,
                similarity_score REAL,
                sel_close REAL,
                buy_price REAL,
                ret_1 REAL,
                ret_5 REAL,
                ret_10 REAL,
                ret_20 REAL,
                max_gain REAL,
                max_drawdown REAL,
                days_tracked INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                updated_at TEXT,
                UNIQUE(view_id, run_date, code)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_perf_view_date
            ON performance(view_id, run_date)
        """)
        # 旧库原地迁移：保留原始毛收益字段，新增可成交性和版本证据。
        existing = {r["name"] for r in conn.execute("PRAGMA table_info(performance)").fetchall()}
        columns = {
            "entry_feasible": "INTEGER",
            "exit_feasible_5": "INTEGER",
            "one_word_limit_down_next_open": "INTEGER",
            "next_open_gap_pct": "REAL",
            "net_ret_5": "REAL",
            "execution_json": "TEXT",
            "strategy_version": "TEXT",
            "data_version": "TEXT",
            "as_of": "TEXT",
        }
        for name, kind in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE performance ADD COLUMN {name} {kind}")


def _sync_from_results() -> int:
    """把 results 表中的选股记录同步为 performance 待追踪行，返回新增行数.

    同步时顺带清理"被同日重跑覆盖掉的旧候选"：results 表的 save_result 是
    DELETE+INSERT 覆盖式写入，但此前 performance 里已同步进去的旧候选行会
    永久残留并继续回填收益，污染胜率统计/温度计适应度/AI荐票 prompt。
    这里对每个 (view_id, run_date)，把不在最新 stocks_json 里、且尚未追踪
    完成（pending/partial）的行删掉；已 complete 的历史行保留。
    """
    added = 0
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT view_id, run_date, stocks_json FROM results"
        ).fetchall()
        from utils.decision_versions import data_version, strategy_version

        now = datetime.now().astimezone().isoformat(timespec="seconds")
        strategy_ver = strategy_version()
        data_ver = data_version()
        for row in rows:
            try:
                stocks = orjson.loads(row["stocks_json"]) if row["stocks_json"] else []
            except Exception:
                continue
            codes = [s.get("code") for s in stocks if s.get("code")]
            placeholders = ",".join("?" for _ in codes)
            not_in = f"AND code NOT IN ({placeholders})" if codes else ""
            conn.execute(
                f"""DELETE FROM performance
                    WHERE view_id = ? AND run_date = ?
                      AND status IN ('pending', 'partial') {not_in}""",
                [row["view_id"], row["run_date"], *codes],
            )
            for s in stocks:
                code = s.get("code")
                if not code:
                    continue
                cursor = conn.execute(
                    """INSERT OR IGNORE INTO performance
                       (view_id, run_date, code, name, category,
                        similarity_score, sel_close, status, updated_at,
                        strategy_version, data_version, as_of)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)""",
                    (
                        row["view_id"],
                        row["run_date"],
                        code,
                        s.get("name"),
                        s.get("category"),
                        s.get("similarity_score"),
                        s.get("close"),
                        now,
                        strategy_ver,
                        data_ver,
                        f"{row['run_date']}T15:00:00+08:00",
                    ),
                )
                added += cursor.rowcount
    return added


def _evaluate_one(daily: pd.DataFrame, run_date: str) -> dict:
    """用一只股票的日线数据计算 run_date 之后的表现.

    daily: 正序（从早到晚）的日线数据，含 date/open/high/low/close
    返回要写入 performance 的字段字典。两种"无收益"情形要区分：
    - 尚无 T+1 数据 → 返回 {}，保持 pending，等有新数据下次再算
    - T+1 开盘价<=0（无法计算收益）→ 返回 {"status": "invalid"} 标记终态，不再重复追踪
    """
    after = daily[daily["date"] > run_date]
    if after.empty:
        return {}

    buy_price = float(after.iloc[0]["open"])
    # buy_price != buy_price 是 NaN 判定：停牌行/抓取缺失的空开盘价同样无法计算收益
    if not buy_price or buy_price <= 0 or buy_price != buy_price:
        return {"status": "invalid"}

    tracked = after.head(MAX_WINDOW)
    days = len(tracked)

    fields = {"buy_price": round(buy_price, 3), "days_tracked": days}
    for n in WINDOWS:
        if days >= n:
            close_n = float(tracked.iloc[n - 1]["close"])
            fields[f"ret_{n}"] = round((close_n - buy_price) / buy_price * 100, 2)
        else:
            fields[f"ret_{n}"] = None

    fields["max_gain"] = round(
        (float(tracked["high"].max()) - buy_price) / buy_price * 100, 2
    )
    fields["max_drawdown"] = round(
        (float(tracked["low"].min()) - buy_price) / buy_price * 100, 2
    )
    fields["status"] = "complete" if days >= MAX_WINDOW else "partial"
    # 保留原有毛收益口径作对照，同时写入保守成交模型的净收益。
    from utils.execution_model import evaluate_trade

    execution = evaluate_trade(daily, run_date, hold_days=5)
    if execution.get("available"):
        fields.update({
            "entry_feasible": int(bool(execution.get("entry_feasible"))),
            "exit_feasible_5": (
                int(bool(execution.get("exit_feasible")))
                if execution.get("exit_feasible") is not None else None
            ),
            "one_word_limit_down_next_open": int(
                bool(execution.get("one_word_limit_down_next_open"))
            ),
            "next_open_gap_pct": execution.get("next_open_gap_pct"),
            "net_ret_5": execution.get("net_return"),
            "execution_json": orjson.dumps(execution).decode(),
        })
    return fields


def update_performance(csv_manager) -> dict:
    """回填所有未完成的追踪记录，返回统计信息.

    每只股票只读一次 CSV（按 code 聚合待处理行）。
    """
    init_performance_table()
    added = _sync_from_results()

    with _get_conn() as conn:
        # complete=已追踪满，invalid=买入价异常无法计算的终态；两者都不再重读 CSV
        pending = conn.execute(
            "SELECT id, view_id, run_date, code FROM performance "
            "WHERE status NOT IN ('complete', 'invalid')"
        ).fetchall()

    by_code = {}
    for row in pending:
        by_code.setdefault(row["code"], []).append(dict(row))

    updated = 0
    invalidated = 0
    for code, items in by_code.items():
        df = csv_manager.read_stock(code)
        if df.empty:
            continue
        keep = [c for c in ("date", "open", "high", "low", "close", "volume") if c in df]
        daily = df[keep].copy()
        daily["date"] = pd.to_datetime(daily["date"]).dt.strftime("%Y-%m-%d")
        if len(daily) > 1 and daily["date"].iloc[0] > daily["date"].iloc[-1]:
            daily = daily.iloc[::-1].reset_index(drop=True)

        now = datetime.now().isoformat()
        with _get_conn() as conn:
            for item in items:
                fields = _evaluate_one(daily, item["run_date"])
                if not fields:
                    continue
                sets = ", ".join(f"{k} = ?" for k in fields)
                conn.execute(
                    f"UPDATE performance SET {sets}, updated_at = ? WHERE id = ?",
                    list(fields.values()) + [now, item["id"]],
                )
                if fields.get("status") == "invalid":
                    invalidated += 1
                else:
                    updated += 1

    stats = {
        "synced": added,
        "updated": updated,
        "invalidated": invalidated,
        "pending_total": len(pending),
    }
    logger.info(
        "战绩回填完成: %s（invalidated=买入价<=0无法计算、已标记终态不再重复处理）", stats
    )
    return stats


def _bucket_similarity(score) -> str:
    """B1 相似度分桶，用于统计"高相似度是否真的涨得多"."""
    if score is None:
        return "无B1分"
    if score >= 80:
        return ">=80"
    if score >= 60:
        return "60-80"
    return "<60"


def _aggregate(rows: list) -> dict:
    """对一组记录算各窗口的样本数/胜率/平均收益 + 持有期最大回撤统计（止损参考）."""
    out = {}
    for n in WINDOWS:
        vals = [r[f"ret_{n}"] for r in rows if r[f"ret_{n}"] is not None]
        if vals:
            out[f"ret_{n}"] = {
                "count": len(vals),
                "win_rate": round(sum(1 for v in vals if v > 0) / len(vals) * 100, 1),
                "avg": round(sum(vals) / len(vals), 2),
            }
        else:
            out[f"ret_{n}"] = {"count": 0, "win_rate": None, "avg": None}
    # 只统计追踪满 20 日(complete)的行：partial 行的回撤还没走完，
    # 计入会系统性低估"持有20日内最大浮亏"
    dds = sorted(
        r["max_drawdown"] for r in rows
        if r.get("max_drawdown") is not None and r.get("status") == "complete"
    )
    if dds:
        mid = len(dds) // 2
        median = dds[mid] if len(dds) % 2 else (dds[mid - 1] + dds[mid]) / 2
        out["drawdown"] = {
            "avg": round(sum(dds) / len(dds), 2),
            "median": round(median, 2),
            "count": len(dds),
        }
    else:
        out["drawdown"] = {"avg": None, "median": None, "count": 0}
    return out


def _benchmark_aggregate(rows: list):
    """同期上证指数各窗口平均收益（"超额收益"的基准）.

    口径：对每条记录，用指数在 run_date 之后第 1 个交易日收盘价为基点，
    第 n 个交易日收盘价算收益（个股用的是 T+1 开盘价买入，指数无开盘口径
    差异极小，前端文案注明"以指数收盘近似"）。指数接口失败时返回 None，
    前端不显示超额行——诚实降级，绝不编数。
    """
    global _benchmark_fail_ts
    import time as _time
    # 负缓存：指数接口失败后 5 分钟内不再重试，避免接口宕机期间
    # 每次战绩汇总/AI荐票都白等 10 秒超时
    if _time.time() - _benchmark_fail_ts < 300:
        return None
    try:
        from utils.market_thermometer import _fetch_index_daily
        idx_rows = _fetch_index_daily()
    except Exception as e:
        logger.warning("指数基准获取失败，本次汇总不含超额对比: %s", e)
        _benchmark_fail_ts = _time.time()
        return None
    if not idx_rows:
        _benchmark_fail_ts = _time.time()
        return None

    dates = [r["date"] for r in idx_rows]
    closes = [r["close"] for r in idx_rows]
    from bisect import bisect_right

    out = {}
    for n in WINDOWS:
        vals = []
        for r in rows:
            if r.get(f"ret_{n}") is None:
                continue
            i = bisect_right(dates, r["run_date"])  # 指数在 run_date 后的第 1 个交易日
            # i==0 说明 run_date 早于指数抓取窗口（320根K线），没有 T+0 基点可用，
            # 跳过——否则会把窗口内最早一根K线错当 T+1，算出完全错位的基准
            if i == 0 or i + n - 1 >= len(dates):
                continue
            # 基点用 run_date 当天(T+0)的指数收盘：T+n 收益 = T+n收盘 vs T+0收盘。
            # 若基点用 T+1 收盘，ret_1 会退化成自己比自己恒等于 0
            base = closes[i - 1]
            if not base:
                continue
            vals.append((closes[i + n - 1] - base) / base * 100)
        out[f"ret_{n}"] = round(sum(vals) / len(vals), 2) if vals else None
    return out


def get_summary(view_id=None) -> dict:
    """战绩汇总：总体 + 按分类 + 按 B1 相似度分桶."""
    init_performance_table()
    query = "SELECT * FROM performance WHERE days_tracked > 0"
    params = []
    if view_id is not None:
        query += " AND view_id = ?"
        params.append(view_id)

    with _get_conn() as conn:
        rows = [dict(r) for r in conn.execute(query, params).fetchall()]

    by_category, by_bucket = {}, {}
    for r in rows:
        by_category.setdefault(r.get("category") or "unknown", []).append(r)
        by_bucket.setdefault(_bucket_similarity(r.get("similarity_score")), []).append(r)

    return {
        "total_records": len(rows),
        "overall": _aggregate(rows),
        "by_category": {k: _aggregate(v) for k, v in by_category.items()},
        "by_similarity": {k: _aggregate(v) for k, v in by_bucket.items()},
        "benchmark": _benchmark_aggregate(rows),
    }


def get_records(view_id=None, limit: int = 200) -> list:
    """追踪记录明细（按选出日期倒序）."""
    init_performance_table()
    query = "SELECT * FROM performance"
    params = []
    if view_id is not None:
        query += " WHERE view_id = ?"
        params.append(view_id)
    query += " ORDER BY run_date DESC, id LIMIT ?"
    params.append(limit)

    with _get_conn() as conn:
        return [dict(r) for r in conn.execute(query, params).fetchall()]


def print_summary(summary: dict) -> None:
    """在终端打印人话版战绩摘要（CLI track 命令用）."""
    print("=" * 60)
    print("📊 选股战绩汇总（买入口径：选出次日开盘价）")
    print("=" * 60)
    print(f"有后续数据的记录: {summary['total_records']} 条\n")

    def _print_block(title, agg):
        parts = []
        for n in WINDOWS:
            a = agg[f"ret_{n}"]
            if a["count"]:
                parts.append(f"T+{n}: 胜率{a['win_rate']}% 均{a['avg']:+.2f}% ({a['count']}条)")
        print(f"  {title}")
        print("    " + (" | ".join(parts) if parts else "暂无足够数据"))

    _print_block("总体", summary["overall"])
    cat_names = {
        "bowl_center": "🥣 回落碗中",
        "near_duokong": "📊 靠近多空线",
        "near_short_trend": "📈 靠近短期趋势线",
    }
    print("\n  --- 按分类 ---")
    for cat, agg in summary["by_category"].items():
        _print_block(cat_names.get(cat, cat), agg)
    print("\n  --- 按 B1 相似度 ---")
    for bucket, agg in summary["by_similarity"].items():
        _print_block(f"相似度 {bucket}", agg)
    print("=" * 60)
