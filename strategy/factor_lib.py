"""策略因子共享积木库 - 第三期"策略因子工厂"的公共地基

28 个日线策略因子（源：用户飞书文档 Zxhy，参数已逐字抄录）大量共享同一批
指标与条件判断。本模块提供两层积木：

1. FactorContext：单只股票的指标缓存。扫描引擎为每只股票建一次，
   28 个策略共享同参指标（KDJ(9,3,3)/BBI/MACD(12,26,9)/白线/黄线等）只算一遍——
   这是"一次读CSV多策略共算"架构能跑得动的关键。
2. 条件积木函数：BBI趋势确认（允许回撤）、KDJ超卖（阈值或分位）、价格稳定性、
   少妇策略（AdaptiveTrendSelector）、三度系压力过滤等。

TDX 函数（REF/MA/EMA/LLV/HHV/CROSS/SMA_TDX 等）直接复用 strategy/super_b1.py
的实现——该实现已过公式保真 review，两处口径必须永远一致，故 import 不复制。

语义约定（与 super_b1.py 一致）：
- MA 严格窗口（不足 N 根 NaN）；NaN 参与比较一律 False
- SMA(X,N,M) = ewm(alpha=M/N, adjust=False)；EMA = ewm(span=N, adjust=False)
- 所有计算在正序（从早到晚）序列上进行
"""

import numpy as np
import pandas as pd

from strategy.super_b1 import (  # noqa: F401  (re-export 给 factors/ 用)
    REF,
    MA,
    EMA,
    LLV,
    HHV,
    COUNT,
    EVERY,
    EXIST,
    CROSS,
    BARSLAST,
    SMA_TDX,
)


def _last(s):
    """取序列最后一个值，NaN 安全（NaN → None 语义由调用方比较自然为 False）."""
    v = s.iloc[-1]
    return float(v) if v == v else float("nan")


class FactorContext:
    """单只股票的指标计算缓存.

    df 必须已清洗：正序、date/open/high/low/close/volume 齐全、数值为 float。
    同参指标只算一次；带参指标按参数元组缓存。
    """

    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.C = df["close"].astype(float)
        self.O = df["open"].astype(float)
        self.H = df["high"].astype(float)
        self.L = df["low"].astype(float)
        self.V = df["volume"].astype(float)
        self._cache = {}

    def _memo(self, key, fn):
        if key not in self._cache:
            self._cache[key] = fn()
        return self._cache[key]

    # ---- 指标积木 ----

    def kdj(self, n=9, m1=3, m2=3):
        """通达信 KDJ：返回 (K, D, J)."""

        def _calc():
            llv = LLV(self.L, n)
            hhv = HHV(self.H, n)
            rsv = (self.C - llv) / (hhv - llv).replace(0, np.nan) * 100
            k = SMA_TDX(rsv.fillna(50), m1, 1)
            d = SMA_TDX(k, m2, 1)
            j = 3 * k - 2 * d
            return k, d, j

        return self._memo(("kdj", n, m1, m2), _calc)

    def bbi(self):
        """BBI = (MA3+MA6+MA12+MA24)/4."""
        return self._memo(
            "bbi",
            lambda: (MA(self.C, 3) + MA(self.C, 6) + MA(self.C, 12) + MA(self.C, 24))
            / 4,
        )

    def macd(self, fast=12, slow=26, signal=9):
        """标准 MACD：返回 (DIF, DEA)."""

        def _calc():
            dif = EMA(self.C, fast) - EMA(self.C, slow)
            dea = EMA(dif, signal)
            return dif, dea

        return self._memo(("macd", fast, slow, signal), _calc)

    def white_line(self):
        """知行短期趋势线（白线）= EMA(EMA(C,10),10)."""
        return self._memo("white", lambda: EMA(EMA(self.C, 10), 10))

    def yellow_line(self, m1=14, m2=28, m3=57, m4=114):
        """知行多空线（黄线）= (MA14+MA28+MA57+MA114)/4，严格窗口."""
        return self._memo(
            ("yellow", m1, m2, m3, m4),
            lambda: (MA(self.C, m1) + MA(self.C, m2) + MA(self.C, m3) + MA(self.C, m4))
            / 4,
        )

    def rsv(self, n):
        """通达信 RSV(n) = (C-LLV(L,n))/(HHV(H,n)-LLV(L,n))*100."""

        def _calc():
            llv = LLV(self.L, n)
            rng = (HHV(self.H, n) - llv).replace(0, np.nan)
            return (self.C - llv) / rng * 100

        return self._memo(("rsv", n), _calc)

    def rsi_tdx(self, n):
        """通达信 RSI：SMA(MAX(C-LC,0),N,1)/SMA(ABS(C-LC),N,1)*100."""

        def _calc():
            lc = REF(self.C, 1)
            up = (self.C - lc).clip(lower=0)
            total = (self.C - lc).abs()
            return (
                SMA_TDX(up.fillna(0), n, 1)
                / SMA_TDX(total.fillna(0), n, 1).replace(0, np.nan)
                * 100
            )

        return self._memo(("rsi", n), _calc)

    def brick(self, fast=4, slow=6):
        """砖型指标值：SMA((C-LLV(L,fast))/(HHV(H,fast)-LLV(L,fast))*100, slow, 1).

        与 super_b1.py 内嵌的砖图口径同源。"转红"=砖值上升，"转绿"=砖值下降。
        """

        def _calc():
            llv = LLV(self.L, fast)
            rng = (HHV(self.H, fast) - llv).replace(0, np.nan)
            raw = (self.C - llv) / rng * 100
            return SMA_TDX(raw.fillna(50), slow, 1)

        return self._memo(("brick", fast, slow), _calc)

    def ma(self, n):
        """严格窗口均线（带缓存）."""
        return self._memo(("ma", n), lambda: MA(self.C, n))

    def slope(self, n):
        """近 n 日收盘价对序号的滚动线性回归斜率（神魔操盘用）.

        向量化实现：slope = (n*Σxy - Σx*Σy) / (n*Σx² - (Σx)²)，
        x 取 0..n-1 固定，故只需 y 与 xy 的滚动和。
        """

        def _calc():
            x = np.arange(n, dtype=float)
            sx = x.sum()
            sxx = (x * x).sum()
            denom = n * sxx - sx * sx
            sy = self.C.rolling(n, min_periods=n).sum()
            sxy = self.C.rolling(n, min_periods=n).apply(
                lambda w: float((w * x).sum()), raw=True
            )
            return (n * sxy - sx * sy) / denom

        return self._memo(("slope", n), _calc)

    def pct_change(self):
        """日涨跌幅（%）."""
        return self._memo("pct", lambda: self.C.pct_change() * 100)


