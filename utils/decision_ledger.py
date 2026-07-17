"""版本化决策账本。

账本保存收盘候选、盘前复核、模型注册和逐票证据链。
表位于现有 data/views.db，并使用同一套 WAL/并发连接策略。
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

import orjson

from views.view_manager import _get_conn


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


def _json(value: Any) -> str:
    return orjson.dumps(value if value is not None else {}).decode()


def _loads(value: str | None, fallback):
    if not value:
        return fallback
    try:
        return orjson.loads(value)
    except Exception:
        return fallback


def _table_exists(conn, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone() is not None


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
    conn.execute(DECISION_RUNS_SCHEMA.replace("decision_runs", "decision_runs_v2_migration"))
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
                days_tracked INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                updated_at TEXT NOT NULL,
                PRIMARY KEY(run_id, code),
                FOREIGN KEY(run_id) REFERENCES decision_runs(run_id) ON DELETE CASCADE
            )
        """)
        conn.execute("""
            INSERT INTO decision_outcomes_v2_migration
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
        conn.execute("ALTER TABLE decision_candidates_v2_migration RENAME TO decision_candidates")
    if has_outcomes:
        conn.execute("ALTER TABLE decision_outcomes_v2_migration RENAME TO decision_outcomes")
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError(f"决策账本迁移后外键校验失败: {len(violations)}")


def init_decision_ledger() -> None:
    with _get_conn() as conn:
        _migrate_append_only_runs(conn)
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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS event_evidence (
                event_id TEXT PRIMARY KEY,
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
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS model_registry (
                model_key TEXT NOT NULL,
                version TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('shadow', 'active', 'rejected')),
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
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS decision_outcomes (
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
                FOREIGN KEY(run_id) REFERENCES decision_runs(run_id) ON DELETE CASCADE
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS evolution_runs (
                evolution_id TEXT PRIMARY KEY,
                trade_date TEXT NOT NULL UNIQUE,
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
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_decision_runs_date ON decision_runs(trade_date, stage)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_candidates_run_rank ON decision_candidates(run_id, rank_no)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_event_code_time ON event_evidence(code, published_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_outcomes_status ON decision_outcomes(status, trade_date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_evolution_date ON evolution_runs(trade_date)")


def make_run_id(run: dict, candidates: list[dict]) -> str:
    payload = {
        key: run.get(key)
        for key in (
            "trade_date", "stage", "as_of", "status", "final_action",
            "strategy_version", "feature_version", "model_version", "data_version",
            "source_refs", "market", "evaluation", "reason_codes",
        )
    }
    payload["candidates"] = candidates
    raw = orjson.dumps(payload, option=orjson.OPT_SORT_KEYS)
    return hashlib.sha256(raw).hexdigest()[:24]


def save_decision_run(run: dict, candidates: list[dict]) -> str:
    init_decision_ledger()
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    run_id = run.get("run_id") or make_run_id(run, candidates)
    with _get_conn() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO decision_runs
              (run_id, trade_date, stage, as_of, status, final_action,
               strategy_version, feature_version, model_version, data_version,
               source_refs_json, market_json, evaluation_json, reason_codes_json,
               created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            run_id, run["trade_date"], run["stage"], run["as_of"], run["status"],
            run["final_action"], run["strategy_version"], run["feature_version"],
            run.get("model_version", "baseline"), run["data_version"],
            _json(run.get("source_refs", [])), _json(run.get("market", {})),
            _json(run.get("evaluation", {})), _json(run.get("reason_codes", [])),
            run.get("created_at", now), now,
        ))
        for index, candidate in enumerate(candidates, start=1):
            conn.execute("""
                INSERT OR IGNORE INTO decision_candidates
                  (run_id, code, name, industry, rank_no, tie_group, action,
                   baseline_json, market_json, sector_json, stock_json,
                   events_json, reason_codes_json, explanation, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                run_id, candidate["code"], candidate.get("name"), candidate.get("industry"),
                candidate.get("rank", index), candidate.get("tie_group", 1),
                candidate.get("action", "observe"), _json(candidate.get("baseline", {})),
                _json(candidate.get("market", {})), _json(candidate.get("sector", {})),
                _json(candidate.get("stock", {})), _json(candidate.get("events", [])),
                _json(candidate.get("reason_codes", [])), candidate.get("explanation", ""), now,
            ))
    return run_id


