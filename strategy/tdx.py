"""通达信基础函数（正序 pd.Series）。因子库共用，口径必须保持一致。"""

from __future__ import annotations

import numpy as np
import pandas as pd

# ---- TDX 基础函数（正序 pd.Series） ----


def REF(s: pd.Series, n: int) -> pd.Series:
    return s.shift(n)


def MA(s: pd.Series, n: int) -> pd.Series:
    """严格窗口均线：不足 N 根为 NaN（通达信口径）."""
    return s.rolling(n, min_periods=n).mean()


def EMA(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def LLV(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=1).min()


def HHV(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=1).max()


def COUNT(cond: pd.Series, n: int) -> pd.Series:
    return cond.astype(float).rolling(n, min_periods=1).sum()


def EVERY(cond: pd.Series, n: int) -> pd.Series:
    return cond.astype(float).rolling(n, min_periods=n).sum() >= n


def EXIST(cond: pd.Series, n: int) -> pd.Series:
    return cond.astype(float).rolling(n, min_periods=1).max() >= 1


def CROSS(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a > b) & (a.shift(1) <= b.shift(1))


def BARSLAST(cond: pd.Series) -> pd.Series:
    """上一次条件成立到当前的周期数；从未成立为 NaN（比较恒 False）."""
    idx = pd.Series(np.arange(len(cond)), index=cond.index, dtype=float)
    last_true = idx.where(cond.fillna(False)).ffill()
    return idx - last_true


def HHVBARS_LAST(s: pd.Series, n: int) -> pd.Series:
    """N 周期内最高值距今的周期数（0=今天）；平局取最近一次出现."""

    def _bars(w: np.ndarray) -> float:
        return len(w) - 1 - np.where(w == w.max())[0][-1]

    return s.rolling(n, min_periods=1).apply(_bars, raw=True)


def SMA_TDX(s: pd.Series, n: int, m: int) -> pd.Series:
    return s.ewm(alpha=m / n, adjust=False).mean()
