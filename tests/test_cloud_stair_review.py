"""云阶票级复盘单元测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from utils.cloud_stair_review import (
    build_cloud_stair_review,
    enrich_pick,
    iter_cached_cloud_stair_hits,
    summarize_picks,
)


class _FakeCSV:
    def __init__(self, frames: dict[str, pd.DataFrame]):
        self._frames = frames

    def read_stock(self, code: str) -> pd.DataFrame:
        return self._frames.get(code, pd.DataFrame()).copy()


def _daily(rows: list[tuple[str, float, float, float]]) -> pd.DataFrame:
    """rows: date, open, close, high(=close), low(=close), volume."""
    data = []
    for date, open_, close, volume in rows:
        data.append(
            {
                "date": date,
                "open": open_,
                "close": close,
                "high": max(open_, close),
                "low": min(open_, close),
                "volume": volume,
            }
        )
    return pd.DataFrame(data)


def test_iter_reads_flat_and_sealed_cache(tmp_path: Path, monkeypatch):
    cache_dir = tmp_path / "cache"
    ledger = tmp_path / "ledger.json"
    cache_dir.mkdir()
    flat = {
        "cloud_stair": {
            "hits": [{"code": "000001", "name": "平安银行", "close": 10.0}],
            "total_scanned": 1,
        }
    }
    sealed = {
        "results": {
            "cloud_stair": {
                "hits": [{"code": "000002", "name": "万科A", "close": 8.0}],
            }
        },
        "_cache_key": "x",
    }
    (cache_dir / "2026-07-14.json").write_text(json.dumps(flat), encoding="utf-8")
    (cache_dir / "2026-08-04.json").write_text(json.dumps(sealed), encoding="utf-8")
    monkeypatch.setattr("utils.cloud_stair_review.CACHE_DIR", cache_dir)
    monkeypatch.setattr("utils.cloud_stair_review.LEDGER_PATH", ledger)

    picks = iter_cached_cloud_stair_hits()
    assert [(p["pick_date"], p["code"]) for p in picks] == [
        ("2026-08-04", "000002"),
        ("2026-07-14", "000001"),
    ]
    # 补种后账本应留下样本，即使缓存被删也能读到
    for path in cache_dir.glob("*.json"):
        path.unlink()
    picks_after = iter_cached_cloud_stair_hits()
    assert len(picks_after) == 2


def test_enrich_and_summary_hold_windows():
    daily = _daily(
        [
            ("2026-07-14", 10.0, 10.0, 1_000_000),  # signal
            ("2026-07-15", 10.2, 10.5, 1_000_000),  # entry / next day
            ("2026-07-16", 10.4, 10.6, 1_000_000),
            ("2026-07-17", 10.5, 10.8, 1_000_000),
            ("2026-07-18", 10.7, 11.0, 1_000_000),
            ("2026-07-21", 11.0, 11.2, 1_000_000),  # ~T+5 exit open
            ("2026-07-22", 11.1, 11.3, 1_000_000),
            ("2026-07-23", 11.2, 11.4, 1_000_000),
            ("2026-07-24", 11.3, 11.5, 1_000_000),
            ("2026-07-25", 11.4, 11.6, 1_000_000),
            ("2026-07-28", 11.5, 11.7, 1_000_000),
            ("2026-07-29", 11.6, 11.8, 1_000_000),  # past T+10
        ]
    )
    manager = _FakeCSV({"000001": daily})
    pick = enrich_pick(
        manager,
        {
            "pick_date": "2026-07-14",
            "code": "000001",
            "name": "平安银行",
            "signal_close": 10.0,
            "signal_pct_change": 1.0,
            "industry": "银行",
            "peak_date": None,
            "wave_gain_pct": None,
        },
    )
    assert pick["entry_date"] == "2026-07-15"
    assert pick["next_day_chg"] == 5.0  # 10.5 / 10 - 1
    assert pick["ret_to_date"] is not None and pick["ret_to_date"] > 0
    assert pick["ret_1"] is not None
    assert pick["ret_5"] is not None

    summary = summarize_picks([pick])
    assert summary["pick_count"] == 1
    assert summary["next_day"]["count"] == 1
    assert summary["recommended_hold"] is not None
    assert summary["recommended_hold"]["hold_sessions"] in {1, 5, 10, 20}


def test_build_review_empty_cache(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("utils.cloud_stair_review.CACHE_DIR", tmp_path)
    monkeypatch.setattr("utils.cloud_stair_review.LEDGER_PATH", tmp_path / "empty-ledger.json")
    payload = build_cloud_stair_review(_FakeCSV({}), limit=10)
    assert payload["available"] is False
    assert payload["picks"] == []


def test_record_cloud_stair_hits_persists(tmp_path: Path, monkeypatch):
    from utils.cloud_stair_review import record_cloud_stair_hits

    ledger = tmp_path / "ledger.json"
    monkeypatch.setattr("utils.cloud_stair_review.LEDGER_PATH", ledger)
    n = record_cloud_stair_hits(
        "2026-08-05",
        {"hits": [{"code": "003013", "name": "地铁设计", "close": 12.3}]},
    )
    assert n == 1
    payload = json.loads(ledger.read_text(encoding="utf-8"))
    assert payload["pick_count"] == 1
    assert payload["picks"][0]["code"] == "003013"
