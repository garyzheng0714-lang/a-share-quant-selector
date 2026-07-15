"""超级B1独立战绩追踪 - 与碗口策略的 performance 表完全隔离

用户 2026-07-12 拍板：超级B1 信号要有自己的战绩回填，但绝不能写现有
performance 表（会污染碗口策略的胜率统计/温度计适应度/AI荐票 prompt）。

口径与碗口战绩保持一致（直接复用 performance_tracker 的纯函数）：
- 信号日 T 收盘出信号，按 T+1 开盘价模拟买入
- ret_n = (T+n 收盘 - T+1 开盘) / T+1 开盘 * 100
- max_gain / max_drawdown = T+1..T+20 区间相对买入价
- status: pending / partial / complete / invalid（语义同 performance 表）
"""
import logging
from datetime import datetime

import orjson
import pandas as pd

from views.view_manager import _get_conn
from utils.performance_tracker import (
    WINDOWS, _aggregate, _benchmark_aggregate, _evaluate_one,
)

logger = logging.getLogger(__name__)


def init_table() -> None:
    """初始化 super_b1_performance 表（幂等）."""
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS super_b1_performance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_date TEXT NOT NULL,
                code TEXT NOT NULL,
                name TEXT,
                signals TEXT,
                J REAL,
                RSI REAL,
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
                UNIQUE(run_date, code)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_sb1_perf_date
            ON super_b1_performance(run_date)
        """)


def record_hits(hits: list, trade_date: str) -> int:
    """把一次扫描的命中写入追踪表，返回新增行数.

    口径说明：
    - 主板过滤在此统一收口（与今日页展示同口径）：用户只有沪深主板权限，
      战绩必须等于"用户实际看到并能买的信号"的战绩，混入创业板/科创板=失真。
    - 同日重扫清理：删掉该日"不在最新命中里、且尚未开始追踪(pending)"的行。
      与碗口的差异（有意为之）：碗口删 pending+partial，这里只删 pending——
      本架构下 trade_date 恒为最新数据日，该日的行在 T+1 行情落地前必为
      pending，"同日重扫遇到 partial"实际不可达；只删 pending 更保守，
      万一未来支持补录历史日期也不会误删已开始的追踪。
    """
    if not trade_date:
        return 0
    from utils.market_filter import is_main_board, main_board_only

    if main_board_only():
        hits = [h for h in hits if is_main_board(h.get("code", ""))]
    init_table()
    added = 0
    now = datetime.now().isoformat()
    codes = [h.get("code") for h in hits if h.get("code")]
    with _get_conn() as conn:
        placeholders = ",".join("?" for _ in codes)
        not_in = f"AND code NOT IN ({placeholders})" if codes else ""
        conn.execute(
            f"""DELETE FROM super_b1_performance
                WHERE run_date = ? AND status = 'pending' {not_in}""",
            [trade_date, *codes],
        )
        for h in hits:
            code = h.get("code")
            if not code:
                continue
            cursor = conn.execute(
                """INSERT OR IGNORE INTO super_b1_performance
                   (run_date, code, name, signals, J, RSI, sel_close,
                    status, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
                (
                    trade_date,
                    code,
                    h.get("name"),
                    orjson.dumps(h.get("signals") or []).decode(),
                    h.get("J"),
                    h.get("RSI"),
                    h.get("close"),
                    now,
                ),
            )
            added += cursor.rowcount
    return added


def update_performance(csv_manager) -> dict:
    """回填所有未完成的追踪记录（每只股票只读一次 CSV）."""
    init_table()
    with _get_conn() as conn:
        pending = conn.execute(
            "SELECT id, run_date, code FROM super_b1_performance "
            "WHERE status NOT IN ('complete', 'invalid')"
        ).fetchall()

    by_code = {}
    for row in pending:
        by_code.setdefault(row["code"], []).append(dict(row))

    updated = invalidated = 0
    for code, items in by_code.items():
        df = csv_manager.read_stock(code)
        if df.empty:
            continue
        daily = df[["date", "open", "high", "low", "close"]].copy()
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
                    f"UPDATE super_b1_performance SET {sets}, updated_at = ? WHERE id = ?",
                    list(fields.values()) + [now, item["id"]],
                )
                if fields.get("status") == "invalid":
                    invalidated += 1
                else:
                    updated += 1

    stats = {"updated": updated, "invalidated": invalidated, "pending_total": len(pending)}
    logger.info("超级B1战绩回填完成: %s", stats)
    return stats


def get_summary() -> dict:
    """战绩汇总：总体 + 按信号类型（一条记录可含多个信号，各组分别计入）."""
    init_table()
    with _get_conn() as conn:
        rows = [
            dict(r) for r in conn.execute(
                "SELECT * FROM super_b1_performance WHERE days_tracked > 0"
            ).fetchall()
        ]

    by_signal = {}
    for r in rows:
        try:
            signals = orjson.loads(r.get("signals") or "[]")
        except Exception:
            signals = []
        for s in signals:
            by_signal.setdefault(s, []).append(r)

    with _get_conn() as conn:
        total_recorded = conn.execute(
            "SELECT COUNT(*) AS n FROM super_b1_performance"
        ).fetchone()["n"]

    return {
        "total_recorded": total_recorded,   # 已录入的信号数（含尚无行情回填的）
        "total_records": len(rows),          # 有后续数据、进入统计的数
        "overall": _aggregate(rows),
        "by_signal": {k: _aggregate(v) for k, v in by_signal.items()},
        "benchmark": _benchmark_aggregate(rows),
    }


def get_records(limit: int = 200) -> list:
    """追踪记录明细（按信号日期倒序）."""
    init_table()
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM super_b1_performance ORDER BY run_date DESC, id LIMIT ?",
            (limit,),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["signals"] = orjson.loads(d.get("signals") or "[]")
        except Exception:
            d["signals"] = []
        out.append(d)
    return out
