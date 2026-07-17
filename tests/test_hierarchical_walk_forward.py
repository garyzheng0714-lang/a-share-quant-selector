import unittest

import pandas as pd

from tools.hierarchical_walk_forward import (
    DATASET_SCHEMA_VERSION, MARKET_FEATURES, SECTOR_FEATURES, STOCK_FEATURES,
    _layer_frames, _purged_month_split, walk_forward,
)


class HierarchicalWalkForwardTest(unittest.TestCase):
    def test_market_and_sector_use_independent_units(self):
        rows = []
        for date in ("2026-01-05", "2026-01-06"):
            for code, industry, result in (
                ("600000", "银行", 2.0), ("600001", "煤炭", -1.0),
            ):
                row = {
                    "date": date, "label_end_date": "2026-01-13",
                    "code": code, "industry": industry,
                    "net_return_5": result, "excess_5": result - 0.2,
                    "y_quality": int(result > 0), "y_risk": int(result < -5),
                }
                row.update({name: 0.1 for name in MARKET_FEATURES + SECTOR_FEATURES + STOCK_FEATURES})
                rows.append(row)
        units = _layer_frames(pd.DataFrame(rows))

        self.assertEqual(len(units["market"]), 2)
        self.assertEqual(len(units["sector"]), 4)
        self.assertEqual(len(units["quality"]), 4)
        self.assertTrue((units["market"]["training_unit"] == "trade_date").all())

    def test_five_day_labels_are_purged_across_month_boundaries(self):
        data = pd.DataFrame([
            {"date": "2026-01-10", "label_end_date": "2026-01-15", "month": "2026-01"},
            {"date": "2026-01-28", "label_end_date": "2026-02-02", "month": "2026-01"},
            {"date": "2026-02-10", "label_end_date": "2026-02-15", "month": "2026-02"},
            {"date": "2026-02-25", "label_end_date": "2026-03-03", "month": "2026-02"},
            {"date": "2026-03-02", "label_end_date": "2026-03-09", "month": "2026-03"},
        ])

        train, validation, test, _, _ = _purged_month_split(
            data, ["2026-01"], {"2026-02"}, "2026-03",
        )

        self.assertEqual(train["date"].tolist(), ["2026-01-10"])
        self.assertEqual(validation["date"].tolist(), ["2026-02-10"])
        self.assertEqual(test["date"].tolist(), ["2026-03-02"])

    def test_old_dataset_schema_is_rejected_before_training(self):
        row = {
            "dataset_schema_version": DATASET_SCHEMA_VERSION - 1,
            "date": "2026-01-05", "label_end_date": "2026-01-12",
            "code": "600000", "industry": "银行",
            "reference_snapshot_date": "2026-01-05", "universe_coverage": 1.0,
            "weekly_passed": 1, "execution_status": "filled_round_trip",
            "net_return_5": 1.0, "excess_5": 0.5,
            "y_quality": 1, "y_risk": 0,
        }
        row.update({
            name: 0.1 for name in MARKET_FEATURES + SECTOR_FEATURES + STOCK_FEATURES
        })

        with self.assertRaisesRegex(ValueError, "版本不匹配"):
            walk_forward(pd.DataFrame([row]), min_train_months=0, val_months=0)


if __name__ == "__main__":
    unittest.main()
