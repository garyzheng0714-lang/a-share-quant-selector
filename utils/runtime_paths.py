"""运行时持久目录的唯一解析入口。"""

from __future__ import annotations

import os
from pathlib import Path


DEFAULT_MARKET_DATA_DIR = Path("data")


def market_data_dir(value: str | Path | None = None) -> Path:
    """解析市场数据根目录；显式非默认路径始终优先。"""
    if value is None or Path(value) == DEFAULT_MARKET_DATA_DIR:
        configured = os.environ.get("QUANT_DATA_DIR", "").strip()
        if configured:
            return Path(configured).expanduser()
    return Path(value) if value is not None else DEFAULT_MARKET_DATA_DIR


def runtime_state_dir() -> Path:
    """解析任务与决策账本目录；未单独配置时跟随市场数据根目录。"""
    configured = os.environ.get("QUANT_STATE_DIR", "").strip()
    return Path(configured).expanduser() if configured else market_data_dir()


def operations_db_path() -> Path:
    configured = os.environ.get("QUANT_OPERATIONS_DB", "").strip()
    return (
        Path(configured).expanduser()
        if configured
        else runtime_state_dir() / "operations.db"
    )


def views_db_path() -> Path:
    configured = os.environ.get("QUANT_VIEWS_DB", "").strip()
    return (
        Path(configured).expanduser()
        if configured
        else runtime_state_dir() / "views.db"
    )
