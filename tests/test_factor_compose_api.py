"""/api/factor-compose：读缓存做且/或组合，任一因子没有当日结果整体不可用."""

import json

import pandas as pd
import pytest

import app as app_module
import strategy.factors as factors
from utils.store import Store


def _hit(code, j=50.0):
    return {
        "code": code,
        "name": f"N{code}",
        "date": "2026-08-05",
        "close": 10.0,
        "pct_change": 1.0,
        "J": j,
        "RSI": 55.0,
    }


@pytest.fixture
def client(tmp_path, monkeypatch):
    store = Store(tmp_path)
    cache = tmp_path / "factor_cache"
    cache.mkdir()
    today = {
        "a": {"hits": [_hit("000001", 20), _hit("000002", 30)], "total_scanned": 100},
        "b": {"hits": [_hit("000002", 30), _hit("000003", 40)], "total_scanned": 100},
    }
    (cache / "2026-08-05.json").write_text(json.dumps(today), encoding="utf-8")
    prev = {"a": {"hits": [_hit("000002")]}, "b": {"hits": [_hit("000002")]}}
    (cache / "2026-08-04.json").write_text(json.dumps(prev), encoding="utf-8")
    store.save_json("stock_industry.json", {"000002": "化工"})
    store.write_stock(
        "000002",
        pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-08-05", "2026-08-04"]),
                "open": [10, 9.5],
                "close": [10.0, 9.5],
                "high": [10, 9.5],
                "low": [10, 9.5],
                "volume": [1, 1],
            }
        ),
    )
    monkeypatch.setattr(app_module, "store", store)
    monkeypatch.setitem(factors.FACTOR_REGISTRY, "a", {})
    monkeypatch.setitem(factors.FACTOR_REGISTRY, "b", {})
    monkeypatch.setitem(factors.FACTOR_REGISTRY, "zz", {})
    return app_module.app.test_client()


def test_and_returns_intersection_with_matched_and_streak(client):
    r = client.get("/api/factor-compose?keys=a,b&join=and").get_json()
    assert r["available"] and r["trade_date"] == "2026-08-05"
    assert [h["code"] for h in r["hits"]] == ["000002"]
    hit = r["hits"][0]
    assert hit["matched"] == ["a", "b"]
    assert hit["streak"] == 2 and hit["streak_depth"] == 2
    assert hit["spark"] == [9.5, 10.0]
    assert hit["industry"] == "化工"
    assert r["per_key_counts"] == {"a": 2, "b": 2}


def test_or_returns_union_sorted_by_matched_count(client):
    r = client.get("/api/factor-compose?keys=a,b&join=or").get_json()
    assert [h["code"] for h in r["hits"]] == ["000002", "000001", "000003"]


def test_missing_factor_blocks_whole_result(client):
    r = client.get("/api/factor-compose?keys=a,zz&join=and").get_json()
    assert r["available"] is False and "zz" in r["reason"]


def test_bad_params_rejected(client):
    assert client.get("/api/factor-compose?keys=nope").status_code == 400
    assert client.get("/api/factor-compose?keys=a&join=xor").status_code == 400
    assert client.get("/api/factor-compose?keys=a&date=../x").status_code == 400
