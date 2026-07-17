"""按交易日保存训练所需的时点股票池、行业和流通市值。"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path


SCHEMA_VERSION = 1


def _read_mapping(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {key: value for key, value in payload.items() if not key.startswith("_")}


def _update_manifest(
    snapshot_root: Path, trade_date: str, captured_at: str, snapshot_hash: str,
) -> None:
    manifest_path = snapshot_root / "manifest.json"
    manifest = _read_mapping(manifest_path)
    dates = sorted(set(manifest.get("dates") or []) | {trade_date})
    hashes = dict(manifest.get("snapshots") or {})
    if trade_date in (manifest.get("dates") or []) and hashes.get(trade_date) == snapshot_hash:
        return
    hashes[trade_date] = snapshot_hash
    payload = {
        "schema_version": SCHEMA_VERSION,
        "dates": dates,
        "snapshots": {date: hashes[date] for date in dates if date in hashes},
        "updated_at": captured_at,
    }
    tmp = manifest_path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(manifest_path)


def capture_reference_snapshot(data_dir: str | Path = "data", as_of: str | None = None) -> dict:
    root = Path(data_dir)
    trade_date = str(as_of or "")[:10]
    if not trade_date:
        return {"available": False, "reason": "snapshot_date_missing"}

    snapshot_root = root / "reference_snapshots"
    snapshot_root.mkdir(parents=True, exist_ok=True)
    target = snapshot_root / f"{trade_date}.json"
    if target.exists():
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
        if (
            existing.get("schema_version") == SCHEMA_VERSION
            and existing.get("as_of") == trade_date
        ):
            _update_manifest(
                snapshot_root,
                trade_date,
                existing.get("captured_at") or datetime.now().astimezone().isoformat(timespec="seconds"),
                hashlib.sha256(target.read_bytes()).hexdigest(),
            )
            return {
                "available": True, "as_of": trade_date, "existing": True,
                "universe_count": len(existing.get("universe") or []),
                "industry_count": len(existing.get("industries") or {}),
                "cap_count": len(existing.get("market_caps") or {}),
            }

    names = _read_mapping(root / "stock_names.json")
    industries = _read_mapping(root / "stock_industry.json")
    raw_caps = _read_mapping(root / "stock_market_cap.json")
    caps = {}
    for code, value in raw_caps.items():
        if isinstance(value, dict):
            cap = value.get("circ_mv") or value.get("total_mv")
        else:
            cap = value
        if isinstance(cap, (int, float)) and cap > 0:
            caps[code] = float(cap)
    if not names or not caps:
        return {
            "available": False, "reason": "reference_data_incomplete",
            "universe_count": len(names), "cap_count": len(caps),
        }

    captured_at = datetime.now().astimezone().isoformat(timespec="seconds")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "as_of": trade_date,
        "captured_at": captured_at,
        "universe": sorted(names),
        "industries": industries,
        "market_caps": caps,
    }
    tmp = target.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(target)
    _update_manifest(
        snapshot_root, trade_date, captured_at,
        hashlib.sha256(target.read_bytes()).hexdigest(),
    )
    return {
        "available": True, "as_of": trade_date, "existing": False,
        "universe_count": len(names), "industry_count": len(industries), "cap_count": len(caps),
    }


def load_reference_snapshots(data_dir: str | Path = "data") -> dict[str, dict]:
    root = Path(data_dir) / "reference_snapshots"
    snapshots = {}
    if not root.exists():
        return snapshots
    for path in sorted(root.glob("????-??-??.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if payload.get("schema_version") == SCHEMA_VERSION and payload.get("as_of") == path.stem:
            payload["_universe_set"] = set(payload.get("universe") or [])
            snapshots[path.stem] = payload
    return snapshots