def _candidate_from_row(row) -> dict:
    return {
        "code": row["code"], "name": row["name"], "industry": row["industry"],
        "rank": row["rank_no"], "tie_group": row["tie_group"], "action": row["action"],
        "baseline": _loads(row["baseline_json"], {}),
        "market": _loads(row["market_json"], {}),
        "sector": _loads(row["sector_json"], {}),
        "stock": _loads(row["stock_json"], {}),
        "events": _loads(row["events_json"], []),
        "reason_codes": _loads(row["reason_codes_json"], []),
        "explanation": row["explanation"] or "",
    }


def get_decision(run_id: str) -> dict | None:
    init_decision_ledger()
    with _get_conn() as conn:
        row = conn.execute("SELECT * FROM decision_runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        candidates = conn.execute(
            "SELECT * FROM decision_candidates WHERE run_id = ? ORDER BY rank_no, code", (run_id,)
        ).fetchall()
    result = dict(row)
    for key, fallback in (
        ("source_refs_json", []), ("market_json", {}),
        ("evaluation_json", {}), ("reason_codes_json", []),
    ):
        result[key.removesuffix("_json")] = _loads(result.pop(key), fallback)
    result["candidates"] = [_candidate_from_row(r) for r in candidates]
    return result


def get_latest_decision(stage: str | None = None) -> dict | None:
    init_decision_ledger()
    where, params = ("WHERE stage = ?", (stage,)) if stage else ("", ())
    with _get_conn() as conn:
        row = conn.execute(
            f"SELECT run_id FROM decision_runs {where} "
            "ORDER BY trade_date DESC, as_of DESC, created_at DESC, run_id DESC LIMIT 1",
            params,
        ).fetchone()
    return get_decision(row["run_id"]) if row else None


def save_event_evidence(event: dict) -> None:
    init_decision_ledger()
    with _get_conn() as conn:
        conn.execute("""
            INSERT INTO event_evidence
              (event_id, code, source, source_url, published_at, title, text_hash,
               raw_ref, fetched_at, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_id) DO UPDATE SET
              source_url=excluded.source_url, title=excluded.title,
              text_hash=excluded.text_hash, raw_ref=excluded.raw_ref,
              fetched_at=excluded.fetched_at, payload_json=excluded.payload_json
        """, (
            event["event_id"], event["code"], event["source"], event.get("source_url"),
            event["published_at"], event["title"], event["text_hash"],
            event.get("raw_ref"), event["fetched_at"], _json(event),
        ))


def register_model(model: dict) -> None:
    init_decision_ledger()
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    with _get_conn() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO model_registry
              (model_key, version, status, trained_as_of, train_range, test_range,
               feature_names_json, params_json, metrics_json, source_refs_json,
               artifact_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            model["model_key"], model["version"], model.get("status", "shadow"),
            model["trained_as_of"], model.get("train_range"), model.get("test_range"),
            _json(model.get("feature_names", [])), _json(model.get("params", {})),
            _json(model.get("metrics", {})), _json(model.get("source_refs", [])),
            _json(model.get("artifact", {})), now,
        ))


