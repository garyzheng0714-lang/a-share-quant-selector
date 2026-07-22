"""行情新鲜度闸门：过期日线不得生成或展示为当前推荐。"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from utils.csv_manager import CSVManager
from utils.market_snapshot import load_current_market_snapshot, load_market_snapshot

TZ = ZoneInfo("Asia/Shanghai")
ANCHOR_CODES = ("000001", "600030", "600036", "600519")


def _trade_calendar(
    data_dir: str | Path = "data",
    *,
    snapshot_id: str | None = None,
    allow_unpublished_calendar: bool = False,
) -> list[str]:
    """只读已发布快照/本地缓存；请求链路绝不临时访问外部数据源。"""
    root = Path(data_dir)
    snapshot = (
        load_market_snapshot(root, snapshot_id, verify_files=False)
        if snapshot_id
        else load_current_market_snapshot(root, verify_files=False)
    )
    candidates = []
    if snapshot.get("available"):
        candidates.append(Path(snapshot["payload_dir"]) / "trade_calendar.json")
    elif allow_unpublished_calendar and snapshot_id is None:
        # 只供 ingestion staging 使用；生产决策不得回退到根目录旧日历。
        candidates.append(root / "trade_calendar.json")
    for path in candidates:
        try:
            dates = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        normalized = (
            sorted({str(value)[:10] for value in dates})
            if isinstance(dates, list)
            else []
        )
        if normalized:
            return normalized
    return []


def refresh_trade_calendar(output_dir: str | Path) -> list[str]:
    """仅供 ingestion worker 调用，获取并原子保存交易所日历。"""
    import akshare as ak

    frame = ak.tool_trade_date_hist_sina()
    dates = sorted(
        pd.to_datetime(frame["trade_date"]).dt.strftime("%Y-%m-%d").unique().tolist()
    )
    if not dates:
        raise RuntimeError("trading_calendar_empty")
    target = Path(output_dir) / "trade_calendar.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(dates, ensure_ascii=False), encoding="utf-8")
    tmp.replace(target)
    return dates


def expected_completed_trade_date(
    as_of: datetime | None = None,
    *,
    data_dir: str | Path = "data",
    snapshot_id: str | None = None,
    allow_unpublished_calendar: bool = False,
) -> str:
    now = as_of or datetime.now(TZ)
    cutoff = (
        now.date()
        if now.time() >= datetime.strptime("15:05", "%H:%M").time()
        else now.date() - timedelta(days=1)
    )
    calendar = _trade_calendar(
        data_dir,
        snapshot_id=snapshot_id,
        allow_unpublished_calendar=allow_unpublished_calendar,
    )
    eligible = [date for date in calendar if date <= cutoff.isoformat()]
    if eligible:
        return eligible[-1]
    return ""


def next_trade_date(
    after_date: str,
    *,
    data_dir: str | Path = "data",
    snapshot_id: str | None = None,
    allow_unpublished_calendar: bool = False,
) -> str:
    calendar = _trade_calendar(
        data_dir,
        snapshot_id=snapshot_id,
        allow_unpublished_calendar=allow_unpublished_calendar,
    )
    future = [date for date in calendar if date > after_date]
    if future:
        return future[0]
    return ""


def local_data_status(
    csv_manager: CSVManager | None = None, as_of: datetime | None = None
) -> dict:
    data_root = csv_manager.data_dir if csv_manager is not None else Path("data")
    # CSVManager 可能已指向 snapshot payload，此时用它的 base_data_dir。
    data_root = (
        getattr(csv_manager, "base_data_dir", data_root) if csv_manager else data_root
    )
    pinned_snapshot_id = getattr(csv_manager, "snapshot_id", None)
    if csv_manager is not None and pinned_snapshot_id is None:
        return {
            "fresh": False,
            "reason": getattr(csv_manager, "snapshot_error", None)
            or "validated_snapshot_missing",
            "reason_codes": ["validated_snapshot_missing"],
            "local_date": None,
            "expected_date": None,
            "snapshot_id": None,
            "anchor_dates": {},
            "anchor_quorum": 0,
            "coverage_ratio": 0.0,
        }
    expected = expected_completed_trade_date(
        as_of,
        data_dir=data_root,
        snapshot_id=pinned_snapshot_id,
    )
    if not expected:
        return {
            "fresh": False,
            "reason": "trading_calendar_unavailable",
            "reason_codes": ["trading_calendar_unavailable"],
            "local_date": None,
            "expected_date": None,
            "snapshot_id": None,
            "anchor_dates": {},
            "anchor_quorum": 0,
            "coverage_ratio": 0.0,
        }
    snapshot = (
        load_market_snapshot(data_root, pinned_snapshot_id, verify_files=False)
        if pinned_snapshot_id
        else load_current_market_snapshot(data_root, verify_files=False)
    )
    if not snapshot.get("available"):
        return {
            "fresh": False,
            "reason": snapshot.get("reason", "validated_snapshot_missing"),
            "local_date": None,
            "expected_date": expected,
            "snapshot_id": None,
            "anchor_dates": {},
            "anchor_quorum": 0,
            "coverage_ratio": 0.0,
        }
    manifest = snapshot["manifest"]
    local_date = manifest.get("trade_date")
    anchor_dates = manifest.get("anchor_dates") or {}
    exact_date = local_date == expected
    no_future_dates = not manifest.get("future_rows")
    coverage_ok = float(manifest.get("coverage_ratio") or 0) >= float(
        os.environ.get("QUANT_MIN_SNAPSHOT_COVERAGE", "0.98")
    )
    anchors_ok = int(manifest.get("anchor_quorum") or 0) >= 3
    sources_ok = manifest.get("source_quorum_passed") is True
    schema_ok = int(manifest.get("schema_errors") or 0) == 0
    synthetic_ok = int(manifest.get("synthetic_rows") or 0) == 0
    fresh = all(
        (
            exact_date,
            no_future_dates,
            coverage_ok,
            anchors_ok,
            sources_ok,
            schema_ok,
            synthetic_ok,
        )
    )
    reasons = []
    for passed, reason in (
        (exact_date, "trade_date_mismatch"),
        (no_future_dates, "future_market_data"),
        (coverage_ok, "coverage_below_threshold"),
        (anchors_ok, "anchor_quorum_failed"),
        (sources_ok, "source_quorum_failed"),
        (schema_ok, "schema_validation_failed"),
        (synthetic_ok, "synthetic_market_data"),
    ):
        if not passed:
            reasons.append(reason)
    return {
        "fresh": fresh,
        "reason": reasons[0] if reasons else None,
        "reason_codes": reasons,
        "local_date": local_date,
        "expected_date": expected,
        "snapshot_id": snapshot["snapshot_id"],
        "anchor_dates": anchor_dates,
        "anchor_quorum": manifest.get("anchor_quorum"),
        "coverage_ratio": manifest.get("coverage_ratio"),
        "source_set": manifest.get("source_set") or [],
        "closed_at": manifest.get("closed_at"),
    }
