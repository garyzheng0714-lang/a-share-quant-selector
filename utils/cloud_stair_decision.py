"""云阶当日决策读模型。

只聚合 worker 已经固化的云阶因子命中、行业归属和板块热度，
不在 Web 请求中扫描行情、不调用 LLM、不写数据。
"""

from __future__ import annotations

from utils.market_snapshot import read_snapshot_metadata
from utils.quant_pick import CORE_FACTOR, CORE_TRACK


def _industry_map(csv_manager) -> dict:
    value, _snapshot_id = read_snapshot_metadata(
        "stock_industry.json",
        csv_manager.base_data_dir,
        snapshot_id=csv_manager.snapshot_id,
    )
    return value if isinstance(value, dict) else {}


def _sector_heat(csv_manager) -> dict:
    from utils.sector_rotation import get_sector_rotation

    result = get_sector_rotation(csv_manager)
    if not result.get("available"):
        return {}
    return result.get("heat_map") or {}


def _sector_sort_key(row: dict) -> tuple[float, float, str]:
    sector = row.get("sector") or {}
    return (
        float(sector.get("score") if sector.get("score") is not None else -1),
        float(
            sector.get("relative_strength")
            if sector.get("relative_strength") is not None
            else -1
        ),
        str(row.get("code") or ""),
    )


def _sector_reading(sector: dict | None) -> str:
    if not sector:
        return "行业热度数据待补全"
    score = sector.get("score")
    rank = sector.get("rank")
    total = sector.get("total")
    stage = sector.get("stage")
    parts = []
    if score is not None:
        parts.append(f"热度 {float(score):.0f} 分")
    if rank is not None and total is not None:
        parts.append(f"全市场第 {rank}/{total} 名")
    if stage:
        parts.append(str(stage))
    return "·".join(parts) if parts else "行业热度数据待补全"


def _candidate_reason(row: dict) -> tuple[str, list[str]]:
    signal_parts = ["云阶三段结构完整", "当日收盘突破位已确认"]
    wave_gain = row.get("wave_gain_pct")
    if wave_gain is not None:
        signal_parts.append(f"第一波涨幅 {float(wave_gain):.1f}%")
    sector_text = _sector_reading(row.get("sector"))
    evidence = ["；".join(signal_parts), sector_text]
    return "；".join(evidence), evidence


def load_cloud_stair_decision(csv_manager) -> dict:
    """读取与当前快照绑定的云阶决策。"""
    from utils.factor_scan import read_cached_factor_hits
    from utils.market_filter import is_main_board, main_board_only

    if getattr(csv_manager, "snapshot_id", None) is None:
        return {"available": False, "reason": "snapshot_unavailable"}

    result = read_cached_factor_hits(csv_manager, [CORE_FACTOR])
    if not result.get("available"):
        return {
            "available": False,
            "reason": result.get("reason") or "factor_snapshot_not_ready",
            "trade_date": result.get("trade_date"),
        }

    hits = list((result.get("results") or {}).get(CORE_FACTOR, {}).get("hits") or [])
    if main_board_only():
        hits = [row for row in hits if is_main_board(str(row.get("code") or ""))]

    industries = _industry_map(csv_manager)
    heat_map = _sector_heat(csv_manager)
    candidates = []
    for hit in hits:
        code = str(hit.get("code") or "")
        industry = str(industries.get(code) or "").strip()
        row = {
            **hit,
            "industry": industry or "行业待补全",
            "industry_available": bool(industry),
            "sector": heat_map.get(industry) or None,
            # compute_cloud_stair 已完成最后一步突破确认。
            # 与 utils.quant_pick 既有发布口径一致：today_buy = 今天可买。
            "action": "buy",
            "action_label": "值得买入",
            "action_detail": "云阶买点已确认",
        }
        reason, evidence = _candidate_reason(row)
        row["reason"] = reason
        row["evidence"] = evidence
        candidates.append(row)

    candidates.sort(key=_sector_sort_key, reverse=True)
    total = len(candidates)
    for index, row in enumerate(candidates, 1):
        row["rank"] = index
        row["rank_total"] = total

    return {
        "available": True,
        "trade_date": result.get("trade_date"),
        "snapshot_id": csv_manager.snapshot_id,
        "signal_count": total,
        "has_signal": total > 0,
        "summary": (
            f"今日云阶选出 {total} 只，突破买点均已确认"
            if total
            else "今日云阶未选出股票"
        ),
        "core_factor": {
            "key": CORE_FACTOR,
            "name": "云阶",
            "plain": "第一波大涨 → 缩量横盘不破位 → 再次突破前高",
            "decision_rule": "只有完成突破确认才进入今日买入名单",
            "track": CORE_TRACK,
        },
        "candidates": candidates,
        "ranking_note": (
            "云阶决定是否入选；行业热度只决定多只候选的查看顺序，"
            "不会把已确认的云阶买点降级成“观察”。"
        ),
    }