# ---- 条件积木（返回 bool，NaN 语义一律 False） ----


def bbi_uptrend_ok(
    ctx: FactorContext, min_window=20, q_threshold=0.3, max_period=60
) -> bool:
    """BBI 趋势确认（允许回撤）.

    在尾部窗口 w ∈ [min_window, max_period] 中，若存在任一 w 使窗口内
    BBI 日环比下跌的天数占比 <= q_threshold，则认为上升趋势成立。
    """
    bbi = ctx.bbi()
    if len(bbi) < min_window or bbi.iloc[-1] != bbi.iloc[-1]:
        return False
    down = (bbi.diff() < 0).to_numpy()
    n = len(down)
    hi = min(max_period, n)
    for w in range(min_window, hi + 1):
        seg = down[n - w :]
        if seg.sum() / w <= q_threshold:
            return True
    return False


def kdj_oversold_ok(
    ctx: FactorContext, j_threshold=15, j_q_threshold=0.1, window=60
) -> bool:
    """KDJ 超卖：当日 J < 阈值 或 J <= 近 window 日 J 的低分位."""
    _, _, j = ctx.kdj()
    jl = _last(j)
    if jl != jl:
        return False
    if jl < j_threshold:
        return True
    tail = j.iloc[-window:].dropna()
    if tail.empty:
        return False
    return jl <= float(tail.quantile(j_q_threshold))


def macd_bull_ok(ctx: FactorContext) -> bool:
    """MACD 多头：最新 DIF > 0."""
    dif, _ = ctx.macd()
    return _last(dif) > 0


def price_stable_ok(ctx: FactorContext, period=60, range_pct=1.0) -> bool:
    """价格稳定性：近 period 日 (max(close)/min(close)-1) <= range_pct."""
    tail = ctx.C.iloc[-period:]
    lo = float(tail.min())
    if lo <= 0:
        return False
    return float(tail.max()) / lo - 1 <= range_pct


def adaptive_trend_selector(ctx: FactorContext, b1: dict) -> bool:
    """少妇策略（AdaptiveTrendSelector）= 超卖B1 四件套.

    价格稳定 + BBI趋势确认 + KDJ超卖 + MACD多头(DIF>0)。
    多个策略以 B1_params 嵌套复用（白线B1/黄线B1/金叉踩黄/娜娜图/SuperB1…）。
    """
    period = b1.get("trend_max_period", 60)
    return (
        price_stable_ok(ctx, period, b1.get("price_range_pct", 1.0))
        and bbi_uptrend_ok(
            ctx, b1.get("bbi_min_window", 20), b1.get("bbi_q_threshold", 0.3), period
        )
        and kdj_oversold_ok(
            ctx, b1.get("j_threshold", 15), b1.get("j_q_threshold", 0.1), period
        )
        and macd_bull_ok(ctx)
    )


