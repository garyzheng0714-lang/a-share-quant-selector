"""行情新鲜度闸门：过期日线不得生成或展示为当前推荐。"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from utils.csv_manager import CSVManager

TZ = ZoneInfo("Asia/Shanghai")
ANCHOR_CODES = ("000001", "600030", "600036", "600519")
CALENDAR_CACHE = Path("data/trade_calendar.json")


def _trade_calendar() -> list[str]:
    if CALENDAR_CACHE.exists():
        try:
            dates = json.loads(CALENDAR_CACHE.read_text(encoding="utf-8"))
            if dates and dates[-1] >= str(datetime.now(TZ).year) + "-12-01":
                return dates
        except Exception:
            pass
    try:
        import akshare as ak
        frame = ak.tool_trade_date_hist_sina()
        dates = sorted(pd.to_datetime(frame["trade_date"]).dt.strftime("%Y-%m-%d").unique().tolist())
        CALENDAR_CACHE.write_text(json.dumps(dates, ensure_ascii=False), encoding="utf-8")
        return dates
    except Exception:
        return []


def expected_completed_trade_date(as_of: datetime | None = None) -> str:
    now = as_of or datetime.now(TZ)
    cutoff = now.date() if now.time() >= datetime.strptime("15:05", "%H:%M").time() else now.date() - timedelta(days=1)
    calendar = _trade_calendar()
    eligible = [date for date in calendar if date <= cutoff.isoformat()]
    if eligible:
        return eligible[-1]
    while cutoff.weekday() >= 5:
        cutoff -= timedelta(days=1)
    return cutoff.isoformat()


def next_trade_date(after_date: str) -> str:
    calendar = _trade_calendar()
    future = [date for date in calendar if date > after_date]
    if future:
        return future[0]
    cursor = datetime.fromisoformat(after_date).date() + timedelta(days=1)
    while cursor.weekday() >= 5:
        cursor += timedelta(days=1)
    return cursor.isoformat()


def local_data_status(csv_manager: CSVManager | None = None, as_of: datetime | None = None) -> dict:
    manager = csv_manager or CSVManager("data")
    anchor_dates = []
    for code in ANCHOR_CODES:
        frame = manager.read_stock(code, nrows=1)
        if not frame.empty:
            anchor_dates.append(str(frame.iloc[0]["date"])[:10])
    local_date = Counter(anchor_dates).most_common(1)[0][0] if anchor_dates else None
    expected = expected_completed_trade_date(as_of)
    return {
        "fresh": bool(local_date and local_date >= expected),
        "local_date": local_date,
        "expected_date": expected,
        "anchor_dates": dict(Counter(anchor_dates)),
    }
