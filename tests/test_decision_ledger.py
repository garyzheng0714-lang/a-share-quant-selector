import sqlite3
import tempfile
import unittest
from pathlib import Path

import views.view_manager as view_manager
from utils.decision_ledger import (
    DECISION_RUNS_SCHEMA, activate_policy, get_active_models, get_active_policy_models,
    get_decision, get_latest_ai_decision_run, get_latest_decision, get_latest_evolution,
    init_decision_ledger,
    promote_model_bundle, register_model, register_policy_candidate, save_decision_run,
    save_ai_decision_run, save_event_evidence, save_evolution_run,
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

    def test_complete_policy_release_is_atomic(self):
        def register(key, version, status):
            register_model({
                "model_key": key, "version": version, "status": status,
                "trained_as_of": "2026-01-05T16:00:00+08:00",
                "feature_names": [], "params": {}, "metrics": {},
                "source_refs": [
                    "super-b1-original", "point-in-time-reference-snapshots-v1",
                    "purged-walk-forward-v2",
                ],
                "artifact": {},
            })

        for key in ("market", "sector", "risk", "quality"):
            register(key, "challenger", "shadow")
        register_policy_candidate({
            "policy_version": "challenger", "trained_as_of": "2026-01-05T16:00:00+08:00",
            "component_versions": {key: "challenger" for key in
                                   ("market", "sector", "risk", "quality")},
            "source_refs": [
                "super-b1-original", "point-in-time-reference-snapshots-v1",
                "purged-walk-forward-v2",
            ],
        })
        result = activate_policy("challenger", {
            "forward_observation_complete": True, "power_analysis_passed": True,
            "atomic_policy_evaluated": True, "operator_approved": True,
        })

        self.assertTrue(result["activated"])
        active, version = get_active_policy_models()
        self.assertEqual(version, "challenger")
        self.assertEqual(set(active), {"market", "sector", "risk", "quality"})

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

    def test_same_day_evolution_attempts_are_append_only(self):
        base = {
            "trade_date": "2026-01-05", "data_version": "d1",
            "universe_count": 100, "covered_count": 80, "coverage_ratio": 0.8,
            "labels_updated": 0, "dataset_rows": 0,
            "promotion_status": "not_eligible", "reason_codes": [], "metrics": {},
        }

        first = save_evolution_run({**base, "status": "failed"})
        second = save_evolution_run({**base, "status": "complete"})

        self.assertNotEqual(first, second)
        self.assertEqual(get_latest_evolution()["evolution_id"], second)
        with sqlite3.connect(view_manager.DB_PATH) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM evolution_runs").fetchone()[0], 2)

    def test_ai_attempts_and_event_fetches_are_append_only(self):
        ai = {
            "trade_date": "2026-01-05", "decision_run_id": "run-1",
            "as_of": "2026-01-05T16:00:00+08:00", "status": "not_called",
            "role": "explanation", "input_hash": "hash-1",
            "reason_codes": ["no_approved_candidates"],
        }
        first_ai = save_ai_decision_run(ai)
        second_ai = save_ai_decision_run(ai)
        event = {
            "event_id": "event-1", "code": "600000", "source": "test",
            "published_at": "2026-01-05T10:00:00+08:00", "title": "公告",
            "text_hash": "text-1", "fetched_at": "2026-01-05T10:01:00+08:00",
        }
        save_event_evidence(event)
        save_event_evidence({**event, "fetched_at": "2026-01-05T10:02:00+08:00"})

        self.assertNotEqual(first_ai, second_ai)
        self.assertEqual(get_latest_ai_decision_run()["ai_run_id"], second_ai)
        with sqlite3.connect(view_manager.DB_PATH) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM ai_decision_runs").fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT count(*) FROM event_evidence").fetchone()[0], 2)

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

    def test_partial_policy_cannot_be_registered(self):
        with self.assertRaisesRegex(ValueError, "完整策略缺少组件"):
            register_policy_candidate({
                "policy_version": "partial", "trained_as_of": "2026-01-05",
                "component_versions": {"market": "m1"},
            })

    def test_release_requires_forward_and_operator_evidence(self):
        result = activate_policy("missing", {"operator_approved": True})

        self.assertFalse(result["activated"])
        self.assertEqual(result["reason"], "release_evidence_incomplete")

    def test_release_rejects_policy_with_unregistered_components(self):
        register_policy_candidate({
            "policy_version": "missing-models",
            "trained_as_of": "2026-01-05T16:00:00+08:00",
            "component_versions": {
                key: "missing" for key in ("market", "sector", "risk", "quality")
            },
            "source_refs": [
                "super-b1-original", "point-in-time-reference-snapshots-v1",
                "purged-walk-forward-v2",
            ],
        })

        result = activate_policy("missing-models", {
            "forward_observation_complete": True,
            "power_analysis_passed": True,
            "atomic_policy_evaluated": True,
            "operator_approved": True,
        })

        self.assertFalse(result["activated"])
        self.assertEqual(result["reason"], "policy_components_not_releaseable")
        self.assertEqual(len(result["components"]), 4)

    def test_legacy_layer_promotion_is_disabled(self):
        result = promote_model_bundle("new", {"market": "active"})

        self.assertFalse(result["promoted"])
        self.assertEqual(result["reason"], "legacy_layer_promotion_disabled")

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
