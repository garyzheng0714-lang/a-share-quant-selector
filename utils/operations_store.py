"""持久任务、幂等键、调度租约与管理操作审计。"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from utils.runtime_paths import operations_db_path


SCHEMA_VERSION = 6
ALERT_SEVERITIES = {"warning", "critical"}


class TaskQueueCapacityExceeded(RuntimeError):
    def __init__(self, pending: int, limit: int):
        super().__init__("task_queue_capacity_exceeded")
        self.pending = int(pending)
        self.limit = int(limit)


def _db_path() -> Path:
    return operations_db_path()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _insert_alert_event(
    conn: sqlite3.Connection,
    *,
    severity: str,
    alert_type: str,
    source: str,
    subject_id: str | None,
    message: str,
    details: dict | None,
    dedup_key: str,
) -> str:
    """在调用方事务内追加可去重、不可修改的运行告警事件。"""
    if severity not in ALERT_SEVERITIES:
        raise ValueError("invalid_alert_severity")
    identity = json.dumps(
        {
            "alert_type": alert_type,
            "dedup_key": dedup_key,
            "source": source,
            "subject_id": subject_id,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    alert_id = hashlib.sha256(identity.encode()).hexdigest()
    conn.execute(
        """INSERT OR IGNORE INTO alert_events(
               alert_id, occurred_at, severity, alert_type, source, subject_id,
               message, details_json
           ) VALUES(?,?,?,?,?,?,?,?)""",
        (
            alert_id,
            _now(),
            severity,
            str(alert_type)[:128],
            str(source)[:128],
            str(subject_id)[:256] if subject_id else None,
            str(message)[:512],
            json.dumps(
                details or {},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ),
        ),
    )
    return alert_id


def _busy_timeout_ms() -> int:
    try:
        value = int(os.environ.get("QUANT_SQLITE_BUSY_TIMEOUT_MS", "10000"))
    except ValueError:
        value = 10000
    return min(max(value, 10), 60000)


def _max_pending_tasks() -> int:
    try:
        value = int(os.environ.get("QUANT_MAX_PENDING_TASKS", "1000"))
    except ValueError:
        value = 1000
    return min(max(value, 1), 100_000)


@contextmanager
def _migration_connection():
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    timeout_ms = _busy_timeout_ms()
    conn = sqlite3.connect(str(path), timeout=timeout_ms / 1000)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(f"PRAGMA busy_timeout={timeout_ms}")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def _connection(*, immediate: bool = False):
    path = _db_path()
    if not path.is_file():
        raise FileNotFoundError(f"operations_database_not_initialized:{path}")
    timeout_ms = _busy_timeout_ms()
    conn = sqlite3.connect(str(path), timeout=timeout_ms / 1000)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(f"PRAGMA busy_timeout={timeout_ms}")
    try:
        if immediate:
            conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def _read_connection():
    """查询路径禁止 mkdir、migration、journal 切换与 commit。"""
    path = _db_path()
    if not path.is_file():
        raise FileNotFoundError(f"operations_database_not_initialized:{path}")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
    finally:
        conn.close()


def init_operations_db() -> None:
    with _migration_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_meta (
                component TEXT PRIMARY KEY,
                version INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                task_type TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN
                    ('queued','running','succeeded','failed','cancelled')),
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
                attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
                max_attempts INTEGER NOT NULL DEFAULT 3 CHECK(max_attempts >= 1),
                next_attempt_at TEXT,
                UNIQUE(task_type, idempotency_key)
            );
            CREATE INDEX IF NOT EXISTS idx_tasks_claim
                ON tasks(status, created_at);
            CREATE TABLE IF NOT EXISTS task_attempts (
                task_id TEXT NOT NULL REFERENCES tasks(task_id),
                attempt_no INTEGER NOT NULL,
                lease_owner TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('running','succeeded','failed')),
                started_at TEXT NOT NULL,
                finished_at TEXT,
                error_code TEXT,
                result_json TEXT,
                PRIMARY KEY(task_id, attempt_no)
            );
            CREATE TABLE IF NOT EXISTS job_runs (
                job_name TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                snapshot_id TEXT NOT NULL,
                policy_version TEXT NOT NULL,
                task_id TEXT NOT NULL REFERENCES tasks(task_id),
                status TEXT NOT NULL CHECK(status IN ('running','succeeded','failed')),
                started_at TEXT NOT NULL,
                finished_at TEXT,
                created_at TEXT NOT NULL,
                PRIMARY KEY(job_name, trade_date, snapshot_id, policy_version)
            );
            CREATE TABLE IF NOT EXISTS audit_events (
                audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                occurred_at TEXT NOT NULL,
                request_id TEXT,
                actor TEXT NOT NULL,
                role TEXT,
                source_ip TEXT,
                method TEXT,
                path TEXT,
                action TEXT NOT NULL,
                outcome TEXT NOT NULL,
                change_reason TEXT,
                metadata_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_events(occurred_at);
            CREATE TABLE IF NOT EXISTS alert_events (
                alert_id TEXT PRIMARY KEY,
                occurred_at TEXT NOT NULL,
                severity TEXT NOT NULL
                    CHECK(severity IN ('warning','critical')),
                alert_type TEXT NOT NULL,
                source TEXT NOT NULL,
                subject_id TEXT,
                message TEXT NOT NULL,
                details_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_alert_events_time
                ON alert_events(occurred_at DESC);
            CREATE INDEX IF NOT EXISTS idx_alert_events_severity_time
                ON alert_events(severity, occurred_at DESC);
            CREATE TABLE IF NOT EXISTS rate_limits (
                bucket_key TEXT NOT NULL,
                window_start TEXT NOT NULL,
                hits INTEGER NOT NULL,
                PRIMARY KEY(bucket_key, window_start)
            );
            CREATE TABLE IF NOT EXISTS scheduler_leases (
                lease_name TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL,
                heartbeat_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS request_nonces (
                principal_id TEXT NOT NULL,
                nonce TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                PRIMARY KEY(principal_id, nonce)
            );
            CREATE INDEX IF NOT EXISTS idx_request_nonces_expiry
                ON request_nonces(expires_at);
            CREATE TRIGGER IF NOT EXISTS audit_events_no_update
            BEFORE UPDATE ON audit_events
            BEGIN
                SELECT RAISE(ABORT, 'immutable_audit_event');
            END;
            CREATE TRIGGER IF NOT EXISTS audit_events_no_delete
            BEFORE DELETE ON audit_events
            BEGIN
                SELECT RAISE(ABORT, 'immutable_audit_event');
            END;
            CREATE TRIGGER IF NOT EXISTS alert_events_no_update
            BEFORE UPDATE ON alert_events
            BEGIN
                SELECT RAISE(ABORT, 'immutable_alert_event');
            END;
            CREATE TRIGGER IF NOT EXISTS alert_events_no_delete
            BEFORE DELETE ON alert_events
            BEGIN
                SELECT RAISE(ABORT, 'immutable_alert_event');
            END;
            """
        )
        job_run_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(job_runs)").fetchall()
        }
        if "status" not in job_run_columns:
            conn.execute(
                "ALTER TABLE job_runs ADD COLUMN status TEXT NOT NULL "
                "DEFAULT 'succeeded' CHECK(status IN ('running','succeeded','failed'))"
            )
        if "started_at" not in job_run_columns:
            conn.execute("ALTER TABLE job_runs ADD COLUMN started_at TEXT")
            conn.execute("UPDATE job_runs SET started_at=created_at")
        if "finished_at" not in job_run_columns:
            conn.execute("ALTER TABLE job_runs ADD COLUMN finished_at TEXT")
            conn.execute("UPDATE job_runs SET finished_at=created_at")
        task_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()
        }
        if "attempt_count" not in task_columns:
            conn.execute(
                "ALTER TABLE tasks ADD COLUMN attempt_count INTEGER NOT NULL "
                "DEFAULT 0 CHECK(attempt_count >= 0)"
            )
        if "max_attempts" not in task_columns:
            conn.execute(
                "ALTER TABLE tasks ADD COLUMN max_attempts INTEGER NOT NULL "
                "DEFAULT 3 CHECK(max_attempts >= 1)"
            )
        if "next_attempt_at" not in task_columns:
            conn.execute("ALTER TABLE tasks ADD COLUMN next_attempt_at TEXT")
        conn.execute("DROP INDEX IF EXISTS idx_tasks_claim")
        conn.execute(
            "CREATE INDEX idx_tasks_claim ON tasks(status, next_attempt_at, created_at)"
        )
        conn.execute(
            """INSERT INTO schema_meta(component, version, updated_at)
               VALUES('operations', ?, ?)
               ON CONFLICT(component) DO UPDATE SET
                 version=excluded.version, updated_at=excluded.updated_at""",
            (SCHEMA_VERSION, _now()),
        )


