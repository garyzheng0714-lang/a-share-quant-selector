import sqlite3
import tempfile
import unittest
from pathlib import Path

import views.view_manager as view_manager
from utils.decision_ledger import (
    DECISION_RUNS_SCHEMA,
    activate_policy,
    append_decision_outcome,
    get_active_models,
    get_active_policy_models,
    get_decision,
    get_latest_ai_decision_run,
    get_latest_decision,
    get_latest_evolution,
    init_decision_ledger,
    list_decision_outcomes,
    list_pending_outcome_candidates,
    model_artifact_hash,
    outcome_summary,
    promote_model_bundle,
    record_policy_validation,
    register_model,
    register_policy_evidence_artifact,
    register_policy_candidate,
    rollback_active_policy,
    save_decision_run,
    save_ai_decision_run,
    save_event_evidence,
    save_evolution_run,
)
from utils.decision_versions import VALIDATED_MODEL_SOURCE_REFS


COMPONENTS = ("market", "sector", "entry_risk", "exit_risk", "quality")
SOURCE_REFS = sorted(VALIDATED_MODEL_SOURCE_REFS)
DATASET_HASH = "d" * 64
CODE_SHA = "c" * 40
RUNTIME_POLICY_MANIFEST = {"weekly_gate": {"mode": "shadow"}}


def _validation_artifact(artifact_type):
    artifact = {
        "dataset_hash": DATASET_HASH,
        "code_sha": CODE_SHA,
    }
    if artifact_type == "power_analysis":
        artifact.update(
            {
                "forward_window_end": "2026-01-31T23:59:59+08:00",
                "metrics": {
                    "independent_months": 6,
                    "required_independent_months": 6,
                    "sample_count": 500,
                    "achieved_power": 0.90,
                    "monte_carlo_standard_error": 0.005,
                },
            }
        )
    else:
        artifact.update(
            {
                "runtime_policy_manifest": RUNTIME_POLICY_MANIFEST,
                "metrics": {
                    "evaluation_months": 6,
                    "coverage_ratio": 0.98,
                    "baseline_delta_pct": 1.2,
                    "cvar10_pct": -8.0,
                    "max_drawdown_pct": -15.0,
                    "unbuyable_rate": 0.05,
                    "unsellable_rate": 0.02,
                    "opportunity_cost_pct": 0.4,
                    "reconciliation_error": 0.0,
                    "ablation_components": list(COMPONENTS),
                    "execution_policy_version": "a-share-eod-open-open-v3",
                },
            }
        )
    return artifact


def _validation_evidence(power_artifact_id, atomic_artifact_id):
    return {
        "reviewer_id": "reviewer-1",
        "ticket_ref": "CHANGE-123",
        "power_analysis_artifact_id": power_artifact_id,
        "atomic_policy_evaluation_artifact_id": atomic_artifact_id,
        "previous_policy": "baseline-only",
        "rollback_policy": "baseline-only",
    }


def _release_request(evidence_hash="e" * 64):
    return {
        "operator_id": "operator-1",
        "reviewer_id": "reviewer-1",
        "ticket_ref": "CHANGE-123",
        "change_reason": "approved release",
        "evidence_hash": evidence_hash,
        "previous_policy": "baseline-only",
        "rollback_policy": "baseline-only",
    }


class DecisionLedgerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original = view_manager.DB_PATH
        view_manager.DB_PATH = Path(self.tmp.name) / "test.db"
        init_decision_ledger()

    def tearDown(self):
        view_manager.DB_PATH = self.original
        self.tmp.cleanup()

    def _register_releaseable_policy(self, version="validated-policy"):
        artifact = {
            "kind": "test",
            "training_diagnostics": {"converged": True, "releaseable": True},
        }
        for key in COMPONENTS:
            register_model(
                {
                    "model_key": key,
                    "version": version,
                    "status": "shadow",
                    "trained_as_of": "2026-01-05T16:00:00+08:00",
                    "feature_names": [],
                    "params": {
                        "threshold": 0.5,
                        "validation_status": "active",
                        "calibration_status": "independent_holdout",
                        "dataset_hash": DATASET_HASH,
                        "code_sha": CODE_SHA,
                        "artifact_hash": model_artifact_hash(artifact),
                        "optimizer_diagnostics": {
                            "converged": True,
                            "releaseable": True,
                            "coefficient_stability": {"stable": True},
                            "calibration": {"releaseable": True},
                            "feature_drift": {"releaseable": True},
                        },
                    },
                    "metrics": {},
                    "source_refs": SOURCE_REFS,
                    "artifact": artifact,
                }
            )
        register_policy_candidate(
            {
                "policy_version": version,
                "trained_as_of": "2026-01-05T16:00:00+08:00",
                "component_versions": {key: version for key in COMPONENTS},
                "evidence": {
                    "dataset_hash": DATASET_HASH,
                    "code_sha": CODE_SHA,
                    "runtime_policy_manifest": RUNTIME_POLICY_MANIFEST,
                },
                "source_refs": SOURCE_REFS,
            }
        )

    def _validate_policy(self, version="validated-policy"):
        power = register_policy_evidence_artifact(
            version,
            "power_analysis",
            f"experiment:{version}:power",
            _validation_artifact("power_analysis"),
        )
        atomic = register_policy_evidence_artifact(
            version,
            "atomic_policy_evaluation",
            f"experiment:{version}:atomic",
            _validation_artifact("atomic_policy_evaluation"),
        )
        return record_policy_validation(
            version,
            _validation_evidence(power["artifact_id"], atomic["artifact_id"]),
        )

    def test_round_trip_keeps_evidence_chain(self):
        run = {
            "trade_date": "2026-01-05",
            "stage": "close",
            "as_of": "2026-01-05T15:00:00+08:00",
            "status": "complete",
            "final_action": "observe",
            "strategy_version": "s1",
            "feature_version": "f1",
            "model_version": "baseline",
            "data_version": "d1",
            "source_refs": ["eod:2026-01-05"],
            "market": {"gate": "shadow"},
            "evaluation": {},
            "reason_codes": ["model_unvalidated"],
        }
        save_decision_run(
            run,
            [
                {
                    "code": "600000",
                    "name": "浦发银行",
                    "industry": "银行",
                    "action": "observe",
                    "baseline": {"signal": "cloud_stair"},
                    "market": {},
                    "sector": {},
                    "stock": {},
                    "events": [],
                    "reason_codes": ["model_unvalidated"],
                }
            ],
        )
        saved = get_latest_decision("close")
        self.assertEqual(saved["source_refs"], ["eod:2026-01-05"])
        self.assertEqual(saved["candidates"][0]["baseline"]["signal"], "cloud_stair")

    def test_outcome_observations_are_append_only_verified_and_idempotent(self):
        run_id = save_decision_run(
            {
                "trade_date": "2026-01-05",
                "stage": "close",
                "as_of": "2026-01-05T15:00:00+08:00",
                "status": "complete",
                "final_action": "buy",
                "strategy_version": "s1",
                "feature_version": "f1",
                "model_version": "baseline",
                "data_version": "d1",
            },
            [{"code": "600000", "action": "buy"}],
        )
        partial = {
            "run_id": run_id,
            "code": "600000",
            "source_snapshot_id": "a" * 64,
            "stage": "close",
            "trade_date": "2026-01-05",
            "action": "buy",
            "entry_date": "2026-01-06",
            "entry_price": 10.0,
            "entry_feasible": 1,
            "days_tracked": 1,
            "status": "partial",
        }
        self.assertTrue(append_decision_outcome(partial))
        self.assertFalse(append_decision_outcome(partial))
        self.assertEqual(len(list_pending_outcome_candidates()), 1)

        complete = {
            **partial,
            "ret_1": 1.0,
            "net_ret_5": 5.0,
            "max_gain_5": 6.0,
            "max_drawdown_5": -2.0,
            "exit_feasible": 1,
            "execution_status": "filled",
            "execution_policy_version": "a-share-eod-open-open-v3",
            "days_tracked": 5,
            "status": "complete",
        }
        self.assertTrue(append_decision_outcome(complete))

        records = list_decision_outcomes()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["observation_no"], 2)
        self.assertEqual(records[0]["status"], "complete")
        self.assertEqual(len(records[0]["outcome_id"]), 64)
        self.assertEqual(list_pending_outcome_candidates(), [])
        self.assertEqual(outcome_summary()["buy"]["count"], 1)

        with sqlite3.connect(view_manager.DB_PATH) as conn:
            self.assertEqual(
                conn.execute("SELECT count(*) FROM decision_outcomes").fetchone()[0],
                2,
            )
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "UPDATE decision_outcomes SET status='invalid' WHERE outcome_id=?",
                    (records[0]["outcome_id"],),
                )
            conn.rollback()
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "DELETE FROM decision_outcomes WHERE outcome_id=?",
                    (records[0]["outcome_id"],),
                )

        with sqlite3.connect(view_manager.DB_PATH) as conn:
            conn.execute(
                """
                INSERT INTO decision_outcomes
                  (outcome_id, run_id, code, source_snapshot_id, observation_no,
                   stage, trade_date, action, days_tracked, status, updated_at)
                VALUES (?, ?, '600000', ?, 3, 'close', '2026-01-05', 'buy', 5,
                        'complete', '2026-01-13T16:00:00+08:00')
                """,
                ("f" * 64, run_id, "a" * 64),
            )
        with self.assertRaisesRegex(RuntimeError, "decision_outcome_integrity_failed"):
            list_decision_outcomes()

    def test_shadow_policy_cannot_be_activated(self):
        def register(key, version, status):
            register_model(
                {
                    "model_key": key,
                    "version": version,
                    "status": status,
                    "trained_as_of": "2026-01-05T16:00:00+08:00",
                    "feature_names": [],
                    "params": {},
                    "metrics": {},
                    "source_refs": [
                        "super-b1-original",
                        "point-in-time-reference-snapshots-v1",
                        "purged-walk-forward-v2",
                    ],
                    "artifact": {},
                }
            )

        for key in COMPONENTS:
            register(key, "challenger", "shadow")
        register_policy_candidate(
            {
                "policy_version": "challenger",
                "trained_as_of": "2026-01-05T16:00:00+08:00",
                "component_versions": {key: "challenger" for key in COMPONENTS},
                "source_refs": [
                    "super-b1-original",
                    "point-in-time-reference-snapshots-v1",
                    "purged-walk-forward-v2",
                ],
            }
        )
        result = activate_policy("challenger", _release_request())

        self.assertFalse(result["activated"])
        self.assertEqual(result["reason"], "policy_not_validated")
        active, version = get_active_policy_models()
        self.assertEqual(version, "baseline-only")
        self.assertEqual(active, {})

    def test_validated_complete_policy_release_is_atomic(self):
        self._register_releaseable_policy()
        validation = self._validate_policy()
        self.assertTrue(validation["validated"])

        result = activate_policy(
            "validated-policy",
            _release_request(validation["evidence_hash"]),
        )

        self.assertTrue(result["activated"])
        active, version = get_active_policy_models()
        self.assertEqual(version, "validated-policy")
        self.assertEqual(set(active), set(COMPONENTS))

    def test_active_policy_can_only_rollback_to_preapproved_target(self):
        self._register_releaseable_policy()
        validation = self._validate_policy()
        activation = activate_policy(
            "validated-policy",
            _release_request(validation["evidence_hash"]),
        )
        self.assertTrue(activation["activated"])

        wrong = rollback_active_policy(
            "some-other-policy",
            {
                "operator_id": "operator-2",
                "reviewer_id": "reviewer-2",
                "ticket_ref": "ROLLBACK-123",
                "change_reason": "rollback drill",
                "expected_current_policy": "validated-policy",
            },
        )
        self.assertFalse(wrong["rolled_back"])
        self.assertEqual(wrong["reason"], "rollback_target_not_preapproved")

        result = rollback_active_policy(
            "baseline-only",
            {
                "operator_id": "operator-2",
                "reviewer_id": "reviewer-2",
                "ticket_ref": "ROLLBACK-123",
                "change_reason": "rollback drill",
                "expected_current_policy": "validated-policy",
            },
        )
        self.assertTrue(result["rolled_back"])
        active, version = get_active_policy_models()
        self.assertEqual(version, "baseline-only")
        self.assertEqual(active, {})

    def test_policy_evidence_artifacts_are_immutable(self):
        self._register_releaseable_policy()
        registered = register_policy_evidence_artifact(
            "validated-policy",
            "power_analysis",
            "experiment:immutable",
            _validation_artifact("power_analysis"),
        )

        with sqlite3.connect(view_manager.DB_PATH) as connection:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
                connection.execute(
                    "UPDATE policy_evidence_artifacts SET payload_json='{}' "
                    "WHERE artifact_id=?",
                    (registered["artifact_id"],),
                )

    def test_validation_and_release_records_are_immutable(self):
        self._register_releaseable_policy()
        validation = self._validate_policy()
        activation = activate_policy(
            "validated-policy",
            _release_request(validation["evidence_hash"]),
        )

        with sqlite3.connect(view_manager.DB_PATH) as connection:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
                connection.execute(
                    "UPDATE policy_validation_records SET status='rejected' "
                    "WHERE validation_id=?",
                    (validation["validation_id"],),
                )
            with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
                connection.execute(
                    "DELETE FROM policy_release_events WHERE release_id=?",
                    (activation["release_id"],),
                )

    def test_validation_rejects_caller_asserted_pass_boolean(self):
        self._register_releaseable_policy()
        artifact = _validation_artifact("power_analysis")
        artifact["passed"] = True

        with self.assertRaisesRegex(ValueError, "caller_asserted_pass"):
            register_policy_evidence_artifact(
                "validated-policy",
                "power_analysis",
                "experiment:self-asserted",
                artifact,
            )

    def test_decisions_and_registered_artifacts_are_database_immutable(self):
        run_id = save_decision_run(
            {
                "trade_date": "2026-01-05",
                "stage": "close",
                "as_of": "2026-01-05T15:05:00+08:00",
                "status": "complete",
                "final_action": "observe",
                "strategy_version": "s1",
                "feature_version": "f1",
                "model_version": "baseline-only",
                "data_version": "d1",
            },
            [{"code": "600000", "action": "observe"}],
        )
        register_model(
            {
                "model_key": "market",
                "version": "immutable-model",
                "trained_as_of": "2026-01-05T16:00:00+08:00",
                "feature_names": ["x"],
                "params": {"threshold": 0.5},
                "metrics": {},
                "source_refs": [],
                "artifact": {"coef": [1.0]},
            }
        )

        with sqlite3.connect(view_manager.DB_PATH) as connection:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
                connection.execute(
                    "UPDATE decision_runs SET final_action='buy' WHERE run_id=?",
                    (run_id,),
                )
            with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
                connection.execute(
                    "UPDATE model_registry SET artifact_json='{}' "
                    "WHERE model_key='market' AND version='immutable-model'"
                )
            with self.assertRaisesRegex(sqlite3.IntegrityError, "transition"):
                connection.execute(
                    "UPDATE model_registry SET status='active' "
                    "WHERE model_key='market' AND version='immutable-model'"
                )

    def test_runs_are_append_only_across_model_versions(self):
        base = {
            "trade_date": "2026-01-05",
            "stage": "close",
            "status": "complete",
            "final_action": "observe",
            "strategy_version": "s1",
            "feature_version": "f1",
            "data_version": "d1",
        }
        first = save_decision_run(
            {
                **base,
                "as_of": "2026-01-05T15:00:00+08:00",
                "model_version": "m1",
                "created_at": "2026-01-05T15:01:00+08:00",
            },
            [{"code": "600000", "action": "observe"}],
        )
        second = save_decision_run(
            {
                **base,
                "as_of": "2026-01-05T15:00:00+08:00",
                "model_version": "m2",
                "created_at": "2026-01-05T15:02:00+08:00",
            },
            [{"code": "600000", "action": "observe"}],
        )

        self.assertNotEqual(first, second)
        self.assertEqual(get_decision(first)["model_version"], "m1")
        self.assertEqual(get_decision(second)["model_version"], "m2")
        self.assertEqual(get_latest_decision("close")["model_version"], "m2")

    def test_same_day_evolution_attempts_are_append_only(self):
        base = {
            "trade_date": "2026-01-05",
            "data_version": "d1",
            "universe_count": 100,
            "covered_count": 80,
            "coverage_ratio": 0.8,
            "labels_updated": 0,
            "dataset_rows": 0,
            "promotion_status": "not_eligible",
            "reason_codes": [],
            "metrics": {},
        }

        first = save_evolution_run({**base, "status": "failed"})
        second = save_evolution_run({**base, "status": "complete"})

        self.assertNotEqual(first, second)
        self.assertEqual(get_latest_evolution()["evolution_id"], second)
        with sqlite3.connect(view_manager.DB_PATH) as conn:
            self.assertEqual(
                conn.execute("SELECT count(*) FROM evolution_runs").fetchone()[0], 2
            )

    def test_ai_attempts_and_event_fetches_are_append_only(self):
        ai = {
            "trade_date": "2026-01-05",
            "decision_run_id": "run-1",
            "as_of": "2026-01-05T16:00:00+08:00",
            "status": "not_called",
            "role": "explanation",
            "input_hash": "hash-1",
            "reason_codes": ["no_approved_candidates"],
        }
        first_ai = save_ai_decision_run(ai)
        second_ai = save_ai_decision_run(ai)
        event = {
            "event_id": "event-1",
            "code": "600000",
            "source": "test",
            "published_at": "2026-01-05T10:00:00+08:00",
            "title": "公告",
            "text_hash": "text-1",
            "fetched_at": "2026-01-05T10:01:00+08:00",
        }
        save_event_evidence(event)
        save_event_evidence({**event, "fetched_at": "2026-01-05T10:02:00+08:00"})

        self.assertNotEqual(first_ai, second_ai)
        self.assertEqual(get_latest_ai_decision_run()["ai_run_id"], second_ai)
        with sqlite3.connect(view_manager.DB_PATH) as conn:
            self.assertEqual(
                conn.execute("SELECT count(*) FROM ai_decision_runs").fetchone()[0], 2
            )
            self.assertEqual(
                conn.execute("SELECT count(*) FROM event_evidence").fetchone()[0], 2
            )

    def test_research_caller_cannot_self_declare_model_active(self):
        payload = {
            "model_key": "market",
            "version": "champion",
            "status": "active",
            "trained_as_of": "2026-01-05T16:00:00+08:00",
            "feature_names": [],
            "params": {},
            "metrics": {},
            "source_refs": [],
            "artifact": {},
        }
        register_model(payload)
        self.assertEqual(get_active_models(), {})

    def test_partial_policy_cannot_be_registered(self):
        with self.assertRaisesRegex(ValueError, "完整策略缺少组件"):
            register_policy_candidate(
                {
                    "policy_version": "partial",
                    "trained_as_of": "2026-01-05",
                    "component_versions": {"market": "m1"},
                }
            )

    def test_release_requires_forward_and_operator_evidence(self):
        result = activate_policy("missing", {"operator_id": "operator-1"})

        self.assertFalse(result["activated"])
        self.assertEqual(result["reason"], "release_request_incomplete")

    def test_release_rejects_policy_with_unregistered_components(self):
        register_policy_candidate(
            {
                "policy_version": "missing-models",
                "research_status": "validated",
                "trained_as_of": "2026-01-05T16:00:00+08:00",
                "component_versions": {key: "missing" for key in COMPONENTS},
                "source_refs": [
                    "super-b1-original",
                    "point-in-time-reference-snapshots-v1",
                    "purged-walk-forward-v2",
                ],
            }
        )

        result = self._validate_policy("missing-models")

        self.assertFalse(result["validated"])
        self.assertEqual(result["reason"], "validation_evidence_rejected")
        self.assertEqual(
            len(
                [
                    reason
                    for reason in result["reason_codes"]
                    if reason.endswith("_model_missing")
                ]
            ),
            len(COMPONENTS),
        )

    def test_legacy_layer_promotion_is_disabled(self):
        result = promote_model_bundle("new", {"market": "active"})

        self.assertFalse(result["promoted"])
        self.assertEqual(result["reason"], "legacy_layer_promotion_disabled")

    def test_old_unique_schema_migrates_with_children_intact(self):
        init_decision_ledger()
        with sqlite3.connect(view_manager.DB_PATH) as conn:
            candidate_schema = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                ("decision_candidates",),
            ).fetchone()[0]
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute("DROP TABLE decision_candidates")
            conn.execute("DROP TABLE decision_outcomes")
            conn.execute("DROP TABLE decision_runs")
            old_schema = DECISION_RUNS_SCHEMA.rsplit(")", 1)[0]
            old_schema += ", UNIQUE(trade_date, stage, strategy_version, data_version))"
            conn.execute(old_schema)
            conn.execute(candidate_schema)
            conn.execute("""
                CREATE TABLE decision_outcomes (
                    run_id TEXT NOT NULL,
                    code TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    action TEXT NOT NULL,
                    entry_date TEXT,
                    entry_price REAL,
                    ret_1 REAL,
                    net_ret_5 REAL,
                    max_gain_5 REAL,
                    max_drawdown_5 REAL,
                    entry_feasible INTEGER,
                    days_tracked INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pending',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(run_id, code),
                    FOREIGN KEY(run_id) REFERENCES decision_runs(run_id)
                )
            """)
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
                conn.execute("SELECT count(*) FROM decision_candidates").fetchone()[0],
                1,
            )
            self.assertEqual(
                conn.execute("SELECT count(*) FROM decision_outcomes").fetchone()[0], 1
            )
            migrated_outcome = conn.execute(
                "SELECT outcome_id, observation_no, source_snapshot_id "
                "FROM decision_outcomes"
            ).fetchone()
            self.assertEqual(len(migrated_outcome[0]), 64)
            self.assertEqual(migrated_outcome[1], 1)
            self.assertEqual(migrated_outcome[2], "legacy-unverified")
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            for table in ("decision_candidates", "decision_outcomes"):
                parents = {
                    row[2] for row in conn.execute(f"PRAGMA foreign_key_list({table})")
                }
                self.assertIn("decision_runs", parents)
        self.assertEqual(len(list_pending_outcome_candidates()), 1)
        self.assertEqual(outcome_summary()["observe"]["count"], 0)


if __name__ == "__main__":
    unittest.main()
