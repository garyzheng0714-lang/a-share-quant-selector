"""决策与模拟盘账本使用的 SQLite 连接边界。

旧版多视图 CRUD 与可覆盖的 ``results`` 表已经退出生产路径。这个模块暂时保留
原导入位置，只提供显式迁移、生产写入和只读查询三类连接，避免业务请求隐式建库。
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path


DB_PATH = Path(
    os.environ.get(
        "QUANT_VIEWS_DB",
        Path(__file__).parent.parent / "data" / "views.db",
    )
)


def _configure_connection(connection: sqlite3.Connection) -> None:
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=5000")


@contextmanager
def _get_migration_conn():
    """仅供显式 migration 使用；这是唯一允许创建数据库的连接。"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(DB_PATH), timeout=5)
    _configure_connection(connection)
    connection.execute("PRAGMA journal_mode=WAL")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


@contextmanager
def _get_conn():
    """生产写连接；数据库未迁移时拒绝隐式创建。"""
    if not DB_PATH.is_file():
        raise FileNotFoundError(f"database_not_initialized:{DB_PATH}")
    connection = sqlite3.connect(str(DB_PATH), timeout=5)
    _configure_connection(connection)
    connection.execute("PRAGMA journal_mode=WAL")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


@contextmanager
def _get_read_conn():
    """查询连接使用只读 URI，禁止隐式 migration、journal 切换和 commit。"""
    if not DB_PATH.is_file():
        raise FileNotFoundError(f"database_not_initialized:{DB_PATH}")
    connection = sqlite3.connect(
        f"file:{DB_PATH}?mode=ro",
        uri=True,
        timeout=5,
    )
    _configure_connection(connection)
    connection.execute("PRAGMA query_only=ON")
    try:
        yield connection
    finally:
        connection.close()
