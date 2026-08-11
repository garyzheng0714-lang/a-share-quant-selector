"""每日自我进化：真实结果回填、挑战模型训练、样本外评估与受控晋级。"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

import pandas as pd

from utils.csv_manager import CSVManager
from utils.data_freshness import local_data_status
from utils.decision_ledger import (
    append_decision_outcome,
    get_active_policy_models,
    get_current_evolution_run,
    list_pending_outcome_candidates,
    save_evolution_run,
)
from utils.decision_versions import VALIDATED_MODEL_SOURCE_REFS, data_version
from utils.execution_model import (
    DEFAULT_EXECUTION_POLICY,
    evaluate_trade,
    load_exchange_sessions,
)
from utils.market_filter import is_main_board, main_board_only
from utils.market_snapshot import read_snapshot_metadata

logger = logging.getLogger(__name__)

MIN_OOS_MONTHS = 6
MIN_OOS_SAMPLES = 80
MIN_UNIVERSE_COVERAGE = 0.60
MIN_REFERENCE_MONTHS = 21
MIN_SIGNAL_MONTHS = 21
PIT_CONTRACT_VERSION = "pit-forward-feature-and-label-ledger-v2"
EVOLUTION_PIPELINE_SCHEMA_VERSION = "model-evolution-pipeline-v4"


def evolution_pipeline_version() -> str:
    """返回模型进化专用的稳定内容指纹。

    这里故意不绑定 Git SHA：只有会改变训练样本、成交标签、
    walk-forward 或晋级判定的代码/参数才会产生新版本。
    """
    project_root = Path(__file__).resolve().parent.parent
    fixed_paths = (
        "utils/self_evolution.py",
        "utils/execution_model.py",
        "utils/probability_model.py",
        "utils/reference_snapshots.py",
        "utils/market_snapshot.py",
        "utils/market_filter.py",
        "utils/technical.py",
        "utils/csv_manager.py",
        "utils/decision_config.py",
        "utils/policy_engine.py",
        "tools/hierarchical_walk_forward.py",
        "config/strategy_params.yaml",
        "requirements.lock",
    )
    dynamic_paths = sorted((project_root / "strategy").rglob("*.py"))
    paths = [project_root / relative for relative in fixed_paths]
    paths.extend(dynamic_paths)
    digest = hashlib.sha256(EVOLUTION_PIPELINE_SCHEMA_VERSION.encode())
    for path in sorted(set(paths)):
        relative = path.relative_to(project_root).as_posix()
        digest.update(relative.encode())
        digest.update(b"\0")
        if path.exists():
            digest.update(path.read_bytes())
        digest.update(b"\0")
    return f"{EVOLUTION_PIPELINE_SCHEMA_VERSION}-{digest.hexdigest()[:16]}"


def _temporary_artifact_path(target: Path) -> Path:
    """在目标目录内生成临时路径，保证 replace 不跨文件系统。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    return target.with_name(f".{target.name}.{os.getpid()}.{uuid4().hex}.tmp")


def _atomic_write_frame(frame: pd.DataFrame, target: Path) -> None:
    temporary = _temporary_artifact_path(target)
    try:
        frame.to_csv(temporary, index=False)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_write_json(payload: dict, target: Path) -> None:
    temporary = _temporary_artifact_path(target)
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def _check_lease(lease_guard: Callable[[], None] | None) -> None:
    if lease_guard is not None:
        lease_guard()


def _noop_lease_guard() -> None:
    return None


def _deterministic_trained_as_of(frame: pd.DataFrame) -> str:
    """用训练证据的最晚可用日生成稳定训练时点。

    模型版本由训练集内容决定，因此相同训练集重跑时，
    ``trained_as_of`` 也必须只由同一份证据决定。
    """
    required = {"label_end_date", "label_snapshot_date"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"训练集缺少标签可用日字段: {sorted(missing)}")
    label_dates = frame[["label_end_date", "label_snapshot_date"]].apply(
        pd.to_datetime,
        errors="coerce",
    )
    if label_dates.isna().any(axis=None):
        raise ValueError("训练集包含无效的标签可用日")
    evidence_cutoff = label_dates.max(axis=1).max()
    if pd.isna(evidence_cutoff):
        raise ValueError("训练集没有可用的标签截止日")
    return f"{evidence_cutoff.strftime('%Y-%m-%d')}T16:00:00+08:00"


