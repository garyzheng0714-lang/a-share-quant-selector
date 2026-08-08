"""云阶复盘兼容层：实现已迁到 utils.strategy_review。"""

from __future__ import annotations

from utils.strategy_review import (  # noqa: F401
    build_strategy_review,
    enrich_pick,
    iter_strategy_hits,
    record_strategy_hits,
    summarize_picks,
)

STRATEGY_KEY = "cloud_stair"
STRATEGY_NAME = "云阶"


def record_cloud_stair_hits(trade_date: str, bucket: dict | None) -> int:
    return record_strategy_hits(STRATEGY_KEY, trade_date, bucket)


def iter_cached_cloud_stair_hits(cache_dir=None):
    return iter_strategy_hits(STRATEGY_KEY, cache_dir)


def build_cloud_stair_review(csv_manager, *, limit: int = 200) -> dict:
    return build_strategy_review(csv_manager, STRATEGY_KEY, limit=limit)
