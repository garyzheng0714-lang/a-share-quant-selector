#!/usr/bin/env python3
"""部署前只读检查数据库完整性与配置契约。"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def main() -> None:
    sha = os.environ.get("GIT_COMMIT_SHA", "")
    if len(sha) != 40 or any(char not in "0123456789abcdef" for char in sha.lower()):
        raise RuntimeError("full_git_commit_sha_required")
    state_dir = Path(os.environ.get("QUANT_STATE_DIR", "data"))
    for path in sorted(state_dir.glob("*.db")):
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            check = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if check != "ok":
                raise RuntimeError(f"database_integrity_failed:{path.name}:{check}")
    from utils.runtime_schema import verify_runtime_schema

    verify_runtime_schema()
    print("predeploy check passed")


if __name__ == "__main__":
    main()
