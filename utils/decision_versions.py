"""决策版本与数据指纹。

每次推荐都必须能回答「用的是哪一版策略、哪一批数据」。
指纹只基于公开的代码和数据元信息，不读配置密钥。
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
BASELINE_FILES = (
    PROJECT_ROOT / "strategy" / "super_b1.py",
    PROJECT_ROOT / "utils" / "super_b1_scan.py",
    PROJECT_ROOT / "utils" / "technical.py",
    PROJECT_ROOT / "utils" / "decision_versions.py",
    PROJECT_ROOT / "utils" / "hierarchical_decision.py",
    PROJECT_ROOT / "utils" / "decision_ledger.py",
    PROJECT_ROOT / "utils" / "csv_manager.py",
    PROJECT_ROOT / "utils" / "decision_config.py",
    PROJECT_ROOT / "utils" / "policy_engine.py",
    PROJECT_ROOT / "utils" / "market_filter.py",
    PROJECT_ROOT / "utils" / "execution_model.py",
    PROJECT_ROOT / "utils" / "event_risk.py",
    PROJECT_ROOT / "utils" / "probability_model.py",
    PROJECT_ROOT / "utils" / "data_freshness.py",
    PROJECT_ROOT / "tools" / "hierarchical_walk_forward.py",
    PROJECT_ROOT / "config" / "strategy_params.yaml",
)

FEATURE_VERSION = "b1-hierarchy-v6"
LEDGER_VERSION = "decision-ledger-v4"
VALIDATED_MODEL_SOURCE_REFS = frozenset(
    {
        "super-b1-original",
        "immutable-market-snapshots-v2",
        "point-in-time-reference-snapshots-v4",
        "point-in-time-feature-snapshots-v1",
        "pit-security-state-and-listing-regime-v2",
        "a-share-eod-open-open-v3",
        "purged-walk-forward-v2",
        "independent-final-calibration-v1",
    }
)


def _digest_files(paths: tuple[Path, ...]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(str(path.relative_to(PROJECT_ROOT)).encode())
        if path.exists():
            digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def git_commit_sha() -> str:
    """返回构建绑定的完整 SHA；开发环境才读取本地 Git。"""
    configured = os.environ.get("GIT_COMMIT_SHA", "").strip().lower()
    if len(configured) == 40 and all(char in "0123456789abcdef" for char in configured):
        return configured
    try:
        return (
            subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=PROJECT_ROOT,
                check=True,
                capture_output=True,
                text=True,
                timeout=2,
            )
            .stdout.strip()
            .lower()
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _policy_files() -> tuple[Path, ...]:
    """覆盖策略与实际传递依赖，避免手工漏列因子文件。"""
    dynamic = tuple(sorted((PROJECT_ROOT / "strategy").rglob("*.py")))
    critical = tuple(
        PROJECT_ROOT / path
        for path in (
            "utils/factor_scan.py",
            "utils/sector_rotation.py",
            "utils/artifact_integrity.py",
            "utils/reference_snapshots.py",
            "utils/market_snapshot.py",
            "utils/paper_trading.py",
            "utils/execution_model.py",
            "utils/decision_config.py",
            "utils/policy_engine.py",
            "utils/market_filter.py",
            "utils/hierarchical_decision.py",
            "utils/decision_ledger.py",
            "utils/csv_manager.py",
            "tools/hierarchical_walk_forward.py",
            "config/strategy_params.yaml",
            "requirements.in",
            "requirements.lock",
            "frontend/package-lock.json",
        )
    )
    return tuple(dict.fromkeys((*BASELINE_FILES, *dynamic, *critical)))


def strategy_version() -> str:
    """实际生产策略依赖的内容指纹，并绑定构建的完整 Git 身份。"""
    return f"super-b1-{_digest_files(_policy_files())}-git-{git_commit_sha()}"


def data_version(data_dir: str | Path = "data") -> str:
    """数据版本就是经 manifest 内容校验的不可变 snapshot ID。"""
    from utils.market_snapshot import load_current_market_snapshot, load_market_snapshot

    root = Path(data_dir)
    # CSVManager.data_dir 可能已经是 snapshots/<id>/payload。
    if root.name == "payload" and len(root.parent.name) == 64:
        base = root.parents[2]
        snapshot = load_market_snapshot(base, root.parent.name, verify_files=False)
    else:
        snapshot = load_current_market_snapshot(root, verify_files=False)
    return (
        f"snapshot-{snapshot['snapshot_id']}"
        if snapshot.get("available")
        else "snapshot-unavailable"
    )


def cache_identity(csv_manager, namespace: str, schema_version: int | str) -> dict:
    """所有策略缓存共用的完整身份，覆盖同日修正和代码/参数变化。"""
    from utils.market_snapshot import (
        load_current_market_snapshot,
        load_market_snapshot,
    )

    root = Path(getattr(csv_manager, "base_data_dir", "data"))
    pinned_snapshot_id = getattr(csv_manager, "snapshot_id", None)
    if hasattr(csv_manager, "snapshot_id") and pinned_snapshot_id is None:
        return {"cache_key": None, "snapshot_id": None}
    snapshot = (
        load_market_snapshot(root, pinned_snapshot_id, verify_files=False)
        if pinned_snapshot_id
        else load_current_market_snapshot(root, verify_files=False)
    )
    if not snapshot.get("available"):
        return {"cache_key": None, "snapshot_id": None}
    manifest = snapshot["manifest"]
    context = {
        "namespace": namespace,
        "cache_schema_version": schema_version,
        "snapshot_id": snapshot["snapshot_id"],
        "strategy_version": strategy_version(),
        "git_commit_sha": git_commit_sha(),
        "universe_hash": manifest.get("universe_snapshot_id"),
        "reference_snapshot_hash": (
            (manifest.get("metadata_files") or {})
            .get("stock_market_cap.json", {})
            .get("content_hash")
        ),
    }
    context["cache_key"] = hashlib.sha256(
        json.dumps(context, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return context
