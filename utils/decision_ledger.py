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


def _json(value: Any) -> str:
    return orjson.dumps(value if value is not None else {}).decode()


def _loads(value: str | None, fallback):
    if not value:
        return fallback
    try:
        return orjson.loads(value)
    except Exception:
        return fallback


def init_decision_ledger() -> None:
    with _get_conn() as conn:
        conn.execute("""
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
                updated_at TEXT NOT NULL,
                UNIQUE(trade_date, stage, strategy_version, data_version)
            )
        """)
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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_decision_runs_date ON decision_runs(trade_date, stage)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_candidates_run_rank ON decision_candidates(run_id, rank_no)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_event_code_time ON event_evidence(code, published_at)")


def make_run_id(trade_date: str, stage: str, strategy: str, data: str) -> str:
    raw = f"{trade_date}|{stage}|{strategy}|{data}".encode()
    return hashlib.sha256(raw).hexdigest()[:24]


def save_decision_run(run: dict, candidates: list[dict]) -> str:
    init_decision_ledger()
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    run_id = run.get("run_id") or make_run_id(
        run["trade_date"], run["stage"], run["strategy_version"], run["data_version"]
    )
    with _get_conn() as conn:
        conn.execute("""
            INSERT INTO decision_runs
              (run_id, trade_date, stage, as_of, status, final_action,
               strategy_version, feature_version, model_version, data_version,
               source_refs_json, market_json, evaluation_json, reason_codes_json,
               created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
              as_of=excluded.as_of, status=excluded.status,
              final_action=excluded.final_action, model_version=excluded.model_version,
              source_refs_json=excluded.source_refs_json,
              market_json=excluded.market_json,
              evaluation_json=excluded.evaluation_json,
              reason_codes_json=excluded.reason_codes_json,
              updated_at=excluded.updated_at
        """, (
            run_id, run["trade_date"], run["stage"], run["as_of"], run["status"],
            run["final_action"], run["strategy_version"], run["feature_version"],
            run.get("model_version", "baseline"), run["data_version"],
            _json(run.get("source_refs", [])), _json(run.get("market", {})),
            _json(run.get("evaluation", {})), _json(run.get("reason_codes", [])),
            run.get("created_at", now), now,
        ))
        conn.execute("DELETE FROM decision_candidates WHERE run_id = ?", (run_id,))
        for index, candidate in enumerate(candidates, start=1):
            conn.execute("""
                INSERT INTO decision_candidates
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
            f"SELECT run_id FROM decision_runs {where} ORDER BY trade_date DESC, as_of DESC LIMIT 1",
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
            INSERT INTO model_registry
              (model_key, version, status, trained_as_of, train_range, test_range,
               feature_names_json, params_json, metrics_json, source_refs_json,
               artifact_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(model_key, version) DO UPDATE SET
              status=excluded.status, trained_as_of=excluded.trained_as_of,
              train_range=excluded.train_range, test_range=excluded.test_range,
              feature_names_json=excluded.feature_names_json,
              params_json=excluded.params_json, metrics_json=excluded.metrics_json,
              source_refs_json=excluded.source_refs_json,
              artifact_json=excluded.artifact_json, created_at=excluded.created_at
        """, (
            model["model_key"], model["version"], model.get("status", "shadow"),
            model["trained_as_of"], model.get("train_range"), model.get("test_range"),
            _json(model.get("feature_names", [])), _json(model.get("params", {})),
            _json(model.get("metrics", {})), _json(model.get("source_refs", [])),
            _json(model.get("artifact", {})), now,
        ))


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
    """返回每个模型最新注册状态，供决策页解释为何启用或降级。"""
    init_decision_ledger()
    with _get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM model_registry ORDER BY model_key, trained_as_of DESC
        """).fetchall()
    result, seen = [], set()
    for row in rows:
        if row["model_key"] in seen:
            continue
        seen.add(row["model_key"])
        item = dict(row)
        for key, fallback in (
            ("feature_names_json", []), ("params_json", {}), ("metrics_json", {}),
            ("source_refs_json", []), ("artifact_json", {}),
        ):
            item[key.removesuffix("_json")] = _loads(item.pop(key), fallback)
        item.pop("artifact", None)
        result.append(item)
    return result
