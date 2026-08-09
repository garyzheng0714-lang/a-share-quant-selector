"""只为云阶候选服务的市场、板块与事件证据层。

云阶公式仍是唯一入围规则；本模块只生成可追溯的相对排序、情报摘要和
市场执行语境。抓取只发生在 worker，Web 只读取已经落入不可变 AI run 的结果。
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from utils.runtime_paths import runtime_state_dir


TZ = ZoneInfo("Asia/Shanghai")
METHODOLOGY = "cloud_stair_priority_v1"


def build_market_context(csv_manager) -> dict:
    """把已发布市场温度转成不会取消云阶信号的执行语境。"""
    from utils.market_thermometer import get_thermometer

    thermometer = get_thermometer(csv_manager)
    if not thermometer.get("available"):
        return {
            "available": False,
            "reason": thermometer.get("reason") or "market_temperature_unavailable",
            "execution_mode": "证据不足",
            "state_label": "市场温度待补全",
            "summary": "市场温度尚未与当前快照绑定，不影响云阶入选。",
        }
    heat = thermometer.get("heat") or {}
    score = float(heat.get("breadth_score") or 0)
    level = str(heat.get("level") or "normal")
    trend = str(heat.get("trend") or "sideways")
    if level == "hot":
        state_label, execution_mode = "高温分化", "谨慎参与"
    elif level == "cold":
        state_label, execution_mode = "低温修复", "试仓"
    elif trend == "bull":
        state_label, execution_mode = "常温回暖", "正常参与"
    elif trend == "bear":
        state_label, execution_mode = "常温降温", "试仓"
    else:
        state_label, execution_mode = "常温震荡", "正常参与"
    return {
        "available": True,
        "score": round(score, 1),
        "state_label": state_label,
        "execution_mode": execution_mode,
        "level": level,
        "trend": trend,
        "warming_sector_ratio": heat.get("warming_sector_ratio"),
        "cooling_sector_ratio": heat.get("cooling_sector_ratio"),
        "delta3_mean": heat.get("delta3_mean"),
        "sector_count": heat.get("sector_count"),
        "as_of": heat.get("as_of"),
        "summary": (
            f"市场温度 {score:.0f}，{state_label}；只调整执行强度，不取消已确认的云阶买点。"
        ),
        "source_refs": thermometer.get("source_refs") or [],
    }


def _clamp(value: float, low: float = 0, high: float = 100) -> float:
    return max(low, min(high, value))


def _structure_score(candidate: dict) -> tuple[float, dict]:
    wave = float(candidate.get("wave_gain_pct") or 30)
    wave_score = _clamp(100 - abs(wave - 50) * 1.15, 55, 100)
    close = float(candidate.get("close") or 0)
    breakout = float(candidate.get("breakout_price") or 0)
    breakout_gap = (
        ((close / breakout) - 1) * 100 if close > 0 and breakout > 0 else None
    )
    if breakout_gap is None:
        breakout_score = 70
    elif 0 <= breakout_gap <= 3:
        breakout_score = 100
    elif breakout_gap <= 6:
        breakout_score = 90
    elif breakout_gap <= 10:
        breakout_score = 75
    else:
        breakout_score = _clamp(75 - (breakout_gap - 10) * 2, 45, 75)
    day_change = abs(float(candidate.get("pct_change") or 0))
    chase_score = 96 if day_change <= 5 else 82 if day_change <= 8 else 62
    score = wave_score * 0.4 + breakout_score * 0.45 + chase_score * 0.15
    return round(score, 1), {
        "wave_score": round(wave_score, 1),
        "breakout_score": round(breakout_score, 1),
        "breakout_gap_pct": round(breakout_gap, 2)
        if breakout_gap is not None
        else None,
        "chase_score": chase_score,
    }


def _normal_title(value: str) -> str:
    return re.sub(r"[\W_\d]+", "", value, flags=re.UNICODE).lower()


def _dedupe_events(events: list[dict]) -> list[dict]:
    seen: set[str] = set()
    rows = []

    def importance(row: dict) -> tuple[int, int, str]:
        impact = {"high": 3, "medium": 2, "low": 1}.get(str(row.get("impact")), 0)
        relevance = {"direct": 3, "mentioned": 2, "search_result": 1}.get(
            str(row.get("relevance")),
            2 if row.get("source_category") == "announcement" else 0,
        )
        return impact, relevance, str(row.get("published_at") or "")

    for event in sorted(events, key=importance, reverse=True):
        key = _normal_title(str(event.get("title") or ""))
        if not key or key in seen:
            continue
        seen.add(key)
        rows.append(event)
    return rows


def _event_adjustment(events: list[dict]) -> tuple[float, dict]:
    positive = sum(event.get("sentiment") == "positive" for event in events)
    negative = sum(event.get("sentiment") == "negative" for event in events)
    mixed = sum(event.get("sentiment") == "mixed" for event in events)
    hard = sum(bool(event.get("hard_tags")) for event in events)
    adjustment = (
        min(positive * 1.5, 5)
        - min(negative * 2.5 + mixed * 1.5, 8)
        - min(hard * 6, 12)
    )
    return round(adjustment, 1), {
        "positive": positive,
        "negative": negative,
        "mixed": mixed,
        "neutral": max(0, len(events) - positive - negative - mixed),
        "hard_risk": hard,
    }


def _evidence_grade(structure: float, sector: float, counts: dict) -> str:
    if (
        structure >= 88
        and sector >= 70
        and not counts["negative"]
        and not counts["hard_risk"]
    ):
        return "A"
    if structure >= 76 and sector >= 50 and not counts["hard_risk"]:
        return "B"
    return "C"


def _diversified_codes(rows: list[dict], limit: int = 3) -> list[str]:
    selected: list[dict] = []
    used_industries: set[str] = set()
    for row in rows:
        industry = str(row.get("industry") or "")
        if industry and industry not in used_industries:
            selected.append(row)
            used_industries.add(industry)
        if len(selected) >= limit:
            return [str(item["code"]) for item in selected]
    for row in rows:
        if row not in selected:
            selected.append(row)
        if len(selected) >= limit:
            break
    return [str(item["code"]) for item in selected]


def build_cloud_stair_intelligence(
    candidates: list[dict],
    *,
    trade_date: str,
    as_of: str,
    csv_manager,
) -> dict:
    """抓取并固化一次云阶情报快照；外部情报失败时保留云阶结果。"""
    from utils.decision_ledger import get_recent_event_evidence
    from utils.event_risk import fetch_stock_news_events

    cutoff = datetime.fromisoformat(as_of)
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=TZ)
    cutoff = cutoff.astimezone(TZ)
    trade_date_cutoff = datetime.fromisoformat(
        f"{trade_date}T23:59:59+08:00"
    ).astimezone(TZ)
    cutoff = min(cutoff, trade_date_cutoff)
    start_date = (cutoff.date() - timedelta(days=30)).isoformat()
    cache_root = runtime_state_dir() / "event_cache"
    codes = {str(row.get("code") or "").zfill(6) for row in candidates}
    news = fetch_stock_news_events(
        candidates,
        start_date,
        cutoff.isoformat(timespec="seconds"),
        cache_root / "stock-news",
    )
    stored_events = get_recent_event_evidence(
        codes,
        start_at=f"{start_date}T00:00:00+08:00",
        end_at=cutoff.isoformat(timespec="seconds"),
    )
    events_by_code = {code: [] for code in codes}
    for event in [*stored_events, *(news.get("events") or [])]:
        code = str(event.get("code") or "")
        if code in events_by_code:
            events_by_code[code].append(event)

    rows = []
    for candidate in candidates:
        code = str(candidate.get("code") or "").zfill(6)
        events = _dedupe_events(events_by_code.get(code) or [])
        structure, structure_detail = _structure_score(candidate)
        sector_score = float((candidate.get("sector") or {}).get("score") or 50)
        adjustment, counts = _event_adjustment(events)
        priority = _clamp(structure * 0.7 + sector_score * 0.3 + adjustment)
        rows.append(
            {
                "code": code,
                "name": candidate.get("name"),
                "industry": candidate.get("industry"),
                "priority_score": round(priority, 1),
                "structure_score": structure,
                "structure_detail": structure_detail,
                "sector_score": round(sector_score, 1),
                "event_adjustment": adjustment,
                "event_counts": counts,
                "evidence_grade": _evidence_grade(structure, sector_score, counts),
                "events": events[:30],
                "news_available": bool(
                    (news.get("availability_by_code") or {}).get(code)
                ),
            }
        )
    rows.sort(
        key=lambda row: (-row["priority_score"], -row["structure_score"], row["code"])
    )
    for index, row in enumerate(rows, 1):
        row["priority_rank"] = index
        row["rank_label"] = (
            "第一推荐" if index == 1 else "第二推荐" if index == 2 else f"候选 {index}"
        )

    market = build_market_context(csv_manager)
    source_refs = ["event-evidence-ledger:recent", *(news.get("source_refs") or [])]
    content = {
        "methodology": METHODOLOGY,
        "trade_date": trade_date,
        "snapshot_id": getattr(csv_manager, "snapshot_id", None),
        "cutoff_at": cutoff.isoformat(timespec="seconds"),
        "market_context": market,
        "candidates": rows,
        "combination_codes": _diversified_codes(rows),
        "source_refs": source_refs,
    }
    content_hash = hashlib.sha256(
        json.dumps(content, ensure_ascii=False, sort_keys=True, default=str).encode(
            "utf-8"
        )
    ).hexdigest()
    covered = sum(bool(row.get("news_available")) for row in rows)
    return {
        "available": True,
        **content,
        "content_hash": f"sha256:{content_hash}",
        "coverage": {"covered": covered, "total": len(rows)},
        "errors": news.get("errors") or [],
        "ranking_note": (
            "云阶决定入围；结构占 70%、板块占 30%，事件只作小幅修正。"
            "当前为可追溯优先级，不代表收益保证。"
        ),
    }
