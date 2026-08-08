"""真正的时点参考数据目录。

这里不再把“今天的映射”贴上历史日期。只有已发布、内容可校验的行情快照
才能成为训练所用的 universe / industry / market-cap 时点证据。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from utils.market_snapshot import (
    SNAPSHOT_DIR,
    load_current_market_snapshot,
    load_market_snapshot,
)
from utils.runtime_paths import market_data_dir

SCHEMA_VERSION = 4


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
    }
    content["evidence_hash"] = hashlib.sha256(
        json.dumps(
            content, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    content["_universe_set"] = set(content["universe"])
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
        loaded = load_market_snapshot(root, path.name, verify_files=True)
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
