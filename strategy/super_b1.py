"""知行超级B1选股 - 通达信原版公式逐行 Python 翻译（独立模块）

来源：用户 2026-07-12 提供的通达信"知行超级B1选股公式"原文，逐行对照翻译，
不做任何"优化"或参数改动。与既有碗口反弹策略 / B1 相似度打分完全独立，互不引用。

与现系统的关系（口径备忘）：
- 趋势白线 = EMA(EMA(C,10),10) = 现系统的"知行短期趋势线"（同源）
- 大哥黄线 = (MA14+MA28+MA57+MA114)/4 = 现系统的"知行多空线"（同源）
- 但买点逻辑相反：碗口策略要求窗口内出现过 4 倍放量阳线（放量派）；
  本公式要求今日缩量（缩量回调派），二者产出的票池天然不同。

市值口径（FINANCE(40) 流通市值的取数优先级）：
1. 调用方传入的 market_cap 参数（扫描层从 data/stock_market_cap.json 取 circ_mv
   ——真流通市值，与通达信 FINANCE(40) 同口径；缺 circ_mv 时用 total_mv 近似）
2. 行情 CSV 的 market_cap 列最新值（总市值近似，部分票该列为 0）
3. 都取不到 → 市值缺失，该票不发信号（硬条件按原公式执行），
   扫描层会统计缺失数量并显式上报，不静默吞掉。

TDX 语义还原要点：
- MA 用严格窗口（不足 N 根返回 NaN）＝通达信口径；上市不足 114 天的票
  大哥黄线为 NaN，全部条件自然不成立 → 不发信号（与次新股闸门哲学一致）。
- LLV/HHV/COUNT/EXIST 允许不足窗口按已有数据算（通达信实际行为）。
- EVERY 严格要求满窗口。
- HHVBARS 平最高量时取最近一次出现（平局极罕见）。
- BARSLAST 条件从未成立时返回 NaN → 参与比较恒为 False（与 TDX 行为等效）。
- SMA(X,N,M) 为 TDX 递推口径：Y=(M*X+(N-M)*Y')/N，即 ewm(alpha=M/N)。

所有计算都在"正序（从早到晚）"序列上进行；入口自动识别倒序 CSV 并翻转。
"""
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


# ---- 公式主体 ----

DEFAULT_PARAMS = {
    "Z1": 2,        # 涨跌阈值（原注：默认2，可调1-5）
    "Z2": 0,        # 振幅调整（原注：默认0保持不变）
    "min_cap_yi": 50,  # 最小流通值（亿）——以总市值近似，见模块 docstring
}

# 各信号的人话名（前端展示用）
SIGNAL_LABELS = {
    "超卖缩量拐头B": "超卖拐头",
    "超卖缩量B": "超卖缩量",
    "原始B1": "原始B1",
    "超卖超缩量B": "超卖超缩量",
    "回踩白线B": "回踩白线",
    "回踩超级B": "回踩超级",
    "回踩黄线B": "回踩黄线",
}

# 评估最新一根K线所需的最少数据量：最深组合窗口是
# EVERY(趋势白线>大哥黄线, 20)，需要 MA114 有效满 20 根 = 114+19 = 133，留余量取 140
MIN_BARS = 140


