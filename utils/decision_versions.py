"""决策版本与数据指纹。

每次推荐都必须能回答「用的是哪一版策略、哪一批数据」。
指纹只基于公开的代码和数据元信息，不读配置密钥。
"""
from __future__ import annotations

import hashlib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
BASELINE_FILES = (
    PROJECT_ROOT / "strategy" / "super_b1.py",
    PROJECT_ROOT / "utils" / "super_b1_scan.py",
    PROJECT_ROOT / "utils" / "technical.py",
    PROJECT_ROOT / "utils" / "decision_versions.py",
    PROJECT_ROOT / "utils" / "hierarchical_decision.py",
    PROJECT_ROOT / "utils" / "decision_config.py",
    PROJECT_ROOT / "utils" / "execution_model.py",
    PROJECT_ROOT / "utils" / "event_risk.py",
    PROJECT_ROOT / "utils" / "probability_model.py",
    PROJECT_ROOT / "utils" / "data_freshness.py",
    PROJECT_ROOT / "tools" / "hierarchical_walk_forward.py",
    PROJECT_ROOT / "config" / "strategy_params.yaml",
)

FEATURE_VERSION = "b1-hierarchy-v3"
LEDGER_VERSION = "decision-ledger-v2"
VALIDATED_MODEL_SOURCE_REFS = frozenset({
    "super-b1-original",
    "point-in-time-reference-snapshots-v1",
    "purged-walk-forward-v2",
})


def _digest_files(paths: tuple[Path, ...]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(str(path.relative_to(PROJECT_ROOT)).encode())
        if path.exists():
            digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def strategy_version() -> str:
    """纯规则基线的内容指纹。"""
    return f"super-b1-{_digest_files(BASELINE_FILES)}"


def data_version(data_dir: str | Path = "data") -> str:
    """指纹覆盖行情文件和会改变样本语义的参考数据。"""
    root = Path(data_dir)
    files = sorted(root.glob("[0-9][0-9]/*.csv"))
    digest = hashlib.sha256()
    digest.update(str(len(files)).encode())
    for path in files:
        stat = path.stat()
        digest.update(path.stem.encode())
        digest.update(str(stat.st_size).encode())
        digest.update(str(stat.st_mtime_ns).encode())
    for name in (
        "stock_names.json", "stock_industry.json", "stock_market_cap.json",
        "trade_calendar.json", "reference_snapshots/manifest.json",
    ):
        path = root / name
        digest.update(name.encode())
        if path.exists():
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return f"eod-{digest.hexdigest()[:12]}"
