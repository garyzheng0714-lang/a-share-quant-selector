import tempfile
import unittest
from pathlib import Path

import views.view_manager as view_manager
from utils.decision_ledger import get_latest_decision, save_decision_run


class DecisionLedgerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original = view_manager.DB_PATH
        view_manager.DB_PATH = Path(self.tmp.name) / "test.db"

    def tearDown(self):
        view_manager.DB_PATH = self.original
        self.tmp.cleanup()

    def test_round_trip_keeps_evidence_chain(self):
        run = {
            "trade_date": "2026-01-05", "stage": "close",
            "as_of": "2026-01-05T15:00:00+08:00", "status": "complete",
            "final_action": "observe", "strategy_version": "s1",
            "feature_version": "f1", "model_version": "baseline", "data_version": "d1",
            "source_refs": ["eod:2026-01-05"], "market": {"gate": "shadow"},
            "evaluation": {}, "reason_codes": ["model_unvalidated"],
        }
        save_decision_run(run, [{
            "code": "600000", "name": "浦发银行", "industry": "银行", "action": "observe",
            "baseline": {"signal": "cloud_stair"}, "market": {}, "sector": {},
            "stock": {}, "events": [], "reason_codes": ["model_unvalidated"],
        }])
        saved = get_latest_decision("close")
        self.assertEqual(saved["source_refs"], ["eod:2026-01-05"])
        self.assertEqual(saved["candidates"][0]["baseline"]["signal"], "cloud_stair")


if __name__ == "__main__":
    unittest.main()