def _save_evolution_run(
    run: dict,
    lease_guard: Callable[[], None] | None,
) -> str:
    _check_lease(lease_guard)
    return save_evolution_run(run)


def update_decision_outcomes(csv_manager: CSVManager) -> dict:
    """回填 buy/observe/avoid 的真实表现，显式计算错过上涨的机会成本。"""
    from utils.reference_snapshots import (
        load_reference_snapshots,
        validated_snapshot_payload,
    )

    source_snapshot_id = str(csv_manager.snapshot_id or "").lower()
    if len(source_snapshot_id) != 64 or any(
        char not in "0123456789abcdef" for char in source_snapshot_id
    ):
        return {
            "available": False,
            "reason": "market_snapshot_unpinned",
            "pending": 0,
            "updated": 0,
            "complete": 0,
            "missing_data": 0,
        }
    data_root = getattr(csv_manager, "base_data_dir", csv_manager.data_dir)
    reference_snapshots = load_reference_snapshots(data_root)
    trading_sessions = load_exchange_sessions(csv_manager.data_dir)
    rows = list_pending_outcome_candidates()
    updated = complete = missing = 0
    for item in rows:
        trade_date = str(item["trade_date"])[:10]
        code = str(item["code"]).zfill(6)
        try:
            signal_session_index = trading_sessions.index(trade_date)
        except ValueError:
            signal_session_index = -1
        terminal_session_index = (
            signal_session_index
            + 1
            + DEFAULT_EXECUTION_POLICY.holding_sessions
            + DEFAULT_EXECUTION_POLICY.max_exit_delay_sessions
        )
        terminal_date = (
            trading_sessions[terminal_session_index]
            if signal_session_index >= 0
            and terminal_session_index < len(trading_sessions)
            else None
        )
        removal_date = None
        if signal_session_index >= 0:
            for snapshot_date, snapshot in sorted(reference_snapshots.items()):
                if snapshot_date <= trade_date:
                    continue
                if terminal_date is not None and snapshot_date > terminal_date:
                    break
                universe = snapshot.get("_universe_set") or set(
                    snapshot.get("universe") or []
                )
                state = (snapshot.get("security_states") or {}).get(code) or {}
                if code not in universe or state.get("trading_status") == "delisted":
                    removal_date = snapshot_date
                    break
        frame = csv_manager.read_stock(item["code"])
        if frame.empty:
            for snapshot_date, snapshot in sorted(
                reference_snapshots.items(), reverse=True
            ):
                if snapshot_date < trade_date:
                    continue
                universe = snapshot.get("_universe_set") or set(
                    snapshot.get("universe") or []
                )
                if code not in universe:
                    continue
                snapshot_id = str(snapshot.get("market_snapshot_id") or "").lower()
                payload = validated_snapshot_payload(snapshot, data_root, snapshot_id)
                if payload is None:
                    continue
                history_manager = CSVManager(
                    data_root, resolve_snapshot=False, writable=False
                )
                history_manager.data_dir = payload
                history_manager.snapshot_id = snapshot_id
                frame = history_manager.read_stock(code)
                if not frame.empty:
                    break
            if frame.empty:
                missing += 1
                continue
        daily = frame.sort_values("date").reset_index(drop=True).copy()
        daily["date"] = pd.to_datetime(daily["date"]).dt.strftime("%Y-%m-%d")
        after = daily[daily["date"] > item["trade_date"]]
        security_states = {
            date: state
            for date, snapshot in reference_snapshots.items()
            if isinstance(
                state := (snapshot.get("security_states") or {}).get(item["code"]),
                dict,
            )
        }
        one_session_execution = evaluate_trade(
            daily,
            item["trade_date"],
            hold_days=1,
            code=item["code"],
            security_states=security_states,
            trading_sessions=trading_sessions,
            require_pit_status=True,
        )
        execution = evaluate_trade(
            daily,
            item["trade_date"],
            hold_days=5,
            code=item["code"],
            security_states=security_states,
            trading_sessions=trading_sessions,
            require_pit_status=True,
        )
        execution_terminal = bool(
            execution.get("reason")
            in {"entry_unbuyable", "entry_suspended", "exit_unsellable"}
            or execution.get("net_return") is not None
        )
        if removal_date is not None and not execution_terminal:
            entry_mature = execution.get("entry_label_mature") is True
            entry_feasible = execution.get("entry_feasible") if entry_mature else None
            entered = entry_feasible is True
            entry_known = entry_feasible is not None
            execution = {
                **execution,
                "available": True,
                "reason": (
                    "universe_removed_before_label"
                    if entry_known
                    else "universe_removed_with_entry_unknown"
                ),
                "execution_status": (
                    "universe_removed_before_label"
                    if entry_known
                    else "universe_removed_with_entry_unknown"
                ),
                "entry_label_mature": entry_mature,
                "entry_feasible": entry_feasible,
                "exit_label_mature": entered,
                "exit_feasible": False if entered else None,
                "return_label_mature": False,
                "net_return": None,
                "label_end_date": removal_date,
            }
        outcome = {
            **item,
            "source_snapshot_id": source_snapshot_id,
            "days_tracked": min(len(after), 5),
            "status": "pending" if after.empty else "partial",
        }
        if not after.empty:
            entry_price = float(after.iloc[0].get("open", 0) or 0)
            entry_fields = {
                "entry_date": str(after.iloc[0]["date"]),
                "entry_price": round(entry_price, 3) if entry_price > 0 else None,
            }
            if execution.get("entry_feasible") is not None:
                entry_fields["entry_feasible"] = int(
                    bool(execution.get("entry_feasible"))
                )
            outcome.update(entry_fields)
        if execution.get("entry_label_mature") is False:
            outcome.update(
                {
                    "status": "pending",
                    "entry_date": execution.get("entry_date"),
                    "entry_price": None,
                    "entry_feasible": None,
                    "execution_status": execution.get("execution_status")
                    or execution.get("reason"),
                    "execution_policy_version": execution.get(
                        "execution_policy_version"
                    ),
                }
            )
        if one_session_execution.get("net_return") is not None:
            outcome["ret_1"] = one_session_execution["net_return"]
        if execution.get("available"):
            entry_feasible = execution.get("entry_feasible")
            outcome.update(
                {
                    "entry_date": execution.get("entry_date")
                    or outcome.get("entry_date"),
                    "entry_price": execution.get("entry_price"),
                    "entry_feasible": (
                        int(bool(entry_feasible))
                        if entry_feasible is not None
                        else None
                    ),
                    "exit_feasible": (
                        int(bool(execution.get("exit_feasible")))
                        if execution.get("exit_feasible") is not None
                        else None
                    ),
                    "execution_status": execution.get("execution_status")
                    or execution.get("reason"),
                    "execution_policy_version": execution.get(
                        "execution_policy_version"
                    ),
                    "net_ret_5": execution.get("net_return"),
                    "max_gain_5": execution.get("max_gain"),
                    "max_drawdown_5": execution.get("max_drawdown"),
                }
            )
            if execution.get("reason") in {
                "entry_unbuyable",
                "entry_suspended",
                "universe_removed_before_label",
            }:
                outcome["status"] = "complete"
            elif execution.get("net_return") is not None:
                outcome["status"] = "complete"
            elif execution.get("reason") == "exit_unsellable":
                outcome["status"] = "complete"
        if append_decision_outcome(outcome):
            updated += 1
            complete += int(outcome["status"] == "complete")
    return {
        "available": True,
        "source_snapshot_id": source_snapshot_id,
        "pending": len(rows),
        "updated": updated,
        "complete": complete,
        "missing_data": missing,
    }


