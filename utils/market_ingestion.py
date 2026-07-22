"""行情 staging → validate → promote 编排。"""

from __future__ import annotations

import fcntl
import os
import time
from pathlib import Path
from typing import IO

from utils.akshare_fetcher import AKShareFetcher
from utils.data_freshness import expected_completed_trade_date, refresh_trade_calendar
from utils.market_snapshot import (
    find_resumable_rebuild_snapshot,
    prepare_empty_staging_snapshot,
    prepare_staging_snapshot,
    promote_staging_snapshot,
)
from utils.decision_versions import git_commit_sha
from utils.stock_info import refresh_reference_metadata


def _code_sha() -> str:
    return git_commit_sha()


def _acquire_ingestion_lock(data_dir: str | Path) -> IO[str] | None:
    """单机共享 volume 上的跨进程 writer 锁；进程退出时内核自动释放。"""
    root = Path(data_dir)
    root.mkdir(parents=True, exist_ok=True)
    handle = (root / ".market-ingestion.lock").open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    return handle


def _release_ingestion_lock(handle: IO[str]) -> None:
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def _run_daily_ingestion(data_dir: str | Path = "data") -> dict:
    """在独立 staging 中更新；任何一只更新失败都不 promote。"""
    try:
        staging = prepare_staging_snapshot(data_dir)
    except RuntimeError as exc:
        return {
            "success": False,
            "reason": "trusted_base_snapshot_required",
            "detail": str(exc),
            "recovery": "run_full_market_rebuild",
        }
    try:
        refresh_trade_calendar(staging.payload_dir)
    except Exception as exc:
        return {
            "success": False,
            "reason": "trading_calendar_refresh_failed",
            "error_type": type(exc).__name__,
            "staging_dir": str(staging.root),
        }
    trade_date = expected_completed_trade_date(
        data_dir=staging.payload_dir,
        allow_unpublished_calendar=True,
    )
    if not trade_date:
        return {
            "success": False,
            "reason": "completed_trade_date_unavailable",
            "staging_dir": str(staging.root),
        }
    fetcher = AKShareFetcher(
        staging.payload_dir,
        state_dir=Path(data_dir) / ".ingestion_state",
    )
    universe = fetcher.refresh_stock_universe(trade_date)
    if len(universe) < 3000 or not fetcher.universe_refresh_status.get("fresh"):
        return {
            "success": False,
            "reason": "approved_universe_unavailable",
            "staging_dir": str(staging.root),
            "universe_count": len(universe),
            "universe_status": fetcher.universe_refresh_status,
        }
    try:
        reference = refresh_reference_metadata(
            staging.payload_dir,
            list(universe),
            trade_date,
            minimum_industry_coverage=float(
                os.environ.get("QUANT_MIN_INDUSTRY_COVERAGE", "0.80")
            ),
            minimum_cap_coverage=float(
                os.environ.get("QUANT_MIN_CAP_COVERAGE", "0.95")
            ),
        )
    except Exception as exc:
        return {
            "success": False,
            "reason": "reference_metadata_refresh_failed",
            "error_type": type(exc).__name__,
            "staging_dir": str(staging.root),
        }
    if not reference.get("valid"):
        return {
            "success": False,
            "reason": "reference_metadata_incomplete",
            "reference": reference,
            "staging_dir": str(staging.root),
        }
    expansion = fetcher.bootstrap_universe(
        years=6,
        refresh_universe=False,
        missing_only=True,
    )
    if int(expansion.get("failed") or 0) > 0:
        return {
            "success": False,
            "reason": "universe_expansion_incomplete",
            "staging_dir": str(staging.root),
            "expansion": expansion,
        }
    update = fetcher.daily_update()
    if not update or int(update.get("failed") or 0) > 0:
        return {
            "success": False,
            "reason": "market_update_incomplete",
            "staging_dir": str(staging.root),
            "update": update,
        }
    trade_date = str(update.get("target_date") or trade_date)
    promoted = promote_staging_snapshot(
        staging,
        trade_date,
        data_dir=data_dir,
        code_sha=_code_sha(),
        minimum_coverage=float(os.environ.get("QUANT_MIN_SNAPSHOT_COVERAGE", "0.98")),
        required_source_count=int(os.environ.get("QUANT_SNAPSHOT_SOURCE_QUORUM", "2")),
    )
    return {
        "success": bool(promoted.get("promoted")),
        "expansion": expansion,
        "update": update,
        **promoted,
    }


