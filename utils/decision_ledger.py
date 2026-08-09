"""版本化决策账本。

账本保存收盘候选、盘前复核、模型注册和逐票证据链。
表位于现有 data/views.db，并使用同一套 WAL/并发连接策略。
"""

from __future__ import annotations

import hashlib
import math
from datetime import datetime
from typing import Any
from uuid import uuid4

import orjson

from views.view_manager import _get_conn, _get_migration_conn, _get_read_conn


DECISION_RUNS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS decision_runs (
        run_id TEXT PRIMARY KEY,
        trade_date TEXT NOT NULL,
        stage TEXT NOT NULL CHECK(stage IN ('close', 'preopen')),
        as_of TEXT NOT NULL,
        status TEXT NOT NULL,
        final_action TEXT NOT NULL,
        strategy_version TEXT NOT NULL,
        feature_version TEXT NOT NULL,
        model_version TEXT NOT NULL,
        data_version TEXT NOT NULL,
        source_refs_json TEXT NOT NULL,
        market_json TEXT NOT NULL,
        evaluation_json TEXT NOT NULL,
        reason_codes_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
"""

DECISION_OUTCOMES_SCHEMA = """
    CREATE TABLE IF NOT EXISTS decision_outcomes (
        outcome_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        code TEXT NOT NULL,
        source_snapshot_id TEXT NOT NULL CHECK(
            source_snapshot_id = 'legacy-unverified'
            OR length(source_snapshot_id) = 64
        ),
        observation_no INTEGER NOT NULL CHECK(observation_no >= 1),
        stage TEXT NOT NULL CHECK(stage IN ('close', 'preopen')),
        trade_date TEXT NOT NULL,
        action TEXT NOT NULL CHECK(action IN ('buy', 'observe', 'avoid')),
        entry_date TEXT,
        entry_price REAL,
        ret_1 REAL,
        net_ret_5 REAL,
        max_gain_5 REAL,
        max_drawdown_5 REAL,
        entry_feasible INTEGER CHECK(entry_feasible IN (0, 1)),
        exit_feasible INTEGER CHECK(exit_feasible IN (0, 1)),
        execution_status TEXT,
        execution_policy_version TEXT,
        days_tracked INTEGER NOT NULL DEFAULT 0 CHECK(days_tracked BETWEEN 0 AND 5),
        status TEXT NOT NULL DEFAULT 'pending' CHECK(
            status IN ('pending', 'partial', 'complete', 'invalid')
        ),
        updated_at TEXT NOT NULL,
        UNIQUE(run_id, code, observation_no),
        FOREIGN KEY(run_id) REFERENCES decision_runs(run_id) ON DELETE CASCADE
    )
"""

OUTCOME_CONTENT_FIELDS = (
    "run_id",
    "code",
    "source_snapshot_id",
    "stage",
    "trade_date",
    "action",
    "entry_date",
    "entry_price",
    "ret_1",
    "net_ret_5",
    "max_gain_5",
    "max_drawdown_5",
    "entry_feasible",
    "exit_feasible",
    "execution_status",
    "execution_policy_version",
    "days_tracked",
    "status",
)

DECISION_OUTCOME_INSERT = """
    INSERT INTO decision_outcomes
      (outcome_id, observation_no, run_id, code, source_snapshot_id, stage,
       trade_date, action,
       entry_date, entry_price, ret_1, net_ret_5, max_gain_5, max_drawdown_5,
       entry_feasible, exit_feasible, execution_status,
       execution_policy_version, days_tracked, status, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

EVOLUTION_RUNS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS evolution_runs (
        evolution_id TEXT PRIMARY KEY,
        trade_date TEXT NOT NULL,
        status TEXT NOT NULL,
        data_version TEXT NOT NULL,
        universe_count INTEGER NOT NULL,
        covered_count INTEGER NOT NULL,
        coverage_ratio REAL NOT NULL,
        labels_updated INTEGER NOT NULL DEFAULT 0,
        dataset_rows INTEGER NOT NULL DEFAULT 0,
        challenger_version TEXT,
        promotion_status TEXT NOT NULL,
        reason_codes_json TEXT NOT NULL,
        metrics_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
"""

POLICY_REQUIRED_COMPONENTS = frozenset(
    {
        "market",
        "sector",
        "entry_risk",
        "exit_risk",
        "quality",
    }
)

MODEL_REGISTRY_SCHEMA = """
    CREATE TABLE IF NOT EXISTS model_registry (
        model_key TEXT NOT NULL,
        version TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('shadow', 'validated', 'active', 'rejected')),
        trained_as_of TEXT NOT NULL,
        train_range TEXT,
        test_range TEXT,
        feature_names_json TEXT NOT NULL,
        params_json TEXT NOT NULL,
        metrics_json TEXT NOT NULL,
        source_refs_json TEXT NOT NULL,
        artifact_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY(model_key, version)
    )
"""

POLICY_REGISTRY_SCHEMA = """
    CREATE TABLE IF NOT EXISTS policy_registry (
        policy_version TEXT PRIMARY KEY,
        research_status TEXT NOT NULL CHECK(research_status IN ('shadow', 'validated', 'rejected')),
        trained_as_of TEXT NOT NULL,
        train_range TEXT,
        test_range TEXT,
        component_versions_json TEXT NOT NULL,
        metrics_json TEXT NOT NULL,
        evidence_json TEXT NOT NULL,
        source_refs_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
"""

POLICY_VALIDATION_SCHEMA = """
    CREATE TABLE IF NOT EXISTS policy_validation_records (
        validation_id TEXT PRIMARY KEY,
        policy_version TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('validated', 'rejected')),
        forward_window_end TEXT NOT NULL,
        independent_months INTEGER NOT NULL,
        required_independent_months INTEGER NOT NULL,
        dataset_hash TEXT NOT NULL,
        code_sha TEXT NOT NULL,
        reviewer_id TEXT NOT NULL,
        ticket_ref TEXT NOT NULL,
        evidence_hash TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        reason_codes_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(policy_version) REFERENCES policy_registry(policy_version)
    )
"""

POLICY_EVIDENCE_ARTIFACT_SCHEMA = """
    CREATE TABLE IF NOT EXISTS policy_evidence_artifacts (
        artifact_id TEXT PRIMARY KEY,
        policy_version TEXT NOT NULL,
        artifact_type TEXT NOT NULL CHECK(artifact_type IN
            ('power_analysis', 'atomic_policy_evaluation')),
        experiment_ref TEXT NOT NULL,
        dataset_hash TEXT NOT NULL,
        code_sha TEXT NOT NULL,
        artifact_hash TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(policy_version, artifact_type, artifact_hash),
        FOREIGN KEY(policy_version) REFERENCES policy_registry(policy_version)
    )
"""

EVENT_EVIDENCE_SCHEMA = """
    CREATE TABLE IF NOT EXISTS event_evidence (
        evidence_id TEXT PRIMARY KEY,
        event_id TEXT NOT NULL,
        code TEXT NOT NULL,
        source TEXT NOT NULL,
        source_url TEXT,
        published_at TEXT NOT NULL,
        title TEXT NOT NULL,
        text_hash TEXT NOT NULL,
        raw_ref TEXT,
        fetched_at TEXT NOT NULL,
        payload_json TEXT NOT NULL
    )
"""


def _json(value: Any) -> str:
    return orjson.dumps(value if value is not None else {}).decode()


def _loads(value: str | None, fallback):
    if not value:
        return fallback
    try:
        return orjson.loads(value)
    except Exception:
        return fallback


def _optional_finite_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return 0.0 if number == 0 else number


def _canonical_outcome(outcome: Any) -> dict[str, Any]:
    """将结果观测规范化为可稳定取哈希的业务内容。

    观测时间和序号不参与哈希：相同业务状态在 worker 重试时必须幂等。
    """
    raw = dict(outcome)
    payload: dict[str, Any] = {
        "run_id": str(raw.get("run_id") or ""),
        "code": str(raw.get("code") or ""),
        "source_snapshot_id": str(raw.get("source_snapshot_id") or "").lower(),
        "stage": str(raw.get("stage") or ""),
        "trade_date": str(raw.get("trade_date") or ""),
        "action": str(raw.get("action") or ""),
        "entry_date": (
            str(raw["entry_date"]) if raw.get("entry_date") is not None else None
        ),
        "entry_price": _optional_finite_float(raw.get("entry_price")),
        "ret_1": _optional_finite_float(raw.get("ret_1")),
        "net_ret_5": _optional_finite_float(raw.get("net_ret_5")),
        "max_gain_5": _optional_finite_float(raw.get("max_gain_5")),
        "max_drawdown_5": _optional_finite_float(raw.get("max_drawdown_5")),
        "entry_feasible": (
            int(bool(raw["entry_feasible"]))
            if raw.get("entry_feasible") is not None
            else None
        ),
        "exit_feasible": (
            int(bool(raw["exit_feasible"]))
            if raw.get("exit_feasible") is not None
            else None
        ),
        "execution_status": (
            str(raw["execution_status"])
            if raw.get("execution_status") is not None
            else None
        ),
        "execution_policy_version": (
            str(raw["execution_policy_version"])
            if raw.get("execution_policy_version") is not None
            else None
        ),
        "days_tracked": int(raw.get("days_tracked", 0) or 0),
        "status": str(raw.get("status") or "pending"),
    }
    identity_fields = (
        "run_id",
        "code",
        "source_snapshot_id",
        "stage",
        "trade_date",
        "action",
    )
    if not all(payload[key] for key in identity_fields):
        raise ValueError("decision_outcome_identity_required")
    snapshot_id = payload["source_snapshot_id"]
    if snapshot_id != "legacy-unverified" and (
        len(snapshot_id) != 64
        or any(char not in "0123456789abcdef" for char in snapshot_id.lower())
    ):
        raise ValueError("decision_outcome_snapshot_invalid")
    if payload["stage"] not in {"close", "preopen"}:
        raise ValueError("decision_outcome_stage_invalid")
    if payload["action"] not in {"buy", "observe", "avoid"}:
        raise ValueError("decision_outcome_action_invalid")
    if payload["status"] not in {"pending", "partial", "complete", "invalid"}:
        raise ValueError("decision_outcome_status_invalid")
    if not 0 <= payload["days_tracked"] <= 5:
        raise ValueError("decision_outcome_days_tracked_invalid")
    return payload


def _outcome_id(outcome: Any) -> str:
    payload = _canonical_outcome(outcome)
    return hashlib.sha256(
        orjson.dumps(payload, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()


def _verified_outcome(row: Any) -> dict[str, Any]:
    item = dict(row)
    try:
        expected_id = _outcome_id(item)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("decision_outcome_integrity_failed") from exc
    if item.get("outcome_id") != expected_id:
        raise RuntimeError("decision_outcome_integrity_failed")
    return item


def _table_exists(conn, name: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
        ).fetchone()
        is not None
    )


def _migrate_append_only_runs(conn) -> None:
    """移除旧版决策表的业务唯一键，保留全部历史记录与外键。"""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'decision_runs'"
    ).fetchone()
    if row is None:
        return
    normalized = "".join((row["sql"] or "").lower().split())
    if "unique(trade_date,stage,strategy_version,data_version)" not in normalized:
        return

    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("BEGIN IMMEDIATE")
    for table in (
        "decision_outcomes_v2_migration",
        "decision_candidates_v2_migration",
        "decision_runs_v2_migration",
    ):
        conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.execute(
        DECISION_RUNS_SCHEMA.replace("decision_runs", "decision_runs_v2_migration")
    )
    conn.execute("""
        INSERT INTO decision_runs_v2_migration
        SELECT run_id, trade_date, stage, as_of, status, final_action,
               strategy_version, feature_version, model_version, data_version,
               source_refs_json, market_json, evaluation_json, reason_codes_json,
               created_at, updated_at
        FROM decision_runs
    """)

    has_candidates = _table_exists(conn, "decision_candidates")
    if has_candidates:
        conn.execute("""
            CREATE TABLE decision_candidates_v2_migration (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                code TEXT NOT NULL,
                name TEXT,
                industry TEXT,
                rank_no INTEGER,
                tie_group INTEGER DEFAULT 1,
                action TEXT NOT NULL,
                baseline_json TEXT NOT NULL,
                market_json TEXT NOT NULL,
                sector_json TEXT NOT NULL,
                stock_json TEXT NOT NULL,
                events_json TEXT NOT NULL,
                reason_codes_json TEXT NOT NULL,
                explanation TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(run_id, code),
                FOREIGN KEY(run_id) REFERENCES decision_runs(run_id) ON DELETE CASCADE
            )
        """)
        conn.execute("""
            INSERT INTO decision_candidates_v2_migration
            SELECT id, run_id, code, name, industry, rank_no, tie_group, action,
                   baseline_json, market_json, sector_json, stock_json, events_json,
                   reason_codes_json, explanation, created_at
            FROM decision_candidates
        """)

    has_outcomes = _table_exists(conn, "decision_outcomes")
    if has_outcomes:
        conn.execute("""
            CREATE TABLE decision_outcomes_v2_migration (
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
                exit_feasible INTEGER,
                execution_status TEXT,
                execution_policy_version TEXT,
                days_tracked INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                updated_at TEXT NOT NULL,
                PRIMARY KEY(run_id, code),
                FOREIGN KEY(run_id) REFERENCES decision_runs(run_id) ON DELETE CASCADE
            )
        """)
        conn.execute("""
            INSERT INTO decision_outcomes_v2_migration
              (run_id, code, stage, trade_date, action, entry_date, entry_price,
               ret_1, net_ret_5, max_gain_5, max_drawdown_5, entry_feasible,
               days_tracked, status, updated_at)
            SELECT run_id, code, stage, trade_date, action, entry_date, entry_price,
                   ret_1, net_ret_5, max_gain_5, max_drawdown_5, entry_feasible,
                   days_tracked, status, updated_at
            FROM decision_outcomes
        """)

    if has_outcomes:
        conn.execute("DROP TABLE decision_outcomes")
    if has_candidates:
        conn.execute("DROP TABLE decision_candidates")
    conn.execute("DROP TABLE decision_runs")
    conn.execute("ALTER TABLE decision_runs_v2_migration RENAME TO decision_runs")
    if has_candidates:
        conn.execute(
            "ALTER TABLE decision_candidates_v2_migration RENAME TO decision_candidates"
        )
    if has_outcomes:
        conn.execute(
            "ALTER TABLE decision_outcomes_v2_migration RENAME TO decision_outcomes"
        )
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError(f"决策账本迁移后外键校验失败: {len(violations)}")


def _migrate_append_only_outcomes(conn) -> None:
    """将旧版可覆盖结果迁移为内容寻址、只追加的观测序列。"""
    table_info = conn.execute("PRAGMA table_info(decision_outcomes)").fetchall()
    if not table_info:
        return
    columns = {row["name"] for row in table_info}
    required = {
        "outcome_id",
        "observation_no",
        "exit_feasible",
        "execution_status",
        "execution_policy_version",
        *OUTCOME_CONTENT_FIELDS,
    }
    if required <= columns:
        return

    order_by = (
        "run_id, code, observation_no, updated_at"
        if "observation_no" in columns
        else "run_id, code, updated_at"
    )
    source_rows = conn.execute(
        f"SELECT * FROM decision_outcomes ORDER BY {order_by}"
    ).fetchall()
    conn.execute("DROP TRIGGER IF EXISTS decision_outcomes_no_update")
    conn.execute("DROP TRIGGER IF EXISTS decision_outcomes_no_delete")
    conn.execute("DROP TABLE IF EXISTS decision_outcomes_append_migration")
    conn.execute(
        DECISION_OUTCOMES_SCHEMA.replace(
            "decision_outcomes", "decision_outcomes_append_migration", 1
        )
    )

    observation_numbers: dict[tuple[str, str], int] = {}
    seen_ids: set[str] = set()
    for row in source_rows:
        raw = {
            field: row[field] if field in columns else None
            for field in OUTCOME_CONTENT_FIELDS
        }
        if "source_snapshot_id" not in columns:
            raw["source_snapshot_id"] = "legacy-unverified"
        if raw["days_tracked"] is None:
            raw["days_tracked"] = 0
        if raw["status"] is None:
            raw["status"] = "pending"
        payload = _canonical_outcome(raw)
        content_id = _outcome_id(payload)
        if content_id in seen_ids:
            continue
        seen_ids.add(content_id)
        key = (payload["run_id"], payload["code"])
        observation_no = observation_numbers.get(key, 0) + 1
        observation_numbers[key] = observation_no
        updated_at = (
            str(row["updated_at"])
            if "updated_at" in columns and row["updated_at"] is not None
            else datetime.now().astimezone().isoformat(timespec="microseconds")
        )
        conn.execute(
            DECISION_OUTCOME_INSERT.replace(
                "decision_outcomes", "decision_outcomes_append_migration", 1
            ),
            (
                content_id,
                observation_no,
                *(payload[field] for field in OUTCOME_CONTENT_FIELDS),
                updated_at,
            ),
        )

    conn.execute("DROP TABLE decision_outcomes")
    conn.execute(
        "ALTER TABLE decision_outcomes_append_migration RENAME TO decision_outcomes"
    )
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError(f"结果账本迁移后外键校验失败: {len(violations)}")


def _migrate_append_only_evolution_runs(conn) -> None:
    """移除旧版演进表的同日唯一约束，让失败和重跑都永久保留。"""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'evolution_runs'"
    ).fetchone()
    if row is None:
        return
    normalized = "".join((row["sql"] or "").lower().split())
    if "trade_datetextnotnullunique" not in normalized:
        return

    conn.execute("DROP TABLE IF EXISTS evolution_runs_append_migration")
    conn.execute(
        EVOLUTION_RUNS_SCHEMA.replace(
            "evolution_runs", "evolution_runs_append_migration"
        )
    )
    conn.execute("""
        INSERT INTO evolution_runs_append_migration
        SELECT evolution_id, trade_date, status, data_version, universe_count,
               covered_count, coverage_ratio, labels_updated, dataset_rows,
               challenger_version, promotion_status, reason_codes_json,
               metrics_json, created_at, updated_at
        FROM evolution_runs
    """)
    conn.execute("DROP TABLE evolution_runs")
    conn.execute("ALTER TABLE evolution_runs_append_migration RENAME TO evolution_runs")


def _migrate_append_only_event_evidence(conn) -> None:
    columns = conn.execute("PRAGMA table_info(event_evidence)").fetchall()
    if not columns or any(row["name"] == "evidence_id" for row in columns):
        return
    conn.execute("DROP TABLE IF EXISTS event_evidence_append_migration")
    conn.execute(
        EVENT_EVIDENCE_SCHEMA.replace(
            "event_evidence", "event_evidence_append_migration"
        )
    )
    conn.execute("""
        INSERT INTO event_evidence_append_migration
          (evidence_id, event_id, code, source, source_url, published_at, title,
           text_hash, raw_ref, fetched_at, payload_json)
        SELECT event_id, event_id, code, source, source_url, published_at, title,
               text_hash, raw_ref, fetched_at, payload_json
        FROM event_evidence
    """)
    conn.execute("DROP TABLE event_evidence")
    conn.execute("ALTER TABLE event_evidence_append_migration RENAME TO event_evidence")


def _migrate_registry_statuses(conn) -> None:
    """将“研究已验证”与“生产已激活”分开，防止 shadow 被直接发布。"""
    model_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='model_registry'"
    ).fetchone()
    policy_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='policy_registry'"
    ).fetchone()
    model_needs = model_sql is not None and "'validated'" not in (
        model_sql["sql"] or ""
    )
    policy_needs = policy_sql is not None and "'validated'" not in (
        policy_sql["sql"] or ""
    )
    if not model_needs and not policy_needs:
        return
    conn.execute("PRAGMA foreign_keys=OFF")
    if model_needs:
        conn.execute("DROP TABLE IF EXISTS model_registry_status_migration")
        conn.execute(
            MODEL_REGISTRY_SCHEMA.replace(
                "model_registry", "model_registry_status_migration"
            )
        )
        conn.execute("""
            INSERT INTO model_registry_status_migration
            SELECT model_key, version, status, trained_as_of, train_range, test_range,
                   feature_names_json, params_json, metrics_json, source_refs_json,
                   artifact_json, created_at
            FROM model_registry
        """)
        conn.execute("DROP TABLE model_registry")
        conn.execute(
            "ALTER TABLE model_registry_status_migration RENAME TO model_registry"
        )
    if policy_needs:
        conn.execute("DROP TABLE IF EXISTS policy_registry_status_migration")
        conn.execute(
            POLICY_REGISTRY_SCHEMA.replace(
                "policy_registry", "policy_registry_status_migration"
            )
        )
        conn.execute("""
            INSERT INTO policy_registry_status_migration
            SELECT policy_version, research_status, trained_as_of, train_range, test_range,
                   component_versions_json, metrics_json, evidence_json,
                   source_refs_json, created_at
            FROM policy_registry
        """)
        conn.execute("DROP TABLE policy_registry")
        conn.execute(
            "ALTER TABLE policy_registry_status_migration RENAME TO policy_registry"
        )
    conn.execute("PRAGMA foreign_keys=ON")


def init_decision_ledger() -> None:
    with _get_migration_conn() as conn:
        _migrate_append_only_runs(conn)
        _migrate_append_only_outcomes(conn)
        _migrate_append_only_evolution_runs(conn)
        _migrate_append_only_event_evidence(conn)
        _migrate_registry_statuses(conn)
        conn.execute(DECISION_RUNS_SCHEMA)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS decision_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                code TEXT NOT NULL,
                name TEXT,
                industry TEXT,
                rank_no INTEGER,
                tie_group INTEGER DEFAULT 1,
                action TEXT NOT NULL,
                baseline_json TEXT NOT NULL,
                market_json TEXT NOT NULL,
                sector_json TEXT NOT NULL,
                stock_json TEXT NOT NULL,
                events_json TEXT NOT NULL,
                reason_codes_json TEXT NOT NULL,
                explanation TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(run_id, code),
                FOREIGN KEY(run_id) REFERENCES decision_runs(run_id) ON DELETE CASCADE
            )
        """)
        conn.execute(EVENT_EVIDENCE_SCHEMA)
        conn.execute(MODEL_REGISTRY_SCHEMA)
        conn.execute(POLICY_REGISTRY_SCHEMA)
        conn.execute(POLICY_EVIDENCE_ARTIFACT_SCHEMA)
        conn.execute(POLICY_VALIDATION_SCHEMA)
        conn.executescript("""
            CREATE TRIGGER IF NOT EXISTS policy_evidence_artifacts_no_update
            BEFORE UPDATE ON policy_evidence_artifacts
            BEGIN
                SELECT RAISE(ABORT, 'immutable_policy_evidence');
            END;
            CREATE TRIGGER IF NOT EXISTS policy_evidence_artifacts_no_delete
            BEFORE DELETE ON policy_evidence_artifacts
            BEGIN
                SELECT RAISE(ABORT, 'immutable_policy_evidence');
            END;
            CREATE TRIGGER IF NOT EXISTS policy_validation_records_no_update
            BEFORE UPDATE ON policy_validation_records
            BEGIN
                SELECT RAISE(ABORT, 'immutable_policy_validation');
            END;
            CREATE TRIGGER IF NOT EXISTS policy_validation_records_no_delete
            BEFORE DELETE ON policy_validation_records
            BEGIN
                SELECT RAISE(ABORT, 'immutable_policy_validation');
            END;
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS policy_release_events (
                release_id TEXT PRIMARY KEY,
                policy_version TEXT NOT NULL,
                action TEXT NOT NULL CHECK(action IN ('proposed', 'activated', 'rejected', 'rolled_back')),
                target_policy_version TEXT,
                evidence_json TEXT NOT NULL,
                reason_codes_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(policy_version) REFERENCES policy_registry(policy_version)
            )
        """)
        conn.executescript("""
            CREATE TRIGGER IF NOT EXISTS policy_release_events_no_update
            BEFORE UPDATE ON policy_release_events
            BEGIN
                SELECT RAISE(ABORT, 'immutable_policy_release');
            END;
            CREATE TRIGGER IF NOT EXISTS policy_release_events_no_delete
            BEFORE DELETE ON policy_release_events
            BEGIN
                SELECT RAISE(ABORT, 'immutable_policy_release');
            END;
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ai_decision_runs (
                ai_run_id TEXT PRIMARY KEY,
                trade_date TEXT NOT NULL,
                decision_run_id TEXT,
                as_of TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN
                    ('not_called', 'abstained', 'explained', 'shadow_ranked', 'failed')),
                role TEXT NOT NULL,
                model TEXT,
                prompt_version TEXT,
                input_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                reason_codes_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute(DECISION_OUTCOMES_SCHEMA)
        conn.execute(EVOLUTION_RUNS_SCHEMA)
        conn.executescript("""
            CREATE TRIGGER IF NOT EXISTS decision_runs_no_update
            BEFORE UPDATE ON decision_runs
            BEGIN
                SELECT RAISE(ABORT, 'immutable_decision_run');
            END;
            CREATE TRIGGER IF NOT EXISTS decision_runs_no_delete
            BEFORE DELETE ON decision_runs
            BEGIN
                SELECT RAISE(ABORT, 'immutable_decision_run');
            END;
            CREATE TRIGGER IF NOT EXISTS decision_candidates_no_update
            BEFORE UPDATE ON decision_candidates
            BEGIN
                SELECT RAISE(ABORT, 'immutable_decision_candidate');
            END;
            CREATE TRIGGER IF NOT EXISTS decision_candidates_no_delete
            BEFORE DELETE ON decision_candidates
            BEGIN
                SELECT RAISE(ABORT, 'immutable_decision_candidate');
            END;
            CREATE TRIGGER IF NOT EXISTS decision_outcomes_no_update
            BEFORE UPDATE ON decision_outcomes
            BEGIN
                SELECT RAISE(ABORT, 'immutable_decision_outcome');
            END;
            CREATE TRIGGER IF NOT EXISTS decision_outcomes_no_delete
            BEFORE DELETE ON decision_outcomes
            BEGIN
                SELECT RAISE(ABORT, 'immutable_decision_outcome');
            END;
            CREATE TRIGGER IF NOT EXISTS evolution_runs_no_update
            BEFORE UPDATE ON evolution_runs
            BEGIN
                SELECT RAISE(ABORT, 'immutable_evolution_run');
            END;
            CREATE TRIGGER IF NOT EXISTS evolution_runs_no_delete
            BEFORE DELETE ON evolution_runs
            BEGIN
                SELECT RAISE(ABORT, 'immutable_evolution_run');
            END;
            CREATE TRIGGER IF NOT EXISTS event_evidence_no_update
            BEFORE UPDATE ON event_evidence
            BEGIN
                SELECT RAISE(ABORT, 'immutable_event_evidence');
            END;
            CREATE TRIGGER IF NOT EXISTS event_evidence_no_delete
            BEFORE DELETE ON event_evidence
            BEGIN
                SELECT RAISE(ABORT, 'immutable_event_evidence');
            END;
            CREATE TRIGGER IF NOT EXISTS ai_decision_runs_no_update
            BEFORE UPDATE ON ai_decision_runs
            BEGIN
                SELECT RAISE(ABORT, 'immutable_ai_decision_run');
            END;
            CREATE TRIGGER IF NOT EXISTS ai_decision_runs_no_delete
            BEFORE DELETE ON ai_decision_runs
            BEGIN
                SELECT RAISE(ABORT, 'immutable_ai_decision_run');
            END;
            CREATE TRIGGER IF NOT EXISTS model_registry_immutable_fields
            BEFORE UPDATE OF model_key, version, trained_as_of, train_range,
                test_range, feature_names_json, params_json, metrics_json,
                source_refs_json, artifact_json, created_at ON model_registry
            BEGIN
                SELECT RAISE(ABORT, 'immutable_model_artifact');
            END;
            CREATE TRIGGER IF NOT EXISTS model_registry_status_transition
            BEFORE UPDATE OF status ON model_registry
            WHEN NOT (OLD.status = 'shadow' AND NEW.status = 'validated')
            BEGIN
                SELECT RAISE(ABORT, 'invalid_model_status_transition');
            END;
            CREATE TRIGGER IF NOT EXISTS model_registry_no_delete
            BEFORE DELETE ON model_registry
            BEGIN
                SELECT RAISE(ABORT, 'immutable_model_artifact');
            END;
            CREATE TRIGGER IF NOT EXISTS policy_registry_immutable_fields
            BEFORE UPDATE OF policy_version, trained_as_of, train_range,
                test_range, component_versions_json, metrics_json, evidence_json,
                source_refs_json, created_at ON policy_registry
            BEGIN
                SELECT RAISE(ABORT, 'immutable_policy_candidate');
            END;
            CREATE TRIGGER IF NOT EXISTS policy_registry_status_transition
            BEFORE UPDATE OF research_status ON policy_registry
            WHEN NOT (
                OLD.research_status = 'shadow'
                AND NEW.research_status = 'validated'
            )
            BEGIN
                SELECT RAISE(ABORT, 'invalid_policy_status_transition');
            END;
            CREATE TRIGGER IF NOT EXISTS policy_registry_no_delete
            BEFORE DELETE ON policy_registry
            BEGIN
                SELECT RAISE(ABORT, 'immutable_policy_candidate');
            END;
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_decision_runs_date ON decision_runs(trade_date, stage)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_candidates_run_rank ON decision_candidates(run_id, rank_no)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_event_code_time ON event_evidence(code, published_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_event_id ON event_evidence(event_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_outcomes_status ON decision_outcomes(status, trade_date)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_evolution_date ON evolution_runs(trade_date)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_policy_release_time "
            "ON policy_release_events(created_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ai_run_date "
            "ON ai_decision_runs(trade_date, created_at)"
        )


def make_run_id(run: dict, candidates: list[dict]) -> str:
    payload = {
        key: run.get(key)
        for key in (
            "trade_date",
            "stage",
            "as_of",
            "status",
            "final_action",
            "strategy_version",
            "feature_version",
            "model_version",
            "data_version",
            "source_refs",
            "market",
            "evaluation",
            "reason_codes",
        )
    }
    payload["candidates"] = candidates
    raw = orjson.dumps(payload, option=orjson.OPT_SORT_KEYS)
    return hashlib.sha256(raw).hexdigest()[:24]


def save_decision_run(run: dict, candidates: list[dict]) -> str:
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    run_id = run.get("run_id") or make_run_id(run, candidates)
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO decision_runs
              (run_id, trade_date, stage, as_of, status, final_action,
               strategy_version, feature_version, model_version, data_version,
               source_refs_json, market_json, evaluation_json, reason_codes_json,
               created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                run_id,
                run["trade_date"],
                run["stage"],
                run["as_of"],
                run["status"],
                run["final_action"],
                run["strategy_version"],
                run["feature_version"],
                run.get("model_version", "baseline"),
                run["data_version"],
                _json(run.get("source_refs", [])),
                _json(run.get("market", {})),
                _json(run.get("evaluation", {})),
                _json(run.get("reason_codes", [])),
                run.get("created_at", now),
                now,
            ),
        )
        for index, candidate in enumerate(candidates, start=1):
            conn.execute(
                """
                INSERT OR IGNORE INTO decision_candidates
                  (run_id, code, name, industry, rank_no, tie_group, action,
                   baseline_json, market_json, sector_json, stock_json,
                   events_json, reason_codes_json, explanation, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    run_id,
                    candidate["code"],
                    candidate.get("name"),
                    candidate.get("industry"),
                    candidate.get("rank", index),
                    candidate.get("tie_group", 1),
                    candidate.get("action", "observe"),
                    _json(candidate.get("baseline", {})),
                    _json(candidate.get("market", {})),
                    _json(candidate.get("sector", {})),
                    _json(candidate.get("stock", {})),
                    _json(candidate.get("events", [])),
                    _json(candidate.get("reason_codes", [])),
                    candidate.get("explanation", ""),
                    now,
                ),
            )
    return run_id


def _candidate_from_row(row) -> dict:
    return {
        "code": row["code"],
        "name": row["name"],
        "industry": row["industry"],
        "rank": row["rank_no"],
        "tie_group": row["tie_group"],
        "action": row["action"],
        "baseline": _loads(row["baseline_json"], {}),
        "market": _loads(row["market_json"], {}),
        "sector": _loads(row["sector_json"], {}),
        "stock": _loads(row["stock_json"], {}),
        "events": _loads(row["events_json"], []),
        "reason_codes": _loads(row["reason_codes_json"], []),
        "explanation": row["explanation"] or "",
    }


def get_decision(run_id: str) -> dict | None:
    with _get_read_conn() as conn:
        row = conn.execute(
            "SELECT * FROM decision_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            return None
        candidates = conn.execute(
            "SELECT * FROM decision_candidates WHERE run_id = ? ORDER BY rank_no, code",
            (run_id,),
        ).fetchall()
    result = dict(row)
    for key, fallback in (
        ("source_refs_json", []),
        ("market_json", {}),
        ("evaluation_json", {}),
        ("reason_codes_json", []),
    ):
        result[key.removesuffix("_json")] = _loads(result.pop(key), fallback)
    result["candidates"] = [_candidate_from_row(r) for r in candidates]
    return result


def get_latest_decision(stage: str | None = None) -> dict | None:
    where, params = ("WHERE stage = ?", (stage,)) if stage else ("", ())
    with _get_read_conn() as conn:
        row = conn.execute(
            f"SELECT run_id FROM decision_runs {where} "
            "ORDER BY trade_date DESC, as_of DESC, created_at DESC, run_id DESC LIMIT 1",
            params,
        ).fetchone()
    return get_decision(row["run_id"]) if row else None


def save_event_evidence(event: dict) -> None:
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO event_evidence
              (evidence_id, event_id, code, source, source_url, published_at,
               title, text_hash, raw_ref, fetched_at, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                event.get("evidence_id") or uuid4().hex[:24],
                event["event_id"],
                event["code"],
                event["source"],
                event.get("source_url"),
                event["published_at"],
                event["title"],
                event["text_hash"],
                event.get("raw_ref"),
                event["fetched_at"],
                _json(event),
            ),
        )


def get_recent_event_evidence(
    codes: set[str],
    *,
    start_at: str,
    end_at: str,
) -> list[dict]:
    """只读已经抓取过的事件证据，供后续云阶情报快照复用。"""
    normalized = sorted({str(code).zfill(6) for code in codes if code})
    if not normalized:
        return []
    placeholders = ",".join("?" for _ in normalized)
    with _get_read_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT payload_json
            FROM event_evidence
            WHERE code IN ({placeholders})
              AND published_at >= ?
              AND published_at <= ?
            ORDER BY published_at DESC, fetched_at DESC, evidence_id DESC
            """,
            (*normalized, start_at, end_at),
        ).fetchall()
    return [_loads(row["payload_json"], {}) for row in rows]


def save_ai_decision_run(run: dict) -> str:
    now = datetime.now().astimezone().isoformat(timespec="microseconds")
    ai_run_id = run.get("ai_run_id") or uuid4().hex[:24]
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO ai_decision_runs
              (ai_run_id, trade_date, decision_run_id, as_of, status, role,
               model, prompt_version, input_hash, payload_json,
               reason_codes_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                ai_run_id,
                run["trade_date"],
                run.get("decision_run_id"),
                run.get("as_of", now),
                run["status"],
                run.get("role", "explanation"),
                run.get("model"),
                run.get("prompt_version"),
                run["input_hash"],
                _json(run.get("payload", {})),
                _json(run.get("reason_codes", [])),
                now,
            ),
        )
    return ai_run_id


def get_latest_ai_decision_run() -> dict | None:
    with _get_read_conn() as conn:
        row = conn.execute(
            "SELECT * FROM ai_decision_runs "
            "ORDER BY trade_date DESC, created_at DESC, rowid DESC LIMIT 1"
        ).fetchone()
    if row is None:
        return None
    item = dict(row)
    item["payload"] = _loads(item.pop("payload_json"), {})
    item["reason_codes"] = _loads(item.pop("reason_codes_json"), [])
    return item


def model_artifact_hash(artifact: dict) -> str:
    return hashlib.sha256(
        orjson.dumps(artifact or {}, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()


def register_model(model: dict) -> None:
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    requested_status = model.get("status", "shadow")
    # 研究代码无权自称 validated/active；必须由服务器校验记录晋级。
    status = "rejected" if requested_status == "rejected" else "shadow"
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO model_registry
              (model_key, version, status, trained_as_of, train_range, test_range,
               feature_names_json, params_json, metrics_json, source_refs_json,
               artifact_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                model["model_key"],
                model["version"],
                status,
                model["trained_as_of"],
                model.get("train_range"),
                model.get("test_range"),
                _json(model.get("feature_names", [])),
                _json(model.get("params", {})),
                _json(model.get("metrics", {})),
                _json(model.get("source_refs", [])),
                _json(model.get("artifact", {})),
                now,
            ),
        )


def register_policy_candidate(policy: dict) -> None:
    """登记一个不可拆分的完整策略候选；登记本身永远不会改变生产策略。"""
    components = policy.get("component_versions") or {}
    missing = POLICY_REQUIRED_COMPONENTS - set(components)
    if missing:
        raise ValueError(f"完整策略缺少组件: {sorted(missing)}")
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO policy_registry
              (policy_version, research_status, trained_as_of, train_range, test_range,
               component_versions_json, metrics_json, evidence_json,
               source_refs_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                policy["policy_version"],
                (
                    "rejected"
                    if policy.get("research_status") == "rejected"
                    else "shadow"
                ),
                policy["trained_as_of"],
                policy.get("train_range"),
                policy.get("test_range"),
                _json(components),
                _json(policy.get("metrics", {})),
                _json(policy.get("evidence", {})),
                _json(policy.get("source_refs", [])),
                now,
            ),
        )


def _contains_caller_pass_flag(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            str(key).lower() == "passed" or _contains_caller_pass_flag(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_caller_pass_flag(item) for item in value)
    return False


def register_policy_evidence_artifact(
    policy_version: str,
    artifact_type: str,
    experiment_ref: str,
    artifact: dict,
) -> dict:
    """不可变地登记研究产物；校验阶段只能引用 artifact_id。"""
    if artifact_type not in {"power_analysis", "atomic_policy_evaluation"}:
        raise ValueError("unsupported_policy_evidence_type")
    experiment_ref = str(experiment_ref or "").strip()
    if len(experiment_ref) < 3:
        raise ValueError("experiment_reference_required")
    if not isinstance(artifact, dict) or not artifact:
        raise ValueError("policy_evidence_artifact_required")
    if _contains_caller_pass_flag(artifact):
        raise ValueError("caller_asserted_pass_flag_forbidden")

    canonical = {
        **artifact,
        "artifact_type": artifact_type,
        "policy_version": policy_version,
        "experiment_ref": experiment_ref,
    }
    dataset_hash = str(canonical.get("dataset_hash") or "").lower()
    code_sha = str(canonical.get("code_sha") or "").lower()
    if not _is_sha256(dataset_hash):
        raise ValueError("dataset_hash_invalid")
    if not _is_git_sha(code_sha):
        raise ValueError("code_sha_invalid")
    artifact_hash = model_artifact_hash(canonical)
    artifact_id = hashlib.sha256(
        f"{policy_version}|{artifact_type}|{artifact_hash}".encode()
    ).hexdigest()[:24]
    now = datetime.now().astimezone().isoformat(timespec="microseconds")
    with _get_conn() as conn:
        candidate = conn.execute(
            "SELECT 1 FROM policy_registry WHERE policy_version = ?",
            (policy_version,),
        ).fetchone()
        if candidate is None:
            raise ValueError("policy_not_registered")
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO policy_evidence_artifacts
              (artifact_id, policy_version, artifact_type, experiment_ref,
               dataset_hash, code_sha, artifact_hash, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact_id,
                policy_version,
                artifact_type,
                experiment_ref,
                dataset_hash,
                code_sha,
                artifact_hash,
                _json(canonical),
                now,
            ),
        )
        row = conn.execute(
            "SELECT * FROM policy_evidence_artifacts WHERE artifact_id = ?",
            (artifact_id,),
        ).fetchone()
        if row is None or row["artifact_hash"] != artifact_hash:
            raise RuntimeError("policy_evidence_artifact_collision")
    return {
        "artifact_id": artifact_id,
        "artifact_hash": artifact_hash,
        "created": cursor.rowcount == 1,
    }


def _active_policy_version_in_connection(conn) -> str:
    release = conn.execute("""
        SELECT target_policy_version, policy_version
        FROM policy_release_events
        WHERE action IN ('activated', 'rolled_back')
        ORDER BY created_at DESC, rowid DESC LIMIT 1
    """).fetchone()
    if release is None:
        return "baseline-only"
    return release["target_policy_version"] or release["policy_version"]


def _read_policy_evidence_artifact(
    conn,
    artifact_id: str,
    *,
    policy_version: str,
    artifact_type: str,
) -> dict | None:
    row = conn.execute(
        """
        SELECT * FROM policy_evidence_artifacts
        WHERE artifact_id = ? AND policy_version = ? AND artifact_type = ?
        """,
        (artifact_id, policy_version, artifact_type),
    ).fetchone()
    if row is None:
        return None
    payload = _loads(row["payload_json"], {})
    if (
        not isinstance(payload, dict)
        or model_artifact_hash(payload) != row["artifact_hash"]
    ):
        return None
    return {**dict(row), "payload": payload}


def _as_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _power_artifact_is_releaseable(payload: dict, now: datetime) -> tuple[bool, dict]:
    raw_metrics = payload.get("metrics")
    metrics: dict[str, Any] = raw_metrics if isinstance(raw_metrics, dict) else {}
    try:
        independent_months = int(metrics.get("independent_months", 0) or 0)
        requested_months = int(metrics.get("required_independent_months", 6) or 6)
        sample_count = int(metrics.get("sample_count", 0) or 0)
    except (TypeError, ValueError):
        independent_months = requested_months = sample_count = 0
    required_months = max(requested_months, 6)
    achieved_power = _as_float(metrics.get("achieved_power"))
    monte_carlo_se = _as_float(metrics.get("monte_carlo_standard_error"))
    forward_window_end = str(payload.get("forward_window_end") or "").strip()
    try:
        forward_end = datetime.fromisoformat(forward_window_end)
        window_complete = forward_end.tzinfo is not None and forward_end <= now
    except ValueError:
        window_complete = False
    valid = bool(
        window_complete
        and independent_months >= required_months
        and sample_count >= 80
        and achieved_power is not None
        and achieved_power >= 0.80
        and monte_carlo_se is not None
        and 0 <= monte_carlo_se <= 0.01
    )
    return valid, {
        "forward_window_end": forward_window_end,
        "independent_months": independent_months,
        "required_independent_months": required_months,
    }


def _atomic_artifact_is_releaseable(payload: dict, runtime_manifest: dict) -> bool:
    raw_metrics = payload.get("metrics")
    metrics: dict[str, Any] = raw_metrics if isinstance(raw_metrics, dict) else {}
    coverage = _as_float(metrics.get("coverage_ratio"))
    baseline_delta = _as_float(metrics.get("baseline_delta_pct"))
    cvar10 = _as_float(metrics.get("cvar10_pct"))
    max_drawdown = _as_float(metrics.get("max_drawdown_pct"))
    unbuyable_rate = _as_float(metrics.get("unbuyable_rate"))
    unsellable_rate = _as_float(metrics.get("unsellable_rate"))
    opportunity_cost = _as_float(metrics.get("opportunity_cost_pct"))
    reconciliation_error = _as_float(metrics.get("reconciliation_error"))
    try:
        evaluation_months = int(metrics.get("evaluation_months", 0) or 0)
    except (TypeError, ValueError):
        evaluation_months = 0
    ablations = set(metrics.get("ablation_components") or [])
    if (
        coverage is None
        or baseline_delta is None
        or cvar10 is None
        or max_drawdown is None
        or unbuyable_rate is None
        or unsellable_rate is None
        or opportunity_cost is None
        or reconciliation_error is None
    ):
        return False
    return bool(
        payload.get("runtime_policy_manifest") == runtime_manifest
        and metrics.get("execution_policy_version") == "a-share-eod-open-open-v3"
        and evaluation_months >= 6
        and ablations == set(POLICY_REQUIRED_COMPONENTS)
        and coverage >= 0.60
        and baseline_delta >= 0
        and cvar10 >= -30
        and max_drawdown >= -45
        and 0 <= unbuyable_rate <= 1
        and 0 <= unsellable_rate <= 1
        and reconciliation_error <= 1e-6
    )


def record_policy_validation(policy_version: str, evidence: dict) -> dict:
    """只从不可变实验账本取证，服务器按固定阈值导出校验结果。"""
    now = datetime.now().astimezone()
    reviewer_id = str(evidence.get("reviewer_id") or "").strip()
    ticket_ref = str(evidence.get("ticket_ref") or "").strip()
    previous_policy = str(evidence.get("previous_policy") or "").strip()
    rollback_policy = str(evidence.get("rollback_policy") or "").strip()
    reasons: list[str] = []
    if not reviewer_id:
        reasons.append("reviewer_identity_missing")
    if len(ticket_ref) < 3:
        reasons.append("ticket_reference_missing")
    if not previous_policy:
        reasons.append("previous_policy_missing")
    if not rollback_policy:
        reasons.append("rollback_policy_missing")

    forward_window_end = ""
    independent_months = 0
    required_months = 6
    power_artifact_id = str(evidence.get("power_analysis_artifact_id") or "").strip()
    atomic_artifact_id = str(
        evidence.get("atomic_policy_evaluation_artifact_id") or ""
    ).strip()
    power_artifact_hash = ""
    atomic_artifact_hash = ""
    with _get_conn() as conn:
        candidate = conn.execute(
            "SELECT * FROM policy_registry WHERE policy_version = ?",
            (policy_version,),
        ).fetchone()
        if candidate is None:
            return {"validated": False, "reason": "policy_not_registered"}
        components = _loads(candidate["component_versions_json"], {})
        candidate_evidence = _loads(candidate["evidence_json"], {})
        dataset_hash = str(candidate_evidence.get("dataset_hash") or "").lower()
        code_sha = str(candidate_evidence.get("code_sha") or "").lower()
        if not _is_sha256(dataset_hash):
            reasons.append("dataset_hash_invalid")
        if not _is_git_sha(code_sha):
            reasons.append("code_sha_invalid")
        runtime_policy_manifest = candidate_evidence.get("runtime_policy_manifest")
        if not isinstance(runtime_policy_manifest, dict) or not runtime_policy_manifest:
            reasons.append("runtime_policy_manifest_missing")

        power = _read_policy_evidence_artifact(
            conn,
            power_artifact_id,
            policy_version=policy_version,
            artifact_type="power_analysis",
        )
        if power is None:
            reasons.append("power_analysis_not_verified")
        else:
            power_artifact_hash = power["artifact_hash"]
            power_payload = power["payload"]
            power_valid, power_fields = _power_artifact_is_releaseable(
                power_payload, now
            )
            forward_window_end = power_fields["forward_window_end"]
            independent_months = power_fields["independent_months"]
            required_months = power_fields["required_independent_months"]
            if (
                power_payload.get("dataset_hash") != dataset_hash
                or power_payload.get("code_sha") != code_sha
                or not power_valid
            ):
                reasons.append("power_analysis_not_verified")

        atomic = _read_policy_evidence_artifact(
            conn,
            atomic_artifact_id,
            policy_version=policy_version,
            artifact_type="atomic_policy_evaluation",
        )
        if atomic is None:
            reasons.append("atomic_policy_evaluation_not_verified")
        else:
            atomic_artifact_hash = atomic["artifact_hash"]
            atomic_payload = atomic["payload"]
            if (
                atomic_payload.get("dataset_hash") != dataset_hash
                or atomic_payload.get("code_sha") != code_sha
                or not _atomic_artifact_is_releaseable(
                    atomic_payload, runtime_policy_manifest
                )
            ):
                reasons.append("atomic_policy_evaluation_not_verified")

        active_policy = _active_policy_version_in_connection(conn)
        if previous_policy and previous_policy != active_policy:
            reasons.append("previous_policy_is_stale")
        if rollback_policy and rollback_policy != previous_policy:
            reasons.append("rollback_policy_must_equal_previous_policy")
        source_refs = set(_loads(candidate["source_refs_json"], []))
        from utils.decision_versions import VALIDATED_MODEL_SOURCE_REFS

        if not VALIDATED_MODEL_SOURCE_REFS.issubset(source_refs):
            reasons.append("policy_point_in_time_evidence_missing")

        for key in sorted(POLICY_REQUIRED_COMPONENTS):
            row = conn.execute(
                "SELECT * FROM model_registry WHERE model_key = ? AND version = ?",
                (key, components.get(key)),
            ).fetchone()
            if row is None:
                reasons.append(f"{key}_model_missing")
                continue
            params = _loads(row["params_json"], {})
            artifact = _loads(row["artifact_json"], {})
            diagnostics = params.get("optimizer_diagnostics") or artifact.get(
                "training_diagnostics", {}
            )
            model_refs = set(_loads(row["source_refs_json"], []))
            if params.get("validation_status") != "active":
                reasons.append(f"{key}_walk_forward_not_active")
            if params.get("calibration_status") != "independent_holdout":
                reasons.append(f"{key}_calibration_missing")
            if (
                diagnostics.get("converged") is not True
                or diagnostics.get("releaseable") is not True
            ):
                reasons.append(f"{key}_optimizer_not_releaseable")
            if (
                (diagnostics.get("coefficient_stability") or {}).get("stable")
                is not True
                or (diagnostics.get("calibration") or {}).get("releaseable") is not True
                or (diagnostics.get("feature_drift") or {}).get("releaseable")
                is not True
            ):
                reasons.append(f"{key}_model_diagnostics_incomplete")
            if params.get("artifact_hash") != model_artifact_hash(artifact):
                reasons.append(f"{key}_artifact_hash_mismatch")
            if params.get("dataset_hash") != dataset_hash:
                reasons.append(f"{key}_dataset_hash_mismatch")
            if params.get("code_sha") != code_sha:
                reasons.append(f"{key}_code_sha_mismatch")
            if not VALIDATED_MODEL_SOURCE_REFS.issubset(model_refs):
                reasons.append(f"{key}_point_in_time_evidence_missing")

        canonical_evidence = {
            "policy_version": policy_version,
            "forward_window_end": forward_window_end,
            "independent_months": independent_months,
            "required_independent_months": required_months,
            "dataset_hash": dataset_hash,
            "code_sha": code_sha,
            "reviewer_id": reviewer_id,
            "ticket_ref": ticket_ref,
            "power_analysis_artifact_id": power_artifact_id,
            "power_analysis_artifact_hash": power_artifact_hash,
            "atomic_policy_evaluation_artifact_id": atomic_artifact_id,
            "atomic_policy_evaluation_artifact_hash": atomic_artifact_hash,
            "previous_policy": previous_policy,
            "rollback_policy": rollback_policy,
        }
        evidence_hash = hashlib.sha256(
            orjson.dumps(canonical_evidence, option=orjson.OPT_SORT_KEYS)
        ).hexdigest()
        validation_id = hashlib.sha256(
            f"{policy_version}|{evidence_hash}".encode()
        ).hexdigest()[:24]
        status = "rejected" if reasons else "validated"
        conn.execute(
            """
            INSERT OR IGNORE INTO policy_validation_records
              (validation_id, policy_version, status, forward_window_end,
               independent_months, required_independent_months, dataset_hash,
               code_sha, reviewer_id, ticket_ref, evidence_hash, payload_json,
               reason_codes_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                validation_id,
                policy_version,
                status,
                forward_window_end,
                independent_months,
                required_months,
                dataset_hash,
                code_sha,
                reviewer_id,
                ticket_ref,
                evidence_hash,
                _json(canonical_evidence),
                _json(sorted(set(reasons))),
                now.isoformat(timespec="microseconds"),
            ),
        )
        if not reasons:
            conn.execute(
                "UPDATE policy_registry SET research_status = 'validated' "
                "WHERE policy_version = ? AND research_status = 'shadow'",
                (policy_version,),
            )
            for key, version in components.items():
                conn.execute(
                    "UPDATE model_registry SET status = 'validated' "
                    "WHERE model_key = ? AND version = ? AND status = 'shadow'",
                    (key, version),
                )
    return {
        "validated": not reasons,
        "validation_id": validation_id,
        "evidence_hash": evidence_hash,
        "reason": None if not reasons else "validation_evidence_rejected",
        "reason_codes": sorted(set(reasons)),
    }


def _is_sha256(value) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text.lower())


def _is_git_sha(value) -> bool:
    text = str(value or "")
    return len(text) == 40 and all(char in "0123456789abcdef" for char in text.lower())


def activate_policy(policy_version: str, release_request: dict) -> dict:
    """激活完整策略；只信任服务器已落账的 validation record。"""
    required = (
        "operator_id",
        "reviewer_id",
        "ticket_ref",
        "change_reason",
        "evidence_hash",
        "previous_policy",
        "rollback_policy",
    )
    missing = [
        key for key in required if not str(release_request.get(key) or "").strip()
    ]
    if missing:
        return {
            "activated": False,
            "reason": "release_request_incomplete",
            "missing": missing,
        }
    operator_id = str(release_request["operator_id"]).strip()
    reviewer_id = str(release_request["reviewer_id"]).strip()
    if operator_id == reviewer_id:
        return {"activated": False, "reason": "two_person_review_required"}
    now = datetime.now().astimezone().isoformat(timespec="microseconds")
    release_id = uuid4().hex[:24]
    with _get_conn() as conn:
        candidate = conn.execute(
            "SELECT * FROM policy_registry WHERE policy_version = ?", (policy_version,)
        ).fetchone()
        if candidate is None:
            return {"activated": False, "reason": "policy_not_registered"}
        if candidate["research_status"] != "validated":
            return {
                "activated": False,
                "reason": "policy_not_validated",
                "research_status": candidate["research_status"],
            }
        validation = conn.execute(
            """
            SELECT * FROM policy_validation_records
            WHERE policy_version = ? AND status = 'validated'
            ORDER BY created_at DESC, rowid DESC LIMIT 1
        """,
            (policy_version,),
        ).fetchone()
        if validation is None:
            return {"activated": False, "reason": "server_validation_record_missing"}
        if (
            validation["evidence_hash"] != release_request["evidence_hash"]
            or validation["reviewer_id"] != reviewer_id
            or validation["ticket_ref"] != str(release_request["ticket_ref"]).strip()
        ):
            return {"activated": False, "reason": "release_request_validation_mismatch"}
        validation_payload = _loads(validation["payload_json"], {})
        previous_policy = str(release_request["previous_policy"]).strip()
        rollback_policy = str(release_request["rollback_policy"]).strip()
        if (
            validation_payload.get("previous_policy") != previous_policy
            or validation_payload.get("rollback_policy") != rollback_policy
            or rollback_policy != previous_policy
            or _active_policy_version_in_connection(conn) != previous_policy
        ):
            return {
                "activated": False,
                "reason": "release_policy_lineage_mismatch",
            }
        source_refs = set(_loads(candidate["source_refs_json"], []))
        from utils.decision_versions import VALIDATED_MODEL_SOURCE_REFS

        if not VALIDATED_MODEL_SOURCE_REFS.issubset(source_refs):
            return {"activated": False, "reason": "point_in_time_evidence_missing"}
        components = _loads(candidate["component_versions_json"], {})
        unavailable = []
        for key in sorted(POLICY_REQUIRED_COMPONENTS):
            row = conn.execute(
                "SELECT status, params_json, artifact_json, source_refs_json FROM model_registry "
                "WHERE model_key = ? AND version = ?",
                (key, components.get(key)),
            ).fetchone()
            if row is None:
                unavailable.append(f"{key}:missing")
                continue
            model_refs = set(_loads(row["source_refs_json"], []))
            params = _loads(row["params_json"], {})
            artifact = _loads(row["artifact_json"], {})
            if row["status"] != "validated":
                unavailable.append(f"{key}:{row['status']}")
            elif not VALIDATED_MODEL_SOURCE_REFS.issubset(model_refs):
                unavailable.append(f"{key}:evidence_missing")
            elif params.get("artifact_hash") != model_artifact_hash(artifact):
                unavailable.append(f"{key}:artifact_hash_mismatch")
            elif params.get("dataset_hash") != validation["dataset_hash"]:
                unavailable.append(f"{key}:dataset_hash_mismatch")
            elif params.get("code_sha") != validation["code_sha"]:
                unavailable.append(f"{key}:code_sha_mismatch")
            else:
                diagnostics = params.get("optimizer_diagnostics") or artifact.get(
                    "training_diagnostics", {}
                )
                if (
                    (diagnostics.get("coefficient_stability") or {}).get("stable")
                    is not True
                    or (diagnostics.get("calibration") or {}).get("releaseable")
                    is not True
                    or (diagnostics.get("feature_drift") or {}).get("releaseable")
                    is not True
                ):
                    unavailable.append(f"{key}:diagnostics_incomplete")
        if unavailable:
            return {
                "activated": False,
                "reason": "policy_components_not_releaseable",
                "components": unavailable,
            }
        release_evidence = {
            "validation_id": validation["validation_id"],
            "evidence_hash": validation["evidence_hash"],
            "operator_id": operator_id,
            "reviewer_id": reviewer_id,
            "ticket_ref": validation["ticket_ref"],
            "change_reason": str(release_request["change_reason"]).strip(),
            "previous_policy": previous_policy,
            "rollback_policy": rollback_policy,
            "dataset_hash": validation["dataset_hash"],
            "code_sha": validation["code_sha"],
        }
        conn.execute(
            """
            INSERT INTO policy_release_events
              (release_id, policy_version, action, target_policy_version,
               evidence_json, reason_codes_json, created_at)
            VALUES (?, ?, 'activated', ?, ?, '[]', ?)
        """,
            (release_id, policy_version, policy_version, _json(release_evidence), now),
        )
    try:
        from utils.operations_store import record_audit

        record_audit(
            actor=operator_id,
            role="admin",
            action="activate_policy",
            outcome="activated",
            change_reason=release_evidence["change_reason"],
            metadata={
                "policy_version": policy_version,
                "release_id": release_id,
                "reviewer_id": reviewer_id,
                "ticket_ref": release_evidence["ticket_ref"],
                "evidence_hash": release_evidence["evidence_hash"],
            },
        )
    except Exception:
        # 主账本的 release event 已经是权威记录；运维审计库不得使发布半途回滚。
        pass
    return {
        "activated": True,
        "release_id": release_id,
        "policy_version": policy_version,
    }


def rollback_active_policy(target_policy_version: str, rollback_request: dict) -> dict:
    """只允许回到当前策略激活时预先登记的 rollback policy。"""
    required = (
        "operator_id",
        "reviewer_id",
        "ticket_ref",
        "change_reason",
        "expected_current_policy",
    )
    missing = [
        key for key in required if not str(rollback_request.get(key) or "").strip()
    ]
    target_policy_version = str(target_policy_version or "").strip()
    if not target_policy_version:
        missing.append("target_policy_version")
    if missing:
        return {
            "rolled_back": False,
            "reason": "rollback_request_incomplete",
            "missing": sorted(set(missing)),
        }
    operator_id = str(rollback_request["operator_id"]).strip()
    reviewer_id = str(rollback_request["reviewer_id"]).strip()
    if operator_id == reviewer_id:
        return {"rolled_back": False, "reason": "two_person_review_required"}

    now = datetime.now().astimezone().isoformat(timespec="microseconds")
    release_id = uuid4().hex[:24]
    with _get_conn() as conn:
        current_policy = _active_policy_version_in_connection(conn)
        expected_current = str(rollback_request["expected_current_policy"]).strip()
        if current_policy != expected_current:
            return {
                "rolled_back": False,
                "reason": "rollback_current_policy_mismatch",
                "current_policy": current_policy,
            }
        if current_policy == "baseline-only":
            return {"rolled_back": False, "reason": "baseline_has_no_rollback"}

        activation = conn.execute(
            """
            SELECT * FROM policy_release_events
            WHERE action='activated' AND target_policy_version=?
            ORDER BY created_at DESC, rowid DESC LIMIT 1
            """,
            (current_policy,),
        ).fetchone()
        if activation is None:
            return {
                "rolled_back": False,
                "reason": "activation_lineage_missing",
            }
        activation_evidence = _loads(activation["evidence_json"], {})
        approved_target = str(activation_evidence.get("rollback_policy") or "")
        if target_policy_version != approved_target:
            return {
                "rolled_back": False,
                "reason": "rollback_target_not_preapproved",
                "approved_target": approved_target or None,
            }
        if target_policy_version != "baseline-only":
            target = conn.execute(
                "SELECT research_status FROM policy_registry WHERE policy_version=?",
                (target_policy_version,),
            ).fetchone()
            if target is None or target["research_status"] != "validated":
                return {
                    "rolled_back": False,
                    "reason": "rollback_target_unavailable",
                }

        rollback_evidence = {
            "operator_id": operator_id,
            "reviewer_id": reviewer_id,
            "ticket_ref": str(rollback_request["ticket_ref"]).strip(),
            "change_reason": str(rollback_request["change_reason"]).strip(),
            "previous_policy": current_policy,
            "rollback_policy": target_policy_version,
            "activation_release_id": activation["release_id"],
        }
        conn.execute(
            """
            INSERT INTO policy_release_events
              (release_id, policy_version, action, target_policy_version,
               evidence_json, reason_codes_json, created_at)
            VALUES (?, ?, 'rolled_back', ?, ?, '[]', ?)
            """,
            (
                release_id,
                current_policy,
                target_policy_version,
                _json(rollback_evidence),
                now,
            ),
        )
    try:
        from utils.operations_store import record_audit

        record_audit(
            actor=operator_id,
            role="admin",
            action="rollback_policy",
            outcome="rolled_back",
            change_reason=rollback_evidence["change_reason"],
            metadata={
                "release_id": release_id,
                "previous_policy": current_policy,
                "target_policy": target_policy_version,
                "reviewer_id": reviewer_id,
                "ticket_ref": rollback_evidence["ticket_ref"],
            },
        )
    except Exception:
        # release event 是权威记录；运维审计库故障不能造成半回滚。
        pass
    return {
        "rolled_back": True,
        "release_id": release_id,
        "previous_policy": current_policy,
        "policy_version": target_policy_version,
    }


def get_active_policy() -> dict | None:
    with _get_read_conn() as conn:
        release = conn.execute("""
            SELECT * FROM policy_release_events
            WHERE action IN ('activated', 'rolled_back')
            ORDER BY created_at DESC, rowid DESC LIMIT 1
        """).fetchone()
        if release is None:
            return None
        target = release["target_policy_version"] or release["policy_version"]
        row = conn.execute(
            "SELECT * FROM policy_registry WHERE policy_version = ?", (target,)
        ).fetchone()
    if row is None:
        return None
    item = dict(row)
    for key, fallback in (
        ("component_versions_json", {}),
        ("metrics_json", {}),
        ("evidence_json", {}),
        ("source_refs_json", []),
    ):
        item[key.removesuffix("_json")] = _loads(item.pop(key), fallback)
    item["release_id"] = release["release_id"]
    item["released_at"] = release["created_at"]
    return item


def get_active_policy_models() -> tuple[dict[str, dict], str]:
    policy = get_active_policy()
    if not policy:
        return {}, "baseline-only"
    models = {}
    with _get_read_conn() as conn:
        for key, version in policy["component_versions"].items():
            row = conn.execute(
                "SELECT * FROM model_registry WHERE model_key = ? AND version = ?",
                (key, version),
            ).fetchone()
            if row is None:
                return {}, "baseline-only"
            item = dict(row)
            for field, fallback in (
                ("feature_names_json", []),
                ("params_json", {}),
                ("metrics_json", {}),
                ("source_refs_json", []),
                ("artifact_json", {}),
            ):
                item[field.removesuffix("_json")] = _loads(item.pop(field), fallback)
            models[key] = item
    if POLICY_REQUIRED_COMPONENTS - set(models):
        return {}, "baseline-only"
    return models, policy["policy_version"]


def promote_model_bundle(
    version: str,
    validation_status: dict[str, str],
    required: tuple[str, ...] = ("market",),
) -> dict:
    """兼容入口：逐层晋级已被禁用，发布必须走 activate_policy。"""
    return {"promoted": False, "reason": "legacy_layer_promotion_disabled"}


def list_pending_outcome_candidates() -> list[dict]:
    """返回仍需真实行情回填的全部决策候选，包括 observe/avoid。"""
    with _get_read_conn() as conn:
        candidate_rows = conn.execute("""
            SELECT r.run_id, r.trade_date, r.stage,
                   c.code, c.name, c.action
            FROM decision_candidates c
            JOIN decision_runs r ON r.run_id = c.run_id
            ORDER BY r.trade_date, r.stage, c.rank_no
        """).fetchall()
        outcome_rows = conn.execute("""
            WITH latest AS (
                SELECT run_id, code, MAX(observation_no) AS observation_no
                FROM decision_outcomes
                WHERE source_snapshot_id != 'legacy-unverified'
                  AND length(source_snapshot_id) = 64
                GROUP BY run_id, code
            )
            SELECT o.*
            FROM decision_outcomes o
            JOIN latest l
              ON l.run_id = o.run_id
             AND l.code = o.code
             AND l.observation_no = o.observation_no
        """).fetchall()
    latest = {
        (item["run_id"], item["code"]): item
        for row in outcome_rows
        for item in (_verified_outcome(row),)
    }
    pending = []
    for row in candidate_rows:
        item = dict(row)
        outcome = latest.get((item["run_id"], item["code"]))
        item["outcome_status"] = outcome["status"] if outcome else "pending"
        if item["outcome_status"] not in {"complete", "invalid"}:
            pending.append(item)
    return pending


def append_decision_outcome(outcome: dict) -> bool:
    """追加一个结果状态；内容相同的 worker 重试不重复落账。"""
    payload = _canonical_outcome(outcome)
    content_id = _outcome_id(payload)
    now = datetime.now().astimezone().isoformat(timespec="microseconds")
    with _get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT * FROM decision_outcomes WHERE outcome_id = ?", (content_id,)
        ).fetchone()
        if existing is not None:
            _verified_outcome(existing)
            return False
        observation_no = conn.execute(
            """
            SELECT COALESCE(MAX(observation_no), 0) + 1
            FROM decision_outcomes
            WHERE run_id = ? AND code = ?
            """,
            (payload["run_id"], payload["code"]),
        ).fetchone()[0]
        conn.execute(
            DECISION_OUTCOME_INSERT,
            (
                content_id,
                observation_no,
                *(payload[field] for field in OUTCOME_CONTENT_FIELDS),
                now,
            ),
        )
    return True


def outcome_summary() -> dict:
    """同时衡量命中率、错过上涨和躲过下跌，避免只看推荐票。"""
    with _get_read_conn() as conn:
        rows = conn.execute("""
            WITH latest AS (
                SELECT run_id, code, MAX(observation_no) AS observation_no
                FROM decision_outcomes
                WHERE source_snapshot_id != 'legacy-unverified'
                  AND length(source_snapshot_id) = 64
                GROUP BY run_id, code
            )
            SELECT o.*
            FROM decision_outcomes o
            JOIN latest l
              ON l.run_id = o.run_id
             AND l.code = o.code
             AND l.observation_no = o.observation_no
            WHERE o.status = 'complete' AND o.net_ret_5 IS NOT NULL
        """).fetchall()
    verified_rows = [_verified_outcome(row) for row in rows]
    result: dict[str, object] = {}
    for action in ("buy", "observe", "avoid"):
        values = [row["net_ret_5"] for row in verified_rows if row["action"] == action]
        result[action] = {
            "count": len(values),
            "win_rate": round(sum(value > 0 for value in values) / len(values), 4)
            if values
            else None,
            "avg_net_ret_5": round(sum(values) / len(values), 4) if values else None,
        }
    non_buy = [row["net_ret_5"] for row in verified_rows if row["action"] != "buy"]
    result["missed_winner_rate"] = (
        round(sum(value > 0 for value in non_buy) / len(non_buy), 4)
        if non_buy
        else None
    )
    return result


def list_decision_outcomes(limit: int = 100) -> list[dict]:
    bounded = min(max(int(limit), 1), 200)
    with _get_read_conn() as conn:
        rows = conn.execute(
            """
            WITH latest AS (
                SELECT run_id, code, MAX(observation_no) AS observation_no
                FROM decision_outcomes
                WHERE source_snapshot_id != 'legacy-unverified'
                  AND length(source_snapshot_id) = 64
                GROUP BY run_id, code
            )
            SELECT o.*
            FROM decision_outcomes o
            JOIN latest l
              ON l.run_id = o.run_id
             AND l.code = o.code
             AND l.observation_no = o.observation_no
            ORDER BY o.trade_date DESC, o.updated_at DESC, o.run_id DESC, o.code
            LIMIT ?
            """,
            (bounded,),
        ).fetchall()
    return [_verified_outcome(row) for row in rows]


def save_evolution_run(run: dict) -> str:
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    evolution_id = run.get("evolution_id") or uuid4().hex[:24]
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO evolution_runs
              (evolution_id, trade_date, status, data_version, universe_count,
               covered_count, coverage_ratio, labels_updated, dataset_rows,
               challenger_version, promotion_status, reason_codes_json,
               metrics_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                evolution_id,
                run["trade_date"],
                run["status"],
                run["data_version"],
                run["universe_count"],
                run["covered_count"],
                run["coverage_ratio"],
                run.get("labels_updated", 0),
                run.get("dataset_rows", 0),
                run.get("challenger_version"),
                run.get("promotion_status", "not_evaluated"),
                _json(run.get("reason_codes", [])),
                _json(run.get("metrics", {})),
                now,
                now,
            ),
        )
    return evolution_id


def get_latest_evolution() -> dict | None:
    with _get_read_conn() as conn:
        row = conn.execute(
            "SELECT * FROM evolution_runs "
            "ORDER BY trade_date DESC, created_at DESC, rowid DESC LIMIT 1"
        ).fetchone()
    if row is None:
        return None
    item = dict(row)
    item["reason_codes"] = _loads(item.pop("reason_codes_json"), [])
    item["metrics"] = _loads(item.pop("metrics_json"), {})
    item["outcomes"] = outcome_summary()
    return item


def get_active_models() -> dict[str, dict]:
    return get_active_policy_models()[0]


def list_models() -> list[dict]:
    """返回每层当前运行模型，并附上最近一次挑战结果。"""
    policy = get_active_policy()
    active_components = (policy or {}).get("component_versions") or {}
    with _get_read_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM model_registry
            ORDER BY model_key, trained_as_of DESC, created_at DESC, version DESC
        """).fetchall()
    grouped: dict[str, list] = {}
    for row in rows:
        grouped.setdefault(row["model_key"], []).append(row)
    result = []
    for model_key, attempts in grouped.items():
        active = next(
            (
                row
                for row in attempts
                if active_components.get(model_key) == row["version"]
            ),
            None,
        )
        chosen = active or attempts[0]
        item = dict(chosen)
        for key, fallback in (
            ("feature_names_json", []),
            ("params_json", {}),
            ("metrics_json", {}),
            ("source_refs_json", []),
            ("artifact_json", {}),
        ):
            item[key.removesuffix("_json")] = _loads(item.pop(key), fallback)
        item.pop("artifact", None)
        item["model_key"] = model_key
        item["mode"] = (
            "active"
            if active
            else ("shadow" if attempts[0]["status"] == "shadow" else "off")
        )
        item["active_version"] = active["version"] if active else None
        item["latest_attempt_version"] = attempts[0]["version"]
        item["latest_attempt_status"] = attempts[0]["status"]
        result.append(item)
    return result
