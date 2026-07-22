import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import views.view_manager as view_manager
from utils.runtime_schema import migrate_runtime_schema, verify_runtime_schema
from web_server import _initialize_app_state
from worker import _initialize_worker_state


class RuntimeSchemaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_decision_path = view_manager.DB_PATH
        self.original_operations_path = os.environ.get("QUANT_OPERATIONS_DB")
        self.decision_path = Path(self.tmp.name) / "decision.db"
        self.operations_path = Path(self.tmp.name) / "operations.db"
        view_manager.DB_PATH = self.decision_path
        os.environ["QUANT_OPERATIONS_DB"] = str(self.operations_path)

    def tearDown(self):
        view_manager.DB_PATH = self.original_decision_path
        if self.original_operations_path is None:
            os.environ.pop("QUANT_OPERATIONS_DB", None)
        else:
            os.environ["QUANT_OPERATIONS_DB"] = self.original_operations_path
        self.tmp.cleanup()

    def test_verify_fails_closed_without_creating_database(self):
        with self.assertRaisesRegex(RuntimeError, "runtime_database_missing"):
            verify_runtime_schema()

        self.assertFalse(self.decision_path.exists())
        self.assertFalse(self.operations_path.exists())

    def test_explicit_migration_creates_and_verifies_complete_schema(self):
        result = migrate_runtime_schema()

        self.assertTrue(result["verified"])
        self.assertEqual(verify_runtime_schema(), result)

    def test_operations_migration_upgrades_pre_retry_task_schema(self):
        with sqlite3.connect(self.operations_path) as connection:
            connection.execute(
                """
                CREATE TABLE tasks (
                    task_id TEXT PRIMARY KEY,
                    task_type TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    result_json TEXT,
                    requested_by TEXT NOT NULL,
                    request_id TEXT,
                    requested_ip TEXT,
                    change_reason TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    heartbeat_at TEXT,
                    finished_at TEXT,
                    lease_owner TEXT,
                    lease_expires_at TEXT,
                    error_code TEXT,
                    UNIQUE(task_type, idempotency_key)
                )
                """
            )

        from utils.operations_store import init_operations_db

        init_operations_db()
        with sqlite3.connect(self.operations_path) as connection:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(tasks)")}
            attempts = connection.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='table' AND name='task_attempts'"
            ).fetchone()

        self.assertTrue(
            {"attempt_count", "max_attempts", "next_attempt_at"}.issubset(columns)
        )
        self.assertIsNotNone(attempts)

    def test_verify_rejects_incomplete_schema(self):
        migrate_runtime_schema()
        with sqlite3.connect(self.decision_path) as connection:
            connection.execute("DROP TABLE paper_reconciliations")

        with self.assertRaisesRegex(RuntimeError, "runtime_schema_missing_tables"):
            verify_runtime_schema()

    def test_verify_rejects_missing_immutability_trigger(self):
        migrate_runtime_schema()
        with sqlite3.connect(self.decision_path) as connection:
            connection.execute("DROP TRIGGER decision_runs_no_update")

        with self.assertRaisesRegex(RuntimeError, "runtime_schema_missing_triggers"):
            verify_runtime_schema()

    def test_verify_rejects_paper_evidence_without_immutable_snapshot(self):
        migrate_runtime_schema()
        with sqlite3.connect(self.decision_path) as connection:
            connection.execute(
                """
                INSERT INTO paper_nav
                  (nav_id, account_id, trade_date, snapshot_id,
                   execution_policy_version, as_of, cash, market_value,
                   total_equity, exposure, drawdown, turnover, benchmark_value,
                   pricing_status, created_at)
                VALUES ('unverified-nav', 'paper-main-v1', '2026-01-05',
                        'unpublished-test-data', 'a-share-eod-open-open-v3',
                        '2026-01-05T15:00:00+08:00', 1000000, 0, 1000000,
                        0, 0, 0, NULL, 'complete',
                        '2026-01-05T15:00:00+08:00')
                """
            )

        with self.assertRaisesRegex(
            RuntimeError, "runtime_unverified_legacy_paper_evidence"
        ):
            verify_runtime_schema()

    def test_web_and_worker_startup_only_call_read_only_verifier(self):
        with patch("utils.runtime_schema.verify_runtime_schema") as verify:
            _initialize_app_state()
            _initialize_worker_state()

        self.assertEqual(verify.call_count, 2)

    def test_business_writes_do_not_implicitly_create_databases(self):
        from utils.decision_ledger import save_decision_run
        from utils.operations_store import enqueue_task

        with self.assertRaises(FileNotFoundError):
            save_decision_run({}, [])
        with self.assertRaises(FileNotFoundError):
            enqueue_task(
                "daily_market_ingestion",
                "test-key",
                requested_by="test",
            )

        self.assertFalse(self.decision_path.exists())
        self.assertFalse(self.operations_path.exists())

    def test_predeploy_check_runs_as_documented_script_path(self):
        migrate_runtime_schema()
        project_root = Path(__file__).resolve().parents[1]
        environment = {
            **os.environ,
            "QUANT_STATE_DIR": self.tmp.name,
            "QUANT_VIEWS_DB": str(self.decision_path),
            "QUANT_OPERATIONS_DB": str(self.operations_path),
            "GIT_COMMIT_SHA": "a" * 40,
        }

        result = subprocess.run(
            [sys.executable, "tools/predeploy_check.py"],
            cwd=project_root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("predeploy check passed", result.stdout)

    def test_release_backs_up_then_migrates_then_verifies(self):
        project_root = Path(__file__).resolve().parents[1]
        workflow = (project_root / ".github/workflows/release.yml").read_text(
            encoding="utf-8"
        )
        commands = [
            "run --rm --no-deps web python tools/backup_databases.py",
            "run --rm --no-deps migrate",
            "run --rm --no-deps web python tools/predeploy_check.py",
        ]
        positions = [workflow.index(command) for command in commands]

        self.assertEqual(positions, sorted(positions))

    def test_release_verifies_runtime_identity_and_readiness_contract(self):
        project_root = Path(__file__).resolve().parents[1]
        workflow = (project_root / ".github/workflows/release.yml").read_text(
            encoding="utf-8"
        )

        for evidence in (
            'EXPECTED_IMAGE="${IMAGE}@${DIGEST}"',
            "{{.Config.Image}}",
            'version.get("git_commit_sha") == os.environ["EXPECTED_SHA"]',
            'version.get("snapshot_available") is True',
            'readiness.get("ready") is True',
            'scheduler.get("leader")',
            'read_json("/api/stats")',
            'stats_data.get("snapshot_id") == snapshot_id',
        ):
            self.assertIn(evidence, workflow)


if __name__ == "__main__":
    unittest.main()
