"""export_static：把扫描缓存和日线导出成网页直接读的静态 JSON."""

import json

import pandas as pd
import pytest

import strategy.factors as factors
from export_static import export
from utils.store import Store


def _hit(code, j=50.0, date="2026-08-05"):
    return {"code": code, "name": f"N{code}", "date": date, "close": 10.0, "pct_change": 1.0, "J": j, "RSI": 55.0}


def _bars(dates):
    closes = [10.0 + i for i in range(len(dates))][::-1]
    return pd.DataFrame(
        {"date": pd.to_datetime(dates), "open": closes, "close": closes, "high": closes, "low": closes, "volume": 1}
    )


@pytest.fixture
def out(tmp_path, monkeypatch):
    store = Store(tmp_path / "data")
    cache = store.data_dir / "factor_cache"
    cache.mkdir()
    today = {
        "a": {"hits": [_hit("000001", 20), _hit("000002", 30)], "total_scanned": 100},
        "b": {"hits": [_hit("000002", 30)], "total_scanned": 100},
    }
    (cache / "2026-08-05.json").write_text(json.dumps(today), encoding="utf-8")
    prev = {"a": {"hits": [_hit("000002", date="2026-08-04")]}}
    (cache / "2026-08-04.json").write_text(json.dumps(prev), encoding="utf-8")
    store.save_json("stock_names.json", {"000002": "化工股"})
    store.save_json("stock_industry.json", {"000002": "化工"})
    store.save_json("stock_market_cap.json", {"000002": {"circ_mv": 5e9}})
    store.write_stock("000002", _bars(pd.bdate_range(end="2026-08-05", periods=30)))
    monkeypatch.setitem(factors.FACTOR_REGISTRY, "a", {"name": "因子A", "group": "B1", "fn": lambda c: None})
    monkeypatch.setitem(factors.FACTOR_REGISTRY, "b", {"name": "因子B", "group": "B1", "fn": lambda c: None})
    target = tmp_path / "site"
    export(store, target)
    return target


def _read(out, name):
    return json.loads((out / name).read_text(encoding="utf-8"))


def test_index_lists_codes_per_date_and_factor(out):
    index = _read(out, "hits.json")
    assert index["dates"] == ["2026-08-05", "2026-08-04"]
    assert index["hits"]["2026-08-05"] == {"a": ["000001", "000002"], "b": ["000002"]}
    assert index["hits"]["2026-08-04"] == {"a": ["000002"]}


def test_scan_day_decorates_hits_and_carries_spark(out):
    day = _read(out, "scan/2026-08-05.json")
    hit = day["factors"]["a"]["hits"][1]
    assert hit["industry"] == "化工" and hit["cap_yi"] == 50.0
    assert day["factors"]["a"]["total_scanned"] == 100
    assert len(day["spark"]["000002"]) == 20 and day["spark"]["000002"][-1] == 10.0
    assert "000001" not in day["spark"]  # 没有日线就不造走势


def test_factors_count_latest_scan_hits(out):
    meta = {f["key"]: f for f in _read(out, "factors.json")["factors"]}
    assert meta["a"]["today_hits"] == 2 and meta["b"]["today_hits"] == 1
    assert _read(out, "factors.json")["recent_dates"] == ["2026-08-05", "2026-08-04"]


def test_stock_file_has_profile_both_periods_and_signals(out):
    stock = _read(out, "stock/000002.json")
    assert stock["profile"] == {
        "code": "000002", "name": "化工股", "industry": "化工", "cap_yi": 50.0, "latest_date": "2026-08-05"
    }
    assert stock["daily"]["period"] == "daily" and len(stock["daily"]["data"]) == 30
    assert stock["weekly"]["change_label"] == "本周涨跌"
    assert {(s["date"], s["category"]) for s in stock["daily"]["signals"]} == {
        ("2026-08-05", "因子A"), ("2026-08-05", "因子B"), ("2026-08-04", "因子A")
    }
    assert not (out / "stock" / "000001.json").exists()


def test_stats(out):
    assert _read(out, "stats.json") == {"latest_date": "", "scan_date": "2026-08-05", "stock_count": 1}
