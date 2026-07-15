"""每日自我进化：真实结果回填、挑战模型训练、样本外评估与受控晋级。"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

from utils.csv_manager import CSVManager
from utils.data_freshness import local_data_status
from utils.decision_ledger import (
    get_active_models,
    list_pending_outcome_candidates,
    promote_model_bundle,
    save_evolution_run,
    upsert_decision_outcome,
)
from utils.decision_versions import data_version
from utils.execution_model import evaluate_trade
from utils.market_filter import is_main_board, main_board_only

logger = logging.getLogger(__name__)

MIN_OOS_MONTHS = 6
MIN_OOS_SAMPLES = 80
MIN_UNIVERSE_COVERAGE = 0.60


def update_decision_outcomes(csv_manager: CSVManager) -> dict:
    """回填 buy/observe/avoid 的真实表现，显式计算错过上涨的机会成本。"""
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
        execution = evaluate_trade(daily, item["trade_date"], hold_days=5)
        outcome = {
            **item,
            "days_tracked": min(len(after), 5),
            "status": "pending" if after.empty else "partial",
        }
        if not after.empty:
            entry_price = float(after.iloc[0].get("open", 0) or 0)
            outcome.update({
                "entry_date": str(after.iloc[0]["date"]),
                "entry_price": round(entry_price, 3) if entry_price > 0 else None,
                "entry_feasible": int(bool(execution.get("entry_feasible"))),
            })
            if entry_price > 0:
                outcome["ret_1"] = round(
                    (float(after.iloc[0]["close"]) / entry_price - 1) * 100, 2
                )
        if execution.get("available"):
            outcome.update({
                "entry_date": execution.get("entry_date") or outcome.get("entry_date"),
                "entry_price": execution.get("entry_price") or outcome.get("entry_price"),
                "entry_feasible": int(bool(execution.get("entry_feasible"))),
                "net_ret_5": execution.get("net_return"),
                "max_gain_5": execution.get("max_gain"),
                "max_drawdown_5": execution.get("max_drawdown"),
            })
            if execution.get("reason") == "entry_unbuyable":
                outcome["status"] = "complete"
            elif execution.get("net_return") is not None:
                outcome["status"] = "complete"
            elif execution.get("reason") == "exit_unsellable" and len(after) >= 10:
                outcome["status"] = "complete"
        upsert_decision_outcome(outcome)
        updated += 1
        complete += int(outcome["status"] == "complete")
    return {"pending": len(rows), "updated": updated, "complete": complete, "missing_data": missing}


def _coverage(csv_manager: CSVManager, names: dict) -> dict:
    from utils.akshare_fetcher import AKShareFetcher

    universe = {code: name for code, name in names.items()
                if not main_board_only() or is_main_board(code)}
    coverage = AKShareFetcher(str(csv_manager.data_dir)).universe_coverage(universe)
    # 模型晋级使用可训练覆盖率；行情覆盖率仍独立保留给前端展示。
    return {
        **coverage,
        "universe_count": coverage["trainable_eligible_count"],
        "covered_count": coverage["trainable_count"],
        "coverage_ratio": coverage["trainable_ratio"],
    }


def _promotion_reasons(report: dict, coverage: dict, champion: dict) -> list[str]:
    reasons = []
    status = report.get("status", {})
    for key in ("market", "sector"):
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
            if metrics.get("cvar10", float("-inf")) < incumbent.get("cvar10", float("-inf")):
                reasons.append(f"{key}_worse_than_champion_tail")
    if coverage["coverage_ratio"] < MIN_UNIVERSE_COVERAGE:
        reasons.append("universe_coverage_insufficient")
    return sorted(set(reasons))


def run_daily_evolution(csv_manager: CSVManager | None = None) -> dict:
    """运行一次完整进化；失败只保留原冠军，不影响当日决策。"""
    csv_manager = csv_manager or CSVManager("data")
    freshness = local_data_status(csv_manager)
    if not freshness["fresh"]:
        return {"available": False, "reason": "stale_market_data", "freshness": freshness}

    names = json.loads(Path("data/stock_names.json").read_text(encoding="utf-8"))
    industries = json.loads(Path("data/stock_industry.json").read_text(encoding="utf-8"))
    coverage = _coverage(csv_manager, names)
    labels = update_decision_outcomes(csv_manager)
    base_run = {
        "trade_date": freshness["local_date"],
        "data_version": data_version(),
        **coverage,
        "labels_updated": labels["updated"],
    }

    try:
        from tools.hierarchical_walk_forward import build_dataset, train_and_register

        frame = build_dataset(csv_manager, names, industries)
        if frame.empty:
            run = {
                **base_run, "status": "failed", "promotion_status": "kept_champion",
                "reason_codes": ["training_dataset_empty"],
                "metrics": {"strategy": "super-b1-original", "labels": labels},
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
        reasons = _promotion_reasons(result, coverage, get_active_models())
        promotion = (
            promote_model_bundle(version, result["status"])
            if not reasons else {"promoted": False, "reason": "promotion_gate_failed"}
        )
        run = {
            **base_run,
            "status": "complete",
            "dataset_rows": len(frame),
            "challenger_version": version,
            "promotion_status": "promoted" if promotion["promoted"] else "kept_champion",
            "reason_codes": reasons or [],
            "metrics": {
                "strategy": "super-b1-original",
                "labels": labels,
                "validation_status": result["status"],
                "aggregate": result["aggregate"],
                "promotion": promotion,
            },
        }
        run["evolution_id"] = save_evolution_run(run)
        return {"available": True, **run}
    except Exception as exc:
        logger.exception("每日自我进化失败: %s", exc)
        run = {
            **base_run, "status": "failed", "promotion_status": "kept_champion",
            "reason_codes": ["evolution_exception"],
            "metrics": {"strategy": "super-b1-original", "labels": labels, "error": str(exc)},
        }
        run["evolution_id"] = save_evolution_run(run)
        return {"available": True, **run}