def _coverage(csv_manager: CSVManager, names: dict) -> dict:
    from utils.akshare_fetcher import AKShareFetcher

    universe = {
        code: name
        for code, name in names.items()
        if not main_board_only() or is_main_board(code)
    }
    state_dir = Path(getattr(csv_manager, "base_data_dir", "data")) / ".ingestion_state"
    coverage = AKShareFetcher(
        str(csv_manager.data_dir),
        state_dir=state_dir,
    ).universe_coverage(universe)
    # 模型晋级使用可训练覆盖率；行情覆盖率仍独立保留给前端展示。
    return {
        **coverage,
        "universe_count": coverage["trainable_eligible_count"],
        "covered_count": coverage["trainable_count"],
        "coverage_ratio": coverage["trainable_ratio"],
    }


def _promotion_reasons(
    report: dict, coverage: dict, champion: dict
) -> dict[str, list[str]]:
    by_layer: dict[str, list[str]] = {}
    status = report.get("status", {})
    for key in ("market", "sector", "entry_risk", "exit_risk", "quality"):
        reasons = []
        metrics = report.get("aggregate", {}).get(key, {})
        if status.get(key) != "active":
            reasons.append(f"{key}_walk_forward_failed")
        if metrics.get("months", 0) < MIN_OOS_MONTHS:
            reasons.append(f"{key}_months_insufficient")
        if metrics.get("n", 0) < MIN_OOS_SAMPLES:
            reasons.append(f"{key}_samples_insufficient")
        if (metrics.get("avg") or 0) <= 0:
            reasons.append(f"{key}_average_return_nonpositive")
        incumbent = champion.get(key, {}).get("metrics") or {}
        if incumbent:
            if metrics.get("avg", float("-inf")) < incumbent.get("avg", float("-inf")):
                reasons.append(f"{key}_worse_than_champion_return")
            if metrics.get("cvar10", float("-inf")) < incumbent.get(
                "cvar10", float("-inf")
            ):
                reasons.append(f"{key}_worse_than_champion_tail")
        if coverage["coverage_ratio"] < MIN_UNIVERSE_COVERAGE:
            reasons.append("universe_coverage_insufficient")
        by_layer[key] = sorted(set(reasons))
    return by_layer


