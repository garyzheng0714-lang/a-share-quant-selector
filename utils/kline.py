"""K 线接口数据：日线（含 KDJ、知行白线/黄线）与周线（含 MA5/10/20/60）。"""

from __future__ import annotations

import math

import pandas as pd

from strategy.factor_lib import FactorContext


def _num(value, digits: int = 2):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else round(v, digits)


def build_kline(frame: pd.DataFrame, period: str) -> dict:
    """frame 为存储顺序（最新在前）；返回 {as_of, week_end, current_week_partial, data}."""
    df = frame.iloc[::-1].reset_index(drop=True)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    as_of = df["date"].max()
    if period == "weekly":
        weekly = (
            df.resample("W-FRI", on="date")
            .agg(
                open=("open", "first"),
                high=("high", "max"),
                low=("low", "min"),
                close=("close", "last"),
                volume=("volume", "sum"),
            )
            .dropna(subset=["open"])
        )
        close = weekly["close"].astype(float)
        extras = [close.rolling(n).mean() for n in (5, 10, 20, 60)]
        extras.append(
            close.ewm(span=10, adjust=False).mean().ewm(span=10, adjust=False).mean()
        )
        extras.append(sum(close.rolling(n).mean() for n in (14, 28, 57, 114)) / 4)
        week_end = weekly.index[-1] if not weekly.empty else None
        data = [
            [
                date.strftime("%Y-%m-%d"),
                _num(row["open"]),
                _num(row["close"]),
                _num(row["low"]),
                _num(row["high"]),
                int(row["volume"] or 0),
                *[_num(series.iloc[i]) for series in extras],
            ]
            for i, (date, row) in enumerate(weekly.iterrows())
        ]
        return {
            "as_of": as_of.strftime("%Y-%m-%d"),
            "week_end": week_end.strftime("%Y-%m-%d") if week_end is not None else None,
            "current_week_partial": bool(
                week_end is not None and as_of.normalize() < week_end.normalize()
            ),
            "data": data,
        }

    ctx = FactorContext(df)
    k, d, j = ctx.kdj()
    white, yellow = ctx.white_line(), ctx.yellow_line()
    data = [
        [
            row["date"].strftime("%Y-%m-%d"),
            _num(row["open"]),
            _num(row["close"]),
            _num(row["low"]),
            _num(row["high"]),
            int(row["volume"] or 0),
            _num(k.iloc[i]),
            _num(d.iloc[i]),
            _num(j.iloc[i]),
            _num(white.iloc[i]),
            _num(yellow.iloc[i]),
        ]
        for i, row in df.iterrows()
    ]
    return {
        "as_of": as_of.strftime("%Y-%m-%d"),
        "week_end": None,
        "current_week_partial": False,
        "data": data,
    }