def _run_full_rebuild(
    data_dir: str | Path = "data",
    *,
    years: int = 6,
    max_stocks: int | None = None,
) -> dict:
    """从可信外部源全量重建，绝不继承无 provenance 的旧 CSV。"""
    resume_age_hours = max(
        0.0, float(os.environ.get("QUANT_REBUILD_RESUME_MAX_AGE_HOURS", "24"))
    )
    staging = find_resumable_rebuild_snapshot(data_dir, max_age_hours=resume_age_hours)
    resumed_staging = staging is not None
    if staging is None:
        staging = prepare_empty_staging_snapshot(data_dir)
    try:
        refresh_trade_calendar(staging.payload_dir)
    except Exception as exc:
        return {
            "success": False,
            "reason": "trading_calendar_refresh_failed",
            "error_type": type(exc).__name__,
            "staging_dir": str(staging.root),
        }
    trade_date = expected_completed_trade_date(
        data_dir=staging.payload_dir,
        allow_unpublished_calendar=True,
    )
    if not trade_date:
        return {
            "success": False,
            "reason": "completed_trade_date_unavailable",
            "staging_dir": str(staging.root),
        }
    fetcher = AKShareFetcher(
        staging.payload_dir,
        state_dir=Path(data_dir) / ".ingestion_state",
    )
    universe = fetcher.refresh_stock_universe(trade_date)
    if len(universe) < 3000 or not fetcher.universe_refresh_status.get("fresh"):
        return {
            "success": False,
            "reason": "approved_universe_unavailable",
            "staging_dir": str(staging.root),
            "universe_count": len(universe),
            "universe_status": fetcher.universe_refresh_status,
        }
    try:
        reference = refresh_reference_metadata(
            staging.payload_dir,
            list(universe),
            trade_date,
            minimum_industry_coverage=float(
                os.environ.get("QUANT_MIN_INDUSTRY_COVERAGE", "0.80")
            ),
            minimum_cap_coverage=float(
                os.environ.get("QUANT_MIN_CAP_COVERAGE", "0.95")
            ),
        )
    except Exception as exc:
        return {
            "success": False,
            "reason": "reference_metadata_refresh_failed",
            "error_type": type(exc).__name__,
            "staging_dir": str(staging.root),
        }
    if not reference.get("valid"):
        return {
            "success": False,
            "reason": "reference_metadata_incomplete",
            "reference": reference,
            "staging_dir": str(staging.root),
        }
    max_passes = min(
        5, max(1, int(os.environ.get("QUANT_FULL_REBUILD_MAX_PASSES", "3")))
    )
    retry_delay = min(
        60.0,
        max(
            0.0,
            float(os.environ.get("QUANT_FULL_REBUILD_RETRY_DELAY_SECONDS", "5")),
        ),
    )
    result: dict = {}
    pass_summaries = []
    try:
        for pass_number in range(1, max_passes + 1):
            result = fetcher.bootstrap_universe(
                max_stocks=max_stocks,
                years=years,
                refresh_universe=False,
            )
            pass_summaries.append(
                {
                    "pass": pass_number,
                    "attempted": result.get("attempted"),
                    "added": result.get("added"),
                    "failed": result.get("failed"),
                    "remaining_count": result.get("remaining_count"),
                    "failure_reason_counts": result.get("failure_reason_counts") or {},
                }
            )
            if max_stocks is not None or int(result.get("failed") or 0) == 0:
                break
            if pass_number < max_passes:
                time.sleep(retry_delay * pass_number)
    except Exception as exc:
        return {
            "success": False,
            "reason": "full_rebuild_failed",
            "error_type": type(exc).__name__,
            "staging_dir": str(staging.root),
            "resumed_staging": resumed_staging,
            "passes": pass_summaries,
        }
    result = {
        **result,
        "passes": pass_summaries,
        "pass_count": len(pass_summaries),
    }
    if max_stocks is not None or int(result.get("failed") or 0) > 0:
        return {
            "success": False,
            "reason": "full_rebuild_incomplete",
            "staging_dir": str(staging.root),
            "resumed_staging": resumed_staging,
            "bootstrap": result,
        }
    promoted = promote_staging_snapshot(
        staging,
        trade_date,
        data_dir=data_dir,
        code_sha=_code_sha(),
        minimum_coverage=float(os.environ.get("QUANT_MIN_SNAPSHOT_COVERAGE", "0.98")),
        required_source_count=int(os.environ.get("QUANT_SNAPSHOT_SOURCE_QUORUM", "2")),
    )
    return {
        "success": bool(promoted.get("promoted")),
        "resumed_staging": resumed_staging,
        "bootstrap": result,
        **promoted,
    }


def run_daily_ingestion(data_dir: str | Path = "data") -> dict:
    lock = _acquire_ingestion_lock(data_dir)
    if lock is None:
        return {"success": False, "reason": "ingestion_already_running"}
    try:
        return _run_daily_ingestion(data_dir)
    finally:
        _release_ingestion_lock(lock)


def run_full_rebuild(
    data_dir: str | Path = "data",
    *,
    years: int = 6,
    max_stocks: int | None = None,
) -> dict:
    lock = _acquire_ingestion_lock(data_dir)
    if lock is None:
        return {"success": False, "reason": "ingestion_already_running"}
    try:
        return _run_full_rebuild(
            data_dir,
            years=years,
            max_stocks=max_stocks,
        )
    finally:
        _release_ingestion_lock(lock)
