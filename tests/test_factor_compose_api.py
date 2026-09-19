"""/api/factor-compose：只读 worker 快照的且/或组合，任一因子未就绪整体阻断."""
import unittest
from unittest import mock

from flask import Flask

import views.factor_api as factor_api


def _hit(code, j=50.0):
    return {"code": code, "name": f"N{code}", "date": "2026-08-05", "close": 10.0,
            "pct_change": 1.0, "J": j, "RSI": 55.0}


class _FakeManager:
    snapshot_id = "snap-1"
    base_data_dir = "data"

    def __init__(self, *a, **k):
        pass

    def read_stock(self, code, nrows=None):
        import pandas as pd
        return pd.DataFrame({"date": ["2026-08-05", "2026-08-04"], "close": [10.0, 9.5]})


CACHE_TODAY = {
    "a": {"hits": [_hit("000001", 20), _hit("000002", 30)], "total_scanned": 100},
    "b": {"hits": [_hit("000002", 30), _hit("000003", 40)], "total_scanned": 100},
}
CACHE_PREV = {"a": {"hits": [_hit("000002")]}, "b": {"hits": [_hit("000002")]}}


class FactorComposeApiTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.register_blueprint(factor_api.factor_bp)
        self.client = app.test_client()
        patches = [
            mock.patch.object(factor_api, "CSVManager", _FakeManager),
            mock.patch.object(factor_api, "_industry_map", lambda m: {"000002": "化工"}),
            mock.patch.object(factor_api, "_cap_map", lambda m: {}),
            mock.patch.object(factor_api, "_sector_heat", lambda m: {}),
            mock.patch("utils.factor_scan.recent_trade_dates",
                       lambda m, limit=60: ["2026-08-05", "2026-08-04", "2026-08-03"]),
            mock.patch("utils.factor_scan._load_cache",
                       lambda d, m=None: CACHE_PREV if d == "2026-08-04" else {}),
            mock.patch("utils.market_filter.main_board_only", lambda: False),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _cached(self, keys, date=""):
        return {"available": True, "trade_date": "2026-08-05",
                "results": {k: CACHE_TODAY[k] for k in keys if k in CACHE_TODAY}}

    def test_and_returns_intersection_with_matched_and_streak(self):
        with mock.patch("utils.factor_scan.read_cached_factor_hits", side_effect=lambda m, keys, date="": self._cached(keys)), \
             mock.patch.dict("strategy.factors.FACTOR_REGISTRY", {"a": {}, "b": {}}):
            r = self.client.get("/api/factor-compose?keys=a,b&join=and").get_json()
        self.assertTrue(r["available"])
        self.assertEqual([h["code"] for h in r["hits"]], ["000002"])
        hit = r["hits"][0]
        self.assertEqual(hit["matched"], ["a", "b"])
        self.assertEqual(hit["streak"], 2)          # 8/4 缓存里也在交集里，8/3 无缓存即停
        self.assertEqual(hit["streak_depth"], 2)
        self.assertEqual(hit["spark"], [9.5, 10.0])   # 旧→新
        self.assertIsNone(hit["win_rate"])
        self.assertEqual(r["per_key_counts"], {"a": 2, "b": 2})

    def test_or_returns_union_sorted_by_matched_count(self):
        with mock.patch("utils.factor_scan.read_cached_factor_hits", side_effect=lambda m, keys, date="": self._cached(keys)), \
             mock.patch.dict("strategy.factors.FACTOR_REGISTRY", {"a": {}, "b": {}}):
            r = self.client.get("/api/factor-compose?keys=a,b&join=or").get_json()
        self.assertEqual([h["code"] for h in r["hits"]], ["000002", "000001", "000003"])

    def test_missing_factor_snapshot_blocks_whole_result(self):
        with mock.patch("utils.factor_scan.read_cached_factor_hits", side_effect=lambda m, keys, date="": self._cached(["a"])), \
             mock.patch.dict("strategy.factors.FACTOR_REGISTRY", {"a": {}, "zz": {}}):
            r = self.client.get("/api/factor-compose?keys=a,zz&join=and").get_json()
        self.assertFalse(r["available"])
        self.assertIn("zz", r["reason"])

    def test_bad_params_rejected(self):
        with mock.patch.dict("strategy.factors.FACTOR_REGISTRY", {"a": {}}):
            self.assertEqual(self.client.get("/api/factor-compose?keys=nope").status_code, 400)
            self.assertEqual(self.client.get("/api/factor-compose?keys=a&join=xor").status_code, 400)
            self.assertEqual(self.client.get("/api/factor-compose?keys=a&date=../x").status_code, 400)


if __name__ == "__main__":
    unittest.main()
