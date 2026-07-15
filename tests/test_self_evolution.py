import tempfile
import unittest
from pathlib import Path

import pandas as pd

import views.view_manager as view_manager
from utils.csv_manager import CSVManager
from utils.decision_ledger import outcome_summary, save_decision_run
from utils.self_evolution import update_decision_outcomes


class SelfEvolutionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original = view_manager.DB_PATH
        view_manager.DB_PATH = Path(self.tmp.name) / "test.db"

    def tearDown(self):
        view_manager.DB_PATH = self.original
        self.tmp.cleanup()

    def test_observe_is_labeled_to_measure_missed_winners(self):
        manager = CSVManager(Path(self.tmp.name) / "data")
        manager.write_stock("600000", pd.DataFrame([
            {"date": "2026-01-05", "open": 10, "high": 10.2, "low": 9.8, "close": 10, "volume": 100},
            {"date": "2026-01-06", "open": 10, "high": 10.6, "low": 9.9, "close": 10.5, "volume": 100},
            {"date": "2026-01-07", "open": 10.5, "high": 10.8, "low": 10.3, "close": 10.7, "volume": 100},
            {"date": "2026-01-08", "open": 10.7, "high": 11.0, "low": 10.6, "close": 10.9, "volume": 100},
            {"date": "2026-01-09", "open": 10.9, "high": 11.2, "low": 10.8, "close": 11.1, "volume": 100},
            {"date": "2026-01-12", "open": 11.1, "high": 11.5, "low": 11.0, "close": 11.4, "volume": 100},
        ]))
        save_decision_run({
            "trade_date": "2026-01-05", "stage": "close",
            "as_of": "2026-01-05T15:00:00+08:00", "status": "degraded",
            "final_action": "observe", "strategy_version": "s1",
            "feature_version": "f1", "model_version": "m1", "data_version": "d1",
        }, [{"code": "600000", "action": "observe"}])

        result = update_decision_outcomes(manager)
        summary = outcome_summary()
        self.assertEqual(result["complete"], 1)
        self.assertEqual(summary["observe"]["count"], 1)
        self.assertEqual(summary["missed_winner_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()
