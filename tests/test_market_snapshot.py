import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from utils.market_snapshot import (
    ANCHOR_CODES,
    METADATA_FILES,
    StagingSnapshot,
    _approved_universe,
    load_current_market_snapshot,
    promote_staging_snapshot,
    validate_snapshot_payload,
)
from utils.csv_manager import CSVManager


TRADE_DATE = "2026-07-14"


def row(date: str = TRADE_DATE) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": [date],
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close": [10.5],
            "volume": [100],
            "amount": [1000],
            "turnover": [1.0],
        }
    )


class MarketSnapshotTest(unittest.TestCase):
    def _staging(self, data_root: Path) -> StagingSnapshot:
        root = data_root / ".snapshot_staging" / "test-run"
        payload = root / "payload"
        payload.mkdir(parents=True)
        for code in ANCHOR_CODES:
            path = payload / code[:2] / f"{code}.csv"
            path.parent.mkdir(parents=True, exist_ok=True)
            row().to_csv(path, index=False)
        names = {code: code for code in ANCHOR_CODES}
        industries = {code: "测试行业" for code in ANCHOR_CODES}
        caps = {code: {"circ_mv": 10_000_000_000} for code in ANCHOR_CODES}
        values = {
            "stock_names.json": names,
            "stock_industry.json": industries,
            "stock_market_cap.json": caps,
            "trade_calendar.json": [TRADE_DATE],
        }

        def canonical_hash(value):
            return hashlib.sha256(
                json.dumps(
                    value,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()

        values["reference_data_manifest.json"] = {
            "schema_version": "reference-data-v1",
            "as_of": TRADE_DATE,
            "valid": True,
            "industry": {"content_hash": canonical_hash(industries)},
            "market_cap": {"content_hash": canonical_hash(caps)},
        }
        securities = {
            code: {
                "status": "active",
                "verified": True,
                "as_of": TRADE_DATE,
                "source_id": "akshare:stock_tfp_em",
                "is_st": False,
            }
            for code in names
        }
        values["security_status.json"] = {
            "schema_version": "security-status-v1",
            "as_of": TRADE_DATE,
            "captured_at": "2026-07-14T16:00:00+08:00",
            "source_id": "akshare:stock_tfp_em",
            "count": len(securities),
            "suspended_count": 0,
            "content_hash": canonical_hash(securities),
            "securities": securities,
        }
        for name in METADATA_FILES:
            (payload / name).write_text(
                json.dumps(values.get(name, {})), encoding="utf-8"
            )
        return StagingSnapshot(root, payload, None)

    @staticmethod
    def _universe():
        names = {code: code for code in ANCHOR_CODES}
        return names, {
            "valid": True,
            "content_hash": "universe-hash",
            "approved_count": len(names),
        }

    @staticmethod
    def _provenance():
        return {
            code: {
                "source_id": "tencent" if index % 2 else "akshare",
                "fetched_at": "2026-07-14T16:00:00+08:00",
                "adjustment": "qfq",
                "source_trade_date": TRADE_DATE,
                "persisted_start": TRADE_DATE,
                "persisted_end": TRADE_DATE,
                "rows": 1,
                "history_coverage_start": TRADE_DATE,
                "synthetic": False,
            }
            for index, code in enumerate(ANCHOR_CODES)
        }

    def _validate(self, staging, *, calendar=None, provenance=None, universe=None):
        with (
            patch(
                "utils.market_snapshot._approved_universe",
                return_value=universe or self._universe(),
            ),
            patch(
                "utils.market_snapshot._trade_calendar",
                return_value=calendar or {TRADE_DATE},
            ),
            patch(
                "utils.market_snapshot._provenance",
                return_value=provenance or self._provenance(),
            ),
        ):
            return validate_snapshot_payload(
                staging.payload_dir,
                TRADE_DATE,
                minimum_coverage=1.0,
                required_source_count=2,
            )

    def test_validated_snapshot_is_atomically_promoted_and_hash_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            staging = self._staging(data_root)
            with (
                patch(
                    "utils.market_snapshot._approved_universe",
                    return_value=self._universe(),
                ),
                patch(
                    "utils.market_snapshot._trade_calendar", return_value={TRADE_DATE}
                ),
                patch(
                    "utils.market_snapshot._provenance", return_value=self._provenance()
                ),
            ):
                result = promote_staging_snapshot(
                    staging,
                    TRADE_DATE,
                    data_dir=data_root,
                    minimum_coverage=1.0,
                    required_source_count=2,
                )

            self.assertTrue(result["promoted"])
            loaded = load_current_market_snapshot(data_root, verify_files=True)
            self.assertTrue(loaded["available"])
            self.assertEqual(loaded["snapshot_id"], result["snapshot_id"])
            manager = CSVManager(data_root)
            self.assertEqual(manager.snapshot_id, result["snapshot_id"])
            with self.assertRaises(PermissionError):
                manager.write_stock(ANCHOR_CODES[0], row())

            first = next(iter(result["manifest"]["files"].values()))
            (Path(result["payload_dir"]) / first["path"]).write_text(
                "tampered", encoding="utf-8"
            )
            tampered = load_current_market_snapshot(data_root, verify_files=True)
            self.assertFalse(tampered["available"])
            self.assertEqual(tampered["reason"], "snapshot_file_hash_mismatch")

    def test_invalid_snapshot_never_changes_current_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            pointer = data_root / "CURRENT_SNAPSHOT"
            pointer.write_text("f" * 64 + "\n", encoding="utf-8")
            staging = self._staging(data_root)
            bad_provenance = self._provenance()
            bad_provenance[ANCHOR_CODES[0]]["synthetic"] = True
            with (
                patch(
                    "utils.market_snapshot._approved_universe",
                    return_value=self._universe(),
                ),
                patch(
                    "utils.market_snapshot._trade_calendar", return_value={TRADE_DATE}
                ),
                patch("utils.market_snapshot._provenance", return_value=bad_provenance),
            ):
                result = promote_staging_snapshot(
                    staging,
                    TRADE_DATE,
                    data_dir=data_root,
                    minimum_coverage=1.0,
                    required_source_count=2,
                )
            self.assertFalse(result["promoted"])
            self.assertEqual(pointer.read_text(encoding="utf-8").strip(), "f" * 64)
            self.assertGreater(result["quality"]["synthetic_rows"], 0)

    def test_untracked_operational_file_cannot_enter_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            staging = self._staging(data_root)
            (staging.payload_dir / "universe_bootstrap.json").write_text(
                "{}", encoding="utf-8"
            )
            with (
                patch(
                    "utils.market_snapshot._approved_universe",
                    return_value=self._universe(),
                ),
                patch(
                    "utils.market_snapshot._trade_calendar",
                    return_value={TRADE_DATE},
                ),
                patch(
                    "utils.market_snapshot._provenance",
                    return_value=self._provenance(),
                ),
            ):
                result = promote_staging_snapshot(
                    staging,
                    TRADE_DATE,
                    data_dir=data_root,
                    minimum_coverage=1.0,
                    required_source_count=2,
                )

            self.assertFalse(result["promoted"])
            self.assertEqual(
                result["quality"]["unexpected_files"],
                ["universe_bootstrap.json"],
            )

    def test_verified_loader_rejects_file_added_after_promotion(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            staging = self._staging(data_root)
            with (
                patch(
                    "utils.market_snapshot._approved_universe",
                    return_value=self._universe(),
                ),
                patch(
                    "utils.market_snapshot._trade_calendar",
                    return_value={TRADE_DATE},
                ),
                patch(
                    "utils.market_snapshot._provenance",
                    return_value=self._provenance(),
                ),
            ):
                result = promote_staging_snapshot(
                    staging,
                    TRADE_DATE,
                    data_dir=data_root,
                    minimum_coverage=1.0,
                    required_source_count=2,
                )
            Path(result["payload_dir"], "extra.txt").write_text(
                "unexpected", encoding="utf-8"
            )

            loaded = load_current_market_snapshot(data_root, verify_files=True)

            self.assertFalse(loaded["available"])
            self.assertEqual(loaded["reason"], "snapshot_unexpected_files")
            self.assertEqual(loaded["unexpected"], ["extra.txt"])

    def test_interruption_before_pointer_swap_keeps_previous_snapshot_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            pointer = data_root / "CURRENT_SNAPSHOT"
            previous = "f" * 64
            pointer.write_text(previous + "\n", encoding="utf-8")
            staging = self._staging(data_root)
            with (
                patch(
                    "utils.market_snapshot._approved_universe",
                    return_value=self._universe(),
                ),
                patch(
                    "utils.market_snapshot._trade_calendar",
                    return_value={TRADE_DATE},
                ),
                patch(
                    "utils.market_snapshot._provenance",
                    return_value=self._provenance(),
                ),
                patch.object(Path, "replace", side_effect=OSError("disk full")),
            ):
                with self.assertRaisesRegex(OSError, "disk full"):
                    promote_staging_snapshot(
                        staging,
                        TRADE_DATE,
                        data_dir=data_root,
                        minimum_coverage=1.0,
                        required_source_count=2,
                    )

            self.assertEqual(pointer.read_text(encoding="utf-8").strip(), previous)

    def test_future_trade_date_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = Path(tmp)
            for code in ANCHOR_CODES:
                path = payload / code[:2] / f"{code}.csv"
                path.parent.mkdir(parents=True, exist_ok=True)
                row("2026-07-15").to_csv(path, index=False)
            with (
                patch(
                    "utils.market_snapshot._approved_universe",
                    return_value=self._universe(),
                ),
                patch(
                    "utils.market_snapshot._trade_calendar",
                    return_value={TRADE_DATE, "2026-07-15"},
                ),
                patch(
                    "utils.market_snapshot._provenance", return_value=self._provenance()
                ),
            ):
                quality = validate_snapshot_payload(
                    payload,
                    TRADE_DATE,
                    minimum_coverage=1.0,
                    required_source_count=2,
                )
            self.assertFalse(quality["valid"])
            self.assertEqual(quality["future_rows"], len(ANCHOR_CODES))

    def test_invalid_ohlcv_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            staging = self._staging(Path(tmp))
            code = ANCHOR_CODES[0]
            invalid = row()
            invalid.loc[0, "high"] = 9.0
            invalid.loc[0, "volume"] = -1
            invalid.to_csv(staging.payload_dir / code[:2] / f"{code}.csv", index=False)

            quality = self._validate(staging)

        self.assertFalse(quality["valid"])
        self.assertIn("invalid_ohlcv:1", quality["schema_errors"][code])

    def test_duplicate_and_non_trading_dates_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            staging = self._staging(Path(tmp))
            duplicate_code, holiday_code = ANCHOR_CODES[:2]
            pd.concat([row(), row()]).to_csv(
                staging.payload_dir / duplicate_code[:2] / f"{duplicate_code}.csv",
                index=False,
            )
            pd.concat([row("2026-07-13"), row()]).to_csv(
                staging.payload_dir / holiday_code[:2] / f"{holiday_code}.csv",
                index=False,
            )

            quality = self._validate(staging)

        self.assertFalse(quality["valid"])
        self.assertIn("duplicate_dates:1", quality["schema_errors"][duplicate_code])
        self.assertIn("non_trading_dates:1", quality["schema_errors"][holiday_code])

    def test_corrupt_csv_and_missing_metadata_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            staging = self._staging(Path(tmp))
            code = ANCHOR_CODES[0]
            (staging.payload_dir / code[:2] / f"{code}.csv").write_bytes(
                b"\xff\xfe\x00"
            )
            (staging.payload_dir / "stock_market_cap.json").unlink()

            quality = self._validate(staging)

        self.assertFalse(quality["valid"])
        self.assertIn("unreadable_csv", quality["schema_errors"][code])
        self.assertIn("stock_market_cap.json", quality["missing_metadata"])

    def test_single_source_snapshot_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            staging = self._staging(Path(tmp))
            provenance = self._provenance()
            for item in provenance.values():
                item["source_id"] = "akshare"

            quality = self._validate(staging, provenance=provenance)

        self.assertFalse(quality["valid"])
        self.assertFalse(quality["source_quorum_passed"])

    def test_small_universe_manifest_is_never_approved(self):
        with tempfile.TemporaryDirectory() as tmp:
            staging = self._staging(Path(tmp))
            names = {code: code for code in ANCHOR_CODES}
            content_hash = hashlib.sha256(
                json.dumps(
                    names,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            (staging.payload_dir / "universe_manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": "universe-v1",
                        "count": len(names),
                        "content_hash": content_hash,
                        "source": "akshare",
                    }
                ),
                encoding="utf-8",
            )

            universe, manifest = _approved_universe(staging.payload_dir)

        self.assertEqual(len(universe), len(ANCHOR_CODES))
        self.assertFalse(manifest["valid"])

    def test_previous_trade_date_is_stale_not_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            staging = self._staging(Path(tmp))
            code = ANCHOR_CODES[0]
            stale = row("2026-07-13")
            stale.to_csv(staging.payload_dir / code[:2] / f"{code}.csv", index=False)
            provenance = self._provenance()
            provenance[code]["source_trade_date"] = "2026-07-13"
            provenance[code]["history_coverage_start"] = "2026-07-13"

            quality = self._validate(
                staging,
                calendar={"2026-07-13", TRADE_DATE},
                provenance=provenance,
            )

        self.assertFalse(quality["valid"])
        self.assertEqual(quality["stale_codes"][code], "2026-07-13")
        self.assertIn("latest_trade_date_mismatch", quality["schema_errors"][code])

    def test_verified_suspension_allows_previous_trade_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            staging = self._staging(Path(tmp))
            code = ANCHOR_CODES[0]
            row("2026-07-13").to_csv(
                staging.payload_dir / code[:2] / f"{code}.csv", index=False
            )
            status_path = staging.payload_dir / "security_status.json"
            status = json.loads(status_path.read_text(encoding="utf-8"))
            status["securities"][code]["status"] = "suspended"
            status["securities"][code]["reason"] = "临时停牌"
            status["suspended_count"] = 1
            status["content_hash"] = hashlib.sha256(
                json.dumps(
                    status["securities"],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            status_path.write_text(json.dumps(status), encoding="utf-8")
            provenance = self._provenance()
            provenance[code].update(
                {
                    "source_trade_date": "2026-07-13",
                    "persisted_start": "2026-07-13",
                    "persisted_end": "2026-07-13",
                    "history_coverage_start": "2026-07-13",
                }
            )

            quality = self._validate(
                staging,
                calendar={"2026-07-13", TRADE_DATE},
                provenance=provenance,
            )

        self.assertTrue(quality["valid"])
        self.assertEqual(quality["classified_non_trading"][code], "suspended")

    def test_missing_active_stock_is_never_hidden_by_coverage_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            staging = self._staging(Path(tmp))
            code = ANCHOR_CODES[-1]
            (staging.payload_dir / code[:2] / f"{code}.csv").unlink()
            quality = self._validate(staging)

        self.assertFalse(quality["valid"])
        self.assertEqual(quality["schema_errors"][code], ["market_file_missing"])

    def test_provenance_cannot_claim_history_earlier_than_persisted_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            staging = self._staging(Path(tmp))
            provenance = self._provenance()
            code = ANCHOR_CODES[0]
            provenance[code]["history_coverage_start"] = "2020-01-01"

            quality = self._validate(staging, provenance=provenance)

        self.assertFalse(quality["valid"])
        self.assertIn(
            "historical_provenance_incomplete", quality["schema_errors"][code]
        )


if __name__ == "__main__":
    unittest.main()
