"""策略复盘单元测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from utils.strategy_review import (
    build_strategy_review,
    enrich_pick,
    iter_strategy_hits,
    list_strategy_catalog,
    record_strategy_hits,
    seed_strategy_from_cache,
    summarize_picks,
)


class _FakeCSV:
    def __init__(self, frames: dict[str, pd.DataFrame]):
        self._frames = frames

    def read_stock(self, code: str) -> pd.DataFrame:
        return self._frames.get(code, pd.DataFrame()).copy()


def _daily(rows: list[tuple[str, float, float, float]]) -> pd.DataFrame:
    data = []
    for date, open_, close, volume in rows:
        data.append(
            {
                "date": date,
                "open": open_,
                "close": close,
                "high": max(open_, close) + 0.2,
                "low": min(open_, close) - 0.2,
                "volume": volume,
            }
        )
    return pd.DataFrame(data)


def test_ledger_survives_cache_delete(tmp_path: Path, monkeypatch):
    cache_dir = tmp_path / "cache"
    ledger_dir = tmp_path / "ledgers"
    cache_dir.mkdir()
    monkeypatch.setattr("utils.strategy_review.CACHE_DIR", cache_dir)
    monkeypatch.setattr("utils.strategy_review.LEDGER_DIR", ledger_dir)
    monkeypatch.setattr(
        "utils.strategy_review.LEGACY_CLOUD_LEDGER", tmp_path / "legacy.json"
    )

    (cache_dir / "2026-07-14.json").write_text(
        json.dumps(
            {
                "cloud_stair": {
                    "hits": [
                        {"code": "000001", "name": "平安银行", "close": 10.0, "J": 12}
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    assert seed_strategy_from_cache("cloud_stair") == 1
    picks = iter_strategy_hits("cloud_stair")
    assert len(picks) == 1
    for path in cache_dir.glob("*.json"):
        path.unlink()
    assert len(iter_strategy_hits("cloud_stair")) == 1


def test_enrich_includes_path_and_windows():
    daily = _daily(
        [
            ("2026-07-14", 10.0, 10.0, 1_000_000),
            ("2026-07-15", 10.2, 10.5, 1_000_000),
            ("2026-07-16", 10.4, 10.6, 1_000_000),
            ("2026-07-17", 10.5, 10.8, 1_000_000),
            ("2026-07-18", 10.7, 11.0, 1_000_000),
            ("2026-07-21", 11.0, 11.2, 1_000_000),
            ("2026-07-22", 11.1, 11.3, 1_000_000),
        ]
    )
    pick = enrich_pick(
        _FakeCSV({"000001": daily}),
        {
            "pick_date": "2026-07-14",
            "code": "000001",
            "name": "平安银行",
            "signal_close": 10.0,
            "signal_pct_change": 1.0,
            "industry": "银行",
            "signal": {"J": 8},
        },
        strategy="cloud_stair",
        strategy_name="云阶",
        trading_sessions=daily["date"].tolist(),
    )
    assert pick["next_day_chg"] == 5.0
    assert pick["entry_gap_pct"] is not None
    assert pick["path"] and pick["path"][0]["session"] == 1
    assert pick["mfe_to_date"] is not None
    assert pick["windows"]["ret_1"]["net_return"] is not None
    summary = summarize_picks([pick])
    assert summary["top_picks"]


def test_record_and_catalog(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("utils.strategy_review.CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr("utils.strategy_review.LEDGER_DIR", tmp_path / "ledgers")
    monkeypatch.setattr(
        "utils.strategy_review.LEGACY_CLOUD_LEDGER", tmp_path / "legacy.json"
    )
    (tmp_path / "cache").mkdir()
    n = record_strategy_hits(
        "cloud_stair",
        "2026-08-05",
        {"hits": [{"code": "003013", "name": "地铁设计", "close": 12.3}]},
    )
    assert n == 1
    catalog = list_strategy_catalog()
    cloud = next(c for c in catalog if c["key"] == "cloud_stair")
    assert cloud["pick_count"] >= 1
    assert cloud["has_data"] is True


def test_build_empty(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("utils.strategy_review.CACHE_DIR", tmp_path)
    monkeypatch.setattr("utils.strategy_review.LEDGER_DIR", tmp_path / "ledgers")
    monkeypatch.setattr(
        "utils.strategy_review.LEGACY_CLOUD_LEDGER", tmp_path / "legacy.json"
    )
    payload = build_strategy_review(_FakeCSV({}), "cloud_stair", limit=10)
    assert payload["available"] is False
