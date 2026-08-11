import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

from tools.hierarchical_walk_forward import (
    DATASET_SCHEMA_VERSION,
    MARKET_FEATURES,
    PIT_FEATURE_COLUMNS,
    QUALITY_TARGET_VERSION,
    SECTOR_FEATURES,
    STOCK_FEATURES,
    _coefficient_stability,
    _commit_feature_shard,
    _feature_shard_seal_path,
    _layer_frames,
    _purged_month_split,
    _read_feature_shard,
    _snapshot_manager,
    _two_way_cluster_bootstrap_delta,
    build_dataset,
    latest_complete_snapshot_cohort,
    materialize_pit_feature_ledger,
    pit_feature_ledger_version,
    training_readiness,
    walk_forward,
)
from utils.probability_model import BinaryLogit


class HierarchicalWalkForwardTest(unittest.TestCase):
    @staticmethod
    def _contract_row(
        *,
        schema_version=DATASET_SCHEMA_VERSION,
        reference_snapshot_id="a" * 64,
        feature_snapshot_id="a" * 64,
    ):
        row = {
            "dataset_schema_version": schema_version,
            "date": "2026-01-05",
            "label_end_date": "2026-01-12",
            "code": "600000",
            "industry": "银行",
            "reference_snapshot_date": "2026-01-05",
            "reference_snapshot_id": reference_snapshot_id,
            "feature_snapshot_id": feature_snapshot_id,
            "label_snapshot_id": "c" * 64,
            "label_snapshot_date": "2026-01-12",
            "quality_target_version": QUALITY_TARGET_VERSION,
            "universe_coverage": 1.0,
            "weekly_passed": 1,
            "execution_status": "filled_round_trip",
            "execution_policy_version": "a-share-eod-open-open-v5",
            "net_return_5": 1.0,
            "excess_5": 0.5,
            "y_quality": 1,
            "y_risk": 0,
            "entry_label_mature": 1,
            "exit_label_mature": 1,
            "return_label_mature": 1,
            "entry_feasible": 1,
            "exit_feasible": 1,
            "y_entry_risk": 0,
            "y_exit_risk": 0,
        }
        row.update(
            {name: 0.1 for name in MARKET_FEATURES + SECTOR_FEATURES + STOCK_FEATURES}
        )
        return row

    def test_market_and_sector_use_independent_units(self):
        rows = []
        for date in ("2026-01-05", "2026-01-06"):
            for code, industry, result in (
                ("600000", "银行", 2.0),
                ("600001", "煤炭", -1.0),
            ):
                row = {
                    "date": date,
                    "label_end_date": "2026-01-13",
                    "code": code,
                    "industry": industry,
                    "net_return_5": result,
                    "excess_5": result - 0.2,
                    "y_quality": int(result > 0),
                    "y_risk": int(result < -5),
                    "entry_label_mature": 1,
                    "exit_label_mature": 1,
                    "return_label_mature": 1,
                    "entry_feasible": 1,
                    "exit_feasible": 1,
                    "y_entry_risk": 0,
                    "y_exit_risk": 0,
                }
                row.update(
                    {
                        name: 0.1
                        for name in MARKET_FEATURES + SECTOR_FEATURES + STOCK_FEATURES
                    }
                )
                rows.append(row)
        units = _layer_frames(pd.DataFrame(rows))

        self.assertEqual(len(units["market"]), 2)
        self.assertEqual(len(units["sector"]), 4)
        self.assertEqual(len(units["quality"]), 4)
        self.assertEqual(len(units["entry_risk"]), 4)
        self.assertEqual(len(units["exit_risk"]), 4)
        self.assertTrue(
            (units["market"]["training_unit"] == "b1_signal_trade_date").all()
        )

    def test_coefficient_stability_uses_expanding_time_windows(self):
        frame = pd.DataFrame(
            {
                "date": pd.date_range("2025-01-01", periods=120, freq="D").astype(str),
                "x": pd.Series(range(120), dtype=float) - 60,
            }
        )
        frame["y"] = (frame["x"] > 0).astype(int)
        model = BinaryLogit(["x"]).fit(frame, "y")

        diagnostics = _coefficient_stability(frame, model, "y")

        self.assertEqual(diagnostics["method"], "expanding_time_windows_v1")
        self.assertEqual(diagnostics["fit_count"], 3)
        self.assertTrue(diagnostics["stable"])
        self.assertIsNotNone(diagnostics["sign_agreement"])

    def test_unbuyable_and_unsellable_samples_are_retained_in_separate_layers(self):
        base = {
            "date": "2026-01-05",
            "label_end_date": "2026-01-13",
            "industry": "银行",
            "weekly_passed": 1,
        }
        rows = [
            {
                **base,
                "code": "600000",
                "execution_status": "entry_unbuyable",
                "entry_label_mature": 1,
                "exit_label_mature": 0,
                "return_label_mature": 0,
                "entry_feasible": 0,
                "exit_feasible": float("nan"),
                "y_entry_risk": 1,
                "y_exit_risk": float("nan"),
                "net_return_5": float("nan"),
                "excess_5": float("nan"),
                "y_quality": float("nan"),
                "y_risk": 1,
            },
            {
                **base,
                "code": "600001",
                "execution_status": "exit_unsellable",
                "entry_label_mature": 1,
                "exit_label_mature": 1,
                "return_label_mature": 0,
                "entry_feasible": 1,
                "exit_feasible": 0,
                "y_entry_risk": 0,
                "y_exit_risk": 1,
                "net_return_5": float("nan"),
                "excess_5": float("nan"),
                "y_quality": float("nan"),
                "y_risk": 1,
            },
        ]
        for row in rows:
            row.update(
                {
                    name: 0.1
                    for name in MARKET_FEATURES + SECTOR_FEATURES + STOCK_FEATURES
                }
            )

        units = _layer_frames(pd.DataFrame(rows))

        self.assertEqual(units["entry_risk"]["code"].tolist(), ["600000", "600001"])
        self.assertEqual(units["exit_risk"]["code"].tolist(), ["600001"])
        self.assertTrue(units["quality"].empty)

    def test_five_day_labels_are_purged_across_month_boundaries(self):
        data = pd.DataFrame(
            [
                {
                    "date": "2026-01-10",
                    "label_end_date": "2026-01-15",
                    "month": "2026-01",
                },
                {
                    "date": "2026-01-28",
                    "label_end_date": "2026-02-02",
                    "month": "2026-01",
                },
                {
                    "date": "2026-01-20",
                    "label_end_date": "2026-01-27",
                    "label_available_date": "2026-02-05",
                    "month": "2026-01",
                },
                {
                    "date": "2026-02-10",
                    "label_end_date": "2026-02-15",
                    "month": "2026-02",
                },
                {
                    "date": "2026-02-25",
                    "label_end_date": "2026-03-03",
                    "month": "2026-02",
                },
                {
                    "date": "2026-03-02",
                    "label_end_date": "2026-03-09",
                    "month": "2026-03",
                },
            ]
        )

        train, validation, test, _, _ = _purged_month_split(
            data,
            ["2026-01"],
            {"2026-02"},
            "2026-03",
        )

        self.assertEqual(train["date"].tolist(), ["2026-01-10"])
        self.assertEqual(validation["date"].tolist(), ["2026-02-10"])
        self.assertEqual(test["date"].tolist(), ["2026-03-02"])

    def test_old_dataset_schema_is_rejected_before_training(self):
        row = self._contract_row(schema_version=DATASET_SCHEMA_VERSION - 1)

        with self.assertRaisesRegex(ValueError, "版本不匹配"):
            walk_forward(pd.DataFrame([row]), min_train_months=0, val_months=0)

    def test_feature_and_reference_snapshot_mismatch_is_rejected(self):
        row = self._contract_row(feature_snapshot_id="b" * 64)

        with self.assertRaisesRegex(ValueError, "特征快照与参考快照不一致"):
            walk_forward(pd.DataFrame([row]), min_train_months=0, val_months=0)

    def test_sparse_21_month_history_is_typed_as_not_training_ready(self):
        rows = []
        for month_start in pd.date_range("2024-01-01", periods=21, freq="MS"):
            row = self._contract_row()
            row["date"] = (month_start + pd.Timedelta(days=4)).strftime("%Y-%m-%d")
            row["reference_snapshot_date"] = row["date"]
            row["label_end_date"] = (month_start + pd.Timedelta(days=11)).strftime(
                "%Y-%m-%d"
            )
            row["label_snapshot_date"] = row["label_end_date"]
            rows.append(row)

        readiness = training_readiness(pd.DataFrame(rows))

        self.assertFalse(readiness["ready"])
        self.assertEqual(readiness["reason"], "walk_forward_sample_insufficient")
        self.assertEqual(readiness["months"], 21)
        self.assertEqual(readiness["eligible_folds"], 0)

    def test_feature_shard_seal_rejects_tamper_and_recovers_partial_pair(self):
        self.assertEqual(len(PIT_FEATURE_COLUMNS), len(set(PIT_FEATURE_COLUMNS)))
        date = "2026-01-05"
        snapshot_id = "a" * 64
        row = {column: 0.1 for column in PIT_FEATURE_COLUMNS}
        row.update(
            {
                "dataset_schema_version": DATASET_SCHEMA_VERSION,
                "date": date,
                "code": "600000",
                "name": "浦发银行",
                "industry": "银行",
                "reference_snapshot_date": date,
                "reference_snapshot_id": snapshot_id,
                "feature_snapshot_id": snapshot_id,
                "feature_ledger_version": pit_feature_ledger_version(),
                "b1_signals": "B1",
            }
        )
        frame = pd.DataFrame([row], columns=PIT_FEATURE_COLUMNS)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tampered = root / "tampered" / snapshot_id / "features.csv"
            stored, status = _commit_feature_shard(
                frame, tampered, date, snapshot_id, lambda: None
            )
            self.assertEqual(status, "materialized")
            self.assertEqual(len(stored), 1)
            valid_seal = _feature_shard_seal_path(tampered).read_text(encoding="utf-8")

            changed = pd.read_csv(tampered, dtype={"code": str})
            changed.loc[0, "market_ret_1"] = 999
            changed.to_csv(tampered, index=False)
            with self.assertRaisesRegex(ValueError, "seal 冲突"):
                _read_feature_shard(tampered, date, snapshot_id)
            with self.assertRaisesRegex(ValueError, "seal 冲突"):
                _commit_feature_shard(frame, tampered, date, snapshot_id, lambda: None)

            truncated = root / "truncated" / snapshot_id / "features.csv"
            _commit_feature_shard(frame, truncated, date, snapshot_id, lambda: None)
            pd.DataFrame(columns=PIT_FEATURE_COLUMNS).to_csv(truncated, index=False)
            with self.assertRaisesRegex(ValueError, "seal 冲突"):
                _read_feature_shard(truncated, date, snapshot_id)

            csv_only = root / "csv-only" / snapshot_id / "features.csv"
            csv_only.parent.mkdir(parents=True)
            frame.to_csv(csv_only, index=False)
            recovered, recovered_status = _commit_feature_shard(
                frame, csv_only, date, snapshot_id, lambda: None
            )
            self.assertEqual(recovered_status, "materialized")
            self.assertEqual(len(recovered), 1)
            self.assertTrue(_feature_shard_seal_path(csv_only).exists())

            mismatched_csv_only = (
                root / "mismatched-csv-only" / snapshot_id / "features.csv"
            )
            mismatched_csv_only.parent.mkdir(parents=True)
            changed.to_csv(mismatched_csv_only, index=False)
            with self.assertRaisesRegex(ValueError, "单边内容冲突"):
                _commit_feature_shard(
                    frame, mismatched_csv_only, date, snapshot_id, lambda: None
                )

            seal_only = root / "seal-only" / snapshot_id / "features.csv"
            seal_only.parent.mkdir(parents=True)
            _feature_shard_seal_path(seal_only).write_text(valid_seal, encoding="utf-8")
            recovered, recovered_status = _commit_feature_shard(
                frame, seal_only, date, snapshot_id, lambda: None
            )
            self.assertEqual(recovered_status, "materialized")
            self.assertEqual(len(recovered), 1)
            self.assertTrue(seal_only.exists())

            mismatched_seal_only = (
                root / "mismatched-seal-only" / snapshot_id / "features.csv"
            )
            mismatched_seal_only.parent.mkdir(parents=True)
            _feature_shard_seal_path(mismatched_seal_only).write_text(
                "{}", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "单边 seal 冲突"):
                _commit_feature_shard(
                    frame, mismatched_seal_only, date, snapshot_id, lambda: None
                )

    def test_builder_refuses_current_revised_history_as_pit_features(self):
        manager = MagicMock()
        manager.base_data_dir = Path("/tmp/market-data")
        manager.data_dir = (
            Path("/tmp/market-data/market_snapshots") / ("a" * 64) / "payload"
        )
        manager.snapshot_id = "a" * 64
        snapshots = {
            f"{2024 + index // 12}-{index % 12 + 1:02d}-05": {
                "market_snapshot_id": "b" * 64
            }
            for index in range(21)
        }
        with (
            patch(
                "tools.hierarchical_walk_forward.load_reference_snapshots",
                return_value=snapshots,
            ) as load_snapshots,
            patch(
                "tools.hierarchical_walk_forward.load_exchange_sessions",
                return_value=sorted(snapshots),
            ),
            patch("tools.hierarchical_walk_forward.build_panels") as build_panels,
        ):
            frame = build_dataset(manager, {}, {})

        load_snapshots.assert_called_once_with(manager.base_data_dir)
        build_panels.assert_not_called()
        manager.list_all_stocks.assert_not_called()
        self.assertTrue(frame.empty)
        self.assertEqual(frame.attrs["reason"], "pit_feature_history_unavailable")
        self.assertEqual(frame.attrs["mismatched_snapshot_count"], 21)

    def test_latest_cohort_starts_at_first_full_month_after_latest_gap(self):
        sessions = [
            "2026-01-30",
            "2026-02-02",
            "2026-02-03",
            "2026-02-04",
            "2026-03-02",
            "2026-03-03",
        ]
        snapshots = {
            date: {"market_snapshot_id": str(index) * 64}
            for index, date in enumerate(
                (
                    "2026-01-30",
                    "2026-02-03",
                    "2026-02-04",
                    "2026-03-02",
                    "2026-03-03",
                ),
                start=1,
            )
        }

        cohort, evidence = latest_complete_snapshot_cohort(snapshots, sessions)

        self.assertEqual(list(cohort), ["2026-03-02", "2026-03-03"])
        self.assertTrue(evidence["complete"])
        self.assertEqual(evidence["last_gap_session"], "2026-02-02")
        self.assertEqual(evidence["raw_suffix_first_session"], "2026-02-03")
        self.assertEqual(evidence["trimmed_partial_month_sessions"], 2)
        self.assertEqual(evidence["excluded_catalog_snapshot_count"], 3)

    def test_latest_cohort_waits_when_suffix_only_contains_partial_month(self):
        sessions = ["2026-08-07", "2026-08-10", "2026-08-11"]
        snapshots = {
            "2026-08-07": {"market_snapshot_id": "a" * 64},
            "2026-08-11": {"market_snapshot_id": "b" * 64},
        }

        cohort, evidence = latest_complete_snapshot_cohort(snapshots, sessions)

        self.assertEqual(cohort, {})
        self.assertFalse(evidence["complete"])
        self.assertEqual(evidence["reason"], "complete_natural_month_not_started")
        self.assertEqual(evidence["last_gap_session"], "2026-08-10")

    def test_feature_ledger_and_label_builder_share_latest_cohort(self):
        sessions = [
            "2026-01-30",
            "2026-02-02",
            "2026-02-03",
            "2026-02-04",
            "2026-03-02",
            "2026-03-03",
        ]
        snapshots = {
            date: {"market_snapshot_id": f"{index:x}" * 64}
            for index, date in enumerate(
                (
                    "2026-01-30",
                    "2026-02-03",
                    "2026-02-04",
                    "2026-03-02",
                    "2026-03-03",
                ),
                start=1,
            )
        }
        manager = MagicMock()
        manager.base_data_dir = Path("/tmp/market-data")
        manager.data_dir = Path("/tmp/market-data/current/payload")
        manager.snapshot_id = "f" * 64
        shard_path = MagicMock()
        shard_path.exists.return_value = True
        hydrated = pd.DataFrame([{"date": "2026-03-02", "code": "600000"}])

        with (
            patch(
                "tools.hierarchical_walk_forward.load_exchange_sessions",
                return_value=sessions,
            ),
            patch(
                "tools.hierarchical_walk_forward._materialize_feature_shard",
                return_value=(pd.DataFrame(), "existing"),
            ) as materialize_shard,
            patch(
                "tools.hierarchical_walk_forward._feature_shard_path",
                return_value=shard_path,
            ),
            patch(
                "tools.hierarchical_walk_forward._read_feature_shard",
                return_value=pd.DataFrame([{"date": "2026-03-02"}]),
            ),
            patch(
                "tools.hierarchical_walk_forward._hydrate_outcomes",
                return_value=hydrated,
            ) as hydrate,
            patch("tools.hierarchical_walk_forward.MIN_REFERENCE_MONTHS", 1),
        ):
            ledger = materialize_pit_feature_ledger(manager, snapshots=snapshots)
            frame = build_dataset(
                manager,
                {},
                {},
                snapshots=snapshots,
                feature_ledger=ledger,
            )

        materialized_dates = [call.args[1] for call in materialize_shard.call_args_list]
        self.assertEqual(materialized_dates, ["2026-03-02", "2026-03-03"])
        label_snapshots = hydrate.call_args.args[3]
        self.assertEqual(list(label_snapshots), ["2026-03-02", "2026-03-03"])
        self.assertEqual(list(frame["date"]), ["2026-03-02"])
        self.assertEqual(
            frame.attrs["snapshot_cohort"]["cohort_first_session"],
            "2026-03-02",
        )

    def test_bootstrap_resamples_date_and_stock_clusters_together(self):
        frame = pd.DataFrame(
            [
                {
                    "date": date,
                    "code": code,
                    "net_return_5": value,
                    "selected": code == "600000",
                    "reference": True,
                }
                for date, values in (
                    ("2026-01-05", (2.0, -1.0)),
                    ("2026-01-06", (1.0, -0.5)),
                    ("2026-01-07", (3.0, -2.0)),
                )
                for code, value in zip(("600000", "600001"), values)
            ]
        )

        with patch("tools.hierarchical_walk_forward.BOOTSTRAP_ITERATIONS", 200):
            result = _two_way_cluster_bootstrap_delta(
                frame,
                "selected",
                "reference",
            )

        self.assertEqual(result["date_clusters"], 3)
        self.assertEqual(result["stock_clusters"], 2)
        self.assertEqual(
            result["method"],
            "pigeonhole_date_x_stock_cluster_bootstrap",
        )
        self.assertGreater(result["positive_probability"], 0.5)

    def test_snapshot_manager_reuses_catalog_validation_payload(self):
        snapshot_id = "f" * 64
        payload = Path("/tmp") / "validated-snapshot-payload"
        with (
            patch(
                "tools.hierarchical_walk_forward.validated_snapshot_payload",
                return_value=payload,
            ) as resolve_payload,
            patch("utils.market_snapshot.load_market_snapshot") as load_snapshot,
        ):
            manager = _snapshot_manager(
                Path("/tmp/market-data"),
                snapshot_id,
                reference={"market_snapshot_id": snapshot_id},
            )

        resolve_payload.assert_called_once()
        load_snapshot.assert_not_called()
        self.assertIsNotNone(manager)
        self.assertEqual(manager.data_dir, payload)
        self.assertEqual(manager.snapshot_id, snapshot_id)
        self.assertTrue(manager.read_only)


if __name__ == "__main__":
    unittest.main()
