#!/usr/bin/env python3
"""显式执行生产 SQLite 迁移；Web/worker 本身不执行迁移。"""

from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from utils.runtime_schema import migrate_runtime_schema  # noqa: E402


def main() -> None:
    result = migrate_runtime_schema()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
