"""B1系 - 策略因子实现（源：用户飞书文档 Zxhy 2026-07-12）

包含 6 个因子：
1  超卖B1  oversold_b1      —— 少妇策略本体（价稳+BBI升+KDJ超卖+DIF>0）
2  KDJ金叉 kdj_cross        —— 双金叉（K上穿D 且 J上穿D）+ 当日J<55
3  TePu    tepu             —— 放量突破后 J 维持高位，当日 J 极低回落
13 SuperB1 super_b1_factor  —— 回看期少妇命中 + 盘整 + 当日有效回调
14 填坑    fill_pit          —— 峰-坑-峰形态，回踩前峰 + J 极低
15 补票    ticket_refill    —— 长RSV连续高位 + 短RSV首尾高位中途下探

每个因子的参数配置值与文档逐字一致；文档含糊处的实现假设写在各函数 docstring。
所有 compute 函数不抛异常：数据异常（NaN/短数据/零成交量）一律兜底返回 None。
"""

import numpy as np

from strategy.factor_lib import (
    FactorContext,
    hit_payload,
    _last,
    adaptive_trend_selector,
    adaptive_trend_selector_series,
    bbi_uptrend_ok,
    kdj_oversold_ok,
    macd_bull_ok,
    price_stable_ok,
    CROSS,
)


# ====================================================================
# 1. 超卖B1（oversold_b1）
# ====================================================================

OVERSOLD_B1_PARAMS = {
    "j_threshold": 15,
    "j_q_threshold": 0.1,
    "bbi_min_window": 20,
    "bbi_q_threshold": 0.3,
    "price_range_pct": 1,
    "trend_max_period": 60,
}


def compute_oversold_b1(ctx: FactorContext, params=None):
    """超卖B1：BBI上升趋势 + KDJ低位（超卖或低分位）+ MACD多头(DIF>0)
    + 近期收盘价波动受控。即少妇策略（AdaptiveTrendSelector）本体，
    直接复用 factor_lib.adaptive_trend_selector。
    """
    p = {**OVERSOLD_B1_PARAMS, **(params or {})}
    try:
        if adaptive_trend_selector(ctx, p):
            return hit_payload(ctx)
    except Exception:
        return None
    return None


# ====================================================================
# 2. KDJ金叉（kdj_cross）
# ====================================================================

KDJ_CROSS_PARAMS = {
    "j_threshold": 55,
    "bbi_min_window": 20,
    "bbi_q_threshold": 0.3,
    "price_range_pct": 1,
    "trend_max_period": 60,
}


def compute_kdj_cross(ctx: FactorContext, params=None):
    """KDJ金叉：BBI上升 + 价格稳定前提下，当日 K 与 D、J 与 D 同时金叉，
    MACD多头(DIF>0)，且当日 J < j_threshold。

    假设：双金叉按通达信 CROSS 口径——当日 K>D 且昨日 K<=D（J 同理），
    两个金叉必须同日发生。
    """
    p = {**KDJ_CROSS_PARAMS, **(params or {})}
    try:
        k, d, j = ctx.kdj()
        if len(k) < 2:
            return None
        # 双金叉：当日 K 上穿 D 且 J 上穿 D（NaN 参与比较自然为 False）
        if not (bool(CROSS(k, d).iloc[-1]) and bool(CROSS(j, d).iloc[-1])):
            return None
        if not (_last(j) < p["j_threshold"]):
            return None
        period = p["trend_max_period"]
        if not price_stable_ok(ctx, period, p["price_range_pct"]):
            return None
        if not bbi_uptrend_ok(ctx, p["bbi_min_window"], p["bbi_q_threshold"], period):
            return None
        if not macd_bull_ok(ctx):
            return None
        return hit_payload(
            ctx,
            extra={
                "K": round(_last(k), 2) if _last(k) == _last(k) else None,
                "D": round(_last(d), 2) if _last(d) == _last(d) else None,
            },
        )
    except Exception:
        return None


# ====================================================================
# 3. TePu（tepu）
# ====================================================================

TEPU_PARAMS = {
    "offset": 15,
    "j_threshold": 1,
    "up_threshold": 3,
    "j_q_threshold": 0.1,
    "price_range_pct": 1,
    "trend_max_period": 60,
    "volume_threshold": 0.6667,
}


