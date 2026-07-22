#!/usr/bin/env python3
"""对 data 下 SQLite 数据库做在线一致性备份并生成 hash manifest。"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def backup_databases(data: Path, *, stamp: str | None = None) -> dict[str, Any]:
    """在独立连接上使用 SQLite online backup 生成一致副本。"""
    stamp = stamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = data / "backups" / stamp
    target.mkdir(parents=True, exist_ok=False)
    databases: dict[str, dict[str, int | str]] = {}
    manifest: dict[str, Any] = {"created_at": stamp, "databases": databases}
    for source in sorted(data.glob("*.db")):
        destination = target / source.name
        with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as src:
            with sqlite3.connect(str(destination)) as dst:
                src.backup(dst)
                check = dst.execute("PRAGMA integrity_check").fetchone()[0]
        if check != "ok":
            raise RuntimeError(f"backup_integrity_failed:{source.name}:{check}")
        databases[source.name] = {
            "size": destination.stat().st_size,
            "sha256": sha256(destination),
        }
    manifest_path = target / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    return {"backup_dir": str(target), **manifest}


def main() -> None:
    result = backup_databases(Path(os.environ.get("QUANT_STATE_DIR", "data")))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
