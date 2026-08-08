"""云阶复盘兼容层测试（实现已迁到 strategy_review）。"""

from __future__ import annotations

from pathlib import Path

from utils.cloud_stair_review import build_cloud_stair_review, record_cloud_stair_hits


class _EmptyCSV:
    def read_stock(self, code: str):
        import pandas as pd

        return pd.DataFrame()


def test_compat_record_and_build(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("utils.strategy_review.CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr("utils.strategy_review.LEDGER_DIR", tmp_path / "ledgers")
    monkeypatch.setattr(
        "utils.strategy_review.LEGACY_CLOUD_LEDGER", tmp_path / "legacy.json"
    )
    (tmp_path / "cache").mkdir()
    n = record_cloud_stair_hits(
        "2026-08-05",
        {"hits": [{"code": "003013", "name": "地铁设计", "close": 12.3}]},
    )
    assert n == 1
    payload = build_cloud_stair_review(_EmptyCSV(), limit=10)
    assert payload["strategy"] == "cloud_stair"
    assert payload["available"] is True
    assert payload["picks"][0]["code"] == "003013"


def test_compat_empty(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("utils.strategy_review.CACHE_DIR", tmp_path)
    monkeypatch.setattr("utils.strategy_review.LEDGER_DIR", tmp_path / "ledgers")
    monkeypatch.setattr(
        "utils.strategy_review.LEGACY_CLOUD_LEDGER", tmp_path / "legacy.json"
    )
    payload = build_cloud_stair_review(_EmptyCSV(), limit=10)
    assert payload["available"] is False
