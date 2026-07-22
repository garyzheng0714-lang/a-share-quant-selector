import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from utils.market_ingestion import (
    _acquire_ingestion_lock,
    _release_ingestion_lock,
    _run_full_rebuild,
    run_daily_ingestion,
    run_full_rebuild,
)
from utils.market_snapshot import StagingSnapshot


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

    @patch.dict(
        "os.environ",
        {
            "QUANT_FULL_REBUILD_MAX_PASSES": "3",
            "QUANT_FULL_REBUILD_RETRY_DELAY_SECONDS": "0",
        },
    )
    def test_full_rebuild_retries_only_remaining_failures_before_promotion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = root / ".snapshot_staging" / "rebuild-existing" / "payload"
            payload.mkdir(parents=True)
            staging = StagingSnapshot(payload.parent, payload, None)
            universe = {f"60{index:04d}": f"股票{index}" for index in range(3000)}
            fetcher = MagicMock()
            fetcher.universe_refresh_status = {"fresh": True}
            fetcher.refresh_stock_universe.return_value = universe
            fetcher.bootstrap_universe.side_effect = [
                {
                    "attempted": 2,
                    "added": 1,
                    "failed": 1,
                    "remaining_count": 1,
                    "failure_reason_counts": {"all_sources_failed": 1},
                },
                {
                    "attempted": 1,
                    "added": 1,
                    "failed": 0,
                    "remaining_count": 0,
                    "failure_reason_counts": {},
                },
            ]
            with (
                patch(
                    "utils.market_ingestion.find_resumable_rebuild_snapshot",
                    return_value=staging,
                ),
                patch("utils.market_ingestion.refresh_trade_calendar"),
                patch(
                    "utils.market_ingestion.expected_completed_trade_date",
                    return_value="2026-07-14",
                ),
                patch("utils.market_ingestion.AKShareFetcher", return_value=fetcher),
                patch(
                    "utils.market_ingestion.refresh_reference_metadata",
                    return_value={"valid": True},
                ),
                patch(
                    "utils.market_ingestion.promote_staging_snapshot",
                    return_value={"promoted": True, "snapshot_id": "a" * 64},
                ) as promote,
            ):
                result = _run_full_rebuild(root)

            self.assertTrue(result["success"])
            self.assertTrue(result["resumed_staging"])
            self.assertEqual(result["bootstrap"]["pass_count"], 2)
            self.assertEqual(fetcher.bootstrap_universe.call_count, 2)
            promote.assert_called_once()


if __name__ == "__main__":
    unittest.main()
