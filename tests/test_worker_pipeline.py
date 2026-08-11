import threading
from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import worker


def test_worker_releases_its_scheduler_lease_on_graceful_stop():
    stopped = MagicMock()
    stopped.is_set.return_value = True
    with (
        patch.object(worker, "STOP", stopped),
        patch.object(worker, "_initialize_worker_state"),
        patch.object(worker, "release_scheduler_lease") as release,
    ):
        worker.run_worker()

    release.assert_called_once_with("production-scheduler", worker.OWNER_ID)


def test_scheduler_loop_survives_lease_takeover_without_claiming_leadership():
    stopped = MagicMock()
    stopped.is_set.side_effect = [False, True]
    leader = threading.Event()
    leader.set()
    with (
        patch.object(
            worker,
            "reconcile_scheduled_tasks",
            side_effect=RuntimeError("scheduler_lease_not_current"),
        ),
    ):
        worker._scheduler_loop(stopped, leader)

    assert not leader.is_set()
    stopped.wait.assert_called_once_with(worker.SCHEDULER_RECONCILE_INTERVAL_SECONDS)


def test_scheduler_capacity_error_keeps_leader_available_to_drain_queue():
    stopped = MagicMock()
    stopped.is_set.side_effect = [False, True]
    leader = threading.Event()
    with patch.object(
        worker,
        "reconcile_scheduled_tasks",
        side_effect=worker.TaskQueueCapacityExceeded(100, 100),
    ):
        worker._scheduler_loop(stopped, leader)

    assert leader.is_set()
    stopped.wait.assert_called_once_with(worker.SCHEDULER_RECONCILE_INTERVAL_SECONDS)


def test_nonleader_worker_does_not_claim_tasks():
    stopped = threading.Event()

    def reconcile():
        stopped.set()
        return {"leader": False}

    with (
        patch.object(worker, "STOP", stopped),
        patch.object(worker, "_initialize_worker_state"),
        patch.object(worker, "reconcile_scheduled_tasks", side_effect=reconcile),
        patch.object(worker, "process_one") as process,
        patch.object(worker, "release_scheduler_lease"),
    ):
        worker.run_worker()

    process.assert_not_called()


def test_long_task_does_not_block_scheduler_reconciliation():
    stopped = threading.Event()
    process_started = threading.Event()
    reconciled_during_task = threading.Event()
    reconciliations = 0

    def reconcile():
        nonlocal reconciliations
        reconciliations += 1
        if process_started.is_set():
            reconciled_during_task.set()
        return {"leader": True}

    def process_one():
        process_started.set()
        assert reconciled_during_task.wait(timeout=1)
        stopped.set()
        return True

    with (
        patch.object(worker, "STOP", stopped),
        patch.object(worker, "_initialize_worker_state"),
        patch.object(worker, "reconcile_scheduled_tasks", side_effect=reconcile),
        patch.object(worker, "process_one", side_effect=process_one),
        patch.object(worker, "SCHEDULER_RECONCILE_INTERVAL_SECONDS", 0.01),
        patch.object(worker, "release_scheduler_lease"),
    ):
        worker.run_worker()

    assert reconciliations >= 2
    assert reconciled_during_task.is_set()


def test_close_scheduler_routes_fixed_key_through_recoverable_generation_enqueue():
    current = datetime(2026, 7, 15, 16, 20, tzinfo=ZoneInfo("Asia/Shanghai"))
    with (
        patch(
            "utils.data_freshness.expected_completed_trade_date",
            return_value="2026-07-15",
        ),
        patch.object(
            worker,
            "enqueue_scheduled_task",
            return_value=({"task_id": "generation-task"}, True),
        ) as enqueue,
    ):
        result = worker._enqueue_completed_close(current)

    assert result["created"] is True
    enqueue.assert_called_once_with(
        "daily_close_pipeline",
        "scheduled-close:2026-07-15",
        payload={"trade_date": "2026-07-15"},
        scheduler_owner=worker.OWNER_ID,
        requested_by=f"scheduler:{worker.OWNER_ID}",
        change_reason="scheduled close pipeline",
        max_attempts=32,
        recovery_cooldown_seconds=worker.SCHEDULER_RECOVERY_COOLDOWN_SECONDS,
    )


