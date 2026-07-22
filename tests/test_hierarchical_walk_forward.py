import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

from tools.hierarchical_walk_forward import (
    DATASET_SCHEMA_VERSION,
    MARKET_FEATURES,
    SECTOR_FEATURES,
    STOCK_FEATURES,
    _coefficient_stability,
    _layer_frames,
    _purged_month_split,
    _two_way_cluster_bootstrap_delta,
    build_dataset,
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
            "universe_coverage": 1.0,
            "weekly_passed": 1,
            "execution_status": "filled_round_trip",
            "execution_policy_version": "a-share-eod-open-open-v3",
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
            patch("tools.hierarchical_walk_forward.build_panels") as build_panels,
        ):
            frame = build_dataset(manager, {}, {})

        load_snapshots.assert_called_once_with(manager.base_data_dir)
        build_panels.assert_not_called()
        manager.list_all_stocks.assert_not_called()
        self.assertTrue(frame.empty)
        self.assertEqual(frame.attrs["reason"], "pit_feature_history_unavailable")
        self.assertEqual(frame.attrs["mismatched_snapshot_count"], 21)

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


if __name__ == "__main__":
    unittest.main()
