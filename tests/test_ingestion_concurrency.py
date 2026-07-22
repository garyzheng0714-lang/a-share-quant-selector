import tempfile
import unittest
from pathlib import Path

from utils.market_ingestion import (
    _acquire_ingestion_lock,
    _release_ingestion_lock,
    run_daily_ingestion,
    run_full_rebuild,
)


class IngestionConcurrencyTest(unittest.TestCase):
    def test_daily_update_never_launders_unverified_legacy_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "60" / "600000.csv"
            legacy.parent.mkdir(parents=True)
            legacy.write_text("date,open,high,low,close,volume\n", encoding="utf-8")
            before = legacy.read_bytes()

            result = run_daily_ingestion(root)

            self.assertFalse(result["success"])
            self.assertEqual(result["reason"], "trusted_base_snapshot_required")
            self.assertEqual(legacy.read_bytes(), before)
            self.assertFalse((root / ".snapshot_staging").exists())

    def test_bootstrap_and_daily_update_share_one_cross_process_writer_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lock = _acquire_ingestion_lock(root)
            self.assertIsNotNone(lock)
            try:
                daily = run_daily_ingestion(root)
                rebuild = run_full_rebuild(root)
            finally:
                _release_ingestion_lock(lock)

        self.assertEqual(daily["reason"], "ingestion_already_running")
        self.assertEqual(rebuild["reason"], "ingestion_already_running")
        self.assertFalse(daily["success"])
        self.assertFalse(rebuild["success"])


if __name__ == "__main__":
    unittest.main()
