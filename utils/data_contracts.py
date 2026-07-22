"""市场数据获取契约。

生产调用者必须能区分「真实获取成功」与「获取失败」，不得用一个与
真实行情同构的 DataFrame 隐藏来源失败。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class FetchResult:
    """单只证券行情获取结果。"""

    success: bool
    source: str
    reason: str
    data: pd.DataFrame = field(default_factory=pd.DataFrame, repr=False)
    requested_start: str | None = None
    requested_end: str | None = None
    returned_latest_date: str | None = None
    rows: int = 0
    fetched_at: str = field(
        default_factory=lambda: datetime.now()
        .astimezone()
        .isoformat(timespec="seconds")
    )
    synthetic: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def ok(
        cls,
        data: pd.DataFrame,
        *,
        source: str,
        requested_start: str | None = None,
        requested_end: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> "FetchResult":
        frame = data.copy()
        latest = None
        if not frame.empty and "date" in frame:
            dates = pd.to_datetime(frame["date"], errors="coerce").dropna()
            if not dates.empty:
                latest = dates.max().strftime("%Y-%m-%d")
        return cls(
            success=True,
            source=source,
            reason="ok",
            data=frame,
            requested_start=requested_start,
            requested_end=requested_end,
            returned_latest_date=latest,
            rows=len(frame),
            synthetic=False,
            details=details or {},
        )

    @classmethod
    def failure(
        cls,
        *,
        source: str,
        reason: str,
        requested_start: str | None = None,
        requested_end: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> "FetchResult":
        return cls(
            success=False,
            source=source,
            reason=reason,
            requested_start=requested_start,
            requested_end=requested_end,
            synthetic=False,
            details=details or {},
        )


class MarketDataUnavailable(RuntimeError):
    """必需市场数据无法取得，调用链应 fail closed。"""
