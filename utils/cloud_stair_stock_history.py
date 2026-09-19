"""按股票汇总云阶进出次数与胜率，给云阶列表直接展示。"""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CANDIDATE_PATHS = (
    PROJECT_ROOT / "云阶报表" / "云阶-全部历史信号.csv",
    PROJECT_ROOT / "data" / "cloud_stair_history" / "signals.csv",
)

SETTLED_COL = {
    "t1": "T+1_能否结算",
    "t5": "T+5_能否结算",
    "t20": "T+20_能否结算",
}
WIN_COL = {
    "t1": "T+1_是否赚钱",
    "t5": "T+5_是否赚钱",
    "t20": "T+20_是否赚钱",
}


def history_source_path() -> Path | None:
    for path in CANDIDATE_PATHS:
        if path.is_file():
            return path
    return None


def _horizon_stats(rows: list[dict[str, str]], key: str) -> dict[str, Any]:
    settled = [row for row in rows if row.get(SETTLED_COL[key]) == "能"]
    wins = [row for row in settled if row.get(WIN_COL[key]) == "赚"]
    count = len(settled)
    return {
        "settled": count,
        "wins": len(wins),
        "win_rate": round(len(wins) / count * 100, 1) if count else None,
    }


@lru_cache(maxsize=1)
def _index(mtime_ns: int, path: str) -> dict[str, dict[str, Any]]:
    del mtime_ns
    grouped: dict[str, list[dict[str, str]]] = {}
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            code = (row.get("code") or "").strip().zfill(6)
            if not code or code == "000000":
                continue
            grouped.setdefault(code, []).append(row)

    out: dict[str, dict[str, Any]] = {}
    for code, rows in grouped.items():
        rows.sort(key=lambda item: item.get("signal_date") or "")
        dates = [item.get("signal_date") or "" for item in rows if item.get("signal_date")]
        name = next((item.get("name") for item in reversed(rows) if item.get("name")), "")
        out[code] = {
            "code": code,
            "name": name,
            "appear_count": len(rows),
            "first_date": dates[0] if dates else None,
            "last_date": dates[-1] if dates else None,
            "recent_dates": list(reversed(dates[-8:])),
            "t1": _horizon_stats(rows, "t1"),
            "t5": _horizon_stats(rows, "t5"),
            "t20": _horizon_stats(rows, "t20"),
        }
    return out


def load_history_index() -> dict[str, dict[str, Any]]:
    path = history_source_path()
    if path is None:
        return {}
    return _index(path.stat().st_mtime_ns, str(path))


def stock_history(code: str) -> dict[str, Any] | None:
    if not code:
        return None
    return load_history_index().get(code.strip().zfill(6))
