"""知行系 - 策略因子实现（源：用户飞书文档 Zxhy 2026-07-12）

包含 9 个因子：新B2 / 知行白线B1 / 知行黄线B1 / 知行砖图 / 双线 / 砖型+B1 /
金叉踩黄 / 娜娜图 / 知行趋势回踩砖。

每个因子的参数配置值与文档逐字一致；文档含糊处的实现假设写在各函数 docstring。
所有 compute 函数经 @_safe 兜底：任何输入（NaN/短数据/零成交量）不抛异常，返回 None。
"""
import functools

import numpy as np
import pandas as pd

from strategy.factor_lib import (
    FactorContext, hit_payload, adaptive_trend_selector, amplitude_pct,
    _last, CROSS, LLV, HHV,
)


def _safe(fn):
    """异常兜底装饰器：脏数据/短数据引发的任何异常一律吞掉返回 None。"""
    @functools.wraps(fn)
    def wrapper(ctx, params=None):
        try:
            return fn(ctx, params)
        except Exception:
            return None
    return wrapper


def _zx_lines(ctx, p, k1="M1", k2="M2", k3="M3", k4="M4"):
    """取知行白线（EMA(EMA(C,10),10)）与黄线（四均线，参数来自 p）。"""
    white = ctx.white_line()
    yellow = ctx.yellow_line(p[k1], p[k2], p[k3], p[k4])
    return white, yellow


# ====================================================================
# 4. 新B2（new_b2）
# ====================================================================

NEW_B2_PARAMS = {
    "kdj_n": 9, "kdj_m1": 3, "kdj_m2": 3,
    "brick_fast": 4, "brick_slow": 6,
    "long_window_1": 14, "long_window_2": 28,
    "long_window_3": 57, "long_window_4": 114,
    "b1_count_limit": 3, "b1_count_window": 5,
    "b2_pct_threshold": 3.7,
    "bottom_line_ratio": 0.95, "trend_guard_ratio": 0.9,
    "b2_prev_j_threshold": 39, "recent_listing_days": 120,
    "short_trend_window_1": 10, "short_trend_window_2": 10,
    "white_b1_j_threshold": 16,    # 文档标注"保留"，本因子不参与计算
    "golden_b1_j_threshold": 29,   # 文档标注"保留"，本因子不参与计算
}


def _new_b2_series(ctx, p):
    """新B2 启动条件的全序列布尔（向量化，供当日判定与砖型+B1排他复用）。

    返回 (base, env)：
    - base：涨幅唯一性（当日>3.7%、前两日均<=3.7%）+ 放量（V>昨V）
            + 前日J<39 + 实体强于上影 ((C-O)>(H-C))
    - env ：黄线趋势环境（close>=黄线*0.95 且 当日黄线>=昨日黄线*0.9）
    NaN 参与比较一律 False（pandas 天然语义）。
    """
    pct = ctx.C.pct_change() * 100
    _, _, j = ctx.kdj(p["kdj_n"], p["kdj_m1"], p["kdj_m2"])
    yellow = ctx.yellow_line(p["long_window_1"], p["long_window_2"],
                             p["long_window_3"], p["long_window_4"])
    thr = p["b2_pct_threshold"]
    base = (
        (pct > thr)
        & (pct.shift(1) <= thr)
        & (pct.shift(2) <= thr)
        & (ctx.V > ctx.V.shift(1))
        & (j.shift(1) < p["b2_prev_j_threshold"])
        & ((ctx.C - ctx.O) > (ctx.H - ctx.C))
    )
    env = (
        (ctx.C >= yellow * p["bottom_line_ratio"])
        & (yellow >= yellow.shift(1) * p["trend_guard_ratio"])
    )
    return base, env


@_safe
def compute_new_b2(ctx, params=None):
    """新B2：知行趋势环境下的 B2 启动日（涨幅>3.7% 唯一波段+放量+前日J低位）。

    假设：
    - "上市K线<120"以 len(df)（数据条数=上市以来K线数）判定；次新股仅跳过
      黄线环境检查，其余条件（涨幅/放量/J/实体）照常执行。
    - "前两日均未超过3.7%"= 昨日与前日涨幅均 <= b2_pct_threshold。
    """
    p = {**NEW_B2_PARAMS, **(params or {})}
    base, env = _new_b2_series(ctx, p)
    if not bool(base.iloc[-1]):
        return None
    sub_new = len(ctx.df) < p["recent_listing_days"]
    if not sub_new and not bool(env.iloc[-1]):
        return None
    _, _, j = ctx.kdj(p["kdj_n"], p["kdj_m1"], p["kdj_m2"])
    prev_j = float(j.iloc[-2])
    return hit_payload(ctx, extra={
        "is_sub_new": bool(sub_new),
        "prev_J": round(prev_j, 2) if prev_j == prev_j else None,
    })


