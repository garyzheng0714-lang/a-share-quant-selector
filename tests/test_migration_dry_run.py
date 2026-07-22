from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from tools.migration_dry_run import migration_dry_run


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_legacy_database(path: Path, marker: str) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE legacy_marker(value TEXT NOT NULL)")
        connection.execute("INSERT INTO legacy_marker(value) VALUES(?)", (marker,))


def test_migration_dry_run_migrates_copies_without_touching_live_files(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state"
    state.mkdir()
    views = state / "views.db"
    operations = state / "operations.db"
    _make_legacy_database(views, "decision")
    _make_legacy_database(operations, "operations")
    before = {_path.name: _sha256(_path) for _path in (views, operations)}

    result = migration_dry_run(
        state_dir=state,
        views_db=views,
        operations_db=operations,
        git_sha="a" * 40,
    )

    after = {_path.name: _sha256(_path) for _path in (views, operations)}
    assert result["success"] is True
    assert result["source_databases_copied"] == {
        "views.db": True,
        "operations.db": True,
    }
    assert "predeploy check passed" in result["predeploy"]
    assert after == before
    with sqlite3.connect(views) as connection:
        assert connection.execute("SELECT value FROM legacy_marker").fetchone() == (
            "decision",
        )
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE name='runtime_schema_meta'"
            ).fetchone()
            is None
        )


def test_migration_dry_run_supports_first_deploy_without_live_databases(
    tmp_path: Path,
) -> None:
    state = tmp_path / "empty-state"

    result = migration_dry_run(state_dir=state, git_sha="b" * 40)

    assert result["source_databases_copied"] == {
        "views.db": False,
        "operations.db": False,
    }
    assert not state.exists()


def test_migration_dry_run_rejects_invalid_release_identity(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="full_git_commit_sha_required"):
        migration_dry_run(state_dir=tmp_path, git_sha="development")