def compute_tepu(ctx: FactorContext, params=None):
    """TePu：回溯窗口内找突破日 T（单日涨幅>=3%、相对放量、收盘创新高），
    突破后 J 维持高位；当日 DIF>0 且 J 低位/低分位，控制波动。

    假设：
    - 突破日搜索窗口 = 最近 offset 日（不含当日）；
    - "量能显著最大" = 突破日量 >= 该窗口最大量 * volume_threshold；
    - "收盘创窗口新高" = 突破日收盘 >= 窗口起点至突破日（含）的最高收盘；
    - "突破后 J 不塌陷" 按文档给定口径实现为：突破日次日至昨日 J 全部 >= 50
      （无中间交易日则视为通过）；当日 J 不参与该检查（当日要求超卖）。
    """
    p = {**TEPU_PARAMS, **(params or {})}
    try:
        period = p["trend_max_period"]
        off = int(p["offset"])
        n = len(ctx.C)
        if n < off + 2:
            return None
        if not macd_bull_ok(ctx):
            return None
        if not kdj_oversold_ok(ctx, p["j_threshold"], p["j_q_threshold"], period):
            return None
        if not price_stable_ok(ctx, period, p["price_range_pct"]):
            return None

        c = ctx.C.to_numpy(dtype=float)
        v = ctx.V.to_numpy(dtype=float)
        pct = ctx.pct_change().to_numpy(dtype=float)
        _, _, j = ctx.kdj()
        jv = j.to_numpy(dtype=float)

        start = n - 1 - off  # 窗口起点（含）
        win_v = v[start : n - 1]  # 不含当日
        with np.errstate(invalid="ignore"):
            win_vmax = np.nanmax(win_v) if win_v.size else np.nan
        if not (win_vmax == win_vmax and win_vmax > 0):
            return None  # 零成交量/全NaN 兜底

        for t in range(start, n - 1):  # 逐日循环仅 offset=15 天，代价可控
            g = pct[t]
            if not (g == g and g >= p["up_threshold"]):
                continue
            if not (v[t] == v[t] and v[t] >= win_vmax * p["volume_threshold"]):
                continue
            seg_c = c[start : t + 1]
            with np.errstate(invalid="ignore"):
                if not (c[t] == c[t] and c[t] >= np.nanmax(seg_c)):
                    continue
            seg_j = jv[t + 1 : n - 1]  # 突破日次日 ~ 昨日
            if seg_j.size and (np.isnan(seg_j).any() or seg_j.min() < 50):
                continue
            return hit_payload(
                ctx,
                extra={
                    "breakout_date": str(ctx.df["date"].iloc[t]),
                    "breakout_pct": round(float(g), 2),
                },
            )
        return None
    except Exception:
        return None


# ====================================================================
# 13. SuperB1（super_b1_factor）
# （与已上线的"超级B1"通达信7信号公式 strategy/super_b1.py 不是一回事，
#  独立实现，key 避免冲突）
# ====================================================================

SUPER_B1_FACTOR_PARAMS = {
    "B1_params": {
        "j_threshold": 10,
        "j_q_threshold": 0.1,
        "bbi_min_window": 20,
        "bbi_q_threshold": 0.3,
        "price_range_pct": 1,
        "trend_max_period": 60,
    },
    "lookback_n": 10,
    "j_threshold": 10,
    "close_vol_pct": 0.02,
    "j_q_threshold": 0.1,
    "price_drop_pct": 0.02,
}