# ====================================================================
# 5. 知行白线B1（zx_white_b1）
# ====================================================================

ZX_WHITE_B1_PARAMS = {
    "M1": 14, "M2": 28, "M3": 57, "M4": 114,
    "B1_params": {
        "j_threshold": 15, "j_q_threshold": 0.1,
        "bbi_min_window": 20, "bbi_q_threshold": 0.3,
        "price_range_pct": 1, "trend_max_period": 60,
    },
    "require_long_short": False,
    "price_deviation_pct": 0.05,
}


@_safe
def compute_zx_white_b1(ctx, params=None):
    """知行白线B1：少妇策略 + 收盘站上白线且贴近白线（偏离<=5%）+ 白线>黄线。

    require_long_short=False 时不要求收盘在黄线上方（文档默认值）。
    """
    p = {**ZX_WHITE_B1_PARAMS, **(params or {})}
    white, yellow = _zx_lines(ctx, p)
    c = _last(ctx.C)
    w = _last(white)
    y = _last(yellow)
    if not (c > w and w > y):          # NaN 比较自然 False
        return None
    if p["require_long_short"] and not (c > y):
        return None
    dev = abs(c - w) / w
    if not (dev <= p["price_deviation_pct"]):
        return None
    if not adaptive_trend_selector(ctx, p["B1_params"]):
        return None
    return hit_payload(ctx, extra={"white_dev_pct": round(dev * 100, 2)})


# ====================================================================
# 6. 知行黄线B1（zx_yellow_b1）
# ====================================================================

ZX_YELLOW_B1_PARAMS = {
    "M1": 14, "M2": 28, "M3": 57, "M4": 114,
    "B1_params": {
        "j_threshold": 15, "j_q_threshold": 0.1,
        "bbi_min_window": 20, "bbi_q_threshold": 0.3,
        "price_range_pct": 1, "trend_max_period": 60,
    },
    "price_deviation_pct": 0.05,
}


@_safe
def compute_zx_yellow_b1(ctx, params=None):
    """知行黄线B1：少妇策略 + 白线>黄线 + 收盘贴近黄线（偏离<=5%）。

    收盘允许在白线之下（与白线B1的区别）。
    """
    p = {**ZX_YELLOW_B1_PARAMS, **(params or {})}
    white, yellow = _zx_lines(ctx, p)
    c = _last(ctx.C)
    w = _last(white)
    y = _last(yellow)
    if not (w > y and y > 0):
        return None
    dev = abs(c - y) / y
    if not (dev <= p["price_deviation_pct"]):
        return None
    if not adaptive_trend_selector(ctx, p["B1_params"]):
        return None
    return hit_payload(ctx, extra={"yellow_dev_pct": round(dev * 100, 2)})


# ====================================================================
# 7. 知行砖图（zx_brick）
# ====================================================================

ZX_BRICK_PARAMS = {
    "M1": 14, "M2": 28, "M3": 57, "M4": 114,
    "brick_fast": 4, "brick_slow": 6,
    "brick_max_value": 100, "red_strength_ratio": 1,
}