def run_daily_evolution(
    csv_manager: CSVManager | None = None,
    *,
    lease_guard: Callable[[], None] | None = None,
) -> dict:
    """运行一次完整进化；失败只保留原冠军，不影响当日决策。"""
    csv_manager = csv_manager or CSVManager("data", writable=False)
    commit_guard = lease_guard or _noop_lease_guard
    freshness = local_data_status(csv_manager)
    if not freshness["fresh"]:
        return {
            "available": False,
            "reason": "stale_market_data",
            "freshness": freshness,
        }

    from utils.runtime_paths import market_data_dir

    data_root = Path(getattr(csv_manager, "base_data_dir", market_data_dir()))
    pinned_snapshot_id = csv_manager.snapshot_id
    if not pinned_snapshot_id:
        return {
            "available": False,
            "reason": "market_snapshot_unpinned",
            "freshness": freshness,
        }
    trade_date = str(freshness["local_date"])
    current_data_version = data_version(csv_manager.data_dir)
    pipeline_version = evolution_pipeline_version()
    current = get_current_evolution_run(
        trade_date,
        current_data_version,
        pipeline_version,
    )
    if current is not None:
        return {"available": True, "existing": True, **current}

    from utils.reference_snapshots import capture_reference_snapshot

    _check_lease(lease_guard)
    reference_snapshot = capture_reference_snapshot(
        data_root,
        trade_date,
        snapshot_id=pinned_snapshot_id,
    )
    _check_lease(lease_guard)
    late_forward_snapshot = (
        reference_snapshot.get("reason") == "reference_snapshot_not_forward_eligible"
    )
    if not late_forward_snapshot and (
        not reference_snapshot.get("available")
        or reference_snapshot.get("market_snapshot_id") != pinned_snapshot_id
    ):
        return {
            "available": False,
            "reason": "reference_snapshot_unavailable",
            "reference_snapshot": reference_snapshot,
        }

    names, names_snapshot_id = read_snapshot_metadata(
        "stock_names.json", data_root, snapshot_id=csv_manager.snapshot_id
    )
    industries, industries_snapshot_id = read_snapshot_metadata(
        "stock_industry.json", data_root, snapshot_id=csv_manager.snapshot_id
    )
    if (
        not isinstance(names, dict)
        or not names
        or not isinstance(industries, dict)
        or not industries
        or names_snapshot_id != pinned_snapshot_id
        or industries_snapshot_id != pinned_snapshot_id
    ):
        return {
            "available": False,
            "reason": "reference_metadata_unavailable",
            "snapshot_id": pinned_snapshot_id,
        }
    coverage = _coverage(csv_manager, names)
    _check_lease(lease_guard)
    labels = update_decision_outcomes(csv_manager)
    _check_lease(lease_guard)
    try:
        from utils.paper_trading import get_paper_status

        paper_status = get_paper_status(manager=csv_manager)
    except Exception as exc:
        logger.warning("模拟账户状态读取失败: %s", exc)
        paper_status = {"established": False, "reason": "paper_status_unavailable"}
    research_context = {
        "strategy": "super-b1-original",
        "labels": labels,
        "paper_track_record": paper_status,
        "evolution_pipeline_version": pipeline_version,
        "market_snapshot_id": pinned_snapshot_id,
    }
    base_run = {
        "trade_date": trade_date,
        "data_version": current_data_version,
        **coverage,
        "labels_updated": labels["updated"],
    }

    if late_forward_snapshot:
        run = {
            **base_run,
            "status": "complete",
            "dataset_rows": 0,
            "promotion_status": "kept_champion",
            "reason_codes": ["reference_snapshot_not_forward_eligible"],
            "metrics": {
                **research_context,
                "training_status": "skipped_late_forward_snapshot",
                "model_state": "warming_up",
                "trained": False,
                "reference_snapshot": reference_snapshot,
            },
        }
        run["evolution_id"] = _save_evolution_run(run, lease_guard)
        return {"available": True, **run}

    # 数据门槛未满足时只回填结果并记录进度，不运行昂贵且无效的训练。
    if coverage["coverage_ratio"] < MIN_UNIVERSE_COVERAGE:
        run = {
            **base_run,
            "status": "complete",
            "dataset_rows": 0,
            "promotion_status": "kept_champion",
            "reason_codes": ["universe_coverage_insufficient"],
            "metrics": {
                **research_context,
                "training_status": "skipped_data_gate",
                "model_state": "warming_up",
                "trained": False,
                "minimum_coverage": MIN_UNIVERSE_COVERAGE,
                "reference_snapshot": reference_snapshot,
            },
        }
        run["evolution_id"] = _save_evolution_run(run, lease_guard)
        return {"available": True, **run}

    from tools.hierarchical_walk_forward import (
        latest_complete_snapshot_cohort,
        materialize_pit_feature_ledger,
    )
    from utils.reference_snapshots import load_reference_snapshots

    snapshot_catalog = load_reference_snapshots(data_root)
    trading_sessions = load_exchange_sessions(csv_manager.data_dir)
    snapshots, snapshot_cohort = latest_complete_snapshot_cohort(
        snapshot_catalog,
        trading_sessions,
    )
    _check_lease(lease_guard)
    feature_ledger = materialize_pit_feature_ledger(
        csv_manager,
        snapshots=snapshots,
        commit_guard=commit_guard,
    )
    feature_ledger["snapshot_cohort"] = snapshot_cohort
    _check_lease(lease_guard)
    if feature_ledger.get("complete") is not True:
        run = {
            **base_run,
            "status": "failed",
            "dataset_rows": 0,
            "promotion_status": "kept_champion",
            "reason_codes": ["pit_feature_ledger_incomplete"],
            "metrics": {
                **research_context,
                "training_status": "pit_feature_ledger_failed",
                "model_state": "failed",
                "trained": False,
                "feature_ledger": feature_ledger,
                "snapshot_cohort": snapshot_cohort,
                "reference_snapshot": reference_snapshot,
            },
        }
        run["evolution_id"] = _save_evolution_run(run, lease_guard)
        return {"available": True, **run}
    snapshot_months = sorted({date[:7] for date in snapshots})
    if len(snapshot_months) < MIN_REFERENCE_MONTHS:
        run = {
            **base_run,
            "status": "complete",
            "dataset_rows": 0,
            "promotion_status": "kept_champion",
            "reason_codes": ["reference_history_insufficient"],
            "metrics": {
                **research_context,
                "training_status": "skipped_reference_history",
                "model_state": "warming_up",
                "trained": False,
                "reference_months": len(snapshot_months),
                "minimum_reference_months": MIN_REFERENCE_MONTHS,
                "feature_ledger": feature_ledger,
                "snapshot_cohort": snapshot_cohort,
                "reference_snapshot": reference_snapshot,
            },
        }
        run["evolution_id"] = _save_evolution_run(run, lease_guard)
        return {"available": True, **run}

    try:
        from tools.hierarchical_walk_forward import (
            build_dataset,
            train_and_register,
            training_readiness,
        )

        frame = build_dataset(
            csv_manager,
            names,
            industries,
            snapshots=snapshots,
            feature_ledger=feature_ledger,
            commit_guard=commit_guard,
        )
        if frame.empty:
            dataset_reason = str(frame.attrs.get("reason") or "training_dataset_empty")
            warming_reasons = {
                "pit_daily_snapshot_history_incomplete",
            }
            pit_history_missing = dataset_reason in warming_reasons
            failure_training_status = (
                "training_dataset_empty"
                if dataset_reason == "training_dataset_empty"
                else "pit_evidence_failed"
            )
            run = {
                **base_run,
                "status": "complete" if pit_history_missing else "failed",
                "dataset_rows": 0,
                "promotion_status": "kept_champion",
                "reason_codes": [dataset_reason],
                "metrics": {
                    **research_context,
                    "training_status": (
                        "skipped_pit_evidence_history"
                        if pit_history_missing
                        else failure_training_status
                    ),
                    "model_state": "warming_up" if pit_history_missing else "failed",
                    "trained": False,
                    "pit_contract_version": PIT_CONTRACT_VERSION,
                    "feature_ledger": feature_ledger,
                    "snapshot_cohort": snapshot_cohort,
                    "dataset_gate": dict(frame.attrs),
                    "reference_snapshot": reference_snapshot,
                },
            }
            run["evolution_id"] = _save_evolution_run(run, lease_guard)
            return {"available": True, **run}

        terminal_horizon = (
            1
            + DEFAULT_EXECUTION_POLICY.holding_sessions
            + DEFAULT_EXECUTION_POLICY.max_exit_delay_sessions
        )
        closed_months = {
            month
            for month in {str(value)[:7] for value in frame["date"]}
            if (
                month_sessions := [
                    session for session in trading_sessions if session.startswith(month)
                ]
            )
            and trading_sessions.index(month_sessions[-1]) + terminal_horizon
            < len(trading_sessions)
        }
        excluded_open_months = sorted(
            {str(value)[:7] for value in frame["date"]} - closed_months
        )
        frame = frame[frame["date"].astype(str).str[:7].isin(closed_months)].copy()
        if frame.empty:
            run = {
                **base_run,
                "status": "complete",
                "dataset_rows": 0,
                "promotion_status": "kept_champion",
                "reason_codes": ["closed_signal_history_insufficient"],
                "metrics": {
                    **research_context,
                    "training_status": "skipped_open_signal_months",
                    "model_state": "warming_up",
                    "trained": False,
                    "closed_signal_months": 0,
                    "excluded_open_months": excluded_open_months,
                    "minimum_signal_months": MIN_SIGNAL_MONTHS,
                    "pit_contract_version": PIT_CONTRACT_VERSION,
                    "feature_ledger": feature_ledger,
                    "snapshot_cohort": snapshot_cohort,
                    "reference_snapshot": reference_snapshot,
                },
            }
            run["evolution_id"] = _save_evolution_run(run, lease_guard)
            return {"available": True, **run}

        quality_rows = frame[
            (frame["return_label_mature"] == 1)
            & frame["net_return_5"].notna()
            & frame["excess_5"].notna()
            & frame["y_quality"].notna()
        ]
        entry_rows = frame[
            (frame["entry_label_mature"] == 1) & frame["y_entry_risk"].notna()
        ]
        exit_rows = frame[
            (frame["entry_feasible"] == 1)
            & (frame["exit_label_mature"] == 1)
            & frame["y_exit_risk"].notna()
        ]
        mature_months = {
            "quality_market_sector": len(
                {str(value)[:7] for value in quality_rows["date"]}
            ),
            "entry_risk": len({str(value)[:7] for value in entry_rows["date"]}),
            "exit_risk": len({str(value)[:7] for value in exit_rows["date"]}),
        }
        signal_months = min(mature_months.values(), default=0)
        if signal_months < MIN_SIGNAL_MONTHS:
            run = {
                **base_run,
                "status": "complete",
                "dataset_rows": len(frame),
                "promotion_status": "kept_champion",
                "reason_codes": ["signal_history_insufficient"],
                "metrics": {
                    **research_context,
                    "training_status": "skipped_signal_history",
                    "model_state": "warming_up",
                    "trained": False,
                    "signal_months": signal_months,
                    "mature_signal_months_by_layer": mature_months,
                    "closed_signal_months": len(closed_months),
                    "excluded_open_months": excluded_open_months,
                    "minimum_signal_months": MIN_SIGNAL_MONTHS,
                    "pit_contract_version": PIT_CONTRACT_VERSION,
                    "feature_ledger": feature_ledger,
                    "snapshot_cohort": snapshot_cohort,
                    "reference_snapshot": reference_snapshot,
                },
            }
            run["evolution_id"] = _save_evolution_run(run, lease_guard)
            return {"available": True, **run}

        readiness = training_readiness(frame)
        if readiness.get("ready") is not True:
            readiness_reason = str(
                readiness.get("reason") or "walk_forward_sample_insufficient"
            )
            run = {
                **base_run,
                "status": "complete",
                "dataset_rows": len(frame),
                "promotion_status": "kept_champion",
                "reason_codes": [readiness_reason],
                "metrics": {
                    **research_context,
                    "training_status": "skipped_training_readiness",
                    "model_state": "warming_up",
                    "trained": False,
                    "training_readiness": readiness,
                    "signal_months": signal_months,
                    "mature_signal_months_by_layer": mature_months,
                    "closed_signal_months": len(closed_months),
                    "excluded_open_months": excluded_open_months,
                    "pit_contract_version": PIT_CONTRACT_VERSION,
                    "feature_ledger": feature_ledger,
                    "snapshot_cohort": snapshot_cohort,
                    "reference_snapshot": reference_snapshot,
                },
            }
            run["evolution_id"] = _save_evolution_run(run, lease_guard)
            return {"available": True, **run}

        artifact_relative_dir = (
            Path("research_artifacts")
            / "model_evolution"
            / trade_date
            / pipeline_version
            / pinned_snapshot_id
        )
        artifact_dir = data_root / artifact_relative_dir
        dataset_path = artifact_dir / "hierarchical_training.csv"
        bundle_path = artifact_dir / "hierarchical_model_bundle.json"
        report_path = artifact_dir / "hierarchical_walk_forward.json"
        _check_lease(lease_guard)
        _atomic_write_frame(frame, dataset_path)
        _check_lease(lease_guard)
        temporary_bundle = _temporary_artifact_path(bundle_path)
        try:
            _check_lease(lease_guard)
            trained_as_of = _deterministic_trained_as_of(frame)
            result = train_and_register(
                frame,
                temporary_bundle,
                commit_guard=commit_guard,
                trained_as_of=trained_as_of,
            )
            _check_lease(lease_guard)
            temporary_bundle.replace(bundle_path)
            _check_lease(lease_guard)
        finally:
            temporary_bundle.unlink(missing_ok=True)
        _check_lease(lease_guard)
        _atomic_write_json(result, report_path)
        _check_lease(lease_guard)
        version = result["bundle"]["version"]
        active_models, _ = get_active_policy_models()
        champions = {
            key: model
            for key, model in active_models.items()
            if VALIDATED_MODEL_SOURCE_REFS.issubset(set(model.get("source_refs") or []))
        }
        reasons_by_layer = _promotion_reasons(result, coverage, champions)
        reasons = sorted(
            {reason for values in reasons_by_layer.values() for reason in values}
        )
        # 日任务只登记 shadow 研究结果。生产策略只能在独立的发布窗口中切换。
        release = {
            "released": False,
            "state": "forward_observation_required",
            "reason": "release_review_required",
        }
        reasons = sorted(set([*reasons, "release_review_required"]))
        run = {
            **base_run,
            "status": "complete",
            "dataset_rows": len(frame),
            "challenger_version": version,
            "promotion_status": "shadow_registered",
            "reason_codes": reasons,
            "metrics": {
                **research_context,
                "training_status": "shadow_trained",
                "model_state": "shadow_observation",
                "trained": True,
                "reference_snapshot": reference_snapshot,
                "pit_contract_version": PIT_CONTRACT_VERSION,
                "feature_ledger": feature_ledger,
                "snapshot_cohort": snapshot_cohort,
                "signal_months": signal_months,
                "mature_signal_months_by_layer": mature_months,
                "closed_signal_months": len(closed_months),
                "excluded_open_months": excluded_open_months,
                "validation_status": result["status"],
                "promotion_reasons_by_layer": reasons_by_layer,
                "aggregate": result["aggregate"],
                "release": release,
                "artifacts": {
                    "dataset": (artifact_relative_dir / dataset_path.name).as_posix(),
                    "model_bundle": (
                        artifact_relative_dir / bundle_path.name
                    ).as_posix(),
                    "walk_forward_report": (
                        artifact_relative_dir / report_path.name
                    ).as_posix(),
                },
            },
        }
        run["evolution_id"] = _save_evolution_run(run, lease_guard)
        return {"available": True, **run}
    except Exception as exc:
        logger.exception("每日自我进化失败: %s", exc)
        run = {
            **base_run,
            "status": "failed",
            "promotion_status": "kept_champion",
            "reason_codes": ["evolution_exception"],
            "metrics": {**research_context, "error": str(exc)},
        }
        run["evolution_id"] = _save_evolution_run(run, lease_guard)
        return {"available": True, **run}