def test_close_pipeline_claims_business_key_before_downstream_side_effects():
    events = []
    manager = MagicMock(snapshot_id="a" * 64)
    freshness = {
        "fresh": True,
        "local_date": "2026-07-15",
        "snapshot_id": "a" * 64,
    }

    def claim(*_args, **_kwargs):
        events.append("claim")
        return {"claimed": True, "status": "running"}

    def downstream(*_args, **_kwargs):
        events.append("downstream")
        return {"success": True, "stage": "complete"}

    def finish(*_args, **_kwargs):
        events.append("finish")
        return True

    with (
        patch.object(worker, "_daily_ingestion", return_value={"success": True}),
        patch("utils.csv_manager.CSVManager", return_value=manager),
        patch("utils.data_freshness.local_data_status", return_value=freshness),
        patch("utils.decision_versions.strategy_version", return_value="policy-1"),
        patch.object(worker, "_require_execution_lease"),
        patch.object(worker, "update_task_progress", return_value=True),
        patch.object(worker, "claim_job_run", side_effect=claim),
        patch.object(worker, "_run_daily_close_downstream", side_effect=downstream),
        patch.object(worker, "finish_job_run", side_effect=finish),
    ):
        result = worker._daily_close_pipeline(
            {"task_id": "task-1", "execution_token": "token-1"}
        )

    assert result["success"] is True
    assert events == ["claim", "downstream", "finish"]


def test_close_pipeline_replays_completed_business_key_without_side_effects():
    manager = MagicMock(snapshot_id="a" * 64)
    freshness = {
        "fresh": True,
        "local_date": "2026-07-15",
        "snapshot_id": "a" * 64,
    }
    with (
        patch.object(worker, "_daily_ingestion", return_value={"success": True}),
        patch("utils.csv_manager.CSVManager", return_value=manager),
        patch("utils.data_freshness.local_data_status", return_value=freshness),
        patch("utils.decision_versions.strategy_version", return_value="policy-1"),
        patch.object(worker, "_require_execution_lease"),
        patch.object(worker, "update_task_progress", return_value=True),
        patch.object(
            worker,
            "claim_job_run",
            return_value={
                "claimed": False,
                "status": "succeeded",
                "task_id": "original-task",
            },
        ),
        patch.object(worker, "_run_daily_close_downstream") as downstream,
    ):
        result = worker._daily_close_pipeline(
            {"task_id": "duplicate-task", "execution_token": "token-2"}
        )

    assert result["success"] is True
    assert result["stage"] == "idempotent_replay"
    downstream.assert_not_called()


def test_snapshot_materialization_repairs_missing_current_decision_without_ingestion():
    snapshot_id = "b" * 64
    manager = MagicMock(snapshot_id=snapshot_id)
    freshness = {
        "fresh": True,
        "local_date": "2026-07-15",
        "expected_date": "2026-07-15",
        "snapshot_id": snapshot_id,
    }
    materialized = {
        "success": True,
        "stage": "complete",
        "decision": {"available": True, "run_id": "run-current"},
    }
    with (
        patch("utils.csv_manager.CSVManager", return_value=manager),
        patch("utils.data_freshness.local_data_status", return_value=freshness),
        patch("utils.decision_versions.strategy_version", return_value="policy-new"),
        patch(
            "utils.daily_strategy_review.review_pipeline_version",
            return_value="review-new",
        ),
        patch(
            "utils.self_evolution.evolution_pipeline_version",
            return_value="evolution-new",
        ),
        patch.object(worker, "_learning_pipeline_version", return_value="learning-new"),
        patch.object(worker, "_require_execution_lease"),
        patch("utils.decision_ledger.get_latest_decision", return_value=None),
        patch(
            "utils.factor_evidence.refresh_factor_outcomes",
            return_value={"available": True},
        ),
        patch(
            "utils.daily_strategy_review.materialize_daily_strategy_review",
            return_value={"available": True},
        ),
        patch.object(
            worker,
            "_run_evolution_once",
            return_value={"available": True, "status": "complete"},
        ),
        patch.object(
            worker,
            "claim_job_run",
            return_value={"claimed": True, "status": "running"},
        ) as claim,
        patch.object(
            worker, "_run_decision_materialization", return_value=materialized
        ) as run_materialization,
        patch.object(worker, "finish_job_run") as finish,
        patch.object(worker, "_daily_ingestion") as ingestion,
    ):
        result = worker._materialize_snapshot_decision(
            {
                "task_id": "repair-task",
                "trade_date": "2026-07-15",
                "snapshot_id": snapshot_id,
                "strategy_version": "policy-new",
                "review_version": "review-new",
                "evolution_version": "evolution-new",
                "learning_version": "learning-new",
                "execution_token": "repair-token",
            }
        )

    assert result == materialized
    ingestion.assert_not_called()
    run_materialization.assert_called_once_with(
        manager,
        freshness,
        execution_context={
            "task_id": "repair-task",
            "trade_date": "2026-07-15",
            "snapshot_id": snapshot_id,
            "strategy_version": "policy-new",
            "review_version": "review-new",
            "evolution_version": "evolution-new",
            "learning_version": "learning-new",
            "execution_token": "repair-token",
        },
    )
    claim.assert_called_once_with(
        "snapshot_decision_materialization",
        "2026-07-15",
        snapshot_id,
        "learning-new",
        "repair-task",
        execution_token="repair-token",
    )
    finish.assert_called_once_with(
        "snapshot_decision_materialization",
        "2026-07-15",
        snapshot_id,
        "learning-new",
        "repair-task",
        succeeded=True,
        execution_token="repair-token",
    )