def enqueue_task(
    task_type: str,
    idempotency_key: str,
    *,
    payload: dict | None = None,
    requested_by: str,
    request_id: str | None = None,
    requested_ip: str | None = None,
    change_reason: str | None = None,
    max_attempts: int = 3,
) -> tuple[dict, bool]:
    if not task_type or not idempotency_key:
        raise ValueError("task_type_and_idempotency_key_required")
    if not 1 <= int(max_attempts) <= 100:
        raise ValueError("max_attempts_out_of_range")
    canonical = f"{task_type}\0{idempotency_key}".encode()
    task_id = hashlib.sha256(canonical).hexdigest()[:32]
    created_at = _now()
    body = json.dumps(
        payload or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    capacity_error: TaskQueueCapacityExceeded | None = None
    row = None
    with _connection(immediate=True) as conn:
        existing = conn.execute(
            "SELECT * FROM tasks WHERE task_id=?", (task_id,)
        ).fetchone()
        if existing is not None:
            return _task_dict(existing), False
        pending = int(
            conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE status IN ('queued','running')"
            ).fetchone()[0]
        )
        limit = _max_pending_tasks()
        if pending >= limit:
            _insert_alert_event(
                conn,
                severity="critical",
                alert_type="task_queue_capacity_exceeded",
                source="task_queue",
                subject_id=task_id,
                message="持久任务队列已达到容量上限",
                details={
                    "limit": limit,
                    "pending": pending,
                    "task_type": task_type,
                },
                dedup_key=f"{task_id}:{pending}:{limit}",
            )
            capacity_error = TaskQueueCapacityExceeded(pending, limit)
        else:
            conn.execute(
                """INSERT INTO tasks(
                       task_id, task_type, idempotency_key, status, payload_json,
                       requested_by, request_id, requested_ip, change_reason,
                       created_at, max_attempts
                   ) VALUES(?,?,?,'queued',?,?,?,?,?,?,?)""",
                (
                    task_id,
                    task_type,
                    idempotency_key,
                    body,
                    requested_by,
                    request_id,
                    requested_ip,
                    change_reason,
                    created_at,
                    int(max_attempts),
                ),
            )
            row = conn.execute(
                "SELECT * FROM tasks WHERE task_id=?", (task_id,)
            ).fetchone()
    if capacity_error is not None:
        raise capacity_error
    assert row is not None
    return _task_dict(row), True


