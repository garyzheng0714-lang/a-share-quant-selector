"""
选股视图管理器 - 基于 SQLite 的多视图管理

每个视图保存一组独立的选股参数，支持 CRUD 操作。
"""
import sqlite3
import logging
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

import orjson
import yaml

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "views.db"
DEFAULT_PARAMS_PATH = Path(__file__).parent.parent / "config" / "strategy_params.yaml"


def _load_default_params() -> dict:
    """从 strategy_params.yaml 加载默认参数."""
    if DEFAULT_PARAMS_PATH.exists():
        with open(DEFAULT_PARAMS_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data.get("BowlReboundStrategy", {})
    return {}


def _load_default_b1_params() -> dict:
    """从 strategy_params.yaml 加载 B1 匹配默认参数."""
    if DEFAULT_PARAMS_PATH.exists():
        with open(DEFAULT_PARAMS_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data.get("B1PatternMatch", {})
    return {}


@contextmanager
def _get_conn():
    """获取 SQLite 连接的上下文管理器."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """初始化数据库表结构."""
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS views (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                params TEXT NOT NULL,
                b1_params TEXT,
                b1_enabled INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                view_id INTEGER NOT NULL,
                run_date TEXT NOT NULL,
                stocks_json TEXT NOT NULL,
                run_params TEXT,
                total_selected INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (view_id) REFERENCES views(id) ON DELETE CASCADE
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_results_view_date
            ON results(view_id, run_date)
        """)

        # 确保默认视图存在
        row = conn.execute(
            "SELECT id FROM views WHERE name = ?", ("默认策略",)
        ).fetchone()
        if row is None:
            now = datetime.now().isoformat()
            default_params = _load_default_params()
            default_b1 = _load_default_b1_params()
            conn.execute(
                """INSERT INTO views
                   (name, params, b1_params, b1_enabled, is_active,
                    created_at, updated_at)
                   VALUES (?, ?, ?, 0, 1, ?, ?)""",
                (
                    "默认策略",
                    orjson.dumps(default_params).decode(),
                    orjson.dumps(default_b1).decode(),
                    now,
                    now,
                ),
            )


def list_views() -> list[dict]:
    """列出所有视图."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM views ORDER BY id"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_view(view_id: int) -> Optional[dict]:
    """获取单个视图详情."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM views WHERE id = ?", (view_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None


def create_view(
    name: str,
    params: Optional[dict] = None,
    b1_params: Optional[dict] = None,
    b1_enabled: bool = False,
) -> dict:
    """创建新视图.

    Args:
        name: 视图名称
        params: 选股参数，None 则使用默认参数
        b1_params: B1 匹配参数
        b1_enabled: 是否启用 B1 匹配

    Returns:
        创建的视图字典
    """
    if params is None:
        params = _load_default_params()
    if b1_params is None:
        b1_params = _load_default_b1_params()

    now = datetime.now().isoformat()
    with _get_conn() as conn:
        cursor = conn.execute(
            """INSERT INTO views
               (name, params, b1_params, b1_enabled, is_active,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, 1, ?, ?)""",
            (
                name,
                orjson.dumps(params).decode(),
                orjson.dumps(b1_params).decode(),
                int(b1_enabled),
                now,
                now,
            ),
        )
        view_id = cursor.lastrowid
    return get_view(view_id)


def update_view(
    view_id: int,
    name: Optional[str] = None,
    params: Optional[dict] = None,
    b1_params: Optional[dict] = None,
    b1_enabled: Optional[bool] = None,
    is_active: Optional[bool] = None,
) -> Optional[dict]:
    """更新视图.

    Args:
        view_id: 视图 ID
        name: 新名称
        params: 新选股参数
        b1_params: 新 B1 参数
        b1_enabled: 是否启用 B1 匹配
        is_active: 是否活跃

    Returns:
        更新后的视图字典，不存在返回 None
    """
    fields = []
    values = []

    if name is not None:
        fields.append("name = ?")
        values.append(name)
    if params is not None:
        fields.append("params = ?")
        values.append(orjson.dumps(params).decode())
    if b1_params is not None:
        fields.append("b1_params = ?")
        values.append(orjson.dumps(b1_params).decode())
    if b1_enabled is not None:
        fields.append("b1_enabled = ?")
        values.append(int(b1_enabled))
    if is_active is not None:
        fields.append("is_active = ?")
        values.append(int(is_active))

    if not fields:
        return get_view(view_id)

    fields.append("updated_at = ?")
    values.append(datetime.now().isoformat())
    values.append(view_id)

    with _get_conn() as conn:
        conn.execute(
            f"UPDATE views SET {', '.join(fields)} WHERE id = ?",
            values,
        )
    return get_view(view_id)


def delete_view(view_id: int) -> bool:
    """删除视图（级联删除关联结果）."""
    with _get_conn() as conn:
        cursor = conn.execute(
            "DELETE FROM views WHERE id = ?", (view_id,)
        )
    return cursor.rowcount > 0


def duplicate_view(view_id: int, new_name: str) -> Optional[dict]:
    """复制视图.

    Args:
        view_id: 源视图 ID
        new_name: 新视图名称

    Returns:
        新视图字典
    """
    source = get_view(view_id)
    if source is None:
        return None
    return create_view(
        name=new_name,
        params=source["params"],
        b1_params=source["b1_params"],
        b1_enabled=source["b1_enabled"],
    )


# ---- 选股结果管理 ----


def save_result(
    view_id: int,
    run_date: str,
    stocks: list[dict],
    run_params: Optional[dict] = None,
) -> int:
    """保存选股结果.

    Args:
        view_id: 视图 ID
        run_date: 运行日期 (YYYY-MM-DD)
        stocks: 选股结果列表
        run_params: 运行时使用的参数

    Returns:
        结果记录 ID
    """
    now = datetime.now().isoformat()
    with _get_conn() as conn:
        # 删除同日旧结果
        conn.execute(
            "DELETE FROM results WHERE view_id = ? AND run_date = ?",
            (view_id, run_date),
        )
        cursor = conn.execute(
            """INSERT INTO results
               (view_id, run_date, stocks_json, run_params,
                total_selected, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                view_id,
                run_date,
                orjson.dumps(stocks).decode(),
                orjson.dumps(run_params).decode() if run_params else None,
                len(stocks),
                now,
            ),
        )
    return cursor.lastrowid


def get_results(
    view_id: int, limit: int = 30
) -> list[dict]:
    """获取某视图的历史结果.

    Args:
        view_id: 视图 ID
        limit: 返回数量

    Returns:
        结果列表
    """
    with _get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM results
               WHERE view_id = ?
               ORDER BY run_date DESC
               LIMIT ?""",
            (view_id, limit),
        ).fetchall()
    return [_result_to_dict(r) for r in rows]


def get_result_by_date(
    view_id: int, run_date: str
) -> Optional[dict]:
    """获取某日选股详情."""
    with _get_conn() as conn:
        row = conn.execute(
            """SELECT * FROM results
               WHERE view_id = ? AND run_date = ?""",
            (view_id, run_date),
        ).fetchone()
    return _result_to_dict(row) if row else None


# ---- 内部工具 ----


def _row_to_dict(row: sqlite3.Row) -> dict:
    """将视图行转为字典."""
    d = dict(row)
    d["params"] = orjson.loads(d["params"]) if d["params"] else {}
    d["b1_params"] = orjson.loads(d["b1_params"]) if d.get("b1_params") else {}
    d["b1_enabled"] = bool(d.get("b1_enabled", 0))
    d["is_active"] = bool(d.get("is_active", 1))
    return d


def _result_to_dict(row: sqlite3.Row) -> dict:
    """将结果行转为字典."""
    d = dict(row)
    d["stocks"] = orjson.loads(d["stocks_json"]) if d["stocks_json"] else []
    d.pop("stocks_json", None)
    d["run_params"] = (
        orjson.loads(d["run_params"]) if d.get("run_params") else None
    )
    return d
