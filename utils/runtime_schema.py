"""生产运行时数据库迁移与只读校验边界。

只有显式迁移命令可以创建或修改表结构。Web 和 worker 启动时只用 SQLite
read-only URI 校验结构，结构缺失或版本不符时立即停止。
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path


RUNTIME_SCHEMA_VERSION = 6

DECISION_IMMUTABILITY_TRIGGERS = {
    "decision_runs_no_update",
    "decision_runs_no_delete",
    "decision_candidates_no_update",
    "decision_candidates_no_delete",
    "decision_outcomes_no_update",
    "decision_outcomes_no_delete",
    "evolution_runs_no_update",
    "evolution_runs_no_delete",
    "event_evidence_no_update",
    "event_evidence_no_delete",
    "ai_decision_runs_no_update",
    "ai_decision_runs_no_delete",
    "strategy_review_runs_no_update",
    "strategy_review_runs_no_delete",
    "factor_signal_runs_no_update",
    "factor_signal_runs_no_delete",
    "factor_run_stats_no_update",
    "factor_run_stats_no_delete",
    "factor_signals_no_update",
    "factor_signals_no_delete",
    "factor_outcome_observations_no_update",
    "factor_outcome_observations_no_delete",
    "model_registry_immutable_fields",
    "model_registry_status_transition",
    "model_registry_no_delete",
    "policy_registry_immutable_fields",
    "policy_registry_status_transition",
    "policy_registry_no_delete",
    "policy_evidence_artifacts_no_update",
    "policy_evidence_artifacts_no_delete",
    "policy_validation_records_no_update",
    "policy_validation_records_no_delete",
    "policy_release_events_no_update",
    "policy_release_events_no_delete",
    "quant_comment_runs_no_update",
    "quant_comment_runs_no_delete",
    *{
        f"{table}_{operation}"
        for table in (
            "paper_accounts",
            "paper_orders",
            "paper_fills",
            "paper_position_lots",
            "paper_lot_closures",
            "paper_cash_events",
            "paper_nav",
            "paper_reconciliations",
        )
        for operation in ("no_update", "no_delete")
    },
}

DECISION_SCHEMA: dict[str, set[str]] = {
    "runtime_schema_meta": {"component", "version", "updated_at"},
    "decision_runs": {
        "run_id",
        "trade_date",
        "stage",
        "as_of",
        "strategy_version",
        "feature_version",
        "model_version",
        "data_version",
    },
    "decision_candidates": {"run_id", "code", "action", "rank_no"},
    "decision_outcomes": {
        "outcome_id",
        "run_id",
        "code",
        "source_snapshot_id",
        "observation_no",
        "entry_feasible",
        "exit_feasible",
        "execution_status",
        "execution_policy_version",
    },
    "evolution_runs": {"evolution_id", "trade_date", "status", "data_version"},
    "event_evidence": {"evidence_id", "event_id", "code", "published_at"},
    "model_registry": {"model_key", "version", "status", "artifact_json"},
    "policy_registry": {"policy_version", "research_status"},
    "policy_evidence_artifacts": {
        "artifact_id",
        "policy_version",
        "artifact_type",
        "artifact_hash",
        "payload_json",
    },
    "policy_validation_records": {
        "validation_id",
        "policy_version",
        "evidence_hash",
        "status",
    },
    "policy_release_events": {"release_id", "policy_version", "action"},
    "ai_decision_runs": {"ai_run_id", "trade_date", "status", "input_hash"},
    "strategy_review_runs": {
        "review_id",
        "trade_date",
        "snapshot_id",
        "decision_run_id",
        "status",
        "model_version",
        "primary_horizon",
        "input_hash",
        "ai_status",
    },
    "factor_signal_runs": {
        "run_id",
        "trade_date",
        "snapshot_id",
        "strategy_version",
        "registry_version",
        "cache_key",
        "source_artifact_hash",
        "scanned_count",
        "factor_count",
        "status",
    },
    "factor_run_stats": {
        "run_id",
        "factor_key",
        "hit_count",
        "scanned_count",
        "error_count",
    },
    "factor_signals": {
        "signal_id",
        "run_id",
        "trade_date",
        "factor_key",
        "code",
        "payload_json",
    },
    "factor_outcome_observations": {
        "observation_id",
        "signal_id",
        "horizon_sessions",
        "observed_as_of",
        "pricing_snapshot_id",
        "execution_policy_version",
        "evidence_tier",
        "status",
        "content_hash",
    },
    "quant_comment_runs": {
        "comment_id",
        "trade_date",
        "decision_run_id",
        "payload_json",
    },
    "paper_accounts": {"account_id", "initial_cash", "rule_version"},
    "paper_orders": {"order_id", "account_id", "side", "earliest_trade_date"},
    "paper_fills": {
        "fill_id",
        "order_id",
        "trade_date",
        "snapshot_id",
        "execution_policy_version",
        "outcome",
    },
    "paper_position_lots": {"lot_id", "account_id", "quantity", "sellable_date"},
    "paper_lot_closures": {"closure_id", "lot_id", "sell_fill_id", "quantity"},
    "paper_cash_events": {"cash_event_id", "account_id", "amount"},
    "paper_nav": {
        "nav_id",
        "account_id",
        "trade_date",
        "snapshot_id",
        "execution_policy_version",
        "total_equity",
    },
    "paper_reconciliations": {
        "reconciliation_id",
        "account_id",
        "nav_id",
        "balanced",
    },
}

OPERATIONS_SCHEMA: dict[str, set[str]] = {
    "schema_meta": {"component", "version", "updated_at"},
    "tasks": {
        "task_id",
        "task_type",
        "idempotency_key",
        "status",
        "lease_owner",
        "lease_expires_at",
        "attempt_count",
        "max_attempts",
        "next_attempt_at",
    },
    "task_attempts": {
        "task_id",
        "attempt_no",
        "lease_owner",
        "status",
        "started_at",
        "finished_at",
        "error_code",
    },
    "job_runs": {
        "job_name",
        "trade_date",
        "snapshot_id",
        "policy_version",
        "task_id",
        "execution_token",
        "status",
    },
    "audit_events": {"audit_id", "occurred_at", "actor", "action", "outcome"},
    "alert_events": {
        "alert_id",
        "occurred_at",
        "severity",
        "alert_type",
        "source",
        "subject_id",
        "message",
        "details_json",
    },
    "rate_limits": {"bucket_key", "window_start", "hits"},
    "scheduler_leases": {"lease_name", "owner_id", "expires_at"},
    "request_nonces": {"principal_id", "nonce", "created_at", "expires_at"},
}

OPERATIONS_IMMUTABILITY_TRIGGERS = {
    "audit_events_no_update",
    "audit_events_no_delete",
    "alert_events_no_update",
    "alert_events_no_delete",
}


@contextmanager
def _read_only_connection(path: Path):
    if not path.is_file():
        raise RuntimeError(f"runtime_database_missing:{path.name}")
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=5000")
    try:
        yield connection
    finally:
        connection.close()


def _verify_tables(
    path: Path,
    required: dict[str, set[str]],
    *,
    component: str,
    required_triggers: set[str] | None = None,
) -> None:
    with _read_only_connection(path) as connection:
        quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
        if quick_check != "ok":
            raise RuntimeError(f"runtime_database_corrupt:{component}:{quick_check}")
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        missing_tables = sorted(set(required) - tables)
        if missing_tables:
            raise RuntimeError(
                f"runtime_schema_missing_tables:{component}:{','.join(missing_tables)}"
            )
        triggers = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            ).fetchall()
        }
        missing_triggers = sorted((required_triggers or set()) - triggers)
        if missing_triggers:
            raise RuntimeError(
                "runtime_schema_missing_triggers:"
                f"{component}:{','.join(missing_triggers)}"
            )
        for table, expected_columns in required.items():
            actual_columns = {
                row[1]
                for row in connection.execute(
                    f'SELECT * FROM pragma_table_info("{table}")'
                ).fetchall()
            }
            missing_columns = sorted(expected_columns - actual_columns)
            if missing_columns:
                raise RuntimeError(
                    "runtime_schema_missing_columns:"
                    f"{component}:{table}:{','.join(missing_columns)}"
                )
        foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchone()
        if foreign_key_errors is not None:
            raise RuntimeError(f"runtime_foreign_key_violation:{component}")


def migrate_runtime_schema() -> dict:
    """运行向前兼容的显式迁移，并创建默认模拟账户。"""
    from datetime import datetime, timezone

    from utils.decision_ledger import init_decision_ledger
    from utils.daily_pick import init_comments_table
    from utils.operations_store import init_operations_db
    from utils.paper_trading import ensure_default_account, init_paper_ledger
    from views import view_manager

    init_decision_ledger()
    init_paper_ledger()
    init_comments_table()
    ensure_default_account()
    with view_manager._get_migration_conn() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS runtime_schema_meta (
                component TEXT PRIMARY KEY,
                version INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for component in ("decision_ledger", "paper_ledger"):
            connection.execute(
                """
                INSERT INTO runtime_schema_meta(component, version, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(component) DO UPDATE SET
                    version=excluded.version,
                    updated_at=excluded.updated_at
                """,
                (component, RUNTIME_SCHEMA_VERSION, updated_at),
            )
    init_operations_db()
    return verify_runtime_schema()


def verify_runtime_schema() -> dict:
    """只读校验两个运行时数据库的完整性、表、列和版本。"""
    from utils.operations_store import SCHEMA_VERSION, _db_path
    from utils.paper_trading import DEFAULT_ACCOUNT_ID
    from views import view_manager

    decision_path = Path(view_manager.DB_PATH)
    operations_path = _db_path()
    _verify_tables(
        decision_path,
        DECISION_SCHEMA,
        component="decision",
        required_triggers=DECISION_IMMUTABILITY_TRIGGERS,
    )
    _verify_tables(
        operations_path,
        OPERATIONS_SCHEMA,
        component="operations",
        required_triggers=OPERATIONS_IMMUTABILITY_TRIGGERS,
    )

    with _read_only_connection(decision_path) as connection:
        versions = {
            row["component"]: int(row["version"])
            for row in connection.execute(
                "SELECT component, version FROM runtime_schema_meta"
            ).fetchall()
        }
        expected = {
            "decision_ledger": RUNTIME_SCHEMA_VERSION,
            "paper_ledger": RUNTIME_SCHEMA_VERSION,
        }
        if any(
            versions.get(component, -1) < version
            for component, version in expected.items()
        ):
            raise RuntimeError("runtime_schema_version_mismatch:decision")
        account = connection.execute(
            "SELECT 1 FROM paper_accounts WHERE account_id = ?",
            (DEFAULT_ACCOUNT_ID,),
        ).fetchone()
        deposit = connection.execute(
            "SELECT 1 FROM paper_cash_events "
            "WHERE cash_event_id = ? AND account_id = ?",
            (f"initial-{DEFAULT_ACCOUNT_ID}", DEFAULT_ACCOUNT_ID),
        ).fetchone()
        if account is None or deposit is None:
            raise RuntimeError("runtime_default_paper_account_missing")
        unverified_paper_evidence = connection.execute("""
            SELECT 1 FROM paper_fills
            WHERE snapshot_id IS NULL
               OR length(snapshot_id) != 64
               OR lower(snapshot_id) GLOB '*[^0-9a-f]*'
               OR execution_policy_version IS NULL
               OR execution_policy_version = ''
            UNION ALL
            SELECT 1 FROM paper_nav
            WHERE snapshot_id IS NULL
               OR length(snapshot_id) != 64
               OR lower(snapshot_id) GLOB '*[^0-9a-f]*'
               OR execution_policy_version IS NULL
               OR execution_policy_version = ''
            LIMIT 1
        """).fetchone()
        if unverified_paper_evidence is not None:
            raise RuntimeError("runtime_unverified_legacy_paper_evidence")

    with _read_only_connection(operations_path) as connection:
        row = connection.execute(
            "SELECT version FROM schema_meta WHERE component='operations'"
        ).fetchone()
        if row is None or int(row["version"]) < SCHEMA_VERSION:
            raise RuntimeError("runtime_schema_version_mismatch:operations")

    return {
        "verified": True,
        "decision_database": decision_path.name,
        "operations_database": operations_path.name,
        "runtime_schema_version": RUNTIME_SCHEMA_VERSION,
        "operations_schema_version": SCHEMA_VERSION,
    }
