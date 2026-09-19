"""扫描器：只对目标日有 K 线的股票计算，ST/退市不入池，结果落缓存."""

import numpy as np
import pandas as pd

from utils import scan
from utils.store import Store


def _bars(days, start="2026-01-01"):
    dates = pd.bdate_range(start, periods=days)
    close = np.linspace(10, 12, days)
    return pd.DataFrame(
        {
            "date": dates,
            "open": close * 0.99,
            "close": close,
            "high": close * 1.01,
            "low": close * 0.98,
            "volume": 1e6,
        }
    )


def test_scan_writes_cache_and_skips_stale_or_st(tmp_path):
    store = Store(tmp_path)
    store.write_stock("000001", _bars(200))
    store.write_stock("600030", _bars(200))
    store.write_stock("600036", _bars(200))
    store.write_stock("600519", _bars(200))
    store.write_stock("000002", _bars(190))  # 目标日无 K 线 → 跳过
    store.write_stock("000003", _bars(200))  # ST → 不入池
    store.save_json(
        "stock_names.json",
        {
            "000001": "平安",
            "000002": "旧",
            "000003": "ST三",
            "600030": "a",
            "600036": "b",
            "600519": "c",
        },
    )

    result = scan.scan(store, workers=1)

    assert result["available"] is True
    assert result["trade_date"] == store.latest_date()
    assert all(v["total_scanned"] == 5 for v in result["results"].values())
    assert scan.cache_dates(store) == [result["trade_date"]]
    cached = scan.load_cache(store, result["trade_date"])
    assert set(cached) == set(result["results"])


def test_scan_without_data_is_unavailable(tmp_path):
    result = scan.scan(Store(tmp_path), workers=1)
    assert result["available"] is False
