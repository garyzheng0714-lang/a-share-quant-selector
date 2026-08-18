"""把已封存的全市云阶研究摊成复盘页可读的汇总和分页名单。"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SHIPPED_DIR = PROJECT_ROOT / "shipped" / "cloud-stair-history"
SUMMARY_PATH = SHIPPED_DIR / "summary.json"
SIGNALS_PATH = SHIPPED_DIR / "signals.json"


def _require_shipped() -> None:
    if not SUMMARY_PATH.is_file() or not SIGNALS_PATH.is_file():
        raise FileNotFoundError("cloud_stair_history_not_finalized")


@lru_cache(maxsize=1)
def _loaded(
    summary_mtime: int, signals_mtime: int
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    del summary_mtime, signals_mtime
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    rows = json.loads(SIGNALS_PATH.read_text(encoding="utf-8"))
    if not isinstance(summary, dict) or not isinstance(rows, list):
        raise FileNotFoundError("cloud_stair_history_not_finalized")
    return summary, rows


def load_history() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    _require_shipped()
    return _loaded(
        int(SUMMARY_PATH.stat().st_mtime_ns),
        int(SIGNALS_PATH.stat().st_mtime_ns),
    )


def history_summary() -> dict[str, Any]:
    summary, _rows = load_history()
    payload = dict(summary)
    payload["available"] = True
    return payload


HORIZON_KEYS = ("t1", "t5", "t20")
RESULT_KEYS = ("all", "win", "loss", "unsettled")


def _horizon_key(horizon: str) -> str:
    key = str(horizon or "t1").strip().lower()
    return key if key in HORIZON_KEYS else "t1"


def _result_key(result: str) -> str:
    key = str(result or "all").strip().lower()
    return key if key in RESULT_KEYS else "all"


def row_outcome(row: dict[str, Any], horizon: str) -> str:
    key = _horizon_key(horizon)
    if not row.get(f"{key}_settled"):
        return "unsettled"
    try:
        value = float(row.get(f"{key}_net_return_pct"))
    except (TypeError, ValueError):
        return "unsettled"
    return "win" if value > 0 else "loss"


def history_signals(
    *,
    query: str = "",
    date: str = "",
    horizon: str = "t1",
    result: str = "all",
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    summary, rows = load_history()
    listing = rows
    wanted_date = str(date or "")[:10]
    if wanted_date:
        listing = [
            row for row in listing if str(row.get("signal_date") or "") == wanted_date
        ]
    needle = str(query or "").strip()
    if needle:
        lowered = needle.lower()
        listing = [
            row
            for row in listing
            if lowered in str(row.get("code") or "").lower()
            or lowered in str(row.get("name") or "").lower()
        ]
    horizon_key = _horizon_key(horizon)
    result_key = _result_key(result)
    if result_key != "all":
        listing = [
            row for row in listing if row_outcome(row, horizon_key) == result_key
        ]
    page = max(int(page or 1), 1)
    page_size = max(1, min(int(page_size or 50), 200))
    total = len(listing)
    start = (page - 1) * page_size
    return {
        "available": True,
        "cutoff": summary.get("cutoff"),
        "query": needle,
        "date": wanted_date,
        "horizon": horizon_key,
        "result": result_key,
        "page": page,
        "page_size": page_size,
        "total": total,
        "page_count": (total + page_size - 1) // page_size if total else 0,
        "rows": listing[start : start + page_size],
    }


def _horizon_stats(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    settled_rows = [row for row in rows if row.get(f"{key}_settled")]
    wins = 0
    for row in settled_rows:
        try:
            if float(row.get(f"{key}_net_return_pct")) > 0:
                wins += 1
        except (TypeError, ValueError):
            if key == "t1" and row.get("t1_win") is True:
                wins += 1
    count = len(settled_rows)
    return {
        "settled": count,
        "wins": wins,
        "win_rate": round(wins / count * 100, 1) if count else None,
    }


@lru_cache(maxsize=1)
def _history_index(summary_mtime: int, signals_mtime: int) -> dict[str, dict[str, Any]]:
    _summary, rows = _loaded(summary_mtime, signals_mtime)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        code = str(row.get("code") or "").strip().zfill(6)
        if not code or code == "000000":
            continue
        grouped.setdefault(code, []).append(row)

    out: dict[str, dict[str, Any]] = {}
    for code, items in grouped.items():
        items.sort(key=lambda item: str(item.get("signal_date") or ""))
        dates = [
            str(item.get("signal_date")) for item in items if item.get("signal_date")
        ]
        name = next(
            (str(item.get("name")) for item in reversed(items) if item.get("name")), ""
        )
        out[code] = {
            "code": code,
            "name": name,
            "appear_count": len(items),
            "first_date": dates[0] if dates else None,
            "last_date": dates[-1] if dates else None,
            "recent_dates": list(reversed(dates[-8:])),
            "t1": _horizon_stats(items, "t1"),
            "t5": _horizon_stats(items, "t5"),
            "t20": _horizon_stats(items, "t20"),
        }
    return out


def stock_history_summary(code: str) -> dict[str, Any] | None:
    if not code:
        return None
    try:
        path_key = (
            int(SUMMARY_PATH.stat().st_mtime_ns),
            int(SIGNALS_PATH.stat().st_mtime_ns),
        )
    except FileNotFoundError:
        return None
    return _history_index(*path_key).get(str(code).strip().zfill(6))
