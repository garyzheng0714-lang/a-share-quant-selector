import sqlite3
import tempfile
import unittest
from pathlib import Path

import views.view_manager as view_manager
from utils.decision_ledger import (
    DECISION_RUNS_SCHEMA, get_active_models, get_decision, get_latest_decision,
    init_decision_ledger, promote_model_bundle, register_model, save_decision_run,
)


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

    def test_model_bundle_promotion_is_atomic(self):
        def register(key, version, status):
            register_model({
                "model_key": key, "version": version, "status": status,
                "trained_as_of": "2026-01-05T16:00:00+08:00",
                "feature_names": [], "params": {}, "metrics": {},
                "source_refs": [], "artifact": {},
            })

        for key in ("market", "sector"):
            register(key, "champion", "active")
            register(key, "challenger", "shadow")
        result = promote_model_bundle(
            "challenger", {"market": "active", "sector": "active"}
        )
        self.assertTrue(result["promoted"])
        active = get_active_models()
        self.assertEqual({item["version"] for item in active.values()}, {"challenger"})

    def test_runs_are_append_only_across_model_versions(self):
        base = {
            "trade_date": "2026-01-05", "stage": "close",
            "status": "complete", "final_action": "observe",
            "strategy_version": "s1", "feature_version": "f1", "data_version": "d1",
        }
        first = save_decision_run({
            **base, "as_of": "2026-01-05T15:00:00+08:00", "model_version": "m1",
            "created_at": "2026-01-05T15:01:00+08:00",
        }, [{"code": "600000", "action": "observe"}])
        second = save_decision_run({
            **base, "as_of": "2026-01-05T15:00:00+08:00", "model_version": "m2",
            "created_at": "2026-01-05T15:02:00+08:00",
        }, [{"code": "600000", "action": "observe"}])

        self.assertNotEqual(first, second)
        self.assertEqual(get_decision(first)["model_version"], "m1")
        self.assertEqual(get_decision(second)["model_version"], "m2")
        self.assertEqual(get_latest_decision("close")["model_version"], "m2")

    def test_reregistering_same_model_does_not_demote_active_champion(self):
        payload = {
            "model_key": "market", "version": "champion", "status": "active",
            "trained_as_of": "2026-01-05T16:00:00+08:00",
            "feature_names": [], "params": {}, "metrics": {},
            "source_refs": [], "artifact": {},
        }
        register_model(payload)
        register_model({**payload, "status": "shadow"})

        self.assertEqual(get_active_models()["market"]["version"], "champion")

    def test_independent_layer_promotion_keeps_other_champion(self):
        def register(key, version, status):
            register_model({
                "model_key": key, "version": version, "status": status,
                "trained_as_of": "2026-01-05T16:00:00+08:00",
                "feature_names": [], "params": {}, "metrics": {},
                "source_refs": [], "artifact": {},
            })

        register("market", "old-market", "active")
        register("sector", "old-sector", "active")
        register("market", "new-market", "shadow")
        result = promote_model_bundle("new-market", {"market": "active"})

        self.assertTrue(result["promoted"])
        active = get_active_models()
        self.assertEqual(active["market"]["version"], "new-market")
        self.assertEqual(active["sector"]["version"], "old-sector")

    def test_missing_optional_challenger_does_not_demote_its_champion(self):
        payload = {
            "trained_as_of": "2026-01-05T16:00:00+08:00",
            "feature_names": [], "params": {}, "metrics": {},
            "source_refs": [], "artifact": {},
        }
        register_model({
            **payload, "model_key": "sector", "version": "old-sector", "status": "active",
        })
        register_model({
            **payload, "model_key": "market", "version": "new", "status": "shadow",
        })

        result = promote_model_bundle("new", {"market": "active", "sector": "active"})

        self.assertTrue(result["promoted"])
        self.assertEqual(result["missing_optional_layers"], ["sector"])
        active = get_active_models()
        self.assertEqual(active["market"]["version"], "new")
        self.assertEqual(active["sector"]["version"], "old-sector")

    def test_old_unique_schema_migrates_with_children_intact(self):
        init_decision_ledger()
        with sqlite3.connect(view_manager.DB_PATH) as conn:
            child_schemas = {
                table: conn.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
                ).fetchone()[0]
                for table in ("decision_candidates", "decision_outcomes")
            }
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute("DROP TABLE decision_candidates")
            conn.execute("DROP TABLE decision_outcomes")
            conn.execute("DROP TABLE decision_runs")
            old_schema = DECISION_RUNS_SCHEMA.rsplit(")", 1)[0]
            old_schema += ", UNIQUE(trade_date, stage, strategy_version, data_version))"
            conn.execute(old_schema)
            conn.execute(child_schemas["decision_candidates"])
            conn.execute(child_schemas["decision_outcomes"])
            conn.execute(
                """INSERT INTO decision_runs VALUES
                ('run-1', '2026-01-05', 'close', '2026-01-05T15:00:00+08:00',
                 'complete', 'observe', 's1', 'f1', 'm1', 'd1', '[]', '{}',
                 '{}', '[]', '2026-01-05T15:00:00+08:00', '2026-01-05T15:00:00+08:00')"""
            )
            conn.execute(
                """INSERT INTO decision_candidates
                (run_id, code, name, industry, rank_no, tie_group, action,
                 baseline_json, market_json, sector_json, stock_json, events_json,
                 reason_codes_json, explanation, created_at)
                VALUES ('run-1', '600000', '浦发银行', '银行', 1, 1, 'observe',
                        '{}', '{}', '{}', '{}', '[]', '[]', '', '2026-01-05')"""
            )
            conn.execute(
                """INSERT INTO decision_outcomes
                (run_id, code, stage, trade_date, action, days_tracked, status, updated_at)
                VALUES ('run-1', '600000', 'close', '2026-01-05', 'observe', 0,
                        'pending', '2026-01-05')"""
            )

        init_decision_ledger()

        with sqlite3.connect(view_manager.DB_PATH) as conn:
            schema = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='decision_runs'"
            ).fetchone()[0]
            self.assertNotIn(
                "unique(trade_date,stage,strategy_version,data_version)",
                "".join(schema.lower().split()),
            )
            self.assertEqual(
                conn.execute("SELECT count(*) FROM decision_candidates").fetchone()[0], 1
            )
            self.assertEqual(
                conn.execute("SELECT count(*) FROM decision_outcomes").fetchone()[0], 1
            )
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            for table in ("decision_candidates", "decision_outcomes"):
                parents = {
                    row[2] for row in conn.execute(f"PRAGMA foreign_key_list({table})")
                }
                self.assertIn("decision_runs", parents)


if __name__ == "__main__":
    unittest.main()