@_safe
def compute_zx_brick(ctx, params=None):
    """知行砖图：砖型绿转红拐点 + 红柱强于昨日绿柱 + 白线>黄线 + close>黄线。

    口径（与规格通用积木一致）：
    - 绿转红拐点 = 砖值今日上升（diff>0）且昨日下降（diff<0）
    - 红柱强度 = 今日砖值变化量 >= 昨日绿柱变化量绝对值 * red_strength_ratio
    """
    p = {**ZX_BRICK_PARAMS, **(params or {})}
    white, yellow = _zx_lines(ctx, p)
    c = _last(ctx.C)
    if not (_last(white) > _last(yellow) and c > _last(yellow)):
        return None
    brick = ctx.brick(p["brick_fast"], p["brick_slow"])
    if len(brick) < 3:
        return None
    d1 = float(brick.iloc[-1] - brick.iloc[-2])
    d0 = float(brick.iloc[-2] - brick.iloc[-3])
    if not (d1 > 0 and d0 < 0):
        return None
    if not (abs(d1) >= abs(d0) * p["red_strength_ratio"]):
        return None
    bv = _last(brick)
    if not (bv <= p["brick_max_value"]):
        return None
    return hit_payload(ctx, extra={
        "brick": round(bv, 2), "red_strength": round(abs(d1), 2),
    })


# ====================================================================
# 8. 双线（double_line）
# ====================================================================

DOUBLE_LINE_PARAMS = {
    "M1": 14, "M2": 28, "M3": 57, "M4": 114,
    "top_volume_ratio": 0.7, "amplitude_threshold": 9,
    "volume_shrink_ratio": 0.8,
    "oscillation_max_days": 20, "oscillation_min_days": 5,
    "pct_change_threshold": 3, "huge_volume_threshold": 1.5,
    "oscillation_tolerance": 0.05, "max_after_volume_ratio": 0.7,
    "volume_surge_threshold": 1, "support_break_tolerance": 0.95,
    # ---- 以下为实现口径参数（文档未给数值，见 docstring 假设） ----
    "max_break_count": 2,      # 破黄线支撑/越白线上轨的次数上限（规格"<=2次口径"）
    "start_lookback": 10,      # 启动日搜索：震荡窗口首日前推天数
    "prev_vol_window": 20,     # 启动日"前期均量"窗口
    "calm_days": 3,            # 缩量/小阴小阳检查的近日数
}


@_safe
def compute_double_line(ctx, params=None):
    """双线：白黄线间震荡 + 放量启动→顶部无量→缩量→小阴小阳的量能模式。

    假设（文档未给出精确口径，按以下实现）：
    1. 震荡窗口：从 oscillation_max_days(20) 往下找最长 w>=5，使窗口内
       每天白线>黄线、low<黄线*0.95 的天数<=2、close>白线*1.05 的天数<=2。
    2. 启动日：窗口首日及其前 10 日内成交量最大的一天，要求
       启动量>=其前20日均量*volume_surge_threshold；>=均量*1.5 记为巨量启动。
    3. 顶部无量：震荡窗口内收盘最高日的量 <= 启动量*top_volume_ratio。
    4. 启动后不再放量：启动日之后所有日的量 <= 启动量*max_after_volume_ratio。
    5. 缩量：最近3日均量 <= 启动量*volume_shrink_ratio。
    6. 小阴小阳：最近3日 |涨跌幅| <= pct_change_threshold。
    """
    p = {**DOUBLE_LINE_PARAMS, **(params or {})}
    amp = amplitude_pct(ctx)
    if not (amp == amp and amp <= p["amplitude_threshold"]):
        return None
    white, yellow = _zx_lines(ctx, p)
    n = len(ctx.df)
    # 1. 震荡窗口（取最长满足的 w）
    w_found = None
    for w in range(p["oscillation_max_days"], p["oscillation_min_days"] - 1, -1):
        if n < w:
            continue
        wh = white.iloc[-w:]
        yl = yellow.iloc[-w:]
        if wh.isna().any() or yl.isna().any():
            continue
        if not bool((wh > yl).all()):
            continue
        breaks = int((ctx.L.iloc[-w:].to_numpy()
                      < yl.to_numpy() * p["support_break_tolerance"]).sum())
        overs = int((ctx.C.iloc[-w:].to_numpy()
                     > wh.to_numpy() * (1 + p["oscillation_tolerance"])).sum())
        if breaks <= p["max_break_count"] and overs <= p["max_break_count"]:
            w_found = w
            break
    if w_found is None:
        return None
    # 2. 启动日
    idx0 = n - w_found
    lo = max(0, idx0 - p["start_lookback"])
    seg = ctx.V.iloc[lo:idx0 + 1].to_numpy()
    if seg.size == 0:
        return None
    s = lo + int(np.argmax(seg))
    if s < p["prev_vol_window"]:
        return None
    v0 = float(ctx.V.iloc[s])
    prev_mean = float(ctx.V.iloc[s - p["prev_vol_window"]:s].mean())
    if not (v0 > 0 and prev_mean > 0):
        return None
    if v0 < prev_mean * p["volume_surge_threshold"]:
        return None
    huge = v0 >= prev_mean * p["huge_volume_threshold"]
    # 3. 顶部无量
    win_c = ctx.C.iloc[-w_found:].to_numpy()
    ti = n - w_found + int(np.argmax(win_c))
    if float(ctx.V.iloc[ti]) > v0 * p["top_volume_ratio"]:
        return None
    # 4. 启动后不再放量
    after = ctx.V.iloc[s + 1:].to_numpy()
    if after.size and float(after.max()) > v0 * p["max_after_volume_ratio"]:
        return None
    # 5. 缩量
    k = p["calm_days"]
    if float(ctx.V.iloc[-k:].mean()) > v0 * p["volume_shrink_ratio"]:
        return None
    # 6. 小阴小阳
    pct_tail = (ctx.C.pct_change() * 100).iloc[-k:]
    if pct_tail.isna().any() or not bool(
            (pct_tail.abs() <= p["pct_change_threshold"]).all()):
        return None
    return hit_payload(ctx, extra={
        "osc_days": int(w_found), "huge_start": bool(huge),
    })


