"""真正的时点参考数据目录。

这里不再把“今天的映射”贴上历史日期。只有已发布、内容可校验的行情快照
才能成为训练所用的 universe / industry / market-cap 时点证据。
"""

from __future__ import annotations

import hashlib
import json
import logging
import stat
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from utils.market_snapshot import (
    SNAPSHOT_DIR,
    load_current_market_snapshot,
    load_market_snapshot,
)
from utils.runtime_paths import market_data_dir

SCHEMA_VERSION = 4
TZ = ZoneInfo("Asia/Shanghai")
VALIDATION_CACHE_SCHEMA_VERSION = "reference-snapshot-validation-cache-v1"
VALIDATION_CACHE_DIR = ".snapshot_validation_cache"
_VALIDATED_PAYLOAD_KEY = "_validated_snapshot_payload"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ValidatedSnapshotPayload:
    """仅在本次进程内传递的已验证载荷。

    这个对象在 evidence hash 之外附加，不改变参考快照的业务身份。
    """

    snapshot_id: str
    payload_dir: Path
    metadata_fingerprint: str
    validation_source: str


class _SnapshotMetadataError(ValueError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _validation_cache_path(data_root: Path, snapshot_id: str) -> Path:
    return (
        data_root
        / VALIDATION_CACHE_DIR
        / VALIDATION_CACHE_SCHEMA_VERSION
        / f"{snapshot_id}.json"
    )


def _manifest_payload_paths(manifest: dict) -> list[str]:
    items = list((manifest.get("files") or {}).values())
    items.extend((manifest.get("metadata_files") or {}).values())
    paths: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise _SnapshotMetadataError("snapshot_manifest_file_entry_invalid")
        raw = str(item.get("path") or "")
        relative = Path(raw)
        if (
            not raw
            or relative.is_absolute()
            or ".." in relative.parts
            or relative.as_posix() != raw
        ):
            raise _SnapshotMetadataError("snapshot_manifest_file_path_invalid")
        paths.add(raw)
    return sorted(paths)


def _stat_signature(path: Path, logical_path: str, *, directory: bool) -> bytes:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise _SnapshotMetadataError(
            f"snapshot_path_unavailable:{logical_path}"
        ) from exc
    expected_type = stat.S_ISDIR if directory else stat.S_ISREG
    if path.is_symlink() or not expected_type(metadata.st_mode):
        raise _SnapshotMetadataError(f"snapshot_path_type_invalid:{logical_path}")
    return _canonical(
        [
            logical_path,
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_mode,
            metadata.st_uid,
            metadata.st_gid,
            metadata.st_size,
            metadata.st_mtime_ns,
        ]
    )


def _snapshot_metadata_fingerprint(
    snapshot: dict,
    data_root: Path,
    snapshot_id: str,
) -> tuple[str, int]:
    """对已发布快照做便宜但可靠的变更检测。

    文件内容改写会改变 mtime/size，替换会改变 inode，增删会改变
    父目录 mtime。这里故意不纳入 ctime/nlink：新快照会对未变行情
    创建硬链接，只增加链接数不改变已封存内容。
    """
    payload = Path(str(snapshot.get("payload_dir") or ""))
    manifest = snapshot.get("manifest")
    if not isinstance(manifest, dict):
        raise _SnapshotMetadataError("snapshot_validation_payload_invalid")
    expected_payload = (data_root / SNAPSHOT_DIR / snapshot_id / "payload").resolve()
    try:
        payload = payload.resolve(strict=True)
    except OSError as exc:
        raise _SnapshotMetadataError("snapshot_validation_payload_invalid") from exc
    if payload != expected_payload:
        raise _SnapshotMetadataError("snapshot_validation_payload_mismatch")
    snapshot_root = payload.parent
    relative_files = _manifest_payload_paths(manifest)
    actual_files: set[str] = set()
    directories = {Path(".")}
    try:
        entries = payload.rglob("*")
        for entry in entries:
            if entry.is_symlink():
                raise _SnapshotMetadataError("snapshot_symlink_forbidden")
            relative = entry.relative_to(payload)
            if entry.is_dir():
                directories.add(relative)
            elif entry.is_file():
                actual_files.add(relative.as_posix())
            else:
                raise _SnapshotMetadataError("snapshot_special_file_forbidden")
    except OSError as exc:
        raise _SnapshotMetadataError("snapshot_tree_unavailable") from exc
    if actual_files != set(relative_files):
        raise _SnapshotMetadataError("snapshot_payload_paths_changed")

    digest = hashlib.sha256()
    digest.update(_canonical(manifest))
    digest.update(_stat_signature(snapshot_root, "snapshot", directory=True))
    for relative_dir in sorted(directories, key=lambda item: item.as_posix()):
        logical = (
            "payload"
            if relative_dir == Path(".")
            else f"payload/{relative_dir.as_posix()}"
        )
        digest.update(_stat_signature(payload / relative_dir, logical, directory=True))
    for relative_file in relative_files:
        digest.update(
            _stat_signature(
                payload / relative_file,
                f"payload/{relative_file}",
                directory=False,
            )
        )
    return digest.hexdigest(), len(actual_files)


def _read_validation_cache(path: Path, snapshot_id: str) -> dict | None:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(record, dict):
        return None
    seal = record.pop("record_hash", None)
    valid = (
        record.get("schema_version") == VALIDATION_CACHE_SCHEMA_VERSION
        and record.get("snapshot_id") == snapshot_id
        and isinstance(record.get("metadata_fingerprint"), str)
        and isinstance(record.get("file_count"), int)
        and seal == hashlib.sha256(_canonical(record)).hexdigest()
    )
    return record if valid else None


def _write_validation_cache(
    path: Path,
    *,
    snapshot_id: str,
    metadata_fingerprint: str,
    file_count: int,
) -> None:
    record = {
        "schema_version": VALIDATION_CACHE_SCHEMA_VERSION,
        "snapshot_id": snapshot_id,
        "metadata_fingerprint": metadata_fingerprint,
        "file_count": file_count,
        "validated_at": datetime.now(tz=TZ).isoformat(timespec="seconds"),
    }
    record["record_hash"] = hashlib.sha256(_canonical(record)).hexdigest()
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(
            json.dumps(record, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError as exc:
        # 缓存写失败只影响下次性能，不否定本次已完成的全量验证。
        logger.warning("快照验证缓存写入失败 %s: %s", path, exc)
    finally:
        temporary.unlink(missing_ok=True)


def _load_verified_market_snapshot(data_root: Path, snapshot_id: str) -> dict:
    """先用元数据指纹命中已验证缓存，变动时退回全量 hash。"""
    loaded = load_market_snapshot(data_root, snapshot_id, verify_files=False)
    if not loaded.get("available"):
        return loaded
    try:
        before_fingerprint, file_count = _snapshot_metadata_fingerprint(
            loaded, data_root, snapshot_id
        )
    except _SnapshotMetadataError:
        before_fingerprint, file_count = "", -1
    cached = _read_validation_cache(
        _validation_cache_path(data_root, snapshot_id), snapshot_id
    )
    if (
        before_fingerprint
        and cached is not None
        and cached.get("metadata_fingerprint") == before_fingerprint
        and cached.get("file_count") == file_count
    ):
        return {
            **loaded,
            _VALIDATED_PAYLOAD_KEY: _ValidatedSnapshotPayload(
                snapshot_id=snapshot_id,
                payload_dir=Path(loaded["payload_dir"]),
                metadata_fingerprint=before_fingerprint,
                validation_source="persistent_metadata_cache",
            ),
        }

    verified = load_market_snapshot(data_root, snapshot_id, verify_files=True)
    if not verified.get("available"):
        return verified
    try:
        after_fingerprint, verified_file_count = _snapshot_metadata_fingerprint(
            verified, data_root, snapshot_id
        )
    except _SnapshotMetadataError:
        return {
            "available": False,
            "reason": "snapshot_validation_metadata_unavailable",
        }
    if before_fingerprint and before_fingerprint != after_fingerprint:
        return {
            "available": False,
            "reason": "snapshot_changed_during_validation",
        }
    _write_validation_cache(
        _validation_cache_path(data_root, snapshot_id),
        snapshot_id=snapshot_id,
        metadata_fingerprint=after_fingerprint,
        file_count=verified_file_count,
    )
    return {
        **verified,
        _VALIDATED_PAYLOAD_KEY: _ValidatedSnapshotPayload(
            snapshot_id=snapshot_id,
            payload_dir=Path(verified["payload_dir"]),
            metadata_fingerprint=after_fingerprint,
            validation_source="full_content_hash",
        ),
    }


def validated_snapshot_payload(
    reference: dict | None,
    data_dir: str | Path,
    snapshot_id: str,
) -> Path | None:
    """仅解析 ``load_reference_snapshots`` 在本次运行中产生的载荷。"""
    candidate = (reference or {}).get(_VALIDATED_PAYLOAD_KEY)
    if not isinstance(candidate, _ValidatedSnapshotPayload):
        return None
    normalized_id = str(snapshot_id).lower()
    if candidate.snapshot_id != normalized_id:
        return None
    expected = (
        market_data_dir(data_dir) / SNAPSHOT_DIR / normalized_id / "payload"
    ).resolve()
    try:
        actual = candidate.payload_dir.resolve(strict=True)
    except OSError:
        return None
    return actual if actual == expected and actual.is_dir() else None


def forward_capture_evidence(snapshot: dict) -> dict:
    """只有下一交易会话开盘前封存的收盘快照可作为 forward 证据。"""
    manifest = snapshot.get("manifest") or {}
    trade_date = str(manifest.get("trade_date") or "")[:10]
    captured_at = str(manifest.get("captured_at") or "")
    payload = Path(str(snapshot.get("payload_dir") or ""))
    try:
        captured = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
        if captured.tzinfo is None:
            raise ValueError("captured_at_timezone_missing")
        sessions_document = json.loads(
            (payload / "trade_calendar.json").read_text(encoding="utf-8")
        )
        sessions = sorted(
            {
                str(value)[:10]
                for value in sessions_document
                if isinstance(value, str) and len(str(value)) >= 10
            }
        )
        next_session = next(value for value in sessions if value > trade_date)
        session_close = datetime.combine(
            date.fromisoformat(trade_date), time(15, 0), tzinfo=TZ
        )
        next_open = datetime.combine(
            date.fromisoformat(next_session), time(9, 30), tzinfo=TZ
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError, StopIteration) as exc:
        return {
            "eligible": False,
            "reason": f"forward_capture_unverifiable:{type(exc).__name__}",
            "captured_at": captured_at or None,
            "trade_date": trade_date or None,
        }
    captured_local = captured.astimezone(TZ)
    eligible = session_close <= captured_local < next_open
    return {
        "eligible": eligible,
        "reason": "ok" if eligible else "outside_forward_capture_window",
        "captured_at": captured.isoformat(),
        "captured_at_local": captured_local.isoformat(),
        "trade_date": trade_date,
        "session_close": session_close.isoformat(),
        "next_session": next_session,
        "next_session_open": next_open.isoformat(),
    }


def _mapping(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(value, dict):
        return {}
    return {
        str(key): item for key, item in value.items() if not str(key).startswith("_")
    }


def _security_states(payload: Path, trade_date: str, universe: set[str]) -> dict:
    """读取并独立复验快照中的当日证券状态，不用名称猜测停牌状态。"""
    try:
        document = json.loads((payload / "security_status.json").read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    securities = document.get("securities")
    if not isinstance(securities, dict):
        return {}
    canonical = json.dumps(
        securities,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    from utils.market_snapshot import TRUSTED_SECURITY_STATUS_SOURCES

    if (
        document.get("schema_version") != "security-status-v1"
        or document.get("as_of") != trade_date
        or document.get("source_id") not in TRUSTED_SECURITY_STATUS_SOURCES
        or document.get("count") != len(securities)
        or document.get("content_hash") != hashlib.sha256(canonical).hexdigest()
        or set(securities) != universe
    ):
        return {}
    states = {}
    for code, item in securities.items():
        if (
            not isinstance(item, dict)
            or item.get("verified") is not True
            or item.get("as_of") != trade_date
            or item.get("source_id") not in TRUSTED_SECURITY_STATUS_SOURCES
            or item.get("status") not in {"active", "suspended", "delisted"}
            or not isinstance(item.get("is_st"), bool)
        ):
            return {}
        states[code] = {
            "as_of": trade_date,
            "is_st": item["is_st"],
            "trading_status": item["status"],
            "source": item["source_id"],
            "listing_rule_verified": False,
            "status_verified": True,
        }
    return states


def _reference_from_market_snapshot(snapshot: dict) -> dict | None:
    if not snapshot.get("available"):
        return None
    manifest = snapshot["manifest"]
    payload = Path(snapshot["payload_dir"])
    forward_capture = forward_capture_evidence(snapshot)
    if forward_capture.get("eligible") is not True:
        return None
    names = _mapping(payload / "stock_names.json")
    industries = _mapping(payload / "stock_industry.json")
    raw_caps = _mapping(payload / "stock_market_cap.json")
    caps: dict[str, float] = {}
    for code, value in raw_caps.items():
        cap = (
            value.get("circ_mv") or value.get("total_mv")
            if isinstance(value, dict)
            else value
        )
        if isinstance(cap, (int, float)) and cap > 0:
            caps[code] = float(cap)
    if not names or not industries or not caps:
        return None
    trade_date = str(manifest.get("trade_date") or "")[:10]
    security_states = _security_states(payload, trade_date, set(names))
    if len(security_states) != len(names):
        return None
    content = {
        "schema_version": SCHEMA_VERSION,
        "as_of": trade_date,
        "captured_at": manifest.get("captured_at"),
        "market_snapshot_id": snapshot["snapshot_id"],
        "universe": sorted(names),
        "industries": industries,
        "market_caps": caps,
        "security_states": security_states,
        "forward_capture": forward_capture,
    }
    content["evidence_hash"] = hashlib.sha256(
        json.dumps(
            content, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    content["_universe_set"] = set(content["universe"])
    validated_payload = snapshot.get(_VALIDATED_PAYLOAD_KEY)
    if isinstance(validated_payload, _ValidatedSnapshotPayload):
        content[_VALIDATED_PAYLOAD_KEY] = validated_payload
    return content


def capture_reference_snapshot(
    data_dir: str | Path = "data",
    as_of: str | None = None,
    *,
    snapshot_id: str | None = None,
) -> dict:
    """登记一个已发布快照为 PIT 证据；禁止补写或倒签历史日期。

    在线任务应显式传入其已绑定的 ``snapshot_id``，避免任务运行期间
    ``CURRENT_SNAPSHOT`` 切换后混用两个版本。省略参数仅保留给离线运维命令。
    """
    current = (
        load_market_snapshot(data_dir, snapshot_id, verify_files=True)
        if snapshot_id is not None
        else load_current_market_snapshot(data_dir, verify_files=True)
    )
    if not current.get("available"):
        return {
            "available": False,
            "reason": current.get("reason", "market_snapshot_missing"),
        }
    trade_date = str(current["manifest"].get("trade_date") or "")[:10]
    requested = str(as_of or trade_date)[:10]
    if requested != trade_date:
        return {
            "available": False,
            "reason": "historical_backdating_forbidden",
            "requested_as_of": requested,
            "current_trade_date": trade_date,
        }
    reference = _reference_from_market_snapshot(current)
    if reference is None:
        forward_capture = forward_capture_evidence(current)
        if forward_capture.get("eligible") is not True:
            return {
                "available": False,
                "reason": "reference_snapshot_not_forward_eligible",
                "as_of": trade_date,
                "forward_capture": forward_capture,
            }
        return {
            "available": False,
            "reason": "reference_data_incomplete",
            "as_of": trade_date,
        }
    return {
        "available": True,
        "as_of": trade_date,
        "existing": True,
        "market_snapshot_id": current["snapshot_id"],
        "evidence_hash": reference["evidence_hash"],
        "universe_count": len(reference["universe"]),
        "industry_count": len(reference["industries"]),
        "cap_count": len(reference["market_caps"]),
    }


def load_reference_snapshots(data_dir: str | Path = "data") -> dict[str, dict]:
    """从不可变行情快照重建 PIT 目录；损坏或不完整的快照不会进入训练。"""
    root = market_data_dir(data_dir)
    snapshots: dict[str, dict] = {}
    snapshot_root = root / SNAPSHOT_DIR
    if not snapshot_root.exists():
        return snapshots
    for path in sorted(snapshot_root.iterdir()):
        if not path.is_dir():
            continue
        loaded = _load_verified_market_snapshot(root, path.name)
        reference = _reference_from_market_snapshot(loaded)
        if reference is None or not reference.get("as_of"):
            continue
        trade_date = str(reference["as_of"])
        previous = snapshots.get(trade_date)
        if previous is None or str(reference.get("captured_at")) > str(
            previous.get("captured_at")
        ):
            snapshots[trade_date] = reference
    return snapshots
