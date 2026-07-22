"""旧多视图账本，仅供仓库外隔离研究复现。"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import orjson


DB_PATH: Path | None = None


def configure_database(research_root: Path) -> Path:
    """显式绑定隔离研究数据库；模块导入时绝不创建默认库。"""
    global DB_PATH
    root = research_root.resolve()
    repository = Path(__file__).resolve().parents[2]
    if (
        root == Path("/")
        or root == repository
        or repository in root.parents
        or root in repository.parents
    ):
        raise RuntimeError("legacy_database_must_be_isolated_from_repository")
    DB_PATH = root / "legacy_views.db"
    return DB_PATH


@contextmanager
def _get_conn():
    if DB_PATH is None:
        raise RuntimeError("legacy_database_not_configured")
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(DB_PATH))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=5000")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db() -> None:
    """创建旧研究所需的最小 views/results schema。"""
    with _get_conn() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS views (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                params TEXT NOT NULL,
                b1_params TEXT,
                b1_enabled INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                view_id INTEGER NOT NULL,
                run_date TEXT NOT NULL,
                stocks_json TEXT NOT NULL,
                run_params TEXT,
                total_selected INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (view_id) REFERENCES views(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_legacy_results_view_date
                ON results(view_id, run_date);
            """
        )
        if (
            connection.execute(
                "SELECT 1 FROM views WHERE name=?", ("默认策略",)
            ).fetchone()
            is None
        ):
            now = datetime.now().isoformat()
            connection.execute(
                """
                INSERT INTO views(
                    name, params, b1_params, b1_enabled, is_active,
                    created_at, updated_at
                ) VALUES (?, ?, ?, 0, 1, ?, ?)
                """,
                ("默认策略", "{}", "{}", now, now),
            )


def list_views() -> list[dict]:
    with _get_conn() as connection:
        rows = connection.execute("SELECT * FROM views ORDER BY id").fetchall()
    output = []
    for row in rows:
        item = dict(row)
        item["params"] = orjson.loads(item.get("params") or "{}")
        item["b1_params"] = orjson.loads(item.get("b1_params") or "{}")
        item["b1_enabled"] = bool(item.get("b1_enabled"))
        item["is_active"] = bool(item.get("is_active"))
        output.append(item)
    return output


def save_result(
    view_id: int,
    run_date: str,
    stocks: list[dict],
    run_params: dict | None = None,
) -> int:
    """保留旧实验的同日覆盖语义，但只写隔离库。"""
    with _get_conn() as connection:
        connection.execute(
            "DELETE FROM results WHERE view_id=? AND run_date=?",
            (view_id, run_date),
        )
        cursor = connection.execute(
            """
            INSERT INTO results(
                view_id, run_date, stocks_json, run_params,
                total_selected, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                view_id,
                run_date,
                orjson.dumps(stocks).decode(),
                orjson.dumps(run_params).decode() if run_params else None,
                len(stocks),
                datetime.now().isoformat(),
            ),
        )
    return int(cursor.lastrowid)