# ====================================================================
# 9. 砖型+B1（brick_b1）
# ====================================================================

BRICK_B1_PARAMS = {**NEW_B2_PARAMS}   # 文档参数与新B2完全一致（逐字同值）


@_safe
def compute_brick_b1(ctx, params=None):
    """砖型+B1：知行多头环境 + 砖型绿转红 + J低位(<=29) + B2排他 + 近5日限频<=3。

    假设：
    - 限频窗口含当日：近 b1_count_window(5) 日信号次数（含今天）<= b1_count_limit(3)。
    - B2排他与限频用的历史信号序列统一按"非次新口径"（含黄线环境）向量化计算——
      本因子的多头环境本身要求黄线存在，次新股（黄线NaN）不会命中，故无偏差。
    """
    p = {**BRICK_B1_PARAMS, **(params or {})}
    white = ctx.white_line()
    yellow = ctx.yellow_line(p["long_window_1"], p["long_window_2"],
                             p["long_window_3"], p["long_window_4"])
    brick = ctx.brick(p["brick_fast"], p["brick_slow"])
    _, _, j = ctx.kdj(p["kdj_n"], p["kdj_m1"], p["kdj_m2"])
    d = brick.diff()
    turn = (d > 0) & (d.shift(1) < 0)
    env = (
        (white > yellow)
        & (ctx.C >= yellow * p["bottom_line_ratio"])
        & (yellow >= yellow.shift(1) * p["trend_guard_ratio"])
    )
    j_low = j <= p["golden_b1_j_threshold"]
    b2_base, b2_env = _new_b2_series(ctx, p)
    sig = env & turn & j_low & ~(b2_base & b2_env)
    if not bool(sig.iloc[-1]):
        return None
    cnt = int(sig.iloc[-p["b1_count_window"]:].sum())
    if cnt > p["b1_count_limit"]:
        return None
    return hit_payload(ctx, extra={
        "brick": round(_last(brick), 2), "count_in_window": cnt,
    })


# ====================================================================
# 10. 金叉踩黄（cross_step_yellow）
# ====================================================================

CROSS_STEP_YELLOW_PARAMS = {
    "M1": 14, "M2": 28, "M3": 57, "M4": 114,
    "B1_params": {
        "j_threshold": 15, "j_q_threshold": 0.1,
        "bbi_min_window": 20, "bbi_q_threshold": 0.3,
        "price_range_pct": 1, "trend_max_period": 60,
    },
    "lookback_days": 160,
    "touch_tolerance": 0.03,   # 回踩容忍度（规格注明 tol=0.03 口径）
}