def compute_super_b1_factor(ctx: FactorContext, params=None):
    """SuperB1：回溯 lookback_n 内至少一次满足少妇策略(B1_params)，
    之后 [t_m, 昨日] 收盘低波动盘整（max/min-1 <= close_vol_pct），
    当日相对昨日有效回调（(close_prev-close)/close_prev >= price_drop_pct），
    且当日 J 极低（<j_threshold）或处于低分位。

    假设：
    - t_m 取回看期内任一满足少妇策略的日子（存在满足盘整约束者即命中）；
    - 盘整窗口 = [t_m, 昨日]（含两端，不含当日），口径 max(close)/min(close)-1；
    - J 低分位窗口取 B1_params.trend_max_period=60。
    - 便宜条件（当日回调 + J超卖）先行判断，通过后才逐日重算少妇序列，
      控制单股耗时（factor_lib 的逐日截断实现 lookback<=10 时代价可控）。
    """
    p = {**SUPER_B1_FACTOR_PARAMS, **(params or {})}
    try:
        b1 = p["B1_params"]
        n = len(ctx.C)
        lb = int(p["lookback_n"])
        if n < lb + 2:
            return None
        c_today = _last(ctx.C)
        c_prev = float(ctx.C.iloc[-2])
        if not (c_prev > 0 and c_today == c_today):
            return None
        drop = (c_prev - c_today) / c_prev
        if not (drop >= p["price_drop_pct"]):
            return None
        if not kdj_oversold_ok(
            ctx, p["j_threshold"], p["j_q_threshold"], b1.get("trend_max_period", 60)
        ):
            return None
        # 回看期内每天是否满足少妇策略（列表最后一个元素 = 昨日）
        hits = adaptive_trend_selector_series(ctx, b1, lb)
        c = ctx.C.to_numpy(dtype=float)
        for i, ok in enumerate(hits):
            if not ok:
                continue
            t_m = n - lb - 1 + i  # hits[i] 的绝对下标
            seg = c[t_m : n - 1]  # [t_m, 昨日]
            lo = np.nanmin(seg)
            hi = np.nanmax(seg)
            if lo > 0 and hi / lo - 1 <= p["close_vol_pct"]:
                return hit_payload(
                    ctx,
                    extra={
                        "b1_date": str(ctx.df["date"].iloc[t_m]),
                        "drop_pct": round(drop * 100, 2),
                    },
                )
        return None
    except Exception:
        return None


# ====================================================================
# 14. 填坑（fill_pit）
# ====================================================================

FILL_PIT_PARAMS = {
    "j_threshold": 10,
    "gap_threshold": 0.2,
    "j_q_threshold": 0.1,
    "fluc_threshold": 0.03,
    "trend_max_period": 100,
}


def compute_fill_pit(ctx: FactorContext, params=None):
    """填坑：回看 trend_max_period 内的收盘价峰值结构——最新峰高于前峰、
    两峰之间其他峰不超过前峰、前峰 >= 区间最低收盘*(1+gap_threshold)（坑够深）；
    目标日收盘接近前峰（偏离<=fluc_threshold）且 J 极低或低分位。

    假设：
    - 峰 = 严格大于左右相邻收盘的局部极大值（scipy.signal.find_peaks 默认
      口径的手写实现，不引入 scipy）；
    - 最新峰取窗口内最后一个峰；前峰在其之前的所有峰中从近到远搜索，
      存在任一满足全部约束者即命中；
    - "偏离" = |close - 前峰收盘| / 前峰收盘；
    - "区间" = [前峰, 最新峰]（含两端）。
    """
    p = {**FILL_PIT_PARAMS, **(params or {})}
    try:
        period = int(p["trend_max_period"])
        n = len(ctx.C)
        if n < period:
            return None
        if not kdj_oversold_ok(ctx, p["j_threshold"], p["j_q_threshold"], period):
            return None
        c = ctx.C.iloc[-period:].to_numpy(dtype=float)
        if np.isnan(c).any():
            return None
        # 局部极大值（严格大于左右邻居），向量化检出
        interior = (c[1:-1] > c[:-2]) & (c[1:-1] > c[2:])
        peaks = np.where(interior)[0] + 1
        if len(peaks) < 2:
            return None
        p2 = int(peaks[-1])  # 最新峰
        close_today = c[-1]
        for p1 in peaks[:-1][::-1]:  # 前峰从近到远搜索（峰数量有限）
            p1 = int(p1)
            if not (c[p2] > c[p1]):  # 最新峰须高于前峰
                continue
            mids = peaks[(peaks > p1) & (peaks < p2)]
            if mids.size and (c[mids] > c[p1]).any():
                continue  # 区间内其他峰抬高了前峰 → 不合形态
            interval_min = c[p1 : p2 + 1].min()
            if not (
                interval_min > 0 and c[p1] >= interval_min * (1 + p["gap_threshold"])
            ):
                continue  # 坑不够深
            if abs(close_today - c[p1]) / c[p1] <= p["fluc_threshold"]:
                return hit_payload(
                    ctx,
                    extra={
                        "prev_peak": round(float(c[p1]), 2),
                        "last_peak": round(float(c[p2]), 2),
                    },
                )
        return None
    except Exception:
        return None


