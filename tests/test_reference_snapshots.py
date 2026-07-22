import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.reference_snapshots import (
    capture_reference_snapshot,
    load_reference_snapshots,
)


class ReferenceSnapshotsTest(unittest.TestCase):
    @staticmethod
    def _snapshot(payload: Path, *, trade_date="2026-07-14", snapshot_id="a" * 64):
        return {
            "available": True,
            "snapshot_id": snapshot_id,
            "payload_dir": str(payload),
            "manifest": {
                "trade_date": trade_date,
                "captured_at": f"{trade_date}T16:00:00+08:00",
            },
        }

    @staticmethod
    def _write_metadata(payload: Path):
        payload.mkdir(parents=True, exist_ok=True)
        (payload / "stock_names.json").write_text(
            json.dumps({"600000": "浦发银行"}),
            encoding="utf-8",
        )
        (payload / "stock_industry.json").write_text(
            json.dumps({"600000": "银行"}),
            encoding="utf-8",
        )
        (payload / "stock_market_cap.json").write_text(
            json.dumps({"600000": {"circ_mv": 10_000_000_000}}),
            encoding="utf-8",
        )
        securities = {
            "600000": {
                "status": "active",
                "verified": True,
                "as_of": "2026-07-14",
                "source_id": "akshare:stock_tfp_em",
                "is_st": False,
            }
        }
        canonical = json.dumps(
            securities,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        (payload / "security_status.json").write_text(
            json.dumps(
                {
                    "schema_version": "security-status-v1",
                    "as_of": "2026-07-14",
                    "source_id": "akshare:stock_tfp_em",
                    "count": 1,
                    "content_hash": hashlib.sha256(canonical).hexdigest(),
                    "securities": securities,
                }
            ),
            encoding="utf-8",
        )

    def test_only_immutable_market_snapshot_can_be_pit_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = root / "market_snapshots" / ("a" * 64) / "payload"
            self._write_metadata(payload)
            snapshot = self._snapshot(payload)
            with patch(
                "utils.reference_snapshots.load_current_market_snapshot",
                return_value=snapshot,
            ):
                result = capture_reference_snapshot(root, "2026-07-14")

            self.assertTrue(result["available"])
            self.assertEqual(result["market_snapshot_id"], "a" * 64)
            self.assertFalse(
                (root / "reference_snapshots" / "2026-07-14.json").exists()
            )

    def test_backdating_current_mappings_is_forbidden(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = root / "payload"
            self._write_metadata(payload)
            with patch(
                "utils.reference_snapshots.load_current_market_snapshot",
                return_value=self._snapshot(payload),
            ):
                result = capture_reference_snapshot(root, "2023-05-10")
            self.assertFalse(result["available"])
            self.assertEqual(result["reason"], "historical_backdating_forbidden")

    def test_pinned_snapshot_is_loaded_directly_instead_of_following_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot_id = "c" * 64
            payload = root / "market_snapshots" / snapshot_id / "payload"
            self._write_metadata(payload)
            snapshot = self._snapshot(payload, snapshot_id=snapshot_id)
            with (
                patch(
                    "utils.reference_snapshots.load_market_snapshot",
                    return_value=snapshot,
                ) as load_exact,
                patch(
                    "utils.reference_snapshots.load_current_market_snapshot"
                ) as load_current,
            ):
                result = capture_reference_snapshot(
                    root,
                    "2026-07-14",
                    snapshot_id=snapshot_id,
                )

            load_exact.assert_called_once_with(root, snapshot_id, verify_files=True)
            load_current.assert_not_called()
            self.assertEqual(result["market_snapshot_id"], snapshot_id)

    def test_catalog_is_rebuilt_from_verified_market_snapshots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot_id = "b" * 64
            payload = root / "market_snapshots" / snapshot_id / "payload"
            self._write_metadata(payload)
            with patch(
                "utils.reference_snapshots.load_market_snapshot",
                return_value=self._snapshot(payload, snapshot_id=snapshot_id),
            ):
                snapshots = load_reference_snapshots(root)
            self.assertEqual(snapshots["2026-07-14"]["industries"]["600000"], "银行")
            self.assertEqual(
                snapshots["2026-07-14"]["market_caps"]["600000"], 10_000_000_000
            )
            self.assertFalse(
                snapshots["2026-07-14"]["security_states"]["600000"]["is_st"]
            )
            self.assertEqual(
                snapshots["2026-07-14"]["security_states"]["600000"]["trading_status"],
                "active",
            )
            self.assertIn("600000", snapshots["2026-07-14"]["_universe_set"])

    def test_snapshot_without_verified_security_status_is_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot_id = "d" * 64
            payload = root / "market_snapshots" / snapshot_id / "payload"
            self._write_metadata(payload)
            (payload / "security_status.json").unlink()
            with patch(
                "utils.reference_snapshots.load_market_snapshot",
                return_value=self._snapshot(payload, snapshot_id=snapshot_id),
            ):
                snapshots = load_reference_snapshots(root)

            self.assertEqual(snapshots, {})


if __name__ == "__main__":
    unittest.main()