def compute_super_b1(df: pd.DataFrame, code: str, params: dict = None,
                     market_cap: float = None, return_history: bool = False,
                     market_cap_by_date: dict[str, float] | None = None):
    """对单只股票计算最新一根K线的超级B1信号.

    Args:
        df: 日线数据（date/open/high/low/close/volume[/market_cap]），正序倒序均可
        code: 6位股票代码（板块前缀判断用）
        params: 覆盖 DEFAULT_PARAMS
        market_cap: 市值（元），调用方从市值缓存传入（优先级见模块 docstring）；
                    None 时回退 CSV 的 market_cap 列
        market_cap_by_date: 历史训练专用的时点市值映射。传入后，每个历史信号只使用
                            同交易日快照，不允许用当前市值回填过去。

    Returns:
        选中: {"signals": [...], ...}；未选中: None；
        市值缺失(两个来源都取不到): {"cap_missing": True}（供扫描层统计上报）
    """
    p = dict(DEFAULT_PARAMS)
    if params:
        p.update(params)

    if df is None or len(df) < MIN_BARS:
        return None

    d = df.copy()
    if len(d) > 1 and d["date"].iloc[0] > d["date"].iloc[-1]:
        d = d.iloc[::-1].reset_index(drop=True)

    C = d["close"].astype(float)
    O = d["open"].astype(float)
    H = d["high"].astype(float)
    L = d["low"].astype(float)
    V = d["volume"].astype(float)

    # {定义最小流通市值条件}（取数优先级见模块 docstring）
    uses_point_in_time_cap = bool(return_history and market_cap_by_date is not None)
    if uses_point_in_time_cap:
        market_cap = 0.0
        流通市值满足 = True
    else:
        if market_cap is None or market_cap <= 0:
            market_cap = float(d["market_cap"].iloc[-1]) if "market_cap" in d.columns else 0.0
        if market_cap <= 0 or market_cap != market_cap:
            return {"cap_missing": True}
        流通市值满足 = market_cap >= p["min_cap_yi"] * 1e8

    # {定义基础判定信息}
    趋势白线 = EMA(EMA(C, 10), 10)
    BBI = (MA(C, 3) + MA(C, 6) + MA(C, 12) + MA(C, 24)) / 4
    大哥黄线 = (MA(C, 14) + MA(C, 28) + MA(C, 57) + MA(C, 114)) / 4

    是双创北证 = str(code).startswith(("68", "30", "4", "8", "9"))
    有20cm历史 = bool(EXIST(C / REF(C, 1) > 1.15, 200).iloc[-1])
    振幅区间 = (8 if (是双创北证 or 有20cm历史) else 5) + p["Z2"]
    涨跌放宽系数 = 0.9 if (是双创北证 or 有20cm历史) else 1.0

    当日振幅 = (H - L) / L * 100
    当日涨跌幅 = (C - REF(C, 1)).abs() / REF(C, 1) * 100 * 涨跌放宽系数
    上涨十字星 = (C > REF(C, 1)) & ((C - O).abs() / O * 100 * 涨跌放宽系数 < 1.8)

    短期 = 100 * (C - LLV(L, 3)) / (HHV(C, 3) - LLV(L, 3))
    长期 = 100 * (C - LLV(L, 21)) / (HHV(C, 21) - LLV(L, 21))
    单针下20 = ((短期 <= 20) & (长期 >= 75)) | ((长期 - 短期) >= 70)
    聚宝盆 = (COUNT(长期 >= 75, 8) >= 6) & (COUNT(短期 <= 70, 7) >= 4) & (COUNT(短期 <= 50, 8) >= 1)
    双叉戟 = EVERY(长期 >= 75, 8) & (COUNT(短期 <= 50, 6) >= 2) & (COUNT(短期 <= 20, 7) >= 1)
    红肥绿瘦 = (COUNT(C >= O, 15) > 7) | (COUNT(C > REF(C, 1), 11) > 5)

    # 逐日计算40日最大量K线是否为大绿棒。这样同一份公式既能用于今日扫描，
    # 也能一次向量化产出历史B1样本，避免逐日重复滚动计算。
    vdays = HHVBARS_LAST(V, 40).fillna(0).astype(int)
    big_green_ok = []
    for i, vday in enumerate(vdays):
        i_v = max(0, i - int(vday))
        c_v, o_v = C.iloc[i_v], O.iloc[i_v]
        c_v_prev = C.iloc[i_v - 1] if i_v >= 1 else np.nan
        not_big_green = bool((not np.isnan(c_v_prev)) and c_v >= c_v_prev) or bool(c_v >= o_v)
        big_green_ok.append(not_big_green or ((vday >= 15) and not not_big_green))
    大绿棒条件 = pd.Series(big_green_ok, index=d.index)

    缩量 = (V < HHV(V, 20) * 0.416) | (V < HHV(V, 50) / 3)
    回踩缩量 = (V < HHV(V, 20) * 0.45) | (V < HHV(V, 50) / 3)
    适当缩量 = (V < HHV(V, 20) * 0.618) | (V < HHV(V, 50) / 3)
    超缩量 = (V < HHV(V, 30) / 4) | (V < HHV(V, 50) / 6)

    # {KDJ / 3日RSI}
    rsv = (C - LLV(L, 9)) / (HHV(H, 9) - LLV(L, 9)) * 100
    K = SMA_TDX(rsv, 3, 1)
    D = SMA_TDX(K, 3, 1)
    J = 3 * K - 2 * D
    lc = REF(C, 1)
    RSI = SMA_TDX((C - lc).clip(lower=0), 3, 1) / SMA_TDX((C - lc).abs(), 3, 1) * 100

    # {定义振幅}
    近期振幅 = (HHV(H, 20) - LLV(L, 20)) / LLV(L, 20) * 100
    近期异动 = 近期振幅 >= 15
    远期振幅 = (HHV(H, 50) - LLV(L, 50)) / LLV(L, 50) * 100
    远期异动 = 远期振幅 >= 30
    超级异动 = 近期振幅 >= 60
    洗盘异动 = (COUNT(单针下20, 10) >= 2) | 聚宝盆 | 双叉戟

    # {定义趋势股}
    做上涨趋势 = (趋势白线 >= 大哥黄线) & ((C >= 大哥黄线) | ((C > 大哥黄线 * 0.975) & (C > O)))
    强趋势股 = (
        EVERY(大哥黄线 >= REF(大哥黄线, 1) * 0.999, 13)
        & (趋势白线 >= REF(趋势白线, 1))
        & EVERY(趋势白线 > 大哥黄线, 20)
        & EVERY(趋势白线 >= REF(趋势白线, 1), 11)
        & 红肥绿瘦
    )
    超牛股 = (
        (EVERY(BBI >= REF(BBI, 1) * 0.999, 20) | (COUNT(BBI >= REF(BBI, 1), 25) >= 23))
        & ((近期振幅 >= 30) | (远期振幅 > 80))
        & (BARSLAST(CROSS(C, 大哥黄线)) > 12)
    )

    # {定义回踩白线 / 回踩黄线}
    距离白线 = (C - 趋势白线).abs() / C * 100
    L距离白线 = (L - 趋势白线).abs() / 趋势白线 * 100
    距离BBI = (C - BBI).abs() / C * 100
    L距离BBI = (L - BBI).abs() / BBI * 100
    回踩白线 = (
        ((C >= 趋势白线) & (距离白线 <= 2))
        | ((C < 趋势白线) & (距离白线 < 0.8))
        | ((C >= BBI) & (距离BBI < 2.5) & (L距离BBI < 1) & (距离白线 <= 3)
           & (当日涨跌幅 < 1) & (C > REF(C, 1)))
    )
    白线支撑 = (C >= 趋势白线) & (距离白线 < 1.5)
    强势回踩不破 = ((L距离白线 < 1) | (L距离BBI < 0.5)) & (C > 趋势白线) & (距离白线 <= 3.5)
    距离黄线 = (C - 大哥黄线).abs() / 大哥黄线 * 100
    回踩黄线 = (
        ((C >= 大哥黄线) & ((距离黄线 <= 1.5) | ((距离黄线 <= 2) & (当日涨跌幅 < 1))))
        | ((C < 大哥黄线) & (距离黄线 <= 0.8))
    )

    Z1 = p["Z1"]
    异动任一 = 近期异动 | 远期异动 | 洗盘异动

    # {判定买入提示}（大绿棒条件为最新一根的标量，直接并入）
    超卖缩量拐头B = (
        做上涨趋势 & ((RSI - 15) >= REF(RSI, 1))
        & ((REF(RSI, 1) < 20) | (REF(J, 1) < 14))
        & (当日振幅 < (振幅区间 + 0.5))
        & ((当日涨跌幅 < (2.3 + Z1)) | 上涨十字星)
        & 异动任一 & (C >= 大哥黄线)
    )
    超卖缩量B = (
        做上涨趋势 & ((J < 14) | (RSI < 23))
        & ((RSI + J < 55) | (J == LLV(J, 20)))
        & (当日振幅 < 振幅区间)
        & ((当日涨跌幅 < (2.5 + Z1)) | 上涨十字星)
        & (缩量 | (适当缩量 & (当日涨跌幅 < (1 + Z1))))
        & 异动任一
    )
    原始B1 = (
        (趋势白线 > 大哥黄线) & (C >= 大哥黄线 * 0.99)
        & (大哥黄线 >= REF(大哥黄线, 1))
        & ((J < 13) | (RSI < 21))
        & ((RSI + J) < LLV(RSI + J, 15) * 1.5)
        & 适当缩量
        & (((C - O).abs() * 100 / O < 1.5) | 超缩量
           | (适当缩量 & ((距离白线 < 1.8) | (距离BBI < 1.5) | (距离黄线 < 2.8))))
        & 异动任一
    )
    超卖超缩量B = (
        做上涨趋势 & ((J < 14) | (RSI < 23)) & (RSI + J < 60)
        & (远期振幅 >= 45)
        & ((当日振幅 < 振幅区间)
           | (超级异动 & (当日振幅 < 振幅区间 + 3.2) & (C > O) & (C > 趋势白线)))
        & (((C < O) & (V < REF(V, 1)) & (C >= 大哥黄线)) | (C >= O))
        & ((当日涨跌幅 < (2 + Z1)) | 上涨十字星)
        & 超缩量 & 异动任一
    )
    回踩白线B = (
        强趋势股 & ((J < 30) | (RSI < 40) | 洗盘异动) & (RSI + J < 70)
        & ((当日振幅 < 振幅区间 + 0.5) | (距离白线 < 1) | (距离BBI < 1))
        & 回踩白线
        & ((当日涨跌幅 < 2) | ((当日涨跌幅 < 5) & 白线支撑))
        & 回踩缩量 & 异动任一 & (L <= REF(C, 1))
    )
    回踩超级B = (
        超牛股 & ((J < 35) | (RSI < 45) | 洗盘异动) & (RSI + J < 80)
        & ((RSI + J) == LLV(RSI + J, 25))
        & (当日振幅 < 振幅区间 + 1)
        & ((当日涨跌幅 < (2.5 + Z1)) | (距离白线 < 2))
        & 强势回踩不破 & 异动任一 & 适当缩量
    )
    回踩黄线B = (
        (趋势白线 >= 大哥黄线) & (C >= 大哥黄线 * 0.975)
        & ((J < 13) | (RSI < 18)) & 回踩黄线
        & (缩量 | (适当缩量 & ((J == LLV(J, 20)) | (RSI == LLV(RSI, 14)))))
        & (大哥黄线 >= REF(大哥黄线, 1) * 0.997)
        & (MA(C, 60) >= REF(MA(C, 60), 1))
        & (近期振幅 >= 11.9) & (远期振幅 >= 19.5)
    )

    # 原文逐条核对：7 个 B 条件全部包含 (不是大绿棒 OR 大绿棒离得远)。
    all_signals = {
        "超卖缩量拐头B": 超卖缩量拐头B,
        "超卖缩量B": 超卖缩量B,
        "原始B1": 原始B1,
        "超卖超缩量B": 超卖超缩量B,
        "回踩白线B": 回踩白线B,
        "回踩超级B": 回踩超级B,
        "回踩黄线B": 回踩黄线B,
    }
    if return_history:
        rows = []
        if not 流通市值满足:
            return rows
        for i in range(MIN_BARS - 1, len(d)):
            fired_at = [
                name for name, series in all_signals.items()
                if bool(大绿棒条件.iloc[i]) and bool(series.iloc[i])
            ]
            if fired_at:
                signal_date = str(d["date"].iloc[i])[:10]
                cap_at_signal = (
                    float((market_cap_by_date or {}).get(signal_date, 0) or 0)
                    if uses_point_in_time_cap else float(market_cap)
                )
                if cap_at_signal < p["min_cap_yi"] * 1e8:
                    continue
                rows.append({
                    "signals": fired_at,
                    "signal_labels": [SIGNAL_LABELS.get(s, s) for s in fired_at],
                    "close": round(float(C.iloc[i]), 2),
                    "J": round(float(J.iloc[i]), 2),
                    "RSI": round(float(RSI.iloc[i]), 2),
                    "market_cap_yi": round(cap_at_signal / 1e8, 2),
                    "date": signal_date,
                })
        return rows

    fired = [name for name, series in all_signals.items()
             if bool(大绿棒条件.iloc[-1]) and bool(series.iloc[-1])]

    if not fired or not 流通市值满足:
        return None

    return {
        "signals": fired,
        "signal_labels": [SIGNAL_LABELS.get(s, s) for s in fired],
        "close": round(float(C.iloc[-1]), 2),
        "J": round(float(J.iloc[-1]), 2),
        "RSI": round(float(RSI.iloc[-1]), 2),
        "market_cap_yi": round(market_cap / 1e8, 2),
        "date": str(d["date"].iloc[-1])[:10],
    }
