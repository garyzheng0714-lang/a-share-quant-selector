"""因子信号与结果的不可变证据链。

这里只接受已绑定行情快照、已封印且包含完整因子注册表的扫描产物。
信号批次、零命中统计、具体信号与后续成交观测全部只追加，不会读取或
回填旧 ``factor_track_record``。查询函数始终使用 SQLite 只读连接。
"""

from __future__ import annotations

import hashlib
import inspect
import json
import math
import re
from collections.abc import Mapping
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import orjson
import pandas as pd

from strategy.factors import FACTOR_REGISTRY
from utils import execution_model
from utils.artifact_integrity import artifact_is_valid
from views import view_manager


HORIZON_SESSIONS = (1, 5, 10, 20)
FACTOR_EVIDENCE_VERSION = "factor-evidence-v1"
FACTOR_OUTCOME_VERSION = "factor-outcome-observation-v1"
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ORJSON_OPTIONS = orjson.OPT_SORT_KEYS | orjson.OPT_SERIALIZE_NUMPY


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    item = getattr(value, "item", None)
    if callable(item):
        return item()
    raise TypeError(f"unsupported_json_type:{type(value).__name__}")


def _json_bytes(value: Any) -> bytes:
    return orjson.dumps(value, option=_ORJSON_OPTIONS, default=_json_default)


def _json_text(value: Any) -> str:
    return _json_bytes(value).decode("utf-8")


def _plain_json(value: Any) -> Any:
    """归一化成 orjson 可序列化的基础类型。"""
    return orjson.loads(_json_bytes(value))