def promote_model_bundle(version: str, validation_status: dict[str, str],
                         required: tuple[str, ...] = ("market",)) -> dict:
    """逐层原子晋级；未通过的层继续保留各自原冠军。"""
    init_decision_ledger()
    if not all(validation_status.get(key) == "active" for key in required):
        return {"promoted": False, "reason": "required_layers_not_validated"}
    requested_active = sorted(
        key for key, status in validation_status.items() if status == "active"
    )
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT model_key FROM model_registry WHERE version = ?", (version,)
        ).fetchall()
        registered = {row["model_key"] for row in rows}
        if not set(required).issubset(registered):
            return {"promoted": False, "reason": "bundle_incomplete"}
        active_keys = [key for key in requested_active if key in registered]
        for key in active_keys:
            conn.execute(
                "UPDATE model_registry SET status = 'shadow' "
                "WHERE model_key = ? AND status = 'active'",
                (key,),
            )
            conn.execute(
                "UPDATE model_registry SET status = 'active' "
                "WHERE version = ? AND model_key = ?",
                (version, key),
            )
    return {
        "promoted": True, "version": version, "model_keys": active_keys,
        "missing_optional_layers": sorted(set(requested_active) - registered),
    }


def list_pending_outcome_candidates() -> list[dict]:
    """返回仍需真实行情回填的全部决策候选，包括 observe/avoid。"""
    init_decision_ledger()
    with _get_conn() as conn:
        rows = conn.execute("""
            SELECT r.run_id, r.trade_date, r.stage,
                   c.code, c.name, c.action,
                   COALESCE(o.status, 'pending') AS outcome_status
            FROM decision_candidates c
            JOIN decision_runs r ON r.run_id = c.run_id
            LEFT JOIN decision_outcomes o ON o.run_id = c.run_id AND o.code = c.code
            WHERE o.status IS NULL OR o.status NOT IN ('complete', 'invalid')
            ORDER BY r.trade_date, r.stage, c.rank_no
        """).fetchall()
    return [dict(row) for row in rows]


def upsert_decision_outcome(outcome: dict) -> None:
    init_decision_ledger()
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    with _get_conn() as conn:
        conn.execute("""
            INSERT INTO decision_outcomes
              (run_id, code, stage, trade_date, action, entry_date, entry_price,
               ret_1, net_ret_5, max_gain_5, max_drawdown_5, entry_feasible,
               days_tracked, status, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id, code) DO UPDATE SET
              action=excluded.action, entry_date=excluded.entry_date,
              entry_price=excluded.entry_price, ret_1=excluded.ret_1,
              net_ret_5=excluded.net_ret_5, max_gain_5=excluded.max_gain_5,
              max_drawdown_5=excluded.max_drawdown_5,
              entry_feasible=excluded.entry_feasible,
              days_tracked=excluded.days_tracked, status=excluded.status,
              updated_at=excluded.updated_at
        """, (
            outcome["run_id"], outcome["code"], outcome["stage"], outcome["trade_date"],
            outcome["action"], outcome.get("entry_date"), outcome.get("entry_price"),
            outcome.get("ret_1"), outcome.get("net_ret_5"), outcome.get("max_gain_5"),
            outcome.get("max_drawdown_5"), outcome.get("entry_feasible"),
            outcome.get("days_tracked", 0), outcome.get("status", "pending"), now,
        ))


def outcome_summary() -> dict:
    """同时衡量命中率、错过上涨和躲过下跌，避免只看推荐票。"""
    init_decision_ledger()
    with _get_conn() as conn:
        rows = [dict(row) for row in conn.execute(
            "SELECT action, net_ret_5 FROM decision_outcomes "
            "WHERE status = 'complete' AND net_ret_5 IS NOT NULL"
        ).fetchall()]
    result = {}
    for action in ("buy", "observe", "avoid"):
        values = [row["net_ret_5"] for row in rows if row["action"] == action]
        result[action] = {
            "count": len(values),
            "win_rate": round(sum(value > 0 for value in values) / len(values), 4) if values else None,
            "avg_net_ret_5": round(sum(values) / len(values), 4) if values else None,
        }
    non_buy = [row["net_ret_5"] for row in rows if row["action"] != "buy"]
    result["missed_winner_rate"] = (
        round(sum(value > 0 for value in non_buy) / len(non_buy), 4) if non_buy else None
    )
    return result


