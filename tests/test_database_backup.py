from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from tools.backup_databases import backup_databases, sha256


def test_online_backup_is_readable_and_matches_manifest(tmp_path: Path) -> None:
    source = tmp_path / "operations.db"
    with sqlite3.connect(source) as conn:
        conn.execute("CREATE TABLE audit_events (id INTEGER PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO audit_events(value) VALUES ('kept')")

    result = backup_databases(tmp_path, stamp="20260722T010203Z")

    backup_dir = Path(result["backup_dir"])
    backup = backup_dir / source.name
    manifest = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))
    with sqlite3.connect(f"file:{backup}?mode=ro", uri=True) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert conn.execute("SELECT value FROM audit_events").fetchone() == ("kept",)
    assert manifest["databases"][source.name] == {
        "size": backup.stat().st_size,
        "sha256": sha256(backup),
    }


def test_backup_of_empty_data_directory_still_has_manifest(tmp_path: Path) -> None:
    result = backup_databases(tmp_path, stamp="20260722T010204Z")

    manifest = json.loads(
        (Path(result["backup_dir"]) / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest == {
        "created_at": "20260722T010204Z",
        "databases": {},
    }
