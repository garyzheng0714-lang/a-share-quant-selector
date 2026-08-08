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


def test_close_pipeline_claims_business_key_before_downstream_side_effects():
    events = []
    manager = MagicMock(snapshot_id="a" * 64)
    freshness = {
        "fresh": True,
        "local_date": "2026-07-15",
        "snapshot_id": "a" * 64,
    }

    def claim(*_args):
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
        patch.object(worker, "update_task_progress", return_value=True),
        patch.object(worker, "claim_job_run", side_effect=claim),
        patch.object(worker, "_run_daily_close_downstream", side_effect=downstream),
        patch.object(worker, "finish_job_run", side_effect=finish),
    ):
        result = worker._daily_close_pipeline({"task_id": "task-1"})

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
        result = worker._daily_close_pipeline({"task_id": "duplicate-task"})

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
        patch("utils.decision_ledger.get_latest_decision", return_value=None),
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
            }
        )

    assert result == materialized
    ingestion.assert_not_called()
    run_materialization.assert_called_once_with(manager, freshness)
    claim.assert_called_once_with(
        "snapshot_decision_materialization",
        "2026-07-15",
        snapshot_id,
        "policy-new",
        "repair-task",
    )
    finish.assert_called_once_with(
        "snapshot_decision_materialization",
        "2026-07-15",
        snapshot_id,
        "policy-new",
        "repair-task",
        succeeded=True,
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
        patch.object(worker, "claim_job_run") as claim,
        patch.object(worker, "_run_decision_materialization") as materialize,
    ):
        result = worker._materialize_snapshot_decision(
            {
                "task_id": "repair-task",
                "trade_date": "2026-07-15",
                "snapshot_id": "b" * 64,
                "strategy_version": "policy-new",
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
        patch.object(worker, "update_task_progress", return_value=True),
        patch.object(worker, "claim_job_run") as claim,
        patch.object(worker, "_run_daily_close_downstream") as downstream,
    ):
        result = worker._daily_close_pipeline(
            {"task_id": "task-1", "trade_date": "2026-07-15"}
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
