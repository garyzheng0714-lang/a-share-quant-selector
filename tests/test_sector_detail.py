import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
from flask import Flask

from utils import sector_rotation
from utils.artifact_integrity import seal_artifact
from views.insight_api import insight_bp


class SectorRotationCacheTest(unittest.TestCase):
    def test_industry_mapping_change_invalidates_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_file = Path(tmp) / "sector.json"
            cache_file.write_text(
                json.dumps(
                    {
                        "available": True,
                        "trade_date": "2026-07-14",
                        "heat_map": {"旧板块": {"score": 80}},
                        "universe_fingerprint": "old-map",
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch.object(sector_rotation, "CACHE_FILE", cache_file),
                patch.object(
                    sector_rotation, "_latest_data_date", return_value="2026-07-14"
                ),
                patch.object(
                    sector_rotation, "_universe_fingerprint", return_value="new-map"
                ),
            ):
                self.assertIsNone(sector_rotation._read_valid_cache(MagicMock()))

    def test_matching_mapping_keeps_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_file = Path(tmp) / "sector.json"
            expected = seal_artifact(
                {
                    "available": True,
                    "trade_date": "2026-07-14",
                    "cache_version": sector_rotation.SECTOR_CACHE_VERSION,
                    "heat_map": {"医药": {"score": 80}},
                    "universe_fingerprint": "same-map",
                    "cache_key": "same-cache",
                }
            )
            cache_file.write_text(json.dumps(expected), encoding="utf-8")
            with (
                patch.object(sector_rotation, "CACHE_FILE", cache_file),
                patch.object(
                    sector_rotation, "_latest_data_date", return_value="2026-07-14"
                ),
                patch.object(
                    sector_rotation, "_universe_fingerprint", return_value="same-map"
                ),
                patch.object(
                    sector_rotation,
                    "cache_identity",
                    return_value={"cache_key": "same-cache"},
                ),
            ):
                self.assertEqual(
                    sector_rotation._read_valid_cache(MagicMock()), expected
                )


class SectorDetailApiTest(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.register_blueprint(insight_bp)
        self.client = self.app.test_client()
        self.tmp = tempfile.TemporaryDirectory()
        self.previous_cwd = os.getcwd()
        os.chdir(self.tmp.name)
        Path("data").mkdir()

    def tearDown(self):
        os.chdir(self.previous_cwd)
        self.tmp.cleanup()

    def _write_universe(self, industries):
        Path("data/stock_names.json").write_text(
            json.dumps({"000001": "平安银行", "000002": "万科A"}),
            encoding="utf-8",
        )
        Path("data/stock_industry.json").write_text(
            json.dumps(industries),
            encoding="utf-8",
        )

    @staticmethod
    def _metadata(industries):
        def load(filename, *_args, **_kwargs):
            value = (
                {"000001": "平安银行", "000002": "万科A"}
                if filename == "stock_names.json"
                else industries
            )
            return value, "a" * 64

        return load

    def test_stale_sector_link_returns_explanation_instead_of_load_error(self):
        self._write_universe({"000001": "银行"})
        cm = MagicMock()
        with (
            patch("utils.csv_manager.CSVManager", return_value=cm),
            patch(
                "utils.market_snapshot.read_snapshot_metadata",
                side_effect=self._metadata({"000001": "银行"}),
            ),
            patch(
                "utils.sector_rotation.read_cached_sector_rotation",
                return_value={
                    "available": True,
                    "trade_date": "2026-07-14",
                    "heat_map": {"银行": {}},
                },
            ),
        ):
            response = self.client.get("/api/sectors/%E6%97%A7%E6%9D%BF%E5%9D%97")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json["available"])
        self.assertIn("板块分类已更新", response.json["reason"])

    def test_bad_stock_file_fails_closed_instead_of_returning_partial_sector(self):
        self._write_universe({"000001": "银行", "000002": "银行"})
        cm = MagicMock()
        cm.read_stock.side_effect = [
            pd.DataFrame({"close": [10.0, 9.8, 9.6, 9.7, 9.5, 9.4]}),
            pd.DataFrame({"date": ["2026-07-14"]}),
        ]
        state = {
            "score": 80.0,
            "delta3": 5.0,
            "stage": "主线候选",
            "rank": 1,
            "total": 10,
            "relative_strength": 88.0,
        }
        with (
            patch("utils.csv_manager.CSVManager", return_value=cm),
            patch(
                "utils.market_snapshot.read_snapshot_metadata",
                side_effect=self._metadata({"000001": "银行", "000002": "银行"}),
            ),
            patch(
                "utils.sector_rotation.read_cached_sector_rotation",
                return_value={
                    "available": True,
                    "trade_date": "2026-07-14",
                    "heat_map": {"银行": state},
                },
            ),
            patch(
                "utils.super_b1_scan.read_cached_super_b1", return_value={"hits": []}
            ),
            patch(
                "utils.factor_scan.read_cached_factor_hits",
                return_value={"available": False},
            ),
            patch("utils.decision_ledger.get_latest_decision", return_value={}),
        ):
            response = self.client.get("/api/sectors/%E9%93%B6%E8%A1%8C")
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json["available"])
        self.assertEqual(response.json["reason"], "snapshot_stock_read_failed")
        self.assertEqual(response.json["error_count"], 1)


if __name__ == "__main__":
    unittest.main()
