"""分层推荐决策引擎：收盘候选 + 盘前风险复核。"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from strategy.factor_lib import FactorContext
from utils.csv_manager import CSVManager
from utils.decision_config import get_decision_config
from utils.decision_ledger import get_active_models, get_latest_decision, save_decision_run
from utils.decision_versions import FEATURE_VERSION, data_version, strategy_version
from utils.data_freshness import local_data_status, next_trade_date
from utils.probability_model import BinaryLogit

logger = logging.getLogger(__name__)
TZ = ZoneInfo("Asia/Shanghai")


def _load_json(path: str) -> dict:
    file = Path(path)
    return json.loads(file.read_text(encoding="utf-8")) if file.exists() else {}


def _baseline_candidates() -> tuple[str | None, list[dict]]:
    from utils.factor_scan import get_factor_hits
    from utils.market_filter import is_main_board, main_board_only
    from utils.quant_pick import CORE_FACTOR
    from utils.sector_rotation import get_sector_rotation

    cm = CSVManager("data")
    names = _load_json("data/stock_names.json")
    industries = _load_json("data/stock_industry.json")
    caps = _load_json("data/stock_market_cap.json")
    scan = get_factor_hits(cm, names, [CORE_FACTOR])
    if not scan.get("available"):
        return None, []
    hits = scan["results"][CORE_FACTOR]["hits"]
    if main_board_only():
        hits = [h for h in hits if is_main_board(h.get("code", ""))]
    sectors = get_sector_rotation(cm)
    heat = sectors.get("heat_map") or {}
    rows = []
    for hit in hits:
        code = hit.get("code", "")
        industry = industries.get(code, "")
        cap = caps.get(code, {})
        cap_value = (cap.get("circ_mv") or cap.get("total_mv")) if isinstance(cap, dict) else None
        rows.append({
            **hit, "name": hit.get("name") or names.get(code, code), "industry": industry,
            "cap_yi": round(cap_value / 1e8, 1) if isinstance(cap_value, (int, float)) and cap_value > 0 else None,
            "sector": heat.get(industry),
        })
    return scan["trade_date"], rows


def _active_model_bundle() -> tuple[dict, str]:
    models = get_active_models()
    version = next(iter(models.values()))["version"] if models else "baseline-only"
    return models, version


def _live_feature_rows(candidates: list[dict], trade_date: str) -> pd.DataFrame:
    """与训练工具共用特征定义。仅在存在 active 模型时计算。"""
    from tools.hierarchical_walk_forward import (
        MARKET_FEATURES, SECTOR_FEATURES, STOCK_FEATURES, _stock_features, build_panels,
    )

    cm = CSVManager("data")
    industries = _load_json("data/stock_industry.json")
    codes = [c for c in cm.list_all_stocks() if c.isdigit() and len(c) == 6]
    market, sector, stock_frames = build_panels(cm, codes, industries)
    rows = []
    for candidate in candidates:
        code, industry = candidate["code"], candidate.get("industry") or "未知"
        frame = stock_frames.get(code)
        if frame is None or trade_date not in market.index or (trade_date, industry) not in sector.index:
            rows.append({"code": code, "feature_missing": True})
            continue
        sub = frame[frame["date"] <= trade_date]
        if len(sub) < 60:
            rows.append({"code": code, "feature_missing": True})
            continue
        record = {"code": code, "feature_missing": False}
        record.update({k: float(market.loc[trade_date].get(k)) for k in MARKET_FEATURES})
        record.update({k: float(sector.loc[(trade_date, industry)].get(k)) for k in SECTOR_FEATURES})
        record.update(_stock_features(FactorContext(sub)))
        rows.append(record)
    return pd.DataFrame(rows)


def _predict(models: dict, features: pd.DataFrame) -> dict[str, dict[str, float]]:
    out = {code: {} for code in features["code"]}
    valid = features[~features["feature_missing"]]
    for key, registration in models.items():
        model = BinaryLogit.from_dict(registration["artifact"])
        values = model.predict_proba(valid)
        for code, value in zip(valid["code"], values):
            out[code][key] = round(float(value), 4)
            out[code][f"{key}_threshold"] = registration.get("params", {}).get("threshold")
    return out


def run_close_decision(as_of: str | None = None) -> dict:
    config = get_decision_config()
    if not config["enabled"]:
        return {"available": False, "reason": "hierarchy_disabled"}
    freshness = local_data_status()
    if not freshness["fresh"]:
        return {"available": False, "reason": "stale_market_data", "freshness": freshness}
    trade_date, baseline = _baseline_candidates()
    if not trade_date:
        return {"available": False, "reason": "baseline_unavailable"}
    as_of = as_of or f"{trade_date}T15:00:00+08:00"
    models, model_version = _active_model_bundle()
    predictions = {}
    if models and baseline:
        try:
            predictions = _predict(models, _live_feature_rows(baseline, trade_date))
        except Exception as exc:
            logger.exception("实时分层特征计算失败: %s", exc)
            models = {}
            model_version = "baseline-only"

    reason_codes = []
    if not baseline:
        final_action, status = "none", "complete"
        reason_codes.append("no_rule_hits")
    elif config["strict_unvalidated_gate"] and not {"market", "sector"}.issubset(models):
        final_action, status = "observe", "degraded"
        reason_codes.append("hierarchy_models_unvalidated")
    else:
        final_action, status = "buy", "complete"

    candidates = []
    for row in baseline:
        probability = predictions.get(row["code"], {})
        reasons = []
        action = "buy" if final_action == "buy" else "observe"
        market_p, market_t = probability.get("market"), probability.get("market_threshold")
        sector_p, sector_t = probability.get("sector"), probability.get("sector_threshold")
        risk_p, risk_t = probability.get("risk"), probability.get("risk_threshold")
        if action == "buy" and (market_p is None or market_t is None or market_p < market_t):
            action, reasons = "avoid", ["market_gate"]
        elif action == "buy" and (sector_p is None or sector_t is None or sector_p < sector_t):
            action, reasons = "avoid", ["sector_gate"]
        elif action == "buy" and risk_p is not None and risk_t is not None and risk_p > risk_t:
            action, reasons = "avoid", ["stock_risk_veto"]
        elif action == "observe":
            reasons = ["hierarchy_models_unvalidated"]
        candidates.append({
            "code": row["code"], "name": row.get("name"), "industry": row.get("industry"),
            "action": action, "baseline": {
                "signal": "cloud_stair", "close": row.get("close"), "J": row.get("J"),
                "RSI": row.get("RSI"), "cap_yi": row.get("cap_yi"),
            },
            "market": {"probability": market_p, "threshold": market_t},
            "sector": {**(row.get("sector") or {}), "probability": sector_p, "threshold": sector_t},
            "stock": {"risk_probability": risk_p, "risk_threshold": risk_t,
                      "quality_probability": probability.get("quality")},
            "events": [], "reason_codes": reasons,
        })

    actionable = [c for c in candidates if c["action"] == "buy"]
    if actionable and "quality" in models:
        actionable.sort(key=lambda c: c["stock"].get("quality_probability") or -1, reverse=True)
        keep = {c["code"] for c in actionable[:3]}
        for candidate in candidates:
            if candidate["action"] == "buy" and candidate["code"] not in keep:
                candidate["action"] = "observe"
                candidate["reason_codes"].append("outside_top3")
    elif len(actionable) > 3:
        # 无经验证的个股质量模型时，不伪造 top-1。
        for candidate in candidates:
            if candidate["action"] == "buy":
                candidate["action"] = "observe"
                candidate["reason_codes"].append("unresolved_tie_over_3")
    candidates.sort(key=lambda c: (
        {"buy": 0, "observe": 1, "avoid": 2}[c["action"]],
        -(c["sector"].get("probability") or -1),
        -(c["stock"].get("quality_probability") or -1), c["code"],
    ))
    for index, candidate in enumerate(candidates, start=1):
        candidate["rank"] = index
        candidate["tie_group"] = 1 if candidate["action"] == "buy" else index

    if not any(c["action"] == "buy" for c in candidates) and final_action == "buy":
        final_action = "observe"
        reason_codes.append("all_candidates_downgraded")
    run = {
        "trade_date": trade_date, "stage": "close", "as_of": as_of,
        "status": status, "final_action": final_action,
        "strategy_version": strategy_version(), "feature_version": FEATURE_VERSION,
        "model_version": model_version, "data_version": data_version(),
        "source_refs": [f"local-eod:{trade_date}", "factor:cloud_stair"],
        "market": {
            "models_active": sorted(models),
            "gate_order": ["market", "sector", "stock", "execution"],
            "decision_for_date": next_trade_date(trade_date),
        },
        "evaluation": {k: v.get("metrics", {}) for k, v in models.items()},
        "reason_codes": reason_codes,
    }
    run_id = save_decision_run(run, candidates)
    from utils.decision_ledger import get_decision
    return {"available": True, **get_decision(run_id)}


def run_preopen_decision(as_of: str | None = None) -> dict:
    from utils.event_risk import review_candidates

    config = get_decision_config()
    if not config["enabled"] or not config["preopen_event_check"]:
        return {"available": False, "reason": "preopen_review_disabled"}
    close_run = get_latest_decision("close") or run_close_decision()
    if not close_run or not close_run.get("candidates"):
        return {"available": False, "reason": "close_list_unavailable"}
    as_of = as_of or datetime.now(TZ).replace(hour=8, minute=45, second=0, microsecond=0).isoformat()
    model_active = "event_llm" in get_active_models()
    review = review_candidates(close_run["candidates"], close_run["trade_date"], as_of, model_active)
    candidates = []
    for item in close_run["candidates"]:
        candidate = {**item, "events": review["events_by_code"].get(item["code"], [])}
        reasons = list(candidate.get("reason_codes", []))
        if item["code"] in review["veto_codes"]:
            candidate["action"] = "avoid"
            reasons.append("overnight_event_veto")
        elif not review["available"]:
            candidate["action"] = "observe"
            reasons.append("overnight_source_missing")
        elif item["code"] in review["review_codes"] and candidate["action"] == "buy":
            candidate["action"] = "observe"
            reasons.append("overnight_event_review")
        candidate["reason_codes"] = sorted(set(reasons))
        candidates.append(candidate)
    buy_count = sum(c["action"] == "buy" for c in candidates)
    final_action = "buy" if buy_count else ("observe" if candidates else "none")
    run = {
        "trade_date": close_run["trade_date"], "stage": "preopen", "as_of": as_of,
        "status": "complete" if review["available"] else "degraded", "final_action": final_action,
        "strategy_version": close_run["strategy_version"],
        "feature_version": close_run["feature_version"], "model_version": close_run["model_version"],
        "data_version": close_run["data_version"],
        "source_refs": close_run["source_refs"] + review["source_refs"],
        "market": close_run["market"],
        "evaluation": {"close_run_id": close_run["run_id"], "event_llm": review["llm"]},
        "reason_codes": [] if review["available"] else ["overnight_source_missing"],
    }
    run_id = save_decision_run(run, candidates)
    from utils.decision_ledger import get_decision
    return {"available": True, **get_decision(run_id)}