# ====================================================================
# 15. 补票（ticket_refill）
# ====================================================================

TICKET_REFILL_PARAMS = {
    "m": 3,
    "n_long": 21,
    "n_short": 3,
    "bbi_min_window": 2,
    "bbi_q_threshold": 0.2,
    "trend_max_period": 60,
}


def compute_ticket_refill(ctx: FactorContext, params=None):
    """补票：BBI确认上升（允许回撤，bbi_min_window=2/q=0.2），
    最近 m=3 日长期 RSV(21) 全部 >= 80，短期 RSV(3) 首尾高位
    （第1天与第m天 >= 80）且期间出现低位穿越（<20），MACD多头(DIF>0)。

    假设：
    - 高位阈值 80 / 低位阈值 20 取自文档概述文字（非参数表项）；
    - "期间出现低位穿越" = m 日窗口中首尾之间的日子 RSV(n_short) 最小值 < 20
      （m=3 时即中间那一天），故要求 m >= 3；
    - 任一 RSV 值为 NaN 一律判 False。
    """
    p = {**TICKET_REFILL_PARAMS, **(params or {})}
    try:
        m = int(p["m"])
        if m < 3 or len(ctx.C) < max(p["n_long"], 24) + m:
            return None
        if not macd_bull_ok(ctx):
            return None
        if not bbi_uptrend_ok(
            ctx, p["bbi_min_window"], p["bbi_q_threshold"], p["trend_max_period"]
        ):
            return None
        rsv_long = ctx.rsv(int(p["n_long"])).iloc[-m:].to_numpy(dtype=float)
        if len(rsv_long) < m or np.isnan(rsv_long).any():
            return None
        if (rsv_long < 80).any():
            return None  # 长线未能连续高位
        rsv_short = ctx.rsv(int(p["n_short"])).iloc[-m:].to_numpy(dtype=float)
        if np.isnan(rsv_short).any():
            return None
        if not (rsv_short[0] >= 80 and rsv_short[-1] >= 80):
            return None  # 短线首尾不高
        if not (rsv_short[1:-1].min() < 20):
            return None  # 期间未下探低位
        return hit_payload(
            ctx,
            extra={
                "RSV21": round(float(rsv_long[-1]), 2),
                "RSV3": round(float(rsv_short[-1]), 2),
            },
        )
    except Exception:
        return None


# ====================================================================
# 因子注册表
# ====================================================================

FACTORS = {
    "oversold_b1": {
        "name": "超卖B1",
        "group": "B1系",
        "min_bars": 90,
        "params": OVERSOLD_B1_PARAMS,
        "fn": compute_oversold_b1,
    },
    "kdj_cross": {
        "name": "KDJ金叉",
        "group": "B1系",
        "min_bars": 90,
        "params": KDJ_CROSS_PARAMS,
        "fn": compute_kdj_cross,
    },
    "tepu": {
        "name": "TePu",
        "group": "B1系",
        "min_bars": 80,
        "params": TEPU_PARAMS,
        "fn": compute_tepu,
    },
    "super_b1_factor": {
        "name": "SuperB1",
        "group": "B1系",
        "min_bars": 150,
        "params": SUPER_B1_FACTOR_PARAMS,
        "fn": compute_super_b1_factor,
    },
    "fill_pit": {
        "name": "填坑",
        "group": "B1系",
        "min_bars": 120,
        "params": FILL_PIT_PARAMS,
        "fn": compute_fill_pit,
    },
    "ticket_refill": {
        "name": "补票",
        "group": "B1系",
        "min_bars": 90,
        "params": TICKET_REFILL_PARAMS,
        "fn": compute_ticket_refill,
    },
}
