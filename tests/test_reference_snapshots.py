import json
import tempfile
import unittest
from pathlib import Path

from utils.decision_versions import data_version
from utils.reference_snapshots import capture_reference_snapshot, load_reference_snapshots


class ReferenceSnapshotsTest(unittest.TestCase):
    def test_captures_point_in_time_universe_industry_and_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "stock_names.json").write_text(
                json.dumps({"600000": "浦发银行"}), encoding="utf-8"
            )
            (root / "stock_industry.json").write_text(
                json.dumps({"600000": "银行"}), encoding="utf-8"
            )
            (root / "stock_market_cap.json").write_text(
                json.dumps({"600000": {"circ_mv": 10000000000}}), encoding="utf-8"
            )

            result = capture_reference_snapshot(root, "2026-07-14")
            snapshots = load_reference_snapshots(root)

            self.assertTrue(result["available"])
            self.assertEqual(snapshots["2026-07-14"]["industries"]["600000"], "银行")
            self.assertEqual(snapshots["2026-07-14"]["market_caps"]["600000"], 10000000000)
            self.assertIn("600000", snapshots["2026-07-14"]["_universe_set"])

            first_version = data_version(root)
            repeated = capture_reference_snapshot(root, "2026-07-14")
            second_version = data_version(root)
            self.assertTrue(repeated["existing"])
            self.assertEqual(first_version, second_version)

            (root / "stock_market_cap.json").write_text(
                json.dumps({"600000": {"circ_mv": 20000000000}}), encoding="utf-8"
            )
            repeated_after_source_change = capture_reference_snapshot(root, "2026-07-14")

            self.assertTrue(repeated_after_source_change["existing"])
            self.assertEqual(
                load_reference_snapshots(root)["2026-07-14"]["market_caps"]["600000"],
                10000000000,
            )


if __name__ == "__main__":
    unittest.main()