def get_task(task_id: str) -> dict | None:
    try:
        with _read_connection() as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE task_id=?", (task_id,)
            ).fetchone()
            attempts = conn.execute(
                "SELECT * FROM task_attempts WHERE task_id=? ORDER BY attempt_no",
                (task_id,),
            ).fetchall()
    except FileNotFoundError:
        return None
    if row is None:
        return None
    task = _task_dict(row)
    task["attempts"] = [_attempt_dict(attempt) for attempt in attempts]
    return task


def get_latest_task(task_type: str) -> dict | None:
    """读取某类任务最近一次运行，供只读运行状态聚合使用。"""
    if not str(task_type).strip():
        raise ValueError("task_type_required")
    try:
        with _read_connection() as conn:
            row = conn.execute(
                """SELECT * FROM tasks WHERE task_type=?
                   ORDER BY created_at DESC, task_id DESC LIMIT 1""",
                (str(task_type),),
            ).fetchone()
            attempts = (
                conn.execute(
                    """SELECT * FROM task_attempts WHERE task_id=?
                       ORDER BY attempt_no""",
                    (row["task_id"],),
                ).fetchall()
                if row is not None
                else []
            )
    except FileNotFoundError:
        return None
    if row is None:
        return None
    task = _task_dict(row)
    task["attempts"] = [_attempt_dict(attempt) for attempt in attempts]
    return task


