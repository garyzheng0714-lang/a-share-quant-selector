import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from utils.csv_manager import CSVManager, MarketDataReadError
from utils.market_snapshot import SCHEMA_VERSION, _snapshot_id


class CsvManagerTest(unittest.TestCase):
    @staticmethod
    def _publish(data_root: Path, close: float) -> str:
        body = {
            "schema_version": SCHEMA_VERSION,
            "status": "validated",
            "trade_date": "2026-07-14",
            "files": {},
            "metadata_files": {},
            "close_marker": close,
        }
        snapshot_id = _snapshot_id(body)
        root = data_root / "market_snapshots" / snapshot_id
        path = root / "payload" / "60" / "600000.csv"
        path.parent.mkdir(parents=True)
        pd.DataFrame({"date": ["2026-07-14"], "close": [close]}).to_csv(
            path, index=False
        )
        (root / "manifest.json").write_text(
            json.dumps({"snapshot_id": snapshot_id, **body}), encoding="utf-8"
        )
        (data_root / "CURRENT_SNAPSHOT").write_text(
            snapshot_id + "\n", encoding="utf-8"
        )
        return snapshot_id

    def test_training_csv_is_not_treated_as_stock(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "600000.csv").write_text("date,close\n2026-07-14,10\n")
            Path(tmp, "hierarchical_training.csv").write_text(
                "date,target\n2026-07-14,1\n"
            )
            self.assertEqual(CSVManager(tmp).list_all_stocks(), ["600000"])

    def test_reader_stays_on_one_snapshot_when_pointer_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            first = self._publish(data_root, 10.0)
            manager = CSVManager(data_root, writable=False)

            second = self._publish(data_root, 20.0)

            self.assertNotEqual(first, second)
            self.assertEqual(manager.snapshot_id, first)
            self.assertEqual(float(manager.read_stock("600000").iloc[0]["close"]), 10.0)
            self.assertEqual(
                float(
                    CSVManager(data_root, writable=False)
                    .read_stock("600000")
                    .iloc[0]["close"]
                ),
                20.0,
            )

    def test_read_only_manager_does_not_create_or_fall_back_to_legacy_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp) / "absent"
            legacy = data_root / "60" / "600000.csv"
            legacy.parent.mkdir(parents=True)
            legacy.write_text("date,close\n2026-07-14,10\n", encoding="utf-8")

            manager = CSVManager(data_root, writable=False)

            self.assertIsNone(manager.snapshot_id)
            self.assertTrue(manager.read_stock("600000").empty)
            untouched = Path(tmp) / "never-created"
            CSVManager(untouched, writable=False)
            self.assertFalse(untouched.exists())

    def test_existing_corrupt_market_file_is_not_treated_as_no_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "60" / "600000.csv"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"\xff\xfe\x00")

            manager = CSVManager(tmp, resolve_snapshot=False)

            with self.assertRaises(MarketDataReadError):
                manager.read_stock("600000")


if __name__ == "__main__":
    unittest.main()