def adaptive_trend_selector_series(ctx: FactorContext, b1: dict, lookback: int) -> list:
    """回看窗口内每一天是否满足少妇策略（SuperB1/金叉踩黄需要历史信号点）.

    返回最近 lookback 天（不含当日）每天的 bool，列表按时间正序、
    最后一个元素 = 昨日。用截断 ctx 逐日算代价高，这里做窗口化近似会引入
    偏差，故老老实实逐日截断——lookback 通常 <= 10，代价可控。
    """
    out = []
    n = len(ctx.df)
    for i in range(n - lookback - 1, n - 1):
        if i < 130:  # 黄线/BBI 等长窗口不足时必 False，提前跳过
            out.append(False)
            continue
        sub = FactorContext(ctx.df.iloc[: i + 1])
        out.append(adaptive_trend_selector(sub, b1))
    return out


# ---- 三度系共用：量时空安全（压力过滤，返回 True=安全/通过） ----


def top_pressure_safe(
    ctx: FactorContext, lookback=120, volume_ratio=2.0, price_dist=0.15
) -> bool:
    """顶部压力过滤：近 lookback 日的"放量顶部"若悬在当前价上方且距离
    不足 price_dist（如 15%），视为压力过近 → 不安全.

    放量顶部口径：当日成交量 >= 窗口均量*volume_ratio 的 K 线的最高价。
    """
    n = len(ctx.df)
    lb = min(lookback, n - 1)
    if lb < 20:
        return True
    h = ctx.H.iloc[-lb:]
    v = ctx.V.iloc[-lb:]
    close = _last(ctx.C)
    vmean = float(v.mean())
    if vmean <= 0 or close != close:
        return True
    tops = h[v >= vmean * volume_ratio]
    if tops.empty:
        return True
    # 取"悬在当前价上方的最近一个压力位"判距离——只看最高顶部会让
    # 近处的较低压力被远处更高的顶部掩盖（review 数值复现确认）
    above = tops[tops > close]
    if above.empty:  # 全部压力位已被突破，不构成压制
        return True
    return float(above.min()) / close - 1 >= price_dist


def gap_pressure_safe(ctx: FactorContext, lookback=120, volume_min_ratio=1.3) -> bool:
    """下跳缺口压力过滤：近 lookback 日存在放量下跳缺口（今日 high < 昨日 low
    且当日量 >= 窗口均量*ratio），且缺口上沿仍悬在当前价上方 → 不安全."""
    n = len(ctx.df)
    lb = min(lookback, n - 1)
    if lb < 20:
        return True
    h = ctx.H.iloc[-lb:]
    l_prev = ctx.L.shift(1).iloc[-lb:]
    v = ctx.V.iloc[-lb:]
    close = _last(ctx.C)
    vmean = float(v.mean())
    if vmean <= 0 or close != close:
        return True
    gap = (h < l_prev) & (v >= vmean * volume_min_ratio)
    if not bool(gap.any()):
        return True
    upper = float(l_prev[gap].max())  # 最高的缺口上沿
    return upper <= close  # 已收复则安全


def trend_pressure_safe(ctx: FactorContext, ma_period=60) -> bool:
    """趋势压力过滤：收盘价在 MA(ma_period) 之下视为趋势压制 → 不安全.

    假设：文档仅给出"趋势压力均线周期60/回看120"，未给判定式；
    按"当前收盘须站上趋势均线"实现。
    """
    ma_v = _last(ctx.ma(ma_period))
    close = _last(ctx.C)
    if ma_v != ma_v or close != close:
        return False
    return close >= ma_v


# ---- 通用小工具 ----


def amplitude_pct(ctx: FactorContext) -> float:
    """当日振幅（%）：(high/low - 1) * 100；low<=0 时返回 nan."""
    hi, lo = _last(ctx.H), _last(ctx.L)
    if lo <= 0 or hi != hi:
        return float("nan")
    return (hi / lo - 1) * 100


def body_pct(ctx: FactorContext) -> float:
    """当日实体涨幅（%）：(close/open - 1) * 100."""
    o, c = _last(ctx.O), _last(ctx.C)
    if o <= 0 or c != c:
        return float("nan")
    return (c / o - 1) * 100


def hit_payload(ctx: FactorContext, extra: dict = None) -> dict:
    """命中时的标准展示字段：close / pct_change / J / RSI6，可附加策略特有字段."""
    _, _, j = ctx.kdj()
    payload = {
        "close": round(_last(ctx.C), 2),
        "pct_change": round(_last(ctx.pct_change()), 2)
        if _last(ctx.pct_change()) == _last(ctx.pct_change())
        else None,
        "J": round(_last(j), 2) if _last(j) == _last(j) else None,
    }
    rsi = _last(ctx.rsi_tdx(6))
    payload["RSI"] = round(rsi, 2) if rsi == rsi else None
    if extra:
        payload.update(extra)
    return payload
