"""bootstrap / universe seed 合同：过期快照先日更，空重建可种入 LKG 名单。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import bootstrap_market_snapshot as bootstrap
from utils.akshare_fetcher import AKShareFetcher
from utils.market_snapshot import (
    prepare_empty_staging_snapshot,
    seed_universe_metadata_from_current,
)


class BootstrapPreferenceTest(unittest.TestCase):
    def test_bootstrap_prefers_daily_ingestion_when_validated_snapshot_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            with (
                patch.object(
                    bootstrap,
                    "snapshot_status",
                    side_effect=[
                        {
                            "ready": False,
                            "reason": "trade_date_mismatch",
                            "snapshot_id": "snap-1",
                            "trade_date": "2026-08-04",
                            "expected_date": "2026-08-05",
                        },
                        {
                            "ready": True,
                            "reason": "fresh",
                            "snapshot_id": "snap-2",
                            "trade_date": "2026-08-05",
                            "expected_date": "2026-08-05",
                        },
                    ],
                ),
                patch(
                    "utils.market_ingestion.run_daily_ingestion",
                    return_value={
                        "success": True,
                        "reason": None,
                        "snapshot_id": "snap-2",
                        "trade_date": "2026-08-05",
                    },
                ) as daily,
                patch(
                    "utils.market_ingestion.run_full_rebuild",
                ) as rebuild,
            ):
                code = bootstrap.main(["--data-dir", str(data_dir)])

            self.assertEqual(code, 0)
            daily.assert_called_once_with(data_dir)
            rebuild.assert_not_called()

    def test_bootstrap_falls_back_to_rebuild_when_daily_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            with (
                patch.object(
                    bootstrap,
                    "snapshot_status",
                    side_effect=[
                        {
                            "ready": False,
                            "reason": "trade_date_mismatch",
                            "snapshot_id": "snap-1",
                            "trade_date": "2026-08-04",
                            "expected_date": "2026-08-05",
                        },
                        {
                            "ready": True,
                            "reason": "fresh",
                            "snapshot_id": "snap-2",
                            "trade_date": "2026-08-05",
                            "expected_date": "2026-08-05",
                        },
                    ],
                ),
                patch(
                    "utils.market_ingestion.run_daily_ingestion",
                    return_value={
                        "success": False,
                        "reason": "approved_universe_unavailable",
                    },
                ),
                patch(
                    "utils.market_ingestion.run_full_rebuild",
                    return_value={
                        "success": True,
                        "snapshot_id": "snap-2",
                        "trade_date": "2026-08-05",
                        "bootstrap": {},
                        "quality": {},
                    },
                ) as rebuild,
            ):
                code = bootstrap.main(["--data-dir", str(data_dir)])

            self.assertEqual(code, 0)
            rebuild.assert_called_once()


class UniverseSeedTest(unittest.TestCase):
    def test_seed_universe_metadata_copies_only_name_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            current_payload = data_root / "market_snapshots" / "snap-1"
            current_payload.mkdir(parents=True)
            names = {f"{600000 + i:06d}": f"股票{i}" for i in range(3000)}
            fetcher = AKShareFetcher(current_payload)
            fetcher._save_stock_names(names, source="akshare")
            (current_payload / "60" / "600000.csv").parent.mkdir(parents=True)
            (current_payload / "60" / "600000.csv").write_text(
                "date,close\n", encoding="utf-8"
            )
            (data_root / "CURRENT_SNAPSHOT").write_text("snap-1\n", encoding="utf-8")

            # load_current_market_snapshot needs a full validated snapshot; mock it.
            staging = prepare_empty_staging_snapshot(data_root)
            with patch(
                "utils.market_snapshot.load_current_market_snapshot",
                return_value={
                    "available": True,
                    "snapshot_id": "snap-1",
                    "payload_dir": current_payload,
                },
            ):
                result = seed_universe_metadata_from_current(
                    data_root,
                    staging.payload_dir,
                )

            self.assertTrue(result["seeded"])
            self.assertTrue((staging.payload_dir / "stock_names.json").is_file())
            self.assertTrue((staging.payload_dir / "universe_manifest.json").is_file())
            self.assertFalse((staging.payload_dir / "60" / "600000.csv").exists())
            seeded_names = json.loads(
                (staging.payload_dir / "stock_names.json").read_text(encoding="utf-8")
            )
            self.assertEqual(len(seeded_names), 3000)


if __name__ == "__main__":
    unittest.main()
