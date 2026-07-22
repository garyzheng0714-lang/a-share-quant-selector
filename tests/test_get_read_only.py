import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from flask import Flask

import views.view_manager as view_manager
from utils.decision_ledger import init_decision_ledger, save_decision_run
from views.decision_api import decision_bp
from views.factor_api import factor_bp
from views.insight_api import insight_bp
from views.super_b1_api import super_b1_bp


class GetReadOnlyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original = view_manager.DB_PATH
        view_manager.DB_PATH = Path(self.tmp.name) / "test.db"
        init_decision_ledger()
        self.snapshot_id = "a" * 64
        save_decision_run(
            {
                "trade_date": "2026-07-14",
                "stage": "close",
                "as_of": "2026-07-14T15:05:00+08:00",
                "status": "complete",
                "final_action": "none",
                "strategy_version": "s1",
                "feature_version": "f1",
                "model_version": "baseline-only",
                "data_version": f"snapshot-{self.snapshot_id}",
                "market": {"snapshot_id": self.snapshot_id},
            },
            [],
        )
        app = Flask(__name__)
        app.register_blueprint(decision_bp)
        self.client = app.test_client()

    def tearDown(self):
        view_manager.DB_PATH = self.original
        self.tmp.cleanup()

    def test_latest_get_does_not_create_decision_or_release_rows(self):
        with sqlite3.connect(view_manager.DB_PATH) as conn:
            before = {
                table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in (
                    "decision_runs",
                    "policy_release_events",
                    "ai_decision_runs",
                )
            }
        freshness = {
            "fresh": True,
            "local_date": "2026-07-14",
            "expected_date": "2026-07-14",
            "snapshot_id": self.snapshot_id,
        }
        with (
            patch("utils.data_freshness.local_data_status", return_value=freshness),
            patch("utils.decision_versions.strategy_version", return_value="s1"),
        ):
            response = self.client.get("/api/decision/latest")
        with sqlite3.connect(view_manager.DB_PATH) as conn:
            after = {
                table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in (
                    "decision_runs",
                    "policy_release_events",
                    "ai_decision_runs",
                )
            }

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["available"])
        self.assertEqual(after, before)


class CachedArtifactGetTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.register_blueprint(insight_bp)
        app.register_blueprint(super_b1_bp)
        app.register_blueprint(factor_bp)
        self.client = app.test_client()
        self.manager = MagicMock()
        self.manager.snapshot_id = "a" * 64

    def test_market_artifact_gets_never_trigger_recomputation(self):
        with (
            patch("utils.csv_manager.CSVManager", return_value=self.manager),
            patch(
                "utils.market_thermometer.read_thermometer",
                return_value={"available": True, "heat": {}},
            ) as thermometer_read,
            patch(
                "utils.market_thermometer.refresh_thermometer",
            ) as thermometer_refresh,
            patch(
                "utils.sector_rotation.read_cached_sector_rotation",
                return_value={"available": True, "heat_map": {}},
            ) as sector_read,
            patch("utils.sector_rotation.get_sector_rotation") as sector_compute,
        ):
            thermometer = self.client.get("/api/thermometer")
            sectors = self.client.get("/api/sectors")

        self.assertEqual(thermometer.status_code, 200)
        self.assertEqual(sectors.status_code, 200)
        thermometer_read.assert_called_once()
        sector_read.assert_called_once()
        thermometer_refresh.assert_not_called()
        sector_compute.assert_not_called()

    def test_signal_gets_only_read_worker_caches(self):
        with (
            patch("views.super_b1_api.CSVManager", return_value=self.manager),
            patch("views.factor_api.CSVManager", return_value=self.manager),
            patch(
                "utils.super_b1_scan.read_cached_super_b1",
                return_value={
                    "available": True,
                    "hits": [],
                    "trade_date": "2026-07-14",
                },
            ) as super_read,
            patch("utils.super_b1_scan.compute_scan") as super_compute,
            patch(
                "utils.factor_scan.read_cached_factor_hits",
                return_value={
                    "available": True,
                    "trade_date": "2026-07-14",
                    "results": {
                        "cloud_stair": {"hits": [], "total_scanned": 3000, "errors": 0},
                    },
                },
            ) as factor_read,
            patch("utils.factor_scan.compute_scan") as factor_compute,
        ):
            super_response = self.client.get("/api/super-b1")
            factor_response = self.client.get("/api/factor-scan?strategy=cloud_stair")

        self.assertEqual(super_response.status_code, 200)
        self.assertEqual(factor_response.status_code, 200)
        super_read.assert_called_once()
        factor_read.assert_called_once()
        super_compute.assert_not_called()
        factor_compute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
