import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from utils import factor_scan, market_thermometer, sector_rotation, super_b1_scan
from utils.artifact_integrity import artifact_is_valid, seal_artifact


class CachedArtifactIntegrityTest(unittest.TestCase):
    @staticmethod
    def _write_tampered(path: Path, payload: dict) -> None:
        sealed = seal_artifact(payload)
        sealed["trade_date"] = "2099-01-01"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(sealed, ensure_ascii=False), encoding="utf-8")

    def test_canonical_hash_detects_nested_content_change(self):
        value = seal_artifact({"available": True, "nested": {"score": 80}})
        self.assertTrue(artifact_is_valid(value))

        value["nested"]["score"] = 81

        self.assertFalse(artifact_is_valid(value))

    def test_super_b1_reader_rejects_tampered_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "super.json"
            self._write_tampered(
                cache,
                {
                    "available": True,
                    "schema_version": super_b1_scan.CACHE_SCHEMA_VERSION,
                    "trade_date": "2026-07-14",
                    "cache_key": "key",
                    "hits": [],
                },
            )
            with (
                patch.object(super_b1_scan, "CACHE_FILE", cache),
                patch.object(
                    super_b1_scan,
                    "cache_identity",
                    return_value={"cache_key": "key"},
                ),
            ):
                result = super_b1_scan.read_cached_super_b1(MagicMock())

        self.assertFalse(result["available"])

    def test_super_b1_reports_cache_persistence_failure(self):
        with (
            patch.object(
                super_b1_scan,
                "compute_scan",
                return_value={"available": True, "trade_date": "2026-07-14"},
            ),
            patch("builtins.open", side_effect=OSError("disk full")),
        ):
            result = super_b1_scan.get_super_b1(MagicMock(), {}, force=True)

        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "super_b1_cache_write_failed")

    def test_sector_reader_rejects_tampered_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "sector.json"
            self._write_tampered(
                cache,
                {
                    "available": True,
                    "cache_version": sector_rotation.SECTOR_CACHE_VERSION,
                    "trade_date": "2026-07-14",
                    "cache_key": "key",
                    "heat_map": {"银行": {"score": 80}},
                    "universe_fingerprint": "universe",
                },
            )
            with (
                patch.object(sector_rotation, "CACHE_FILE", cache),
                patch.object(
                    sector_rotation,
                    "cache_identity",
                    return_value={"cache_key": "key"},
                ),
                patch.object(
                    sector_rotation,
                    "_universe_fingerprint",
                    return_value="universe",
                ),
            ):
                result = sector_rotation.read_cached_sector_rotation(MagicMock())

        self.assertFalse(result["available"])

    def test_sector_reports_cache_persistence_failure(self):
        with (
            patch.object(
                sector_rotation,
                "compute_sector_rotation",
                return_value={"available": True, "trade_date": "2026-07-14"},
            ),
            patch("builtins.open", side_effect=OSError("disk full")),
        ):
            result = sector_rotation.get_sector_rotation(MagicMock(), force=True)

        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "sector_cache_write_failed")

    def test_factor_reader_rejects_tampered_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "factors"
            cache = cache_dir / "2026-07-14.json"
            self._write_tampered(
                cache,
                {
                    "_cache_schema_version": factor_scan.CACHE_SCHEMA_VERSION,
                    "_cache_key": "key",
                    "trade_date": "2026-07-14",
                    "results": {"cloud_stair": {"hits": []}},
                },
            )
            with (
                patch.object(factor_scan, "CACHE_DIR", cache_dir),
                patch.object(
                    factor_scan,
                    "cache_identity",
                    return_value={"cache_key": "key"},
                ),
            ):
                result = factor_scan._load_cache("2026-07-14", MagicMock())

        self.assertEqual(result, {})

    def test_factor_scan_reports_cache_persistence_failure(self):
        with (
            patch.object(factor_scan, "_latest_data_date", return_value="2026-07-14"),
            patch.object(factor_scan, "_load_cache", return_value={}),
            patch.object(
                factor_scan,
                "compute_scan",
                return_value={
                    "available": True,
                    "trade_date": "2026-07-14",
                    "results": {"cloud_stair": {"hits": []}},
                },
            ),
            patch.object(factor_scan, "_save_cache", return_value=False),
        ):
            result = factor_scan.get_factor_hits(
                MagicMock(), {}, ["cloud_stair"], force=True
            )

        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "factor_cache_write_failed")

    def test_thermometer_reader_rejects_tampered_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "thermometer.json"
            self._write_tampered(
                cache,
                {
                    "available": True,
                    "cache_schema_version": market_thermometer.CACHE_SCHEMA_VERSION,
                    "trade_date": "2026-07-14",
                    "cache_key": "key",
                    "heat": {"breadth_score": 50},
                },
            )
            with (
                patch.object(market_thermometer, "CACHE_FILE", cache),
                patch.object(
                    market_thermometer,
                    "cache_identity",
                    return_value={"cache_key": "key"},
                ),
            ):
                result = market_thermometer.read_thermometer(MagicMock())

        self.assertFalse(result["available"])


if __name__ == "__main__":
    unittest.main()