@_safe
def compute_cross_step_yellow(ctx, params=None):
    """金叉踩黄：白线金叉黄线后，当日首次回踩黄线（low<=黄线*1.03 且 close>=黄线）+ 少妇策略。

    假设：
    - "首次回踩"= 金叉日之后（不含金叉当日）到昨日之间从未出现过回踩条件；
      金叉当日本身即使满足回踩条件也不算回踩日。
    - 金叉距今不超过 lookback_days(160) 个交易日。
    """
    p = {**CROSS_STEP_YELLOW_PARAMS, **(params or {})}
    white, yellow = _zx_lines(ctx, p)
    touch = (ctx.L <= yellow * (1 + p["touch_tolerance"])) & (ctx.C >= yellow)
    if not bool(touch.iloc[-1]):
        return None
    cross = CROSS(white, yellow)
    idxs = np.where(cross.to_numpy())[0]
    if idxs.size == 0:
        return None
    gi = int(idxs[-1])
    n = len(ctx.df)
    if gi >= n - 1:                       # 金叉当日不视为回踩日
        return None
    if n - 1 - gi > p["lookback_days"]:
        return None
    if bool(touch.iloc[gi + 1:n - 1].any()):   # 金叉后已回踩过 → 非首次
        return None
    if not adaptive_trend_selector(ctx, p["B1_params"]):
        return None
    return hit_payload(ctx, extra={"days_since_cross": int(n - 1 - gi)})


# ====================================================================
# 11. 娜娜图（nana_chart）
# ====================================================================

NANA_CHART_PARAMS = {
    "M1": 14, "M2": 28, "M3": 57, "M4": 114,
    "B1_params": {
        "j_threshold": 15, "j_q_threshold": 0.1,
        "bbi_min_window": 20, "bbi_q_threshold": 0.5,
        "price_range_pct": 1, "trend_max_period": 60,
    },
    "amplitude_threshold": 7, "volume_shrink_ratio": 0.3,
    "pct_change_threshold": 2, "volume_surge_threshold": 2,
    # ---- 实现口径参数（文档未给数值，见 docstring 假设） ----
    "pattern_window": 30,      # 量价模式回看天数（规格"近30日"）
    "prev_vol_window": 20,     # 启动日"前期均量"窗口
    "calm_days": 3,            # 地量/小阴小阳检查的近日数
    "min_days_after_surge": 3, # 启动日距当日的最少天数
}


@_safe
def compute_nana_chart(ctx, params=None):
    """娜娜图：少妇策略(bbi_q=0.5) + 白线>黄线 + 放量→缩到地量→小阴小阳 + 振幅<=7%。

    假设（量价模式口径）：
    - 启动日 = 近30日内成交量最大的一天，且距当日>=3天，
      启动量 >= 其前20日均量 * volume_surge_threshold(2)。
    - 顶部无量：因启动日取窗口内最大量日，"顶部日量<启动量"在该口径下自动成立，
      不再单独设阈值。
    - 缩量到地量：最近3日均量 <= 启动量 * volume_shrink_ratio(0.3)。
    - 小阴小阳：最近3日 |涨跌幅| <= pct_change_threshold(2)。
    """
    p = {**NANA_CHART_PARAMS, **(params or {})}
    amp = amplitude_pct(ctx)
    if not (amp == amp and amp <= p["amplitude_threshold"]):
        return None
    white, yellow = _zx_lines(ctx, p)
    if not (_last(white) > _last(yellow)):
        return None
    n = len(ctx.df)
    win = p["pattern_window"]
    if n < win:
        return None
    v_win = ctx.V.iloc[-win:].to_numpy()
    s = n - win + int(np.argmax(v_win))
    if s > n - 1 - p["min_days_after_surge"]:
        return None
    if s < p["prev_vol_window"]:
        return None
    v0 = float(ctx.V.iloc[s])
    prev_mean = float(ctx.V.iloc[s - p["prev_vol_window"]:s].mean())
    if not (v0 > 0 and prev_mean > 0):
        return None
    if v0 < prev_mean * p["volume_surge_threshold"]:
        return None
    k = p["calm_days"]
    if float(ctx.V.iloc[-k:].mean()) > v0 * p["volume_shrink_ratio"]:
        return None
    pct_tail = (ctx.C.pct_change() * 100).iloc[-k:]
    if pct_tail.isna().any() or not bool(
            (pct_tail.abs() <= p["pct_change_threshold"]).all()):
        return None
    if not adaptive_trend_selector(ctx, p["B1_params"]):
        return None
    return hit_payload(ctx, extra={
        "surge_ratio": round(v0 / prev_mean, 2),
        "days_after_surge": int(n - 1 - s),
    })