def _loads(value: str | bytes | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return orjson.loads(value)
    except orjson.JSONDecodeError:
        return fallback


def _sha256(value: Any) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _valid_snapshot_id(value: Any) -> str:
    snapshot_id = str(value or "").strip().lower()
    if not _SHA256_RE.fullmatch(snapshot_id):
        raise ValueError("pinned_market_snapshot_required")
    return snapshot_id


def _valid_trade_date(value: Any) -> str:
    trade_date = str(value or "").strip()[:10]
    if not _DATE_RE.fullmatch(trade_date):
        raise ValueError("invalid_trade_date")
    return trade_date


def _nonnegative_int(value: Any, field: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid_{field}") from exc
    if number < 0:
        raise ValueError(f"invalid_{field}")
    return number


def _finite_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _registry_version() -> str:
    """因子注册表与实际实现源码的独立指纹。"""
    factors = []
    for key in sorted(FACTOR_REGISTRY):
        meta = FACTOR_REGISTRY[key]
        fn = meta.get("fn")
        source_path = inspect.getsourcefile(fn) if callable(fn) else None
        source_hash = None
        if source_path:
            try:
                source_hash = hashlib.sha256(Path(source_path).read_bytes()).hexdigest()
            except OSError:
                source_hash = None
        factors.append(
            {
                "key": key,
                "name": str(meta.get("name") or ""),
                "group": str(meta.get("group") or ""),
                "min_bars": int(meta.get("min_bars") or 0),
                "params": meta.get("params") or {},
                "callable": (
                    f"{getattr(fn, '__module__', '')}."
                    f"{getattr(fn, '__qualname__', getattr(fn, '__name__', ''))}"
                ),
                "source_hash": source_hash,
            }
        )
    project_root = Path(__file__).resolve().parents[1]
    shared_sources = []
    dependency_paths = [
        *sorted((project_root / "strategy").rglob("*.py")),
        project_root / "utils" / "factor_scan.py",
        project_root / "utils" / "technical.py",
        project_root / "utils" / "market_filter.py",
        project_root / "utils" / "csv_manager.py",
        project_root / "config" / "strategy_params.yaml",
        project_root / "requirements.lock",
    ]
    for path in dependency_paths:
        shared_sources.append(
            {
                "path": str(path.relative_to(project_root)),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    manifest = {"factors": factors, "shared_sources": shared_sources}
    return f"factor-registry-v2-{_sha256(manifest)[:20]}"


def factor_registry_version() -> str:
    """公开当前因子实现指纹，供调度和复盘拒绝旧版证据。"""
    return _registry_version()


def _snapshot_trade_date(csv_manager: Any, snapshot_id: str) -> str:
    """从已绑定快照读取交易日；任何 manifest 异常都失败关闭。"""
    try:
        from utils.market_snapshot import load_market_snapshot

        root = getattr(csv_manager, "base_data_dir", "data")
        snapshot = load_market_snapshot(root, snapshot_id, verify_files=False)
    except Exception as exc:
        raise ValueError("snapshot_manifest_unavailable") from exc
    if not snapshot.get("available"):
        raise ValueError(str(snapshot.get("reason") or "snapshot_manifest_unavailable"))
    return _valid_trade_date(
        str((snapshot.get("manifest") or {}).get("trade_date") or "")[:10]
    )


def _cache_key_matches_identity(identity: Mapping[str, Any], cache_key: str) -> bool:
    body = dict(identity)
    body.pop("cache_key", None)
    expected = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return expected == cache_key


def _direct_envelope(scan_result: Mapping[str, Any]) -> dict | None:
    nested = scan_result.get("cache_envelope")
    if isinstance(nested, Mapping):
        return dict(nested)
    if artifact_is_valid(scan_result) and isinstance(scan_result.get("results"), dict):
        return dict(scan_result)

    # 允许 worker 把 envelope 字段与 ``available/trade_date`` 包装在同一结果中。
    identity = scan_result.get("_cache_identity")
    cache_key = scan_result.get("_cache_key") or scan_result.get("cache_key")
    content_hash = scan_result.get("artifact_content_hash")
    results = scan_result.get("results")
    if (
        isinstance(identity, Mapping)
        and isinstance(cache_key, str)
        and isinstance(content_hash, str)
        and isinstance(results, dict)
    ):
        candidate = {
            "_cache_schema_version": scan_result.get(
                "_cache_schema_version",
                identity.get("cache_schema_version"),
            ),
            "_cache_key": cache_key,
            "_cache_identity": dict(identity),
            "results": results,
            "artifact_content_hash": content_hash,
        }
        if artifact_is_valid(candidate):
            return candidate
    return None


def _resolve_envelope(
    csv_manager: Any, scan_result: Mapping[str, Any]
) -> tuple[dict, str]:
    if not isinstance(scan_result, Mapping):
        raise TypeError("scan_result_must_be_mapping")
    if scan_result.get("available") is False:
        raise ValueError(str(scan_result.get("reason") or "factor_scan_unavailable"))

    snapshot_id = _valid_snapshot_id(getattr(csv_manager, "snapshot_id", None))
    trade_date_hint = str(scan_result.get("trade_date") or "")[:10]
    envelope = _direct_envelope(scan_result)
    if envelope is None:
        if not _DATE_RE.fullmatch(trade_date_hint):
            trade_date_hint = _snapshot_trade_date(csv_manager, snapshot_id)
        trade_date_hint = _valid_trade_date(trade_date_hint)
        from utils.factor_scan import _load_cache_envelope

        envelope = _load_cache_envelope(trade_date_hint, csv_manager)
    if not envelope or not artifact_is_valid(envelope):
        raise ValueError("factor_cache_artifact_invalid")

    identity = envelope.get("_cache_identity")
    if not isinstance(identity, Mapping):
        raise ValueError("factor_cache_identity_missing")
    cache_key = str(envelope.get("_cache_key") or "")
    if not _SHA256_RE.fullmatch(cache_key):
        raise ValueError("factor_cache_key_invalid")
    if identity.get("cache_key") != cache_key or not _cache_key_matches_identity(
        identity, cache_key
    ):
        raise ValueError("factor_cache_identity_mismatch")
    if identity.get("namespace") != "factor_scan":
        raise ValueError("factor_cache_namespace_mismatch")
    if str(identity.get("snapshot_id") or "").lower() != snapshot_id:
        raise ValueError("factor_cache_snapshot_mismatch")
    if not str(identity.get("strategy_version") or "").strip():
        raise ValueError("factor_cache_strategy_version_missing")
    if identity.get("cache_schema_version") != envelope.get("_cache_schema_version"):
        raise ValueError("factor_cache_schema_identity_mismatch")

    snapshot_date = _snapshot_trade_date(csv_manager, snapshot_id)
    trade_date = trade_date_hint or snapshot_date
    trade_date = _valid_trade_date(trade_date)
    if snapshot_date != trade_date:
        raise ValueError("factor_cache_trade_date_snapshot_mismatch")
    return envelope, trade_date


def _factor_rows(
    results: Mapping[str, Any], run_id: str, trade_date: str
) -> tuple[list[dict], list[dict], int]:
    expected = set(FACTOR_REGISTRY)
    actual = set(results)
    if actual != expected:
        missing = ",".join(sorted(expected - actual)) or "-"
        extra = ",".join(sorted(actual - expected)) or "-"
        raise ValueError(f"factor_cache_incomplete:missing={missing}:extra={extra}")

    stats: list[dict] = []
    signals: list[dict] = []
    for factor_key in sorted(expected):
        bucket = results.get(factor_key)
        if not isinstance(bucket, Mapping):
            raise ValueError(f"factor_bucket_invalid:{factor_key}")
        scanned = _nonnegative_int(
            bucket.get("total_scanned", bucket.get("scanned_count", 0)),
            "scanned_count",
        )
        errors = _nonnegative_int(
            bucket.get("errors", bucket.get("error_count", 0)), "error_count"
        )
        if errors:
            raise ValueError(f"factor_cache_has_errors:{factor_key}:{errors}")
        raw_hits = bucket.get("hits") or []
        if not isinstance(raw_hits, list):
            raise ValueError(f"factor_hits_invalid:{factor_key}")

        # 一个因子在同一日对同一代码只能有一个信号。旧缓存若有重复项，
        # 按规范 JSON 最小值稳定去重，不让输入顺序改变证据 ID。
        unique: dict[str, tuple[bytes, dict]] = {}
        for raw_hit in raw_hits:
            if not isinstance(raw_hit, Mapping):
                raise ValueError(f"factor_hit_invalid:{factor_key}")
            payload = _plain_json(dict(raw_hit))
            code = str(payload.get("code") or "").strip()
            if not re.fullmatch(r"\d{6}", code):
                raise ValueError(f"factor_signal_code_invalid:{factor_key}:{code}")
            hit_date = str(payload.get("date") or trade_date)[:10]
            if hit_date != trade_date:
                raise ValueError(
                    f"factor_signal_trade_date_mismatch:{factor_key}:{code}"
                )
            encoded = _json_bytes(payload)
            current = unique.get(code)
            if current is None or encoded < current[0]:
                unique[code] = (encoded, payload)

        stats.append(
            {
                "factor_key": factor_key,
                "hit_count": len(unique),
                "scanned_count": scanned,
                "error_count": errors,
            }
        )
        for code in sorted(unique):
            payload = unique[code][1]
            identity = {
                "version": FACTOR_EVIDENCE_VERSION,
                "run_id": run_id,
                "factor_key": factor_key,
                "code": code,
            }
            signals.append(
                {
                    "signal_id": f"fsig_{_sha256(identity)}",
                    "run_id": run_id,
                    "trade_date": trade_date,
                    "factor_key": factor_key,
                    "code": code,
                    "name": (
                        str(payload.get("name"))
                        if payload.get("name") is not None
                        else None
                    ),
                    "close": _finite_float(payload.get("close")),
                    "payload_json": _json_text(payload),
                }
            )
    scanned_count = max((row["scanned_count"] for row in stats), default=0)
    return stats, signals, scanned_count


def _assert_same_run(row: Mapping[str, Any], expected: Mapping[str, Any]) -> None:
    keys = (
        "run_id",
        "trade_date",
        "snapshot_id",
        "strategy_version",
        "registry_version",
        "cache_key",
        "source_artifact_hash",
        "universe_hash",
        "scanned_count",
        "factor_count",
        "status",
    )
    if any(row.get(key) != expected.get(key) for key in keys):
        raise RuntimeError("factor_signal_run_identity_collision")


def materialize_factor_signal_run(
    csv_manager: Any, scan_result: Mapping[str, Any]
) -> dict:
    """将完整、已封印的 28 因子扫描产物追加到运行时账本。

    ``scan_result`` 可以是完整 cache envelope，也可以是扫描返回值；
    后者会按 trade_date 读取已落盘 envelope，不会重扫市场。
    """
    envelope, trade_date = _resolve_envelope(csv_manager, scan_result)
    snapshot_id = _valid_snapshot_id(getattr(csv_manager, "snapshot_id", None))
    identity = dict(envelope["_cache_identity"])
    strategy_version = str(identity["strategy_version"])
    registry_version = _registry_version()
    cache_key = str(envelope["_cache_key"])
    source_artifact_hash = str(envelope.get("artifact_content_hash") or "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", source_artifact_hash):
        raise ValueError("factor_cache_artifact_hash_invalid")
    universe_hash = identity.get("universe_hash")
    if universe_hash is not None:
        universe_hash = str(universe_hash)

    run_identity = {
        "version": FACTOR_EVIDENCE_VERSION,
        "trade_date": trade_date,
        "snapshot_id": snapshot_id,
        "strategy_version": strategy_version,
        "registry_version": registry_version,
        "cache_key": cache_key,
        "source_artifact_hash": source_artifact_hash,
        "universe_hash": universe_hash,
    }
    run_id = f"frun_{_sha256(run_identity)}"
    results = envelope.get("results")
    if not isinstance(results, Mapping):
        raise ValueError("factor_cache_results_invalid")
    stats, signals, scanned_count = _factor_rows(results, run_id, trade_date)
    run = {
        "run_id": run_id,
        "trade_date": trade_date,
        "snapshot_id": snapshot_id,
        "strategy_version": strategy_version,
        "registry_version": registry_version,
        "cache_key": cache_key,
        "source_artifact_hash": source_artifact_hash,
        "universe_hash": universe_hash,
        "scanned_count": scanned_count,
        "factor_count": len(stats),
        "status": "complete",
    }
    created_at = _now()

    with view_manager._get_conn() as connection:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO factor_signal_runs
              (run_id, trade_date, snapshot_id, strategy_version,
               registry_version, cache_key, source_artifact_hash, universe_hash,
               scanned_count, factor_count, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run["run_id"],
                run["trade_date"],
                run["snapshot_id"],
                run["strategy_version"],
                run["registry_version"],
                run["cache_key"],
                run["source_artifact_hash"],
                run["universe_hash"],
                run["scanned_count"],
                run["factor_count"],
                run["status"],
                created_at,
            ),
        )
        inserted = cursor.rowcount == 1
        existing_run = connection.execute(
            """
            SELECT * FROM factor_signal_runs
            WHERE run_id = ? OR
                  (snapshot_id = ? AND strategy_version = ?
                   AND registry_version = ? AND cache_key = ?)
            ORDER BY CASE WHEN run_id = ? THEN 0 ELSE 1 END
            LIMIT 1
            """,
            (
                run_id,
                snapshot_id,
                strategy_version,
                registry_version,
                cache_key,
                run_id,
            ),
        ).fetchone()
        if existing_run is None:
            raise RuntimeError("factor_signal_run_insert_failed")
        _assert_same_run(dict(existing_run), run)

        for stat in stats:
            connection.execute(
                """
                INSERT OR IGNORE INTO factor_run_stats
                  (run_id, factor_key, hit_count, scanned_count, error_count,
                   created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    stat["factor_key"],
                    stat["hit_count"],
                    stat["scanned_count"],
                    stat["error_count"],
                    created_at,
                ),
            )
        for signal in signals:
            connection.execute(
                """
                INSERT OR IGNORE INTO factor_signals
                  (signal_id, run_id, trade_date, factor_key, code, name, close,
                   payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    signal["signal_id"],
                    signal["run_id"],
                    signal["trade_date"],
                    signal["factor_key"],
                    signal["code"],
                    signal["name"],
                    signal["close"],
                    signal["payload_json"],
                    created_at,
                ),
            )

        stored_stats = {
            row["factor_key"]: dict(row)
            for row in connection.execute(
                "SELECT * FROM factor_run_stats WHERE run_id = ?", (run_id,)
            ).fetchall()
        }
        if set(stored_stats) != {row["factor_key"] for row in stats}:
            raise RuntimeError("factor_run_stats_incomplete")
        for stat in stats:
            stored = stored_stats[stat["factor_key"]]
            if any(
                int(stored[key]) != int(stat[key])
                for key in ("hit_count", "scanned_count", "error_count")
            ):
                raise RuntimeError("factor_run_stats_identity_collision")

        stored_signals = {
            (row["factor_key"], row["code"]): dict(row)
            for row in connection.execute(
                "SELECT * FROM factor_signals WHERE run_id = ?", (run_id,)
            ).fetchall()
        }
        expected_signals = {(row["factor_key"], row["code"]): row for row in signals}
        if set(stored_signals) != set(expected_signals):
            raise RuntimeError("factor_signals_incomplete")
        for key, signal in expected_signals.items():
            stored = stored_signals[key]
            if (
                stored["signal_id"] != signal["signal_id"]
                or stored["payload_json"] != signal["payload_json"]
            ):
                raise RuntimeError("factor_signal_identity_collision")

    return {
        "available": True,
        "existing": not inserted,
        **run,
        "signal_count": len(signals),
        "zero_hit_factor_count": sum(row["hit_count"] == 0 for row in stats),
    }


def _normalize_daily(frame: pd.DataFrame, observed_as_of: str) -> pd.DataFrame:
    if frame is None or frame.empty or "date" not in frame.columns:
        return pd.DataFrame()
    daily = frame.copy()
    daily["date"] = pd.to_datetime(daily["date"], errors="coerce")
    daily = daily.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    daily["date"] = daily["date"].dt.strftime("%Y-%m-%d")
    return daily[daily["date"] <= observed_as_of].reset_index(drop=True)


def _reference_context(
    csv_manager: Any, codes: set[str], observed_as_of: str
) -> tuple[dict[str, dict], dict[str, dict[str, dict]]]:
    """一次载入已校验的前向快照与证券状态。

    退市或移出当前股票池的代码不会出现在最新 payload 中，
    但仍必须保留在结果证据链里。
    """
    states: dict[str, dict[str, dict]] = {code: {} for code in codes}
    try:
        from utils.reference_snapshots import load_reference_snapshots

        snapshots = load_reference_snapshots(
            getattr(csv_manager, "base_data_dir", csv_manager.data_dir)
        )
    except Exception:
        return {}, states
    snapshots = {
        str(state_date)[:10]: snapshot
        for state_date, snapshot in snapshots.items()
        if str(state_date)[:10] <= observed_as_of
    }
    for state_date, snapshot in snapshots.items():
        day = str(state_date)[:10]
        by_code = snapshot.get("security_states") or {}
        if not isinstance(by_code, Mapping):
            continue
        for code in codes:
            state = by_code.get(code)
            if isinstance(state, Mapping):
                states[code][day] = _plain_json(dict(state))
    return snapshots, states


def _daily_history_by_code(
    csv_manager: Any,
    codes: set[str],
    observed_as_of: str,
    snapshots: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, pd.DataFrame], dict[str, str | None]]:
    """当前快照缺失代码时，从最后一个仍包含它的不可变快照取历史。"""
    from utils.csv_manager import CSVManager
    from utils.reference_snapshots import validated_snapshot_payload

    data_root = getattr(csv_manager, "base_data_dir", csv_manager.data_dir)
    daily_by_code: dict[str, pd.DataFrame] = {}
    source_snapshot_by_code: dict[str, str | None] = {}
    missing_codes: list[str] = []
    current_snapshot_id = str(getattr(csv_manager, "snapshot_id", "") or "")
    for code in sorted(codes):
        daily = _normalize_daily(csv_manager.read_stock(code), observed_as_of)
        daily_by_code[code] = daily
        if daily.empty:
            missing_codes.append(code)
            source_snapshot_by_code[code] = None
        else:
            source_snapshot_by_code[code] = current_snapshot_id or None

    managers: dict[str, CSVManager] = {}
    ordered_snapshots = sorted(snapshots.items(), reverse=True)
    for code in missing_codes:
        for _snapshot_date, snapshot in ordered_snapshots:
            universe = snapshot.get("_universe_set") or set(
                snapshot.get("universe") or []
            )
            if code not in universe:
                continue
            snapshot_id = str(snapshot.get("market_snapshot_id") or "").lower()
            payload = validated_snapshot_payload(snapshot, data_root, snapshot_id)
            if payload is None:
                continue
            manager = managers.get(snapshot_id)
            if manager is None:
                manager = CSVManager(data_root, resolve_snapshot=False, writable=False)
                manager.data_dir = payload
                manager.snapshot_id = snapshot_id
                managers[snapshot_id] = manager
            daily = _normalize_daily(manager.read_stock(code), observed_as_of)
            if daily.empty:
                continue
            daily_by_code[code] = daily
            source_snapshot_by_code[code] = snapshot_id
            break
    return daily_by_code, source_snapshot_by_code


def _terminal_expected_date(
    trading_calendar: list[str], signal_date: str, horizon_sessions: int
) -> tuple[str | None, bool]:
    """返回最晚应有终局证据的交易所会话日。"""
    try:
        signal_index = trading_calendar.index(signal_date)
    except ValueError:
        return None, False
    terminal_index = (
        signal_index
        + 1
        + int(horizon_sessions)
        + execution_model.DEFAULT_EXECUTION_POLICY.max_exit_delay_sessions
    )
    if terminal_index >= len(trading_calendar):
        return None, True
    return trading_calendar[terminal_index], True


def _first_removal_date(
    snapshots: Mapping[str, Mapping[str, Any]],
    code: str,
    signal_date: str,
    terminal_date: str | None,
) -> str | None:
    """只认定评估窗口内的权威股票池移除/退市证据。"""
    if terminal_date is None:
        return None
    for snapshot_date, snapshot in sorted(snapshots.items()):
        day = str(snapshot_date)[:10]
        if day <= signal_date:
            continue
        if day > terminal_date:
            break
        universe = snapshot.get("_universe_set") or set(snapshot.get("universe") or [])
        state = (snapshot.get("security_states") or {}).get(code) or {}
        if code not in universe or state.get("trading_status") == "delisted":
            return day
    return None


def _execution_is_terminal(execution: Mapping[str, Any]) -> bool:
    if (
        execution.get("return_label_mature") is True
        and _finite_float(execution.get("net_return")) is not None
    ):
        return True
    if (
        execution.get("entry_label_mature") is True
        and execution.get("entry_feasible") is False
    ):
        return True
    return bool(
        execution.get("entry_feasible") is True
        and execution.get("exit_label_mature") is True
        and execution.get("exit_feasible") is False
    )


def _apply_removal_evidence(
    execution: Mapping[str, Any], removal_date: str | None
) -> dict:
    if removal_date is None or _execution_is_terminal(execution):
        return dict(execution)
    entry_mature = execution.get("entry_label_mature") is True
    entry_feasible = execution.get("entry_feasible") if entry_mature else None
    entered = entry_feasible is True
    entry_known = entry_feasible is not None
    reason = (
        "universe_removed_before_label"
        if entry_known
        else "universe_removed_with_entry_unknown"
    )
    return {
        **execution,
        "available": True,
        "reason": reason,
        "execution_status": reason,
        "entry_label_mature": entry_mature,
        "entry_feasible": entry_feasible,
        "exit_label_mature": entered,
        "exit_feasible": False if entered else None,
        "return_label_mature": False,
        "net_return": None,
        "label_end_date": removal_date,
        "universe_removal_date": removal_date,
    }


def _evidence_tier(execution: Mapping[str, Any]) -> str:
    if execution.get("session_axis_verified") is not True:
        return "forward_approximation"
    regimes: list[Mapping[str, Any]] = []
    entry = execution.get("entry_regime")
    if isinstance(entry, Mapping):
        regimes.append(entry)
    exit_regime = execution.get("exit_regime")
    if isinstance(exit_regime, Mapping):
        regimes.append(exit_regime)
    if regimes and all(item.get("point_in_time_verified") is True for item in regimes):
        # 完整收益标签必须同时有入场和出场的 PIT 状态。
        if execution.get("return_label_mature") is True and len(regimes) < 2:
            return "forward_approximation"
        return "pit_verified"
    return "forward_approximation"


def _observation_status(execution: Mapping[str, Any]) -> str:
    net_return = _finite_float(execution.get("net_return"))
    if execution.get("return_label_mature") is True and net_return is not None:
        return "complete"
    terminal_execution_failure = (
        execution.get("return_label_mature") is True
        or (
            execution.get("entry_label_mature") is True
            and execution.get("entry_feasible") is False
        )
        or (
            execution.get("exit_label_mature") is True
            and execution.get("exit_feasible") is False
        )
    )
    if terminal_execution_failure:
        return "invalid"
    if (
        execution.get("entry_label_mature") is False
        or execution.get("exit_label_mature") is False
        or execution.get("reason")
        in {
            "entry_not_available",
            "holding_incomplete",
            "exit_delay_incomplete",
            "no_daily_data",
            "run_date_missing",
            "pit_security_state_missing",
            "market_bar_missing",
        }
    ):
        return "pending"
    return "pending"


def _latest_completed_pairs(
    connection: Any, observed_as_of: str, execution_policy_version: str
) -> set[tuple[str, int]]:
    return {
        (str(row["signal_id"]), int(row["horizon_sessions"]))
        for row in connection.execute(
            """
            SELECT DISTINCT o.signal_id, o.horizon_sessions
            FROM factor_outcome_observations AS o
            JOIN factor_signals AS s ON s.signal_id = o.signal_id
            WHERE (
                    o.status = 'complete'
                    OR (
                        o.status = 'invalid'
                        AND o.execution_status IN (
                            'entry_unbuyable', 'entry_suspended', 'exit_unsellable',
                            'universe_removed_before_label'
                        )
                    )
                  )
              AND s.trade_date <= ?
              AND o.execution_policy_version = ?
            """,
            (observed_as_of, execution_policy_version),
        ).fetchall()
    }


def refresh_factor_outcomes(csv_manager: Any, trade_date: str) -> dict:
    """用调用方已绑定的快照，追加尚未完成的 1/5/10/20 日结果。"""
    observed_as_of = _valid_trade_date(trade_date)
    pricing_snapshot_id = _valid_snapshot_id(getattr(csv_manager, "snapshot_id", None))
    current_policy_version = execution_model.DEFAULT_EXECUTION_POLICY.version
    snapshot_date = _snapshot_trade_date(csv_manager, pricing_snapshot_id)
    if snapshot_date != observed_as_of:
        raise ValueError("pricing_snapshot_trade_date_mismatch")

    with view_manager._get_read_conn() as connection:
        signal_rows = connection.execute(
            """
            WITH latest_runs AS (
              SELECT run_id,
                     ROW_NUMBER() OVER (
                       PARTITION BY trade_date
                       ORDER BY
                         CASE
                           WHEN date(created_at, '+8 hours') = trade_date THEN 0
                           ELSE 1
                         END,
                         created_at DESC, rowid DESC
                     ) AS run_rank
              FROM factor_signal_runs
              WHERE status = 'complete' AND trade_date <= ?
            )
            SELECT s.*, r.snapshot_id AS signal_snapshot_id,
                   r.strategy_version, r.registry_version,
                   r.source_artifact_hash
            FROM factor_signals AS s
            JOIN factor_signal_runs AS r ON r.run_id = s.run_id
            JOIN latest_runs AS lr ON lr.run_id = s.run_id AND lr.run_rank = 1
            WHERE s.trade_date <= ?
            ORDER BY s.code, s.trade_date, s.factor_key, s.signal_id
            """,
            (observed_as_of, observed_as_of),
        ).fetchall()
        completed = _latest_completed_pairs(
            connection, observed_as_of, current_policy_version
        )
        current_observations = {
            (str(row["signal_id"]), int(row["horizon_sessions"])): dict(row)
            for row in connection.execute(
                """
                SELECT o.*
                FROM factor_outcome_observations AS o
                JOIN factor_signals AS s ON s.signal_id = o.signal_id
                WHERE o.pricing_snapshot_id = ? AND s.trade_date <= ?
                  AND o.execution_policy_version = ?
                """,
                (pricing_snapshot_id, observed_as_of, current_policy_version),
            ).fetchall()
        }

    signals = []
    pending_pairs: list[tuple[dict, int]] = []
    for raw in signal_rows:
        signal = dict(raw)
        signal["payload"] = _loads(signal.pop("payload_json"), {})
        signals.append(signal)
        for horizon in HORIZON_SESSIONS:
            key = (signal["signal_id"], horizon)
            if key not in completed and key not in current_observations:
                pending_pairs.append((signal, horizon))

    codes = {signal["code"] for signal, _ in pending_pairs}
    snapshots, states_by_code = _reference_context(csv_manager, codes, observed_as_of)
    daily_by_code, history_source_by_code = _daily_history_by_code(
        csv_manager, codes, observed_as_of, snapshots
    )
    trading_sessions = execution_model.load_exchange_sessions(
        csv_manager.data_dir,
        through_date=observed_as_of,
    )
    full_trading_calendar = execution_model.load_exchange_calendar(csv_manager.data_dir)

    observations: list[dict] = []
    execution_cache: dict[tuple[str, str, int], dict] = {}
    for signal, horizon in pending_pairs:
        execution_key = (signal["code"], signal["trade_date"], horizon)
        if execution_key not in execution_cache:
            result = execution_model.evaluate_trade(
                daily_by_code[signal["code"]],
                signal["trade_date"],
                hold_days=horizon,
                code=signal["code"],
                security_states=states_by_code.get(signal["code"]) or None,
                trading_sessions=trading_sessions,
                require_pit_status=False,
                policy=execution_model.DEFAULT_EXECUTION_POLICY,
            )
            terminal_date, signal_session_known = _terminal_expected_date(
                full_trading_calendar, signal["trade_date"], horizon
            )
            removal_date = _first_removal_date(
                snapshots,
                signal["code"],
                signal["trade_date"],
                terminal_date,
            )
            result = _apply_removal_evidence(result, removal_date)
            provisional_status = _observation_status(result)
            evidence_overdue = bool(
                provisional_status == "pending"
                and (
                    (terminal_date is not None and observed_as_of >= terminal_date)
                    or (
                        not signal_session_known
                        and signal["trade_date"] < observed_as_of
                    )
                )
            )
            result = {
                **result,
                "terminal_expected_date": terminal_date,
                "evidence_overdue": evidence_overdue,
                "history_source_snapshot_id": history_source_by_code.get(
                    signal["code"]
                ),
            }
            execution_cache[execution_key] = _plain_json(result)
        execution = execution_cache[execution_key]
        status = _observation_status(execution)
        tier = _evidence_tier(execution)
        policy_version = str(
            execution.get("execution_policy_version")
            or execution_model.DEFAULT_EXECUTION_POLICY.version
        )
        payload = {
            "schema_version": FACTOR_OUTCOME_VERSION,
            "signal": {
                "signal_id": signal["signal_id"],
                "run_id": signal["run_id"],
                "trade_date": signal["trade_date"],
                "factor_key": signal["factor_key"],
                "code": signal["code"],
                "source_snapshot_id": signal["signal_snapshot_id"],
                "source_artifact_hash": signal["source_artifact_hash"],
                "strategy_version": signal["strategy_version"],
                "registry_version": signal["registry_version"],
                "payload": signal["payload"],
            },
            "horizon_sessions": horizon,
            "observed_as_of": observed_as_of,
            "pricing_snapshot_id": pricing_snapshot_id,
            "execution_policy_version": policy_version,
            "evidence_tier": tier,
            "status": status,
            "execution": execution,
        }
        content_hash = _sha256(payload)
        observation_identity = {
            "version": FACTOR_OUTCOME_VERSION,
            "signal_id": signal["signal_id"],
            "horizon_sessions": horizon,
            "pricing_snapshot_id": pricing_snapshot_id,
            "execution_policy_version": policy_version,
        }
        observations.append(
            {
                "observation_id": f"fobs_{_sha256(observation_identity)}",
                "signal_id": signal["signal_id"],
                "horizon_sessions": horizon,
                "observed_as_of": observed_as_of,
                "pricing_snapshot_id": pricing_snapshot_id,
                "entry_date": execution.get("entry_date"),
                "entry_price": _finite_float(execution.get("entry_price")),
                "exit_date": execution.get("exit_date"),
                "exit_price": _finite_float(execution.get("exit_price")),
                "net_return": _finite_float(execution.get("net_return")),
                "max_gain": _finite_float(execution.get("max_gain")),
                "max_drawdown": _finite_float(execution.get("max_drawdown")),
                "execution_status": str(
                    execution.get("execution_status")
                    or execution.get("reason")
                    or "unknown"
                ),
                "execution_policy_version": policy_version,
                "evidence_tier": tier,
                "status": status,
                "content_hash": content_hash,
                "payload_json": _json_text(payload),
            }
        )

    created_at = _now()
    inserted_rows: list[dict] = []
    existing_count = len(current_observations)
    skipped_completed = len(completed)
    with view_manager._get_conn() as connection:
        completed_now = {
            (str(row["signal_id"]), int(row["horizon_sessions"]))
            for row in connection.execute(
                """
                SELECT signal_id, horizon_sessions
                FROM factor_outcome_observations
                WHERE (
                        status = 'complete'
                        OR (
                            status = 'invalid'
                            AND execution_status IN (
                                'entry_unbuyable', 'entry_suspended', 'exit_unsellable',
                                'universe_removed_before_label'
                            )
                        )
                      )
                  AND execution_policy_version = ?
                """,
                (current_policy_version,),
            ).fetchall()
        }
        candidates = [
            observation
            for observation in observations
            if (
                observation["signal_id"],
                observation["horizon_sessions"],
            )
            not in completed_now
        ]
        skipped_completed += len(observations) - len(candidates)
        candidate_ids = [str(row["observation_id"]) for row in candidates]
        existing_observation_ids: set[str] = set()
        for offset in range(0, len(candidate_ids), 500):
            chunk = candidate_ids[offset : offset + 500]
            placeholders = ",".join("?" for _ in chunk)
            existing_observation_ids.update(
                str(row["observation_id"])
                for row in connection.execute(
                    "SELECT observation_id FROM factor_outcome_observations "
                    f"WHERE observation_id IN ({placeholders})",
                    tuple(chunk),
                ).fetchall()
            )
        before_changes = connection.total_changes
        connection.executemany(
            """
            INSERT OR IGNORE INTO factor_outcome_observations
              (observation_id, signal_id, horizon_sessions, observed_as_of,
               pricing_snapshot_id, entry_date, entry_price, exit_date,
               exit_price, net_return, max_gain, max_drawdown,
               execution_status, execution_policy_version, evidence_tier,
               status, content_hash, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row["observation_id"],
                    row["signal_id"],
                    row["horizon_sessions"],
                    row["observed_as_of"],
                    row["pricing_snapshot_id"],
                    row["entry_date"],
                    row["entry_price"],
                    row["exit_date"],
                    row["exit_price"],
                    row["net_return"],
                    row["max_gain"],
                    row["max_drawdown"],
                    row["execution_status"],
                    row["execution_policy_version"],
                    row["evidence_tier"],
                    row["status"],
                    row["content_hash"],
                    row["payload_json"],
                    created_at,
                )
                for row in candidates
            ],
        )
        inserted_count = connection.total_changes - before_changes
        stored_rows = {
            str(row["observation_id"]): str(row["content_hash"])
            for row in connection.execute(
                """
                SELECT observation_id, content_hash
                FROM factor_outcome_observations
                WHERE pricing_snapshot_id = ? AND execution_policy_version = ?
                """,
                (pricing_snapshot_id, current_policy_version),
            ).fetchall()
        }
        for row in candidates:
            if stored_rows.get(row["observation_id"]) != row["content_hash"]:
                raise RuntimeError("factor_outcome_identity_collision")
        inserted_ids = {
            row["observation_id"]
            for row in candidates
            if row["observation_id"] not in existing_observation_ids
            and stored_rows.get(row["observation_id"]) == row["content_hash"]
        }
        inserted_rows = [
            row for row in candidates if row["observation_id"] in inserted_ids
        ]
        if len(inserted_rows) != inserted_count:
            raise RuntimeError("factor_outcome_insert_count_mismatch")
        existing_count += len(candidates) - inserted_count

    return {
        "available": True,
        "trade_date": observed_as_of,
        "pricing_snapshot_id": pricing_snapshot_id,
        "signals_considered": len(signals),
        "quotes_read": len(daily_by_code),
        "evaluated": len(observations),
        "inserted": len(inserted_rows),
        "existing": existing_count,
        "skipped_complete": skipped_completed,
        "complete": sum(row["status"] == "complete" for row in inserted_rows),
        "pending": sum(row["status"] == "pending" for row in inserted_rows),
        "invalid": sum(row["status"] == "invalid" for row in inserted_rows),
        "pit_verified": sum(
            row["evidence_tier"] == "pit_verified" for row in inserted_rows
        ),
        "forward_approximation": sum(
            row["evidence_tier"] == "forward_approximation" for row in inserted_rows
        ),
    }


def _run_stats(connection: Any, run_id: str) -> list[dict]:
    return [
        dict(row)
        for row in connection.execute(
            """
            SELECT factor_key, hit_count, scanned_count, error_count, created_at
            FROM factor_run_stats
            WHERE run_id = ?
            ORDER BY factor_key
            """,
            (run_id,),
        ).fetchall()
    ]


def get_latest_factor_signal_run(
    trade_date: str | None = None,
    *,
    as_of: str | None = None,
) -> dict | None:
    """只读获取最新信号批次，并携带全部零/非零命中统计。"""
    clauses = []
    params: list[Any] = []
    if trade_date is not None:
        clauses.append("trade_date = ?")
        params.append(_valid_trade_date(trade_date))
    if as_of is not None:
        clauses.append("trade_date <= ?")
        params.append(_valid_trade_date(as_of))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with view_manager._get_read_conn() as connection:
        row = connection.execute(
            f"""
            SELECT * FROM factor_signal_runs
            {where}
            ORDER BY trade_date DESC,
                     CASE
                       WHEN date(created_at, '+8 hours') = trade_date THEN 0
                       ELSE 1
                     END,
                     created_at DESC, rowid DESC
            LIMIT 1
            """,
            tuple(params),
        ).fetchone()
        if row is None:
            return None
        run = dict(row)
        run["stats"] = _run_stats(connection, run["run_id"])
        counts = connection.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM factor_signals WHERE run_id = ?) AS signals,
              (SELECT COUNT(*)
                 FROM factor_outcome_observations AS o
                 JOIN factor_signals AS s ON s.signal_id = o.signal_id
                WHERE s.run_id = ?) AS observations
            """,
            (run["run_id"], run["run_id"]),
        ).fetchone()
        run["signal_count"] = int(counts["signals"])
        run["observation_count"] = int(counts["observations"])
    return run


def list_factor_run_stats(run_id: str) -> list[dict]:
    """只读返回一个批次的全因子统计，包括零命中项。"""
    with view_manager._get_read_conn() as connection:
        return _run_stats(connection, str(run_id))


def list_factor_signals(
    *,
    run_id: str | None = None,
    factor_key: str | None = None,
    trade_date: str | None = None,
    limit: int = 1000,
) -> list[dict]:
    """只读查询已物化信号。"""
    clauses = []
    params: list[Any] = []
    if run_id:
        clauses.append("run_id = ?")
        params.append(str(run_id))
    if factor_key:
        clauses.append("factor_key = ?")
        params.append(str(factor_key))
    if trade_date:
        clauses.append("trade_date = ?")
        params.append(_valid_trade_date(trade_date))
    params.append(max(1, min(int(limit), 50_000)))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with view_manager._get_read_conn() as connection:
        rows = connection.execute(
            f"""
            SELECT * FROM factor_signals
            {where}
            ORDER BY trade_date DESC, factor_key, code, signal_id
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()
    result = []
    for raw in rows:
        item = dict(raw)
        item["payload"] = _loads(item.pop("payload_json"), {})
        result.append(item)
    return result


def list_latest_factor_outcomes(
    *,
    as_of: str | None = None,
    from_trade_date: str | None = None,
    factor_key: str | None = None,
    registry_version: str | None = None,
    execution_policy_version: str | None = None,
    horizon_sessions: int | None = None,
    status: str | None = None,
    evidence_tier: str | None = None,
    limit: int = 10_000,
) -> list[dict]:
    """只读返回每个信号/窗口截至 ``as_of`` 的最新观测。"""
    inner_clauses = []
    inner_params: list[Any] = []
    if as_of:
        inner_clauses.append("o.observed_as_of <= ?")
        inner_params.append(_valid_trade_date(as_of))
    if from_trade_date:
        inner_clauses.append("s.trade_date >= ?")
        inner_params.append(_valid_trade_date(from_trade_date))
    if factor_key:
        inner_clauses.append("s.factor_key = ?")
        inner_params.append(str(factor_key))
    if registry_version:
        inner_clauses.append("lr.registry_version = ?")
        inner_params.append(str(registry_version))
    if execution_policy_version:
        inner_clauses.append("o.execution_policy_version = ?")
        inner_params.append(str(execution_policy_version))
    if horizon_sessions is not None:
        horizon = int(horizon_sessions)
        if horizon not in HORIZON_SESSIONS:
            raise ValueError("invalid_horizon_sessions")
        inner_clauses.append("o.horizon_sessions = ?")
        inner_params.append(horizon)
    outer_clauses = ["observation_rank = 1"]
    outer_params: list[Any] = []
    if status:
        if status not in {"pending", "complete", "invalid"}:
            raise ValueError("invalid_factor_outcome_status")
        outer_clauses.append("status = ?")
        outer_params.append(status)
    if evidence_tier:
        if evidence_tier not in {"pit_verified", "forward_approximation"}:
            raise ValueError("invalid_evidence_tier")
        outer_clauses.append("evidence_tier = ?")
        outer_params.append(evidence_tier)
    inner_where = f"WHERE {' AND '.join(inner_clauses)}" if inner_clauses else ""
    bounded_limit = max(1, min(int(limit), 1_000_000))
    with view_manager._get_read_conn() as connection:
        rows = connection.execute(
            f"""
            WITH latest_runs AS (
              SELECT run_id, registry_version, strategy_version, created_at,
                     ROW_NUMBER() OVER (
                       PARTITION BY trade_date
                       ORDER BY
                         CASE
                           WHEN date(created_at, '+8 hours') = trade_date THEN 0
                           ELSE 1
                         END,
                         created_at DESC, rowid DESC
                     ) AS run_rank
              FROM factor_signal_runs
              WHERE status = 'complete'
            ), ranked AS (
              SELECT o.*, s.run_id, s.trade_date, s.factor_key, s.code,
                     s.name, s.close, s.payload_json AS signal_payload_json,
                     s.created_at AS signal_recorded_at,
                     lr.registry_version, lr.strategy_version,
                     lr.created_at AS signal_run_recorded_at,
                     CASE
                       WHEN date(lr.created_at, '+8 hours') = s.trade_date
                       THEN 'forward_live'
                       ELSE 'backfill'
                     END AS signal_provenance,
                     ROW_NUMBER() OVER (
                       PARTITION BY o.signal_id, o.horizon_sessions,
                                    o.execution_policy_version
                       ORDER BY o.observed_as_of DESC, o.created_at DESC,
                                o.rowid DESC
                     ) AS observation_rank
              FROM factor_outcome_observations AS o
              JOIN factor_signals AS s ON s.signal_id = o.signal_id
              JOIN latest_runs AS lr
                ON lr.run_id = s.run_id AND lr.run_rank = 1
              {inner_where}
            )
            SELECT * FROM ranked
            WHERE {" AND ".join(outer_clauses)}
            ORDER BY trade_date DESC, factor_key, code, horizon_sessions
            LIMIT ?
            """,
            tuple((*inner_params, *outer_params, bounded_limit)),
        ).fetchall()
    result = []
    for raw in rows:
        item = dict(raw)
        item.pop("observation_rank", None)
        item["payload"] = _loads(item.pop("payload_json"), {})
        item["signal_payload"] = _loads(item.pop("signal_payload_json"), {})
        result.append(item)
    return result


# 简短别名，便于后续 scorecard 不需要了解表名。
get_latest_factor_run = get_latest_factor_signal_run
get_factor_run_stats = list_factor_run_stats