def test_snapshot_materialization_rejects_pointer_change_before_side_effects():
    manager = MagicMock(snapshot_id="c" * 64)
    freshness = {
        "fresh": True,
        "local_date": "2026-07-15",
        "expected_date": "2026-07-15",
        "snapshot_id": "c" * 64,
    }
    with (
        patch("utils.csv_manager.CSVManager", return_value=manager),
        patch("utils.data_freshness.local_data_status", return_value=freshness),
        patch("utils.decision_versions.strategy_version", return_value="policy-new"),
        patch(
            "utils.daily_strategy_review.review_pipeline_version",
            return_value="review-new",
        ),
        patch(
            "utils.self_evolution.evolution_pipeline_version",
            return_value="evolution-new",
        ),
        patch.object(worker, "_learning_pipeline_version", return_value="learning-new"),
        patch.object(worker, "_require_execution_lease"),
        patch.object(worker, "claim_job_run") as claim,
        patch.object(worker, "_run_decision_materialization") as materialize,
    ):
        result = worker._materialize_snapshot_decision(
            {
                "task_id": "repair-task",
                "trade_date": "2026-07-15",
                "snapshot_id": "b" * 64,
                "strategy_version": "policy-new",
                "review_version": "review-new",
                "evolution_version": "evolution-new",
                "learning_version": "learning-new",
                "execution_token": "repair-token",
            }
        )

    assert result["success"] is True
    assert result["stage"] == "superseded_snapshot_target"
    claim.assert_not_called()
    materialize.assert_not_called()


def test_scheduled_close_never_runs_against_a_different_trade_date():
    manager = MagicMock(snapshot_id="a" * 64)
    freshness = {
        "fresh": True,
        "local_date": "2026-07-16",
        "snapshot_id": "a" * 64,
    }
    with (
        patch(
            "utils.data_freshness.expected_completed_trade_date",
            return_value="2026-07-16",
        ),
        patch.object(
            worker, "_daily_ingestion", return_value={"success": True}
        ) as ingestion,
        patch("utils.csv_manager.CSVManager", return_value=manager),
        patch("utils.data_freshness.local_data_status", return_value=freshness),
        patch.object(worker, "_require_execution_lease"),
        patch.object(worker, "update_task_progress", return_value=True),
        patch.object(worker, "claim_job_run") as claim,
        patch.object(worker, "_run_daily_close_downstream") as downstream,
    ):
        result = worker._daily_close_pipeline(
            {
                "task_id": "task-1",
                "trade_date": "2026-07-15",
                "execution_token": "token-1",
            }
        )

    assert result["success"] is False
    assert result["stage"] == "scheduled_trade_date_mismatch"
    ingestion.assert_not_called()
    claim.assert_not_called()
    downstream.assert_not_called()


def test_preopen_worker_refuses_late_or_backdated_execution():
    late = datetime(2026, 7, 16, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    with (
        patch.object(worker, "_shanghai_time", return_value=late),
        patch(
            "utils.hierarchical_decision.run_preopen_decision"
        ) as run_preopen_decision,
    ):
        late_result = worker._preopen_decision({"trade_date": "2026-07-16"})
        stale_result = worker._preopen_decision({"trade_date": "2026-07-15"})

    assert late_result["reason"] == "outside_preopen_execution_window"
    assert stale_result["reason"] == "scheduled_trade_date_mismatch"
    run_preopen_decision.assert_not_called()