# ====================================================================
# 12. 知行趋势回踩砖（zx_pullback_brick）
# ====================================================================

ZX_PULLBACK_BRICK_PARAMS = {
    "M1": 14, "M2": 28, "M3": 57, "M4": 114,
    "brick_fast": 4, "brick_slow": 6,
    "rsi_period": 3, "short_window": 3,
}


@_safe
def compute_zx_pullback_brick(ctx, params=None):
    """知行趋势回踩砖：多头结构 + 绿砖回踩转升 + RSI3走强 + DIF>0 + 短期值不弱。

    口径：
    - 绿砖回踩 = 当日砖值上升（diff>0）且昨日砖值下降（diff<0），与规格
      "砖值处于下降后回升"同义。
    - 短期值 = 100*(C-LLV(L,3))/(HHV(C,3)-LLV(L,3))（分子低点用 low、
      分母高点用 close，照抄文档公式），要求今日>=昨日。
    """
    p = {**ZX_PULLBACK_BRICK_PARAMS, **(params or {})}
    white, yellow = _zx_lines(ctx, p)
    c = _last(ctx.C)
    if not (_last(white) > _last(yellow) and c > _last(yellow)):
        return None
    brick = ctx.brick(p["brick_fast"], p["brick_slow"])
    if len(brick) < 3:
        return None
    d1 = float(brick.iloc[-1] - brick.iloc[-2])
    d0 = float(brick.iloc[-2] - brick.iloc[-3])
    if not (d1 > 0 and d0 < 0):
        return None
    rsi = ctx.rsi_tdx(p["rsi_period"])
    r1, r0 = float(rsi.iloc[-1]), float(rsi.iloc[-2])
    if not (r1 == r1 and r0 == r0 and r1 > r0):
        return None
    dif, _ = ctx.macd()
    if not (_last(dif) > 0):
        return None
    sw = p["short_window"]
    llv = LLV(ctx.L, sw)
    rng = (HHV(ctx.C, sw) - llv).replace(0, np.nan)
    short_val = 100 * (ctx.C - llv) / rng
    s1, s0 = float(short_val.iloc[-1]), float(short_val.iloc[-2])
    if not (s1 == s1 and s0 == s0 and s1 >= s0):
        return None
    return hit_payload(ctx, extra={
        "brick": round(_last(brick), 2), "RSI3": round(r1, 2),
    })


# ====================================================================
# 因子注册表
# ====================================================================

FACTORS = {
    "new_b2": {
        "name": "新B2", "group": "知行系", "min_bars": 20,
        "params": NEW_B2_PARAMS, "fn": compute_new_b2,
    },
    "zx_white_b1": {
        "name": "知行白线B1", "group": "知行系", "min_bars": 134,
        "params": ZX_WHITE_B1_PARAMS, "fn": compute_zx_white_b1,
    },
    "zx_yellow_b1": {
        "name": "知行黄线B1", "group": "知行系", "min_bars": 134,
        "params": ZX_YELLOW_B1_PARAMS, "fn": compute_zx_yellow_b1,
    },
    "zx_brick": {
        "name": "知行砖图", "group": "知行系", "min_bars": 134,
        "params": ZX_BRICK_PARAMS, "fn": compute_zx_brick,
    },
    "double_line": {
        "name": "双线", "group": "知行系", "min_bars": 164,
        "params": DOUBLE_LINE_PARAMS, "fn": compute_double_line,
    },
    "brick_b1": {
        "name": "砖型+B1", "group": "知行系", "min_bars": 134,
        "params": BRICK_B1_PARAMS, "fn": compute_brick_b1,
    },
    "cross_step_yellow": {
        "name": "金叉踩黄", "group": "知行系", "min_bars": 134,
        "params": CROSS_STEP_YELLOW_PARAMS, "fn": compute_cross_step_yellow,
    },
    "nana_chart": {
        "name": "娜娜图", "group": "知行系", "min_bars": 164,
        "params": NANA_CHART_PARAMS, "fn": compute_nana_chart,
    },
    "zx_pullback_brick": {
        "name": "知行趋势回踩砖", "group": "知行系", "min_bars": 134,
        "params": ZX_PULLBACK_BRICK_PARAMS, "fn": compute_zx_pullback_brick,
    },
}
