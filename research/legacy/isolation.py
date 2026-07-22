"""旧研究脚本的统一仓库外路径门禁。"""

from __future__ import annotations

import os
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def legacy_root() -> Path:
    if os.environ.get("ALLOW_LEGACY_RESEARCH") != "1":
        raise RuntimeError("legacy_research_requires_explicit_opt_in")
    raw = os.environ.get("LEGACY_RESEARCH_ROOT", "").strip()
    if not raw or not Path(raw).is_absolute():
        raise RuntimeError("absolute_legacy_research_root_required")
    root = Path(raw).resolve()
    if (
        root == Path("/")
        or root == REPOSITORY_ROOT
        or REPOSITORY_ROOT in root.parents
        or root in REPOSITORY_ROOT.parents
    ):
        raise RuntimeError("legacy_research_root_must_be_isolated_from_repository")
    root.mkdir(parents=True, exist_ok=True)
    return root


def legacy_path(value: str | None, default_relative: str) -> Path:
    """解析隔离研究路径；相对路径一律相对研究根目录。"""
    root = legacy_root()
    candidate = Path(value) if value else Path(default_relative)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    if resolved != root and root not in resolved.parents:
        raise RuntimeError("legacy_path_must_be_inside_research_root")
    return resolved