def update_task_progress(task_id: str, owner_id: str, progress: dict) -> bool:
    """运行中更新可读进度；不改变任务终态、租约或重试语义。"""
    result_json = json.dumps(
        progress,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    with _connection(immediate=True) as conn:
        cursor = conn.execute(
            """UPDATE tasks SET result_json=?, heartbeat_at=?
               WHERE task_id=? AND status='running' AND lease_owner=?""",
            (result_json, _now(), task_id, owner_id),
        )
    return cursor.rowcount == 1


def cancel_task(
    task_id: str,
    *,
    requested_by: str,
    change_reason: str,
) -> dict:
    """只取消尚未开始的任务；运行中任务不能伪装成已被终止。"""
    actor = str(requested_by).strip()
    reason = str(change_reason).strip()
    if not actor:
        raise ValueError("cancellation_actor_required")
    if not 3 <= len(reason) <= 500:
        raise ValueError("cancellation_reason_required")
    cancelled_at = _now()
    with _connection(immediate=True) as conn:
        row = conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if row is None:
            return {"cancelled": False, "reason": "task_not_found", "task": None}
        if row["status"] != "queued":
            return {
                "cancelled": False,
                "reason": "task_not_queued",
                "task": _task_dict(row),
            }
        result_json = json.dumps(
            {
                "cancelled_at": cancelled_at,
                "cancelled_by": actor,
                "change_reason": reason,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        conn.execute(
            """UPDATE tasks SET status='cancelled', result_json=?,
                   error_code='cancelled_by_operator', finished_at=?,
                   heartbeat_at=?, lease_owner=NULL, lease_expires_at=NULL,
                   next_attempt_at=NULL
               WHERE task_id=? AND status='queued'""",
            (result_json, cancelled_at, cancelled_at, task_id),
        )
        cancelled = conn.execute(
            "SELECT * FROM tasks WHERE task_id=?", (task_id,)
        ).fetchone()
    assert cancelled is not None
    return {"cancelled": True, "reason": "cancelled", "task": _task_dict(cancelled)}


def claim_next_task(owner_id: str, *, lease_seconds: int = 300) -> dict | None:
    now = datetime.now(timezone.utc)
    now_text = now.isoformat(timespec="seconds")
    expires = (now + timedelta(seconds=lease_seconds)).isoformat(timespec="seconds")
    with _connection(immediate=True) as conn:
        exhausted = conn.execute(
            """SELECT task_id, task_type, attempt_count, max_attempts FROM tasks
               WHERE status='running' AND lease_expires_at < ?
                 AND attempt_count >= max_attempts""",
            (now_text,),
        ).fetchall()
        for expired in exhausted:
            conn.execute(
                """UPDATE task_attempts
                   SET status='failed', finished_at=?, error_code='lease_expired'
                   WHERE task_id=? AND attempt_no=? AND status='running'""",
                (now_text, expired["task_id"], expired["attempt_count"]),
            )
            conn.execute(
                """UPDATE tasks SET status='failed', error_code='lease_expired',
                       finished_at=?, heartbeat_at=?, lease_owner=NULL,
                       lease_expires_at=NULL, next_attempt_at=NULL
                   WHERE task_id=? AND status='running'""",
                (now_text, now_text, expired["task_id"]),
            )
            _insert_alert_event(
                conn,
                severity="critical",
                alert_type="task_terminal_failure",
                source="task_worker",
                subject_id=expired["task_id"],
                message="任务租约耗尽且已达到最大重试次数",
                details={
                    "attempt_no": int(expired["attempt_count"]),
                    "error_code": "lease_expired",
                    "max_attempts": int(expired["max_attempts"]),
                    "task_type": expired["task_type"],
                },
                dedup_key=(
                    f"{expired['task_id']}:{expired['attempt_count']}:"
                    "lease_expired:terminal"
                ),
            )
        # 过期 worker 的 running 任务可恢复，任务自身必须依靠幂等键安全重跑。
        row = conn.execute(
            """SELECT * FROM tasks
               WHERE (status='queued'
                      AND (next_attempt_at IS NULL OR next_attempt_at <= ?))
                  OR (status='running' AND lease_expires_at < ?
                      AND attempt_count < max_attempts)
               ORDER BY created_at, rowid LIMIT 1""",
            (now_text, now_text),
        ).fetchone()
        if row is None:
            return None
        if row["status"] == "running":
            conn.execute(
                """UPDATE task_attempts
                   SET status='failed', finished_at=?, error_code='lease_expired'
                   WHERE task_id=? AND attempt_no=? AND status='running'""",
                (now_text, row["task_id"], row["attempt_count"]),
            )
            _insert_alert_event(
                conn,
                severity="warning",
                alert_type="task_attempt_failed",
                source="task_worker",
                subject_id=row["task_id"],
                message="任务租约过期，已由新 worker 接管",
                details={
                    "attempt_no": int(row["attempt_count"]),
                    "error_code": "lease_expired",
                    "max_attempts": int(row["max_attempts"]),
                    "task_type": row["task_type"],
                },
                dedup_key=(
                    f"{row['task_id']}:{row['attempt_count']}:lease_expired:retry"
                ),
            )
        attempt_no = int(row["attempt_count"]) + 1
        conn.execute(
            """UPDATE tasks SET status='running', lease_owner=?, lease_expires_at=?,
                   started_at=COALESCE(started_at, ?), heartbeat_at=?,
                   attempt_count=?, next_attempt_at=NULL
               WHERE task_id=?""",
            (owner_id, expires, now_text, now_text, attempt_no, row["task_id"]),
        )
        conn.execute(
            """INSERT INTO task_attempts(
                   task_id, attempt_no, lease_owner, status, started_at
               ) VALUES(?,?,?,'running',?)""",
            (row["task_id"], attempt_no, owner_id, now_text),
        )
        claimed = conn.execute(
            "SELECT * FROM tasks WHERE task_id=?",
            (row["task_id"],),
        ).fetchone()
    return _task_dict(claimed)


def heartbeat_task(task_id: str, owner_id: str, *, lease_seconds: int = 300) -> bool:
    now = datetime.now(timezone.utc)
    expires = (now + timedelta(seconds=lease_seconds)).isoformat(timespec="seconds")
    with _connection(immediate=True) as conn:
        cursor = conn.execute(
            """UPDATE tasks SET heartbeat_at=?, lease_expires_at=?
               WHERE task_id=? AND status='running' AND lease_owner=?""",
            (now.isoformat(timespec="seconds"), expires, task_id, owner_id),
        )
    return cursor.rowcount == 1


def finish_task(
    task_id: str,
    owner_id: str,
    *,
    result: dict | None = None,
    error_code: str | None = None,
    retryable: bool = True,
    retry_delay_seconds: int = 30,
) -> bool:
    result_json = json.dumps(
        result or {},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    now = datetime.now(timezone.utc)
    now_text = now.isoformat(timespec="seconds")
    with _connection(immediate=True) as conn:
        row = conn.execute(
            """SELECT task_type, attempt_count, max_attempts FROM tasks
               WHERE task_id=? AND status='running' AND lease_owner=?""",
            (task_id, owner_id),
        ).fetchone()
        if row is None:
            return False
        attempt_no = int(row["attempt_count"])
        attempt_status = "failed" if error_code else "succeeded"
        conn.execute(
            """UPDATE task_attempts SET status=?, finished_at=?, error_code=?,
                   result_json=?
               WHERE task_id=? AND attempt_no=? AND status='running'""",
            (
                attempt_status,
                now_text,
                error_code,
                result_json,
                task_id,
                attempt_no,
            ),
        )
        should_retry = bool(
            error_code and retryable and attempt_no < int(row["max_attempts"])
        )
        if should_retry:
            base_delay = min(max(int(retry_delay_seconds), 0), 900)
            delay = min(base_delay * (2 ** max(attempt_no - 1, 0)), 900)
            next_attempt = (now + timedelta(seconds=delay)).isoformat(
                timespec="seconds"
            )
            conn.execute(
                """UPDATE tasks SET status='queued', result_json=?, error_code=?,
                       finished_at=NULL, heartbeat_at=?, lease_owner=NULL,
                       lease_expires_at=NULL, next_attempt_at=?
                   WHERE task_id=?""",
                (result_json, error_code, now_text, next_attempt, task_id),
            )
        else:
            status = "failed" if error_code else "succeeded"
            conn.execute(
                """UPDATE tasks SET status=?, result_json=?, error_code=?,
                       finished_at=?, heartbeat_at=?, lease_owner=NULL,
                       lease_expires_at=NULL, next_attempt_at=NULL
                   WHERE task_id=?""",
                (status, result_json, error_code, now_text, now_text, task_id),
            )
        if error_code:
            severity = "warning" if should_retry else "critical"
            alert_type = (
                "task_attempt_failed" if should_retry else "task_terminal_failure"
            )
            _insert_alert_event(
                conn,
                severity=severity,
                alert_type=alert_type,
                source="task_worker",
                subject_id=task_id,
                message=(
                    "任务执行失败，已安排重试" if should_retry else "任务执行最终失败"
                ),
                details={
                    "attempt_no": attempt_no,
                    "error_code": error_code,
                    "max_attempts": int(row["max_attempts"]),
                    "retry_scheduled": should_retry,
                    "task_type": row["task_type"],
                },
                dedup_key=(
                    f"{task_id}:{attempt_no}:{error_code}:"
                    f"{'retry' if should_retry else 'terminal'}"
                ),
            )
    return True


def record_alert(
    *,
    severity: str,
    alert_type: str,
    source: str,
    subject_id: str | None,
    message: str,
    details: dict | None,
    dedup_key: str,
) -> str:
    """供非任务运行路径追加同一格式的持久告警。"""
    with _connection(immediate=True) as conn:
        return _insert_alert_event(
            conn,
            severity=severity,
            alert_type=alert_type,
            source=source,
            subject_id=subject_id,
            message=message,
            details=details,
            dedup_key=dedup_key,
        )


def list_alerts(*, limit: int = 100, severity: str | None = None) -> list[dict]:
    if not 1 <= int(limit) <= 200:
        raise ValueError("alert_limit_out_of_range")
    if severity is not None and severity not in ALERT_SEVERITIES:
        raise ValueError("invalid_alert_severity")
    query = "SELECT * FROM alert_events"
    parameters: list[object] = []
    if severity is not None:
        query += " WHERE severity=?"
        parameters.append(severity)
    query += " ORDER BY occurred_at DESC, alert_id DESC LIMIT ?"
    parameters.append(int(limit))
    try:
        with _read_connection() as conn:
            rows = conn.execute(query, parameters).fetchall()
    except FileNotFoundError:
        return []
    return [_alert_dict(row) for row in rows]


def alert_summary(*, window_hours: int = 24) -> dict:
    if not 1 <= int(window_hours) <= 24 * 30:
        raise ValueError("alert_window_out_of_range")
    since = (datetime.now(timezone.utc) - timedelta(hours=int(window_hours))).isoformat(
        timespec="seconds"
    )
    try:
        with _read_connection() as conn:
            counts = {
                row["severity"]: int(row["count"])
                for row in conn.execute(
                    """SELECT severity, COUNT(*) AS count FROM alert_events
                       WHERE occurred_at >= ? GROUP BY severity""",
                    (since,),
                ).fetchall()
            }
            latest = conn.execute(
                "SELECT occurred_at FROM alert_events ORDER BY occurred_at DESC LIMIT 1"
            ).fetchone()
    except FileNotFoundError:
        counts = {}
        latest = None
    warning = counts.get("warning", 0)
    critical = counts.get("critical", 0)
    return {
        "window_hours": int(window_hours),
        "warning": warning,
        "critical": critical,
        "total": warning + critical,
        "latest_at": latest["occurred_at"] if latest else None,
    }


def register_job_run(
    job_name: str,
    trade_date: str,
    snapshot_id: str,
    policy_version: str,
    task_id: str,
) -> bool:
    with _connection(immediate=True) as conn:
        cursor = conn.execute(
            """INSERT OR IGNORE INTO job_runs(
                   job_name, trade_date, snapshot_id, policy_version, task_id,
                   status, started_at, finished_at, created_at
               ) VALUES(?,?,?,?,?,'succeeded',?,?,?)""",
            (
                job_name,
                trade_date,
                snapshot_id,
                policy_version,
                task_id,
                _now(),
                _now(),
                _now(),
            ),
        )
    return cursor.rowcount == 1


def claim_job_run(
    job_name: str,
    trade_date: str,
    snapshot_id: str,
    policy_version: str,
    task_id: str,
) -> dict:
    """在任何下游副作用前原子占用交易日级业务键。"""
    now = _now()
    key = (job_name, trade_date, snapshot_id, policy_version)
    with _connection(immediate=True) as conn:
        row = conn.execute(
            """
            SELECT * FROM job_runs
            WHERE job_name=? AND trade_date=? AND snapshot_id=? AND policy_version=?
            """,
            key,
        ).fetchone()
        if row is None:
            conn.execute(
                """
                INSERT INTO job_runs(
                    job_name, trade_date, snapshot_id, policy_version, task_id,
                    status, started_at, finished_at, created_at
                ) VALUES(?,?,?,?,?,'running',?,NULL,?)
                """,
                (*key, task_id, now, now),
            )
            return {"claimed": True, "status": "running", "resumed": False}
        if row["status"] == "succeeded":
            return {
                "claimed": False,
                "status": "succeeded",
                "task_id": row["task_id"],
            }

        previous_task = conn.execute(
            "SELECT status, lease_expires_at FROM tasks WHERE task_id=?",
            (row["task_id"],),
        ).fetchone()
        previous_still_live = bool(
            row["status"] == "running"
            and row["task_id"] != task_id
            and previous_task is not None
            and previous_task["status"] == "running"
            and (previous_task["lease_expires_at"] or "") >= now
        )
        if previous_still_live:
            return {
                "claimed": False,
                "status": "running",
                "task_id": row["task_id"],
            }
        conn.execute(
            """
            UPDATE job_runs
            SET task_id=?, status='running', started_at=?, finished_at=NULL
            WHERE job_name=? AND trade_date=? AND snapshot_id=? AND policy_version=?
            """,
            (task_id, now, *key),
        )
    return {"claimed": True, "status": "running", "resumed": True}


def finish_job_run(
    job_name: str,
    trade_date: str,
    snapshot_id: str,
    policy_version: str,
    task_id: str,
    *,
    succeeded: bool,
) -> bool:
    status = "succeeded" if succeeded else "failed"
    with _connection(immediate=True) as conn:
        cursor = conn.execute(
            """
            UPDATE job_runs SET status=?, finished_at=?
            WHERE job_name=? AND trade_date=? AND snapshot_id=? AND policy_version=?
              AND task_id=? AND status='running'
            """,
            (
                status,
                _now(),
                job_name,
                trade_date,
                snapshot_id,
                policy_version,
                task_id,
            ),
        )
    return cursor.rowcount == 1


def record_audit(
    *,
    actor: str,
    action: str,
    outcome: str,
    request_id: str | None = None,
    role: str | None = None,
    source_ip: str | None = None,
    method: str | None = None,
    path: str | None = None,
    change_reason: str | None = None,
    metadata: dict | None = None,
) -> None:
    with _connection() as conn:
        conn.execute(
            """INSERT INTO audit_events(
                   occurred_at, request_id, actor, role, source_ip, method, path,
                   action, outcome, change_reason, metadata_json
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                _now(),
                request_id,
                actor,
                role,
                source_ip,
                method,
                path,
                action,
                outcome,
                change_reason,
                json.dumps(
                    metadata or {}, ensure_ascii=False, sort_keys=True, default=str
                ),
            ),
        )


def allow_rate(bucket_key: str, *, limit: int, window_seconds: int = 60) -> bool:
    now = datetime.now(timezone.utc)
    epoch = int(now.timestamp())
    start_epoch = epoch - (epoch % window_seconds)
    start = datetime.fromtimestamp(start_epoch, timezone.utc).isoformat(
        timespec="seconds"
    )
    with _connection(immediate=True) as conn:
        row = conn.execute(
            "SELECT hits FROM rate_limits WHERE bucket_key=? AND window_start=?",
            (bucket_key, start),
        ).fetchone()
        hits = int(row["hits"]) if row else 0
        if hits >= limit:
            return False
        conn.execute(
            """INSERT INTO rate_limits(bucket_key, window_start, hits) VALUES(?,?,1)
               ON CONFLICT(bucket_key, window_start) DO UPDATE SET hits=hits+1""",
            (bucket_key, start),
        )
        conn.execute(
            "DELETE FROM rate_limits WHERE window_start < ?",
            ((now - timedelta(hours=2)).isoformat(timespec="seconds"),),
        )
    return True


def claim_request_nonce(
    principal_id: str,
    nonce: str,
    *,
    expires_at: str,
) -> bool:
    """原子登记已验签请求的 nonce；同一身份下重放只能成功一次。"""
    with _connection(immediate=True) as conn:
        now = _now()
        conn.execute("DELETE FROM request_nonces WHERE expires_at < ?", (now,))
        cursor = conn.execute(
            """INSERT OR IGNORE INTO request_nonces(
                   principal_id, nonce, created_at, expires_at
               ) VALUES(?,?,?,?)""",
            (principal_id, nonce, now, expires_at),
        )
    return cursor.rowcount == 1


def acquire_scheduler_lease(
    lease_name: str,
    owner_id: str,
    *,
    lease_seconds: int = 90,
) -> bool:
    now = datetime.now(timezone.utc)
    now_text = now.isoformat(timespec="seconds")
    expires = (now + timedelta(seconds=lease_seconds)).isoformat(timespec="seconds")
    with _connection(immediate=True) as conn:
        row = conn.execute(
            "SELECT owner_id, expires_at FROM scheduler_leases WHERE lease_name=?",
            (lease_name,),
        ).fetchone()
        if row and row["owner_id"] != owner_id and row["expires_at"] >= now_text:
            return False
        conn.execute(
            """INSERT INTO scheduler_leases(lease_name, owner_id, heartbeat_at, expires_at)
               VALUES(?,?,?,?) ON CONFLICT(lease_name) DO UPDATE SET
                 owner_id=excluded.owner_id, heartbeat_at=excluded.heartbeat_at,
                 expires_at=excluded.expires_at""",
            (lease_name, owner_id, now_text, expires),
        )
    return True


def release_scheduler_lease(
    lease_name: str,
    owner_id: str,
) -> bool:
    """优雅退出时只释放自己仍持有的租约，不能删除接管者的租约。"""
    with _connection(immediate=True) as conn:
        cursor = conn.execute(
            "DELETE FROM scheduler_leases WHERE lease_name=? AND owner_id=?",
            (lease_name, owner_id),
        )
    return cursor.rowcount == 1


def scheduler_status(lease_name: str = "production-scheduler") -> dict:
    try:
        with _read_connection() as conn:
            row = conn.execute(
                "SELECT * FROM scheduler_leases WHERE lease_name=?",
                (lease_name,),
            ).fetchone()
    except FileNotFoundError:
        row = None
    if not row:
        return {"running": False, "leader": None}
    valid = row["expires_at"] >= _now()
    return {
        "running": valid,
        "leader": row["owner_id"] if valid else None,
        "heartbeat_at": row["heartbeat_at"],
        "expires_at": row["expires_at"],
    }


def _task_dict(row: sqlite3.Row) -> dict:
    value = dict(row)
    value["payload"] = json.loads(value.pop("payload_json") or "{}")
    value["result"] = json.loads(value.pop("result_json") or "{}")
    return value


def _attempt_dict(row: sqlite3.Row) -> dict:
    value = dict(row)
    value["result"] = json.loads(value.pop("result_json") or "{}")
    return value


def _alert_dict(row: sqlite3.Row) -> dict:
    value = dict(row)
    value["details"] = json.loads(value.pop("details_json") or "{}")
    return value