def save_evolution_run(run: dict) -> str:
    init_decision_ledger()
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    evolution_id = run.get("evolution_id") or hashlib.sha256(
        f"{run['trade_date']}|{run['data_version']}".encode()
    ).hexdigest()[:24]
    with _get_conn() as conn:
        conn.execute("""
            INSERT INTO evolution_runs
              (evolution_id, trade_date, status, data_version, universe_count,
               covered_count, coverage_ratio, labels_updated, dataset_rows,
               challenger_version, promotion_status, reason_codes_json,
               metrics_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(trade_date) DO UPDATE SET
              evolution_id=excluded.evolution_id, status=excluded.status,
              data_version=excluded.data_version, universe_count=excluded.universe_count,
              covered_count=excluded.covered_count, coverage_ratio=excluded.coverage_ratio,
              labels_updated=excluded.labels_updated, dataset_rows=excluded.dataset_rows,
              challenger_version=excluded.challenger_version,
              promotion_status=excluded.promotion_status,
              reason_codes_json=excluded.reason_codes_json,
              metrics_json=excluded.metrics_json, updated_at=excluded.updated_at
        """, (
            evolution_id, run["trade_date"], run["status"], run["data_version"],
            run["universe_count"], run["covered_count"], run["coverage_ratio"],
            run.get("labels_updated", 0), run.get("dataset_rows", 0),
            run.get("challenger_version"), run.get("promotion_status", "not_evaluated"),
            _json(run.get("reason_codes", [])), _json(run.get("metrics", {})), now, now,
        ))
    return evolution_id


def get_latest_evolution() -> dict | None:
    init_decision_ledger()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM evolution_runs ORDER BY trade_date DESC, updated_at DESC LIMIT 1"
        ).fetchone()
    if row is None:
        return None
    item = dict(row)
    item["reason_codes"] = _loads(item.pop("reason_codes_json"), [])
    item["metrics"] = _loads(item.pop("metrics_json"), {})
    item["outcomes"] = outcome_summary()
    return item


def get_active_models() -> dict[str, dict]:
    init_decision_ledger()
    with _get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM model_registry WHERE status = 'active'
            ORDER BY trained_as_of DESC
        """).fetchall()
    result = {}
    for row in rows:
        if row["model_key"] in result:
            continue
        item = dict(row)
        for key, fallback in (
            ("feature_names_json", []), ("params_json", {}), ("metrics_json", {}),
            ("source_refs_json", []), ("artifact_json", {}),
        ):
            item[key.removesuffix("_json")] = _loads(item.pop(key), fallback)
        result[item["model_key"]] = item
    return result


def list_models() -> list[dict]:
    """返回每层当前运行模型，并附上最近一次挑战结果。"""
    init_decision_ledger()
    with _get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM model_registry
            ORDER BY model_key, trained_as_of DESC, created_at DESC, version DESC
        """).fetchall()
    grouped: dict[str, list] = {}
    for row in rows:
        grouped.setdefault(row["model_key"], []).append(row)
    result = []
    for model_key, attempts in grouped.items():
        active = next((row for row in attempts if row["status"] == "active"), None)
        chosen = active or attempts[0]
        item = dict(chosen)
        for key, fallback in (
            ("feature_names_json", []), ("params_json", {}), ("metrics_json", {}),
            ("source_refs_json", []), ("artifact_json", {}),
        ):
            item[key.removesuffix("_json")] = _loads(item.pop(key), fallback)
        item.pop("artifact", None)
        item["model_key"] = model_key
        item["mode"] = "active" if active else ("shadow" if attempts[0]["status"] == "shadow" else "off")
        item["active_version"] = active["version"] if active else None
        item["latest_attempt_version"] = attempts[0]["version"]
        item["latest_attempt_status"] = attempts[0]["status"]
        result.append(item)
    return result
