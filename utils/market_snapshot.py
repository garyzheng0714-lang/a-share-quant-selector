"""不可变收盘行情快照。

行情先在 staging 目录中构建，通过日期、行情 schema、股票池、来源与内容 hash
校验后，才能原子地 promote 为 CURRENT_SNAPSHOT。任何决策都只应读取已验证
snapshot，不应直接读取可变 data/ CSV。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pandas as pd

from utils.market_filter import is_main_board, main_board_only


SCHEMA_VERSION = "market-eod-v2"
CURRENT_POINTER = "CURRENT_SNAPSHOT"
SNAPSHOT_DIR = "market_snapshots"
STAGING_DIR = ".snapshot_staging"
REBUILD_MARKER = "trusted-rebuild.json"
REBUILD_MARKER_SCHEMA = "trusted-full-rebuild-v1"
REQUIRED_COLUMNS = {
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "turnover",
}
TRUSTED_SOURCES = frozenset({"tencent", "akshare"})
TRUSTED_SECURITY_STATUS_SOURCES = frozenset(
    {
        "akshare:stock_tfp_em",
        "tencent:qt.gtimg.cn",
    }
)
ANCHOR_CODES = ("000001", "600030", "600036", "600519")
METADATA_FILES = (
    "stock_names.json",
    "universe_manifest.json",
    "stock_industry.json",
    "stock_market_cap.json",
    "trade_calendar.json",
    "ingestion_provenance.json",
    "reference_data_manifest.json",
    "security_status.json",
)
UNIVERSE_SEED_FILES = (
    "stock_names.json",
    "universe_manifest.json",
)
_CURRENT_SNAPSHOT = object()


def current_snapshot_payload(
    data_dir: str | Path = "data",
) -> tuple[Path | None, str | None]:
    """返回当前已验证快照的 payload 和 ID；没有快照时绝不回退到可变目录。"""
    current = load_current_market_snapshot(data_dir, verify_files=False)
    if not current.get("available"):
        return None, None
    return Path(current["payload_dir"]), str(current["snapshot_id"])


def read_snapshot_metadata(
    filename: str,
    data_dir: str | Path = "data",
    *,
    snapshot_id: str | None | object = _CURRENT_SNAPSHOT,
) -> tuple[dict | list, str | None]:
    """从当前或显式指定的不可变快照读取元数据。

    省略 ``snapshot_id`` 才表示跟随当前指针；显式传入 ``None``
    表示调用方已经绑定失败，必须 fail closed。
    """
    if filename not in METADATA_FILES:
        raise ValueError(f"unsupported snapshot metadata: {filename}")
    if snapshot_id is _CURRENT_SNAPSHOT:
        payload, resolved_snapshot_id = current_snapshot_payload(data_dir)
    elif snapshot_id is None:
        return {}, None
    else:
        explicit_snapshot_id = cast(str, snapshot_id)
        loaded = load_market_snapshot(
            data_dir, explicit_snapshot_id, verify_files=False
        )
        payload = Path(loaded["payload_dir"]) if loaded.get("available") else None
        resolved_snapshot_id = explicit_snapshot_id if payload is not None else None
    if payload is None:
        return {}, None
    value = _read_json(payload / filename, {})
    return value, resolved_snapshot_id


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_id(manifest_without_id: dict) -> str:
    return hashlib.sha256(_canonical(manifest_without_id)).hexdigest()


def _read_json(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def _approved_universe(payload_dir: Path) -> tuple[dict[str, str], dict]:
    names = _read_json(payload_dir / "stock_names.json", {})
    names = {
        str(code): str(name)
        for code, name in names.items()
        if not str(code).startswith("_")
        and (not main_board_only() or is_main_board(str(code)))
    }
    manifest = _read_json(payload_dir / "universe_manifest.json", {})
    canonical_all_names = _read_json(payload_dir / "stock_names.json", {})
    canonical_all_names = {
        str(code): str(name)
        for code, name in canonical_all_names.items()
        if not str(code).startswith("_")
    }
    expected_hash = hashlib.sha256(_canonical(canonical_all_names)).hexdigest()
    valid = (
        manifest.get("schema_version") == "universe-v1"
        and manifest.get("count") == len(canonical_all_names)
        and manifest.get("content_hash") == expected_hash
        and int(manifest.get("expected_minimum_size") or 0) >= 3000
        and len(canonical_all_names) >= 3000
        and manifest.get("source") in TRUSTED_SOURCES
        and manifest.get("stale") is False
    )
    return names, {**manifest, "valid": valid, "approved_count": len(names)}


def _trade_calendar(payload_dir: Path) -> set[str]:
    values = _read_json(payload_dir / "trade_calendar.json", [])
    return {
        str(value)[:10]
        for value in values
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(value)[:10])
    }


def _provenance(payload_dir: Path) -> dict[str, dict]:
    payload = _read_json(payload_dir / "ingestion_provenance.json", {})
    if payload.get("schema_version") != "ingestion-provenance-v1":
        return {}
    return payload.get("stocks") or {}


def _mapping_hash(mapping: dict) -> str:
    clean = {
        str(key): value
        for key, value in mapping.items()
        if not str(key).startswith("_")
    }
    return hashlib.sha256(_canonical(clean)).hexdigest()


def _reference_quality(payload_dir: Path, universe: dict, trade_date: str) -> dict:
    manifest = _read_json(payload_dir / "reference_data_manifest.json", {})
    industries = _read_json(payload_dir / "stock_industry.json", {})
    caps = _read_json(payload_dir / "stock_market_cap.json", {})
    industries = industries if isinstance(industries, dict) else {}
    caps = caps if isinstance(caps, dict) else {}
    total = len(universe)
    industry_count = sum(bool(industries.get(code)) for code in universe)
    cap_count = sum(
        isinstance(caps.get(code), dict)
        and isinstance(
            caps[code].get("circ_mv") or caps[code].get("total_mv"), (int, float)
        )
        and (caps[code].get("circ_mv") or caps[code].get("total_mv")) > 0
        for code in universe
    )
    industry_ratio = industry_count / total if total else 0.0
    cap_ratio = cap_count / total if total else 0.0
    valid = (
        manifest.get("schema_version") == "reference-data-v1"
        and manifest.get("as_of") == trade_date
        and manifest.get("valid") is True
        and (manifest.get("industry") or {}).get("content_hash")
        == _mapping_hash(industries)
        and (manifest.get("market_cap") or {}).get("content_hash")
        == _mapping_hash(caps)
        and industry_ratio >= 0.80
        and cap_ratio >= 0.95
    )
    return {
        "valid": valid,
        "industry_coverage_ratio": round(industry_ratio, 6),
        "cap_coverage_ratio": round(cap_ratio, 6),
        "industry_count": industry_count,
        "cap_count": cap_count,
    }


def _security_status_quality(
    payload_dir: Path, universe: dict[str, str], trade_date: str
) -> dict:
    payload = _read_json(payload_dir / "security_status.json", {})
    securities = payload.get("securities")
    securities = securities if isinstance(securities, dict) else {}
    canonical_hash = hashlib.sha256(_canonical(securities)).hexdigest()
    all_valid_entries = {
        code: item
        for code, item in securities.items()
        if isinstance(item, dict)
        and item.get("verified") is True
        and item.get("as_of") == trade_date
        and item.get("source_id") in TRUSTED_SECURITY_STATUS_SOURCES
        and item.get("status") in {"active", "suspended", "delisted"}
    }
    valid_entries = {
        code: item for code, item in all_valid_entries.items() if code in universe
    }
    try:
        captured_at = datetime.fromisoformat(str(payload.get("captured_at") or ""))
        captured_at_valid = captured_at.tzinfo is not None
    except ValueError:
        captured_at_valid = False
    suspended_count = sum(
        item.get("status") == "suspended" for item in all_valid_entries.values()
    )
    valid = bool(
        payload.get("schema_version") == "security-status-v1"
        and payload.get("as_of") == trade_date
        and payload.get("source_id") in TRUSTED_SECURITY_STATUS_SOURCES
        and payload.get("count") == len(securities)
        and len(all_valid_entries) == len(securities)
        and len(valid_entries) == len(universe)
        and payload.get("suspended_count") == suspended_count
        and payload.get("content_hash") == canonical_hash
        and captured_at_valid
    )
    return {
        "valid": valid,
        "entries": valid_entries,
        "count": len(valid_entries),
        "suspended_count": suspended_count,
        "content_hash": canonical_hash,
    }


@dataclass(frozen=True)
class StagingSnapshot:
    root: Path
    payload_dir: Path
    base_snapshot_id: str | None


def _link_or_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def prepare_staging_snapshot(data_dir: str | Path = "data") -> StagingSnapshot:
    """只从当前已完整验证快照构建 copy-on-write staging。"""
    data_root = Path(data_dir)
    current = load_current_market_snapshot(data_root, verify_files=True)
    if not current.get("available"):
        raise RuntimeError(
            "validated_base_snapshot_required:"
            f"{current.get('reason', 'snapshot_unavailable')}"
        )
    staging_parent = data_root / STAGING_DIR
    staging_parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix=f"run-{uuid4().hex[:12]}-", dir=staging_parent))
    payload = root / "payload"
    payload.mkdir()
    source_root = Path(current["payload_dir"])
    base_snapshot_id = current["snapshot_id"]

    for path in sorted(source_root.glob("[0-9][0-9]/*.csv")):
        if re.fullmatch(r"\d{6}", path.stem):
            _link_or_copy(path, payload / path.parent.name / path.name)
    for name in METADATA_FILES:
        source = source_root / name
        if source.is_file():
            _link_or_copy(source, payload / name)
    return StagingSnapshot(
        root=root, payload_dir=payload, base_snapshot_id=base_snapshot_id
    )


def prepare_empty_staging_snapshot(data_dir: str | Path = "data") -> StagingSnapshot:
    """为可信全量重建创建空快照，不继承任何 legacy 行情或 provenance。"""
    data_root = Path(data_dir)
    staging_parent = data_root / STAGING_DIR
    staging_parent.mkdir(parents=True, exist_ok=True)
    root = Path(
        tempfile.mkdtemp(prefix=f"rebuild-{uuid4().hex[:12]}-", dir=staging_parent)
    )
    payload = root / "payload"
    payload.mkdir()
    (root / REBUILD_MARKER).write_text(
        json.dumps(
            {
                "schema_version": REBUILD_MARKER_SCHEMA,
                "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return StagingSnapshot(root=root, payload_dir=payload, base_snapshot_id=None)


def seed_universe_metadata_from_current(
    data_dir: str | Path,
    payload_dir: str | Path,
) -> dict[str, Any]:
    """把当前已验证快照的股票池元数据种入空重建 staging。

    只复制名单与 manifest，绝不复制 CSV 行情。东财主表故障时，重建仍可走
    腾讯确认过的 last-known-good 名单，而历史 K 线仍需从可信源重抓。
    """
    current = load_current_market_snapshot(data_dir, verify_files=True)
    if not current.get("available"):
        return {
            "seeded": False,
            "reason": current.get("reason", "validated_snapshot_missing"),
        }
    source_root = Path(current["payload_dir"])
    target = Path(payload_dir)
    target.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for name in UNIVERSE_SEED_FILES:
        source = source_root / name
        if not source.is_file():
            return {
                "seeded": False,
                "reason": f"missing_universe_seed_file:{name}",
                "snapshot_id": current.get("snapshot_id"),
            }
        shutil.copy2(source, target / name)
        copied.append(name)
    return {
        "seeded": True,
        "snapshot_id": current.get("snapshot_id"),
        "files": copied,
    }


def find_resumable_rebuild_snapshot(
    data_dir: str | Path = "data",
    *,
    max_age_hours: float = 24.0,
) -> StagingSnapshot | None:
    """找到最新的可信未完成全量重建，用于只续抓缺口。

    旧版重建没有 marker，因此还会核对股票池、来源记录和 CSV
    的一致性。最终 promote 仍会做全量 hash/schema/日期质量校验。
    """
    if max_age_hours <= 0:
        return None
    staging_parent = Path(data_dir) / STAGING_DIR
    if not staging_parent.is_dir():
        return None
    cutoff = time.time() - max_age_hours * 3600
    candidates = sorted(
        (path for path in staging_parent.glob("rebuild-*") if path.is_dir()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for root in candidates:
        payload = root / "payload"
        if not payload.is_dir() or root.stat().st_mtime < cutoff:
            continue
        marker_path = root / REBUILD_MARKER
        marker = _read_json(marker_path, {})
        if (
            marker_path.is_file()
            and marker.get("schema_version") != REBUILD_MARKER_SCHEMA
        ):
            continue
        universe, universe_manifest = _approved_universe(payload)
        if universe_manifest.get("valid") is not True:
            continue
        provenance_payload = _read_json(payload / "ingestion_provenance.json", {})
        if provenance_payload.get("schema_version") != "ingestion-provenance-v1":
            continue
        provenance = provenance_payload.get("stocks") or {}
        if not isinstance(provenance, dict):
            continue
        csv_codes = {
            path.stem
            for path in payload.glob("[0-9][0-9]/[0-9][0-9][0-9][0-9][0-9][0-9].csv")
        }
        if (
            not csv_codes
            or not csv_codes.issubset(universe)
            or csv_codes != set(provenance)
        ):
            continue
        if any(
            not isinstance(item, dict)
            or item.get("source_id") not in TRUSTED_SOURCES
            or item.get("synthetic") is True
            for item in provenance.values()
        ):
            continue
        return StagingSnapshot(root=root, payload_dir=payload, base_snapshot_id=None)
    return None


def validate_snapshot_payload(
    payload_dir: str | Path,
    trade_date: str,
    *,
    minimum_coverage: float = 0.98,
    required_source_count: int = 2,
) -> dict:
    payload = Path(payload_dir)
    universe, universe_manifest = _approved_universe(payload)
    reference_quality = _reference_quality(payload, universe, trade_date)
    security_status_quality = _security_status_quality(payload, universe, trade_date)
    security_statuses = security_status_quality["entries"]
    calendar = _trade_calendar(payload)
    provenance = _provenance(payload)
    files: dict[str, dict] = {}
    metadata_files: dict[str, dict] = {}
    missing_metadata = []
    for name in METADATA_FILES:
        path = payload / name
        if not path.is_file():
            missing_metadata.append(name)
            continue
        metadata_files[name] = {
            "path": name,
            "content_hash": _sha256_file(path),
            "size": path.stat().st_size,
        }
    schema_errors: dict[str, list[str]] = {}
    stale_codes: dict[str, str | None] = {}
    missing_codes = []
    future_rows = 0
    synthetic_rows = 0
    valid_count = 0
    classified_non_trading: dict[str, str] = {}
    sources = set()
    anchor_dates: dict[str, str | None] = {}

    for code in sorted(universe):
        security_status = security_statuses.get(code) or {}
        legal_non_trading = bool(
            security_status_quality["valid"]
            and security_status.get("status") in {"suspended", "delisted"}
        )
        path = payload / code[:2] / f"{code}.csv"
        if not path.is_file():
            if legal_non_trading:
                classified_non_trading[code] = security_status["status"]
                valid_count += 1
            else:
                missing_codes.append(code)
                schema_errors[code] = ["market_file_missing"]
            if code in ANCHOR_CODES:
                anchor_dates[code] = None
            continue
        errors = []
        try:
            frame = pd.read_csv(path)
        except Exception:
            frame = pd.DataFrame()
            errors.append("unreadable_csv")
        missing_columns = sorted(REQUIRED_COLUMNS - set(frame.columns))
        if missing_columns:
            errors.append("missing_columns:" + ",".join(missing_columns))
        dates = (
            pd.to_datetime(frame.get("date"), errors="coerce")
            if "date" in frame
            else pd.Series(dtype="datetime64[ns]")
        )
        invalid_dates = int(dates.isna().sum()) if len(dates) else len(frame)
        if invalid_dates:
            errors.append(f"invalid_dates:{invalid_dates}")
        valid_dates = dates.dropna()
        date_strings = (
            valid_dates.dt.strftime("%Y-%m-%d")
            if not valid_dates.empty
            else pd.Series(dtype=str)
        )
        duplicate_dates = int(date_strings.duplicated().sum())
        if duplicate_dates:
            errors.append(f"duplicate_dates:{duplicate_dates}")
        file_future_rows = (
            int((date_strings > trade_date).sum()) if not date_strings.empty else 0
        )
        future_rows += file_future_rows
        if file_future_rows:
            errors.append(f"future_rows:{file_future_rows}")
        non_trading = sorted(set(date_strings) - calendar) if calendar else []
        if non_trading:
            errors.append(f"non_trading_dates:{len(non_trading)}")
        if not calendar or trade_date not in calendar:
            errors.append("trade_calendar_unavailable_or_incomplete")
        if REQUIRED_COLUMNS.issubset(frame.columns):
            numeric = frame[["open", "high", "low", "close", "volume"]].apply(
                pd.to_numeric,
                errors="coerce",
            )
            bad_ohlc = (
                (numeric["high"] < numeric[["open", "close"]].max(axis=1))
                | (numeric["low"] > numeric[["open", "close"]].min(axis=1))
                | (numeric["high"] < numeric["low"])
                | (numeric["volume"] < 0)
                | numeric.isna().any(axis=1)
            )
            if int(bad_ohlc.sum()):
                errors.append(f"invalid_ohlcv:{int(bad_ohlc.sum())}")

        latest = date_strings.max() if not date_strings.empty else None
        earliest = date_strings.min() if not date_strings.empty else None
        if code in ANCHOR_CODES:
            anchor_dates[code] = latest
        source = provenance.get(code) or {}
        source_id = source.get("source_id")
        history_source_id = source.get("history_source_id")
        is_synthetic = (
            bool(source.get("synthetic"))
            or source_id not in TRUSTED_SOURCES
            or (
                history_source_id is not None
                and history_source_id not in TRUSTED_SOURCES
            )
        )
        if is_synthetic:
            synthetic_rows += len(frame)
            errors.append("untrusted_or_synthetic_source")
        if source.get("adjustment") != "qfq":
            errors.append("adjustment_mismatch")
        expected_source_date = latest if legal_non_trading else trade_date
        if source.get("source_trade_date") != expected_source_date:
            errors.append("source_trade_date_mismatch")
        try:
            fetched_at = datetime.fromisoformat(str(source.get("fetched_at") or ""))
            if fetched_at.tzinfo is None:
                raise ValueError("timezone required")
        except ValueError:
            errors.append("fetched_at_invalid")
        if source.get("persisted_start") != earliest:
            errors.append("provenance_persisted_start_mismatch")
        if source.get("persisted_end") != latest:
            errors.append("provenance_persisted_end_mismatch")
        if int(source.get("rows") or -1) != len(frame):
            errors.append("provenance_row_count_mismatch")
        history_start = source.get("history_coverage_start")
        if not history_start or (earliest and history_start != earliest):
            errors.append("historical_provenance_incomplete")
        if source_id in TRUSTED_SOURCES:
            sources.add(source_id)
        if history_source_id in TRUSTED_SOURCES:
            sources.add(history_source_id)
        if latest != trade_date:
            stale_codes[code] = latest
            if legal_non_trading:
                classified_non_trading[code] = security_status["status"]
            else:
                errors.append("latest_trade_date_mismatch")

        content_hash = _sha256_file(path)
        files[code] = {
            "path": f"{code[:2]}/{code}.csv",
            "content_hash": content_hash,
            "rows": len(frame),
            "first_trade_date": earliest,
            "source_trade_date": latest,
            "source_id": source_id,
            "history_source_id": history_source_id,
            "fetched_at": source.get("fetched_at"),
            "adjustment": source.get("adjustment"),
            "schema_version": "stock-eod-v1",
            "synthetic": bool(source.get("synthetic")),
        }
        if errors:
            schema_errors[code] = errors
        elif latest == trade_date or legal_non_trading:
            valid_count += 1

    expected_count = len(universe)
    coverage = valid_count / expected_count if expected_count else 0.0
    anchor_quorum = sum(anchor_dates.get(code) == trade_date for code in ANCHOR_CODES)
    source_quorum_passed = len(sources) >= required_source_count
    expected_paths = {item["path"] for item in files.values()} | {
        item["path"] for item in metadata_files.values()
    }
    actual_paths = {
        str(path.relative_to(payload)) for path in payload.rglob("*") if path.is_file()
    }
    unexpected_files = sorted(actual_paths - expected_paths)
    valid = (
        universe_manifest.get("valid") is True
        and expected_count > 0
        and coverage >= minimum_coverage
        and anchor_quorum >= 3
        and not future_rows
        and not synthetic_rows
        and not schema_errors
        and source_quorum_passed
        and not missing_metadata
        and reference_quality["valid"]
        and security_status_quality["valid"]
        and not unexpected_files
    )
    return {
        "valid": valid,
        "trade_date": trade_date,
        "universe_manifest": universe_manifest,
        "universe_hash": universe_manifest.get("content_hash"),
        "expected_count": expected_count,
        "valid_count": valid_count,
        "coverage_ratio": round(coverage, 6),
        "minimum_coverage": minimum_coverage,
        "anchor_dates": anchor_dates,
        "anchor_quorum": anchor_quorum,
        "source_set": sorted(sources),
        "required_source_count": required_source_count,
        "source_quorum_passed": source_quorum_passed,
        "schema_error_count": len(schema_errors),
        "schema_errors": schema_errors,
        "future_rows": future_rows,
        "synthetic_rows": synthetic_rows,
        "missing_codes": missing_codes,
        "stale_codes": stale_codes,
        "classified_non_trading": classified_non_trading,
        "files": files,
        "metadata_files": metadata_files,
        "missing_metadata": missing_metadata,
        "unexpected_files": unexpected_files,
        "reference_quality": reference_quality,
        "security_status_quality": {
            key: value
            for key, value in security_status_quality.items()
            if key != "entries"
        },
    }


def promote_staging_snapshot(
    staging: StagingSnapshot,
    trade_date: str,
    *,
    data_dir: str | Path = "data",
    code_sha: str | None = None,
    minimum_coverage: float = 0.98,
    required_source_count: int = 2,
) -> dict:
    """校验并原子 promote；校验失败时绝不修改 CURRENT_SNAPSHOT。"""
    data_root = Path(data_dir)
    quality = validate_snapshot_payload(
        staging.payload_dir,
        trade_date,
        minimum_coverage=minimum_coverage,
        required_source_count=required_source_count,
    )
    quality_path = staging.root / "quality-report.json"
    quality_path.write_text(
        json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if not quality["valid"]:
        return {
            "promoted": False,
            "reason": "snapshot_validation_failed",
            "staging_dir": str(staging.root),
            "quality": quality,
        }

    captured_at = datetime.now().astimezone().isoformat(timespec="seconds")
    manifest_body = {
        "schema_version": SCHEMA_VERSION,
        "status": "validated",
        "trade_date": trade_date,
        "closed_at": f"{trade_date}T15:05:00+08:00",
        "captured_at": captured_at,
        "base_snapshot_id": staging.base_snapshot_id,
        "universe_snapshot_id": quality["universe_hash"],
        "source_set": quality["source_set"],
        "expected_count": quality["expected_count"],
        "valid_count": quality["valid_count"],
        "coverage_ratio": quality["coverage_ratio"],
        "anchor_dates": quality["anchor_dates"],
        "anchor_quorum": quality["anchor_quorum"],
        "source_quorum_passed": quality["source_quorum_passed"],
        "schema_errors": quality["schema_error_count"],
        "future_rows": quality["future_rows"],
        "synthetic_rows": quality["synthetic_rows"],
        "files": quality["files"],
        "metadata_files": quality["metadata_files"],
        "reference_quality": quality["reference_quality"],
        "quality_report_hash": _sha256_file(quality_path),
        "code_sha": code_sha,
    }
    snapshot_id = _snapshot_id(manifest_body)
    manifest = {"snapshot_id": snapshot_id, **manifest_body}
    (staging.root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    snapshots = data_root / SNAPSHOT_DIR
    snapshots.mkdir(parents=True, exist_ok=True)
    final = snapshots / snapshot_id
    if final.exists():
        existing = _read_json(final / "manifest.json", {})
        if existing != manifest:
            return {
                "promoted": False,
                "reason": "snapshot_id_collision",
                "snapshot_id": snapshot_id,
            }
        shutil.rmtree(staging.root)
    else:
        os.replace(staging.root, final)
    pointer = data_root / CURRENT_POINTER
    pointer_tmp = pointer.with_suffix(f".{os.getpid()}.tmp")
    pointer_tmp.write_text(snapshot_id + "\n", encoding="utf-8")
    pointer_tmp.replace(pointer)
    return {
        "promoted": True,
        "snapshot_id": snapshot_id,
        "trade_date": trade_date,
        "manifest": manifest,
        "payload_dir": str(final / "payload"),
    }


def load_market_snapshot(
    data_dir: str | Path,
    snapshot_id: str,
    *,
    verify_files: bool = False,
) -> dict:
    """按内容 ID 加载快照；replay 只能通过这个入口读取历史快照。"""
    data_root = Path(data_dir)
    if not re.fullmatch(r"[0-9a-f]{64}", snapshot_id):
        return {"available": False, "reason": "snapshot_pointer_invalid"}
    root = data_root / SNAPSHOT_DIR / snapshot_id
    manifest = _read_json(root / "manifest.json", {})
    if not manifest:
        return {"available": False, "reason": "snapshot_manifest_missing"}
    body = {key: value for key, value in manifest.items() if key != "snapshot_id"}
    if manifest.get("snapshot_id") != snapshot_id or _snapshot_id(body) != snapshot_id:
        return {"available": False, "reason": "snapshot_manifest_hash_mismatch"}
    if manifest.get("schema_version") != SCHEMA_VERSION:
        return {"available": False, "reason": "snapshot_schema_unsupported"}
    if manifest.get("status") != "validated":
        return {"available": False, "reason": "snapshot_not_validated"}
    payload = root / "payload"
    if verify_files:
        verified_items = list((manifest.get("files") or {}).values())
        verified_items.extend((manifest.get("metadata_files") or {}).values())
        expected_paths = {str(item.get("path") or "") for item in verified_items}
        actual_paths = {
            str(path.relative_to(payload))
            for path in payload.rglob("*")
            if path.is_file()
        }
        if actual_paths != expected_paths:
            return {
                "available": False,
                "reason": "snapshot_unexpected_files",
                "unexpected": sorted(actual_paths - expected_paths),
                "missing": sorted(expected_paths - actual_paths),
            }
        for item in verified_items:
            path = payload / item.get("path", "")
            if not path.is_file() or _sha256_file(path) != item.get("content_hash"):
                return {
                    "available": False,
                    "reason": "snapshot_file_hash_mismatch",
                    "path": item.get("path"),
                }
    return {
        "available": True,
        "snapshot_id": snapshot_id,
        "manifest": manifest,
        "payload_dir": str(payload),
    }


def load_current_market_snapshot(
    data_dir: str | Path = "data",
    *,
    verify_files: bool = False,
) -> dict:
    data_root = Path(data_dir)
    pointer = data_root / CURRENT_POINTER
    try:
        snapshot_id = pointer.read_text(encoding="utf-8").strip()
    except OSError:
        return {"available": False, "reason": "snapshot_pointer_missing"}
    return load_market_snapshot(data_root, snapshot_id, verify_files=verify_files)
