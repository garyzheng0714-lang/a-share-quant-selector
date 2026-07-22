import os
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from utils.operations_store import (
    TaskQueueCapacityExceeded,
    acquire_scheduler_lease,
    alert_summary,
    allow_rate,
    cancel_task,
    claim_job_run,
    claim_next_task,
    enqueue_task,
    finish_job_run,
    finish_task,
    get_task,
    init_operations_db,
    list_alerts,
    record_audit,
    release_scheduler_lease,
    scheduler_status,
)


class OperationsStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(
            os.environ,
            {"QUANT_OPERATIONS_DB": str(Path(self.tmp.name) / "operations.db")},
        )
        self.env.start()
        init_operations_db()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    @staticmethod
    def _enqueue(key="request-0001"):
        return enqueue_task(
            "daily_market_ingestion",
            key,
            payload={"value": 1},
            requested_by="admin:test",
            request_id="request-id",
            requested_ip="127.0.0.1",
            change_reason="test request",
        )

    def test_idempotency_survives_repeated_submission_and_restart(self):
        first, created = self._enqueue()
        second, repeated_created = self._enqueue()
        init_operations_db()
        persisted = get_task(first["task_id"])

        self.assertTrue(created)
        self.assertFalse(repeated_created)
        self.assertEqual(first["task_id"], second["task_id"])
        self.assertEqual(persisted["payload"], {"value": 1})

    def test_claim_and_finish_are_lease_owner_guarded(self):
        task, _ = self._enqueue()
        claimed = claim_next_task("worker-a", lease_seconds=60)
        self.assertEqual(claimed["task_id"], task["task_id"])
        self.assertFalse(finish_task(task["task_id"], "worker-b", result={"ok": True}))
        self.assertTrue(finish_task(task["task_id"], "worker-a", result={"ok": True}))
        completed = get_task(task["task_id"])
        self.assertEqual(completed["status"], "succeeded")
        self.assertEqual(completed["result"], {"ok": True})
        self.assertEqual(completed["attempt_count"], 1)
        self.assertEqual(completed["attempts"][0]["status"], "succeeded")

    def test_failed_attempt_is_persisted_and_retried_with_backoff(self):
        task, _ = enqueue_task(
            "daily_market_ingestion",
            "retryable-task",
            requested_by="test",
            max_attempts=3,
        )
        first = claim_next_task("worker-a")
        self.assertEqual(first["task_id"], task["task_id"])
        self.assertTrue(
            finish_task(
                task["task_id"],
                "worker-a",
                error_code="upstream_timeout",
                retry_delay_seconds=0,
            )
        )

        waiting = get_task(task["task_id"])
        self.assertEqual(waiting["status"], "queued")
        self.assertEqual(waiting["attempt_count"], 1)
        self.assertEqual(waiting["attempts"][0]["error_code"], "upstream_timeout")
        alerts = list_alerts()
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["severity"], "warning")
        self.assertEqual(alerts[0]["alert_type"], "task_attempt_failed")
        self.assertEqual(alerts[0]["subject_id"], task["task_id"])
        self.assertEqual(alerts[0]["details"]["error_code"], "upstream_timeout")

        second = claim_next_task("worker-b")
        self.assertEqual(second["attempt_count"], 2)
        self.assertTrue(finish_task(second["task_id"], "worker-b", result={"ok": True}))
        completed = get_task(task["task_id"])
        self.assertEqual(completed["status"], "succeeded")
        self.assertEqual(
            [attempt["status"] for attempt in completed["attempts"]],
            ["failed", "succeeded"],
        )

    def test_non_retryable_failure_stops_at_one_attempt(self):
        task, _ = enqueue_task(
            "invalid-task",
            "terminal-task",
            requested_by="test",
            max_attempts=3,
        )
        claim_next_task("worker-a")
        self.assertTrue(
            finish_task(
                task["task_id"],
                "worker-a",
                error_code="invalid_request",
                retryable=False,
            )
        )

        failed = get_task(task["task_id"])
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["attempt_count"], 1)
        self.assertIsNone(claim_next_task("worker-b"))
        alerts = list_alerts(severity="critical")
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["alert_type"], "task_terminal_failure")
        self.assertEqual(alert_summary()["critical"], 1)

        database = Path(os.environ["QUANT_OPERATIONS_DB"])
        with sqlite3.connect(database) as connection:
            with self.assertRaisesRegex(
                sqlite3.IntegrityError, "immutable_alert_event"
            ):
                connection.execute(
                    "UPDATE alert_events SET message='changed' WHERE alert_id=?",
                    (alerts[0]["alert_id"],),
                )
            with self.assertRaisesRegex(
                sqlite3.IntegrityError, "immutable_alert_event"
            ):
                connection.execute(
                    "DELETE FROM alert_events WHERE alert_id=?",
                    (alerts[0]["alert_id"],),
                )

    def test_expired_lease_records_failed_attempt_before_takeover(self):
        task, _ = enqueue_task(
            "daily_market_ingestion",
            "expired-lease-task",
            requested_by="test",
            max_attempts=2,
        )
        claim_next_task("worker-a", lease_seconds=-1)
        takeover = claim_next_task("worker-b")

        self.assertEqual(takeover["task_id"], task["task_id"])
        self.assertEqual(takeover["attempt_count"], 2)
        current = get_task(task["task_id"])
        self.assertEqual(current["attempts"][0]["status"], "failed")
        self.assertEqual(current["attempts"][0]["error_code"], "lease_expired")
        self.assertEqual(current["attempts"][1]["status"], "running")
        alerts = list_alerts()
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["details"]["error_code"], "lease_expired")

    def test_expired_final_lease_becomes_terminal_alert(self):
        task, _ = enqueue_task(
            "daily_market_ingestion",
            "expired-final-lease-task",
            requested_by="test",
            max_attempts=1,
        )
        claim_next_task("worker-a", lease_seconds=-1)

        self.assertIsNone(claim_next_task("worker-b"))
        failed = get_task(task["task_id"])
        alerts = list_alerts(severity="critical")
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["error_code"], "lease_expired")
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["alert_type"], "task_terminal_failure")

    def test_concurrent_duplicate_submission_creates_one_task(self):
        with ThreadPoolExecutor(max_workers=8) as executor:
            values = list(executor.map(lambda _: self._enqueue("same-key"), range(16)))
        self.assertEqual(sum(created for _task, created in values), 1)
        self.assertEqual(len({task["task_id"] for task, _created in values}), 1)

    def test_pending_queue_capacity_is_bounded_but_duplicate_is_idempotent(self):
        with patch.dict(os.environ, {"QUANT_MAX_PENDING_TASKS": "1"}):
            first, created = self._enqueue("capacity-first")
            duplicate, duplicate_created = self._enqueue("capacity-first")
            with self.assertRaises(TaskQueueCapacityExceeded):
                self._enqueue("capacity-second")

            self.assertEqual(duplicate["task_id"], first["task_id"])
            self.assertTrue(created)
            self.assertFalse(duplicate_created)

            claim_next_task("worker-a")
            finish_task(first["task_id"], "worker-a", result={"ok": True})
            second, second_created = self._enqueue("capacity-second")

        self.assertTrue(second_created)
        self.assertNotEqual(second["task_id"], first["task_id"])

    def test_only_queued_task_can_be_cancelled_safely(self):
        queued, _ = self._enqueue("cancel-queued")
        cancelled = cancel_task(
            queued["task_id"],
            requested_by="admin:test",
            change_reason="operator cancelled obsolete task",
        )
        repeated = cancel_task(
            queued["task_id"],
            requested_by="admin:test",
            change_reason="repeat cancellation",
        )

        self.assertTrue(cancelled["cancelled"])
        self.assertEqual(cancelled["task"]["status"], "cancelled")
        self.assertFalse(repeated["cancelled"])
        self.assertEqual(repeated["reason"], "task_not_queued")
        self.assertIsNone(claim_next_task("worker-a"))

        running, _ = self._enqueue("cancel-running")
        claim_next_task("worker-a")
        blocked = cancel_task(
            running["task_id"],
            requested_by="admin:test",
            change_reason="unsafe running cancellation",
        )
        self.assertFalse(blocked["cancelled"])
        self.assertEqual(blocked["task"]["status"], "running")

    def test_rate_limit_is_atomic(self):
        self.assertTrue(allow_rate("actor:path", limit=2))
        self.assertTrue(allow_rate("actor:path", limit=2))
        self.assertFalse(allow_rate("actor:path", limit=2))

    def test_scheduler_lease_has_one_live_owner(self):
        self.assertTrue(
            acquire_scheduler_lease("scheduler", "worker-a", lease_seconds=60)
        )
        self.assertFalse(
            acquire_scheduler_lease("scheduler", "worker-b", lease_seconds=60)
        )
        status = scheduler_status("scheduler")
        self.assertTrue(status["running"])
        self.assertEqual(status["leader"], "worker-a")

        self.assertFalse(release_scheduler_lease("scheduler", "worker-b"))
        self.assertTrue(scheduler_status("scheduler")["running"])
        self.assertTrue(release_scheduler_lease("scheduler", "worker-a"))
        self.assertFalse(scheduler_status("scheduler")["running"])

    def test_business_job_key_blocks_duplicate_side_effects(self):
        first, _ = enqueue_task(
            "daily_close_pipeline", "manual-close-1", requested_by="test"
        )
        second, _ = enqueue_task(
            "daily_close_pipeline", "manual-close-2", requested_by="test"
        )
        claimed = claim_next_task("worker-a", lease_seconds=60)
        self.assertEqual(claimed["task_id"], first["task_id"])

        business = claim_job_run(
            "daily_close_pipeline",
            "2026-07-15",
            "a" * 64,
            "policy-1",
            first["task_id"],
        )
        blocked = claim_job_run(
            "daily_close_pipeline",
            "2026-07-15",
            "a" * 64,
            "policy-1",
            second["task_id"],
        )
        self.assertTrue(business["claimed"])
        self.assertEqual(blocked["status"], "running")

        self.assertTrue(
            finish_job_run(
                "daily_close_pipeline",
                "2026-07-15",
                "a" * 64,
                "policy-1",
                first["task_id"],
                succeeded=True,
            )
        )
        replay = claim_job_run(
            "daily_close_pipeline",
            "2026-07-15",
            "a" * 64,
            "policy-1",
            second["task_id"],
        )
        self.assertFalse(replay["claimed"])
        self.assertEqual(replay["status"], "succeeded")

    def test_failed_business_job_can_be_resumed_by_next_task(self):
        first, _ = enqueue_task(
            "daily_close_pipeline", "retry-close-1", requested_by="test"
        )
        second, _ = enqueue_task(
            "daily_close_pipeline", "retry-close-2", requested_by="test"
        )
        claim_job_run(
            "daily_close_pipeline",
            "2026-07-15",
            "b" * 64,
            "policy-1",
            first["task_id"],
        )
        finish_job_run(
            "daily_close_pipeline",
            "2026-07-15",
            "b" * 64,
            "policy-1",
            first["task_id"],
            succeeded=False,
        )

        resumed = claim_job_run(
            "daily_close_pipeline",
            "2026-07-15",
            "b" * 64,
            "policy-1",
            second["task_id"],
        )

        self.assertTrue(resumed["claimed"])
        self.assertTrue(resumed["resumed"])

    def test_sqlite_lock_fails_explicitly_without_ephemeral_fallback(self):
        path = Path(os.environ["QUANT_OPERATIONS_DB"])
        blocker = sqlite3.connect(path)
        blocker.execute("BEGIN EXCLUSIVE")
        try:
            with patch.dict(os.environ, {"QUANT_SQLITE_BUSY_TIMEOUT_MS": "10"}):
                with self.assertRaises(sqlite3.OperationalError):
                    self._enqueue("locked-request")
        finally:
            blocker.rollback()
            blocker.close()

        self.assertIsNone(get_task("does-not-exist"))

    def test_security_audit_events_are_database_immutable(self):
        record_audit(actor="admin:test", action="update", outcome="accepted")
        path = Path(os.environ["QUANT_OPERATIONS_DB"])
        with sqlite3.connect(path) as connection:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
                connection.execute(
                    "UPDATE audit_events SET outcome='tampered' WHERE audit_id=1"
                )
            with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
                connection.execute("DELETE FROM audit_events WHERE audit_id=1")

    def test_worker_treats_transient_sqlite_lock_as_retryable(self):
        import worker

        with patch.object(
            worker,
            "_process_one",
            side_effect=sqlite3.OperationalError("database is locked"),
        ):
            self.assertFalse(worker.process_one())

    def test_scheduler_takeover_reconciles_missed_close_once(self):
        import worker

        acquire_scheduler_lease(
            "production-scheduler", "stopped-worker", lease_seconds=-1
        )
        current = datetime(2026, 7, 15, 16, 20, tzinfo=ZoneInfo("Asia/Shanghai"))
        with patch(
            "utils.data_freshness.expected_completed_trade_date",
            return_value="2026-07-15",
        ):
            first = worker.reconcile_scheduled_tasks(current)
            repeated = worker.reconcile_scheduled_tasks(current)

        self.assertTrue(first["leader"])
        self.assertTrue(first["close"]["created"])
        self.assertFalse(repeated["close"]["created"])
        task = get_task(first["close"]["task_id"])
        self.assertEqual(task["task_type"], "daily_close_pipeline")
        self.assertEqual(task["payload"], {"trade_date": "2026-07-15"})

    def test_scheduler_materializes_decision_for_replaced_current_snapshot(self):
        import worker

        current = datetime(2026, 7, 16, 8, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
        snapshot_id = "b" * 64
        freshness = {
            "fresh": True,
            "local_date": "2026-07-15",
            "expected_date": "2026-07-15",
            "snapshot_id": snapshot_id,
        }
        old_decision = {
            "trade_date": "2026-07-15",
            "strategy_version": "policy-old",
            "data_version": f"snapshot-{'a' * 64}",
            "market": {"snapshot_id": "a" * 64},
        }
        with (
            patch(
                "utils.data_freshness.expected_completed_trade_date",
                return_value="2026-07-15",
            ),
            patch("utils.data_freshness.local_data_status", return_value=freshness),
            patch(
                "utils.decision_versions.strategy_version", return_value="policy-new"
            ),
            patch(
                "utils.decision_ledger.get_latest_decision", return_value=old_decision
            ),
        ):
            first = worker.reconcile_scheduled_tasks(current)
            repeated = worker.reconcile_scheduled_tasks(current)

        self.assertTrue(first["decision"]["eligible"])
        self.assertTrue(first["decision"]["created"])
        self.assertFalse(repeated["decision"]["created"])
        task = get_task(first["decision"]["task_id"])
        self.assertEqual(task["task_type"], "materialize_snapshot_decision")
        self.assertEqual(
            task["payload"],
            {
                "trade_date": "2026-07-15",
                "snapshot_id": snapshot_id,
                "strategy_version": "policy-new",
            },
        )

    def test_morning_reconciliation_catches_previous_close_before_preopen(self):
        import worker

        current = datetime(2026, 7, 16, 8, 50, tzinfo=ZoneInfo("Asia/Shanghai"))
        with (
            patch(
                "utils.data_freshness.expected_completed_trade_date",
                return_value="2026-07-15",
            ),
            patch("utils.data_freshness.next_trade_date", return_value="2026-07-16"),
        ):
            result = worker.reconcile_scheduled_tasks(current)

        self.assertTrue(result["close"]["created"])
        self.assertTrue(result["preopen"]["created"])
        first = claim_next_task("test-worker")
        self.assertEqual(first["task_type"], "daily_close_pipeline")

    def test_preopen_window_and_exchange_calendar_fail_closed(self):
        import worker

        after_window = datetime(2026, 7, 16, 9, 26, tzinfo=ZoneInfo("Asia/Shanghai"))
        with (
            patch(
                "utils.data_freshness.expected_completed_trade_date",
                return_value="2026-07-15",
            ),
            patch("utils.data_freshness.next_trade_date", return_value="2026-07-16"),
        ):
            late = worker.reconcile_scheduled_tasks(after_window)

        holiday = datetime(2026, 7, 18, 8, 50, tzinfo=ZoneInfo("Asia/Shanghai"))
        with (
            patch(
                "utils.data_freshness.expected_completed_trade_date",
                return_value="2026-07-17",
            ),
            patch("utils.data_freshness.next_trade_date", return_value="2026-07-20"),
        ):
            closed = worker.reconcile_scheduled_tasks(holiday)

        self.assertFalse(late["preopen"]["eligible"])
        self.assertFalse(closed["preopen"]["eligible"])


if __name__ == "__main__":
    unittest.main()
