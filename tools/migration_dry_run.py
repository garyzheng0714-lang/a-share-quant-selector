#!/usr/bin/env python3
"""在临时副本上执行完整 migration 与 predeploy 校验。"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _copy_database(source: Path, destination: Path) -> bool:
    """使用 SQLite online backup 复制活动数据库，不修改源文件。"""
    if not source.is_file():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True, timeout=30) as src:
        src.execute("PRAGMA query_only=ON")
        src.execute("PRAGMA busy_timeout=30000")
        with sqlite3.connect(str(destination), timeout=30) as dst:
            src.backup(dst)
            check = dst.execute("PRAGMA integrity_check").fetchone()[0]
    if check != "ok":
        raise RuntimeError(f"migration_dry_run_copy_corrupt:{source.name}:{check}")
    return True


def _run_checked(name: str, command: list[str], env: dict[str, str]) -> str:
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()[-2000:]
        raise RuntimeError(f"migration_dry_run_{name}_failed:{detail}")
    return completed.stdout.strip()


def migration_dry_run(
    *,
    state_dir: Path | None = None,
    views_db: Path | None = None,
    operations_db: Path | None = None,
    git_sha: str | None = None,
) -> dict[str, Any]:
    """复制当前账本，在一次性目录内迁移并执行生产只读校验。"""
    live_state = state_dir or Path(os.environ.get("QUANT_STATE_DIR", "data"))
    if views_db is not None:
        live_views = views_db
    elif state_dir is not None:
        live_views = live_state / "views.db"
    else:
        live_views = Path(os.environ.get("QUANT_VIEWS_DB", live_state / "views.db"))
    if operations_db is not None:
        live_operations = operations_db
    elif state_dir is not None:
        live_operations = live_state / "operations.db"
    else:
        live_operations = Path(
            os.environ.get("QUANT_OPERATIONS_DB", live_state / "operations.db")
        )
    release_sha = str(git_sha or os.environ.get("GIT_COMMIT_SHA") or "")
    if len(release_sha) != 40 or any(
        character not in "0123456789abcdef" for character in release_sha.lower()
    ):
        raise ValueError("full_git_commit_sha_required")
    if live_views.resolve() == live_operations.resolve():
        raise ValueError("runtime_database_paths_must_be_distinct")

    with tempfile.TemporaryDirectory(prefix="quant-migration-dry-run-") as temporary:
        dry_state = Path(temporary)
        dry_views = dry_state / "views.db"
        dry_operations = dry_state / "operations.db"
        copied = {
            "views.db": _copy_database(live_views, dry_views),
            "operations.db": _copy_database(live_operations, dry_operations),
        }
        env = os.environ.copy()
        env.update(
            {
                "GIT_COMMIT_SHA": release_sha,
                "QUANT_STATE_DIR": str(dry_state),
                "QUANT_VIEWS_DB": str(dry_views),
                "QUANT_OPERATIONS_DB": str(dry_operations),
            }
        )
        migration_output = _run_checked(
            "migration",
            [sys.executable, "tools/migrate_databases.py"],
            env,
        )
        predeploy_output = _run_checked(
            "predeploy",
            [sys.executable, "tools/predeploy_check.py"],
            env,
        )
    return {
        "success": True,
        "source_databases_copied": copied,
        "migration": migration_output,
        "predeploy": predeploy_output,
    }


def main() -> None:
    print(json.dumps(migration_dry_run(), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
