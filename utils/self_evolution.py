"""每日自我进化：真实结果回填、挑战模型训练、样本外评估与受控晋级。"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

from utils.csv_manager import CSVManager
from utils.data_freshness import local_data_status
from utils.decision_ledger import (
    append_decision_outcome,
    get_active_policy_models,
    list_pending_outcome_candidates,
    save_evolution_run,
)
from utils.decision_versions import VALIDATED_MODEL_SOURCE_REFS, data_version
from utils.execution_model import evaluate_trade
from utils.market_filter import is_main_board, main_board_only
from utils.market_snapshot import read_snapshot_metadata

logger = logging.getLogger(__name__)

MIN_OOS_MONTHS = 6
MIN_OOS_SAMPLES = 80
MIN_UNIVERSE_COVERAGE = 0.60
MIN_REFERENCE_MONTHS = 21
MIN_SIGNAL_MONTHS = 21
PIT_CONTRACT_VERSION = "pit-feature-reference-v2"


def update_decision_outcomes(csv_manager: CSVManager) -> dict:
    """回填 buy/observe/avoid 的真实表现，显式计算错过上涨的机会成本。"""
    from utils.reference_snapshots import load_reference_snapshots

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
    rows = list_pending_outcome_candidates()
    updated = complete = missing = 0
    for item in rows:
        frame = csv_manager.read_stock(item["code"])
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
            require_pit_status=True,
        )
        execution = evaluate_trade(
            daily,
            item["trade_date"],
            hold_days=5,
            code=item["code"],
            security_states=security_states,
            require_pit_status=True,
        )
        outcome = {
            **item,
            "source_snapshot_id": source_snapshot_id,
            "days_tracked": min(len(after), 5),
            "status": "pending" if after.empty else "partial",
        }
        if not after.empty:
            entry_price = float(after.iloc[0].get("open", 0) or 0)
            outcome.update(
                {
                    "entry_date": str(after.iloc[0]["date"]),
                    "entry_price": round(entry_price, 3) if entry_price > 0 else None,
                    "entry_feasible": int(bool(execution.get("entry_feasible"))),
                }
            )
        if one_session_execution.get("net_return") is not None:
            outcome["ret_1"] = one_session_execution["net_return"]
        if execution.get("available"):
            outcome.update(
                {
                    "entry_date": execution.get("entry_date")
                    or outcome.get("entry_date"),
                    "entry_price": execution.get("entry_price")
                    or outcome.get("entry_price"),
                    "entry_feasible": int(bool(execution.get("entry_feasible"))),
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
            if execution.get("reason") == "entry_unbuyable":
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


def run_daily_evolution(csv_manager: CSVManager | None = None) -> dict:
    """运行一次完整进化；失败只保留原冠军，不影响当日决策。"""
    csv_manager = csv_manager or CSVManager("data", writable=False)
    freshness = local_data_status(csv_manager)
    if not freshness["fresh"]:
        return {
            "available": False,
            "reason": "stale_market_data",
            "freshness": freshness,
        }

    from utils.reference_snapshots import capture_reference_snapshot

    data_root = getattr(csv_manager, "base_data_dir", Path("data"))
    pinned_snapshot_id = csv_manager.snapshot_id
    if not pinned_snapshot_id:
        return {
            "available": False,
            "reason": "market_snapshot_unpinned",
            "freshness": freshness,
        }
    reference_snapshot = capture_reference_snapshot(
        data_root,
        freshness["local_date"],
        snapshot_id=pinned_snapshot_id,
    )
    if (
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
    labels = update_decision_outcomes(csv_manager)
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
    }
    base_run = {
        "trade_date": freshness["local_date"],
        "data_version": data_version(csv_manager.data_dir),
        **coverage,
        "labels_updated": labels["updated"],
    }

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
                "minimum_coverage": MIN_UNIVERSE_COVERAGE,
                "reference_snapshot": reference_snapshot,
            },
        }
        run["evolution_id"] = save_evolution_run(run)
        return {"available": True, **run}

    from utils.reference_snapshots import load_reference_snapshots

    snapshots = load_reference_snapshots(data_root)
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
                "reference_months": len(snapshot_months),
                "minimum_reference_months": MIN_REFERENCE_MONTHS,
                "reference_snapshot": reference_snapshot,
            },
        }
        run["evolution_id"] = save_evolution_run(run)
        return {"available": True, **run}

    try:
        from tools.hierarchical_walk_forward import build_dataset, train_and_register

        frame = build_dataset(csv_manager, names, industries)
        if frame.empty:
            dataset_reason = str(frame.attrs.get("reason") or "training_dataset_empty")
            pit_history_missing = dataset_reason == "pit_feature_history_unavailable"
            run = {
                **base_run,
                "status": "complete" if pit_history_missing else "failed",
                "dataset_rows": 0,
                "promotion_status": "kept_champion",
                "reason_codes": [dataset_reason],
                "metrics": {
                    **research_context,
                    "training_status": (
                        "skipped_pit_feature_history"
                        if pit_history_missing
                        else "training_dataset_empty"
                    ),
                    "pit_contract_version": PIT_CONTRACT_VERSION,
                    "dataset_gate": dict(frame.attrs),
                    "reference_snapshot": reference_snapshot,
                },
            }
            run["evolution_id"] = save_evolution_run(run)
            return {"available": True, **run}

        signal_months = sorted({str(value)[:7] for value in frame["date"]})
        if len(signal_months) < MIN_SIGNAL_MONTHS:
            run = {
                **base_run,
                "status": "complete",
                "dataset_rows": len(frame),
                "promotion_status": "kept_champion",
                "reason_codes": ["signal_history_insufficient"],
                "metrics": {
                    **research_context,
                    "training_status": "skipped_signal_history",
                    "signal_months": len(signal_months),
                    "minimum_signal_months": MIN_SIGNAL_MONTHS,
                    "pit_contract_version": PIT_CONTRACT_VERSION,
                    "reference_snapshot": reference_snapshot,
                },
            }
            run["evolution_id"] = save_evolution_run(run)
            return {"available": True, **run}

        dataset_path = Path("data/hierarchical_training.csv")
        frame.to_csv(dataset_path, index=False)
        result = train_and_register(frame, Path("data/hierarchical_model_bundle.json"))
        Path("data/hierarchical_walk_forward.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
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
                "reference_snapshot": reference_snapshot,
                "pit_contract_version": PIT_CONTRACT_VERSION,
                "signal_months": len(signal_months),
                "validation_status": result["status"],
                "promotion_reasons_by_layer": reasons_by_layer,
                "aggregate": result["aggregate"],
                "release": release,
            },
        }
        run["evolution_id"] = save_evolution_run(run)
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
        run["evolution_id"] = save_evolution_run(run)
        return {"available": True, **run}
