"""动量系 - 策略因子实现（源：用户飞书文档 Zxhy 2026-07-12）

包含 8 个因子：
16 神魔操盘(angel_devil) / 17 六脉神剑(six_veins) / 18 波段(wave_band) /
19 单针下30(needle_down30) / 20 底部暴力K(bottom_violent_k) /
21 趋势转强(trend_strengthen) / 23 云阶(cloud_stair) / 28 520(ma520)

每个因子的参数配置值与文档逐字一致；文档含糊处的实现假设写在各函数 docstring。
所有 compute 函数对 NaN / 短数据 / 零成交量兜底返回 None，绝不抛异常
（模块级 _safe 装饰器做最终兜底，函数体内先做自然的 NaN/长度防御）。
"""

import functools

import numpy as np

from strategy.factor_lib import (
    hit_payload,
    bbi_uptrend_ok,
    amplitude_pct,
    _last,
    REF,
    MA,
    EMA,
    LLV,
    HHV,
    CROSS,
    SMA_TDX,
)


def _safe(fn):
    """异常兜底装饰器：任何计算异常一律视为不命中（返回 None）.

    规格硬性要求"任何输入不得抛异常"——函数体内已做常规 NaN/长度防御，
    这里是最后一道保险，防御脏数据（如全 NaN 列、全零量）的极端组合。
    """

    @functools.wraps(fn)
    def wrap(ctx, params=None):
        try:
            return fn(ctx, params)
        except Exception:
            return None

    return wrap


# ============ 16. 神魔操盘（angel_devil） ============

ANGEL_DEVIL_PARAMS = {
    "ema_fast": 2,
    "ema_slow": 42,
    "slope_window": 21,
    "slope_multiplier": 20,
}


@_safe
def compute_angel_devil(ctx, params=None):
    """神魔操盘：天使线 EMA(C,2) 当日上穿魔鬼线 EMA(SLOPE(C,21)*20+C, 42).

    SLOPE 用 ctx.slope（近 N 日收盘对序号的滚动线性回归斜率）。
    CROSS 语义：今日 天使>魔鬼 且 昨日 天使<=魔鬼；NaN 参与比较一律 False。
    """
    p = {**ANGEL_DEVIL_PARAMS, **(params or {})}
    if len(ctx.df) < p["ema_slow"] + p["slope_window"]:
        return None
    angel = EMA(ctx.C, p["ema_fast"])
    devil_base = ctx.slope(p["slope_window"]) * p["slope_multiplier"] + ctx.C
    devil = EMA(devil_base, p["ema_slow"])
    if not bool(CROSS(angel, devil).iloc[-1]):
        return None
    a, d = _last(angel), _last(devil)
    return hit_payload(
        ctx,
        extra={
            "angel": round(a, 2) if a == a else None,
            "devil": round(d, 2) if d == d else None,
        },
    )


# ============ 17. 六脉神剑（six_veins） ============

SIX_VEINS_PARAMS = {
    "macd_fast": 8,
    "macd_slow": 13,
    "macd_signal": 5,
    # 以下为文档"-"（未给值）处采用的通达信六脉神剑常用默认（见 docstring 假设）
    "kdj_n": 9,
    "kdj_m1": 3,
    "kdj_m2": 3,
    "rsi_short": 6,
    "rsi_long": 12,
    "lwr_n": 10,
    "zlmm_short": 5,
    "zlmm_long": 10,
}


@_safe
def compute_six_veins(ctx, params=None):
    """六脉神剑：六项多头条件同日共振且首次出现（昨日未全满足）.

    六条：1) MACD(8,13,5) DIF>DEA  2) KDJ K>D  3) RSI6>RSI12（通达信SMA算法）
    4) LWR1>LWR2  5) close>BBI  6) ZLMM MMS>MMM。

    假设：文档除 MACD 参数外均为"-"，其余周期采用通达信六脉神剑常用默认
    （KDJ 9/3/3、RSI 6/12、LWR n=10、BBI 3/6/12/24、ZLMM 5/10）；
    LWR 的原始值在高低区间为零时以中性值 -50 填充（与 factor_lib KDJ 填 50 同理）。
    """
    p = {**SIX_VEINS_PARAMS, **(params or {})}
    if len(ctx.df) < 40:
        return None
    # 1) MACD 多头（自定义 8/13/5）
    dif, dea = ctx.macd(p["macd_fast"], p["macd_slow"], p["macd_signal"])
    c1 = dif > dea
    # 2) KDJ K>D
    k, d, _ = ctx.kdj(p["kdj_n"], p["kdj_m1"], p["kdj_m2"])
    c2 = k > d
    # 3) RSI 短>长
    c3 = ctx.rsi_tdx(p["rsi_short"]) > ctx.rsi_tdx(p["rsi_long"])
    # 4) LWR 多头：尊重市场=-(HHV(H,n)-C)/(HHV(H,n)-LLV(L,n))*100
    hhv, llv = HHV(ctx.H, p["lwr_n"]), LLV(ctx.L, p["lwr_n"])
    rng = (hhv - llv).replace(0, np.nan)
    zsc = (-(hhv - ctx.C) / rng * 100).fillna(-50)
    lwr1 = SMA_TDX(zsc, 3, 1)
    lwr2 = SMA_TDX(lwr1, 3, 1)
    c4 = lwr1 > lwr2
    # 5) close > BBI
    c5 = ctx.C > ctx.bbi()
    # 6) ZLMM：MTM 动量的双周期归一化强度
    mtm = ctx.C.diff()
    am = mtm.abs()
    mms = (
        100
        * EMA(EMA(mtm, p["zlmm_short"]), 3)
        / EMA(EMA(am, p["zlmm_short"]), 3).replace(0, np.nan)
    )
    mmm = (
        100
        * EMA(EMA(mtm, p["zlmm_long"]), 8)
        / EMA(EMA(am, p["zlmm_long"]), 8).replace(0, np.nan)
    )
    c6 = mms > mmm
    allc = c1 & c2 & c3 & c4 & c5 & c6
    # 首次共振：今日全真 且 昨日非全真
    if bool(allc.iloc[-1]) and not bool(allc.iloc[-2]):
        return hit_payload(
            ctx,
            extra={
                "dif": round(_last(dif), 3) if _last(dif) == _last(dif) else None,
            },
        )
    return None


# ============ 18. 波段（wave_band） ============

WAVE_BAND_PARAMS = {"N1": 7, "N2": 5, "N3": 3, "need_len": 50}


@_safe
def compute_wave_band(ctx, params=None):
    """波段：UP 指标拐头向上买点（UP[t]>UP[t-1] 且 UP[t-1]<UP[t-2]）.

    ABC1=(H+L+2C)/4; ABC2=EMA(ABC1,N1); ABC3=ABC1-ABC2;
    ABC5=ABC3/MA(ABS(ABC3),N2)*100; ABC6=EMA(ABC5,N3); UP=EMA(ABC6,10)+45。

    假设：ABC5 按通达信原公式 ABC3/MA(ABS(ABC3),N2)*100 口径实现
    （文档另一说法是滚动 std 标准化，两者对"拐头"判定等价，选原式）；
    need_len=50 仅作为最少数据长度门槛使用。
    """
    p = {**WAVE_BAND_PARAMS, **(params or {})}
    if len(ctx.df) < p["need_len"]:
        return None
    abc1 = (ctx.H + ctx.L + 2 * ctx.C) / 4
    abc2 = EMA(abc1, p["N1"])
    abc3 = abc1 - abc2
    abc5 = abc3 / MA(abc3.abs(), p["N2"]).replace(0, np.nan) * 100
    abc6 = EMA(abc5, p["N3"])
    up = EMA(abc6, 10) + 45
    u0, u1, u2 = float(up.iloc[-1]), float(up.iloc[-2]), float(up.iloc[-3])
    # NaN 参与比较自然为 False
    if u0 > u1 and u1 < u2:
        return hit_payload(ctx, extra={"up": round(u0, 2)})
    return None


# ============ 19. 单针下30（needle_down30） ============

NEEDLE_DOWN30_PARAMS = {
    "n_long": 21,
    "n_short": 3,
    "long_target": 85,
    "short_target": 30,
    "short_cross_lookback": 3,
    "long_stability_window": 5,
    "long_stability_min_ratio": 0.8,
    "require_bbi_uptrend": False,
}


@_safe
def compute_needle_down30(ctx, params=None):
    """单针下30：短期 RSV(3) 近3日下穿30且当日<=30，长期 RSV(21) 稳定高位.

    长线稳定性：最近5日至少80%的天数>=85 且 当日>=85。
    假设：require_bbi_uptrend=false 时跳过 BBI 检查（true 时用 factor_lib
    默认 bbi 参数 20/0.3/60，文档未单独给出 bbi 参数值）。
    """
    p = {**NEEDLE_DOWN30_PARAMS, **(params or {})}
    if len(ctx.df) < p["n_long"] + p["long_stability_window"]:
        return None
    rs = ctx.rsv(p["n_short"])
    rl = ctx.rsv(p["n_long"])
    st, lt = p["short_target"], p["long_target"]
    # 当日短线 <= 30
    if not (_last(rs) <= st):
        return None
    # 近3日内发生过"从30上方下穿到30以下"
    cross_down = (rs <= st) & (REF(rs, 1) > st)
    if not bool(cross_down.iloc[-p["short_cross_lookback"] :].any()):
        return None
    # 长线当日 >= 85 且 近5日 >=85 的天数占比 >= 0.8
    if not (_last(rl) >= lt):
        return None
    tail = rl.iloc[-p["long_stability_window"] :]
    ratio = float((tail >= lt).sum()) / p["long_stability_window"]
    if ratio < p["long_stability_min_ratio"]:
        return None
    if p["require_bbi_uptrend"] and not bbi_uptrend_ok(ctx):
        return None
    return hit_payload(
        ctx,
        extra={
            "rsv_short": round(_last(rs), 1),
            "rsv_long": round(_last(rl), 1),
        },
    )


# ============ 20. 底部暴力K（bottom_violent_k） ============

BOTTOM_VIOLENT_K_PARAMS = {
    "lookback_days": 60,
    "min_pct_change": 4,
    "kdj_j_threshold": 15,
    "consolidation_days": 5,
    "amplitude_threshold": 0.15,
    "volume_ratio_threshold": 2,
    "min_volume_shrink_ratio": 0.7,
    "max_consolidation_volatility": 0.03,
}


@_safe
def compute_bottom_violent_k(ctx, params=None):
    """底部暴力K：底部区域 + 倍量大阳线 + 前期横盘缩量 + 当日振幅约束.

    四段条件：
    1) 底部：昨日J<15 或 价格位置<0.25（(昨收-min)/(max-min)，回看60日收盘、排除当日）
    2) 暴力K：今量>=昨量*2 且 实体涨幅(C/O-1)>=4% 且 强于前期5日平均涨幅
    3) 前期横盘或缩量：前5日(不含今日)波动率 (high_max-low_min)/low_min<=0.03
       或 近3日均量(不含今日) < 再前5日均量*0.7
    4) 当日振幅 (high/low)-1 <= 0.15

    假设：价格位置阈值 0.25 为文档常量（未列入参数）；
    "强于前期5日平均涨幅"取 当日实体涨幅% > 前5个交易日收盘环比涨幅均值%；
    缩量口径的"前期均量"取近3日之前的 consolidation_days=5 日均量。
    """
    p = {**BOTTOM_VIOLENT_K_PARAMS, **(params or {})}
    lb = p["lookback_days"]
    if len(ctx.df) < lb + 2:
        return None
    # 4) 当日振幅
    amp = amplitude_pct(ctx)
    if not (amp == amp and amp <= p["amplitude_threshold"] * 100):
        return None
    # 1) 底部位置
    _, _, j = ctx.kdj()
    j_prev = float(j.iloc[-2])
    cond_j = j_prev == j_prev and j_prev < p["kdj_j_threshold"]
    win = ctx.C.iloc[-(lb + 1) : -1]
    cmin, cmax = float(win.min()), float(win.max())
    c_prev = float(ctx.C.iloc[-2])
    cond_pos = cmax > cmin and (c_prev - cmin) / (cmax - cmin) < 0.25
    if not (cond_j or cond_pos):
        return None
    # 2) 暴力K线
    v_today, v_prev = _last(ctx.V), float(ctx.V.iloc[-2])
    if not (v_today > 0 and v_today >= v_prev * p["volume_ratio_threshold"]):
        return None
    o, c = _last(ctx.O), _last(ctx.C)
    if not (o > 0):
        return None
    body = (c / o - 1) * 100
    if not (body >= p["min_pct_change"]):
        return None
    prior5 = ctx.pct_change().iloc[-6:-1]
    prior_mean = float(prior5.mean())
    if not (prior_mean == prior_mean and body > prior_mean):
        return None
    # 3) 前期横盘 或 缩量
    cd = p["consolidation_days"]
    h_pre = ctx.H.iloc[-(cd + 1) : -1]
    l_pre = ctx.L.iloc[-(cd + 1) : -1]
    lmin = float(l_pre.min())
    vola = (float(h_pre.max()) - lmin) / lmin if lmin > 0 else float("nan")
    cond_flat = vola == vola and vola <= p["max_consolidation_volatility"]
    v3 = float(ctx.V.iloc[-4:-1].mean())  # 近3日均量（不含今日）
    v_ref = float(ctx.V.iloc[-(cd + 4) : -4].mean())  # 再前5日均量
    cond_shrink = v_ref > 0 and v3 < v_ref * p["min_volume_shrink_ratio"]
    if not (cond_flat or cond_shrink):
        return None
    return hit_payload(
        ctx,
        extra={
            "body_pct": round(body, 2),
            "vol_ratio": round(v_today / v_prev, 2) if v_prev > 0 else None,
        },
    )


# ============ 21. 趋势转强（trend_strengthen） ============

TREND_STRENGTHEN_PARAMS = {
    "ema_fast": 13,
    "ema_signal": 8,
    "short_ma": 10,
    "medium_ma": 54,
    "ma_surge_filter": 15,
    "ma_pullback_filter": 10,
    "volume_surge_ratio": 1.2,
    "ma_surge_days_limit": 150,
    "daily_gain_threshold": 0.095,
    "candle_strength_threshold": 0.05,
}


@_safe
def compute_trend_strengthen(ctx, params=None):
    """趋势转强：主力潜伏金叉 + 涨停级大阳突破 + 放量 + 15日限频.

    当日同时满足：DIF=EMA(C,13)-EMA(EMA(C,13),8) 今日>0 且昨日<=0（金叉）、
    涨幅>=9.5%、实体 (C-O)/O>=5%、今量>=昨量*1.2、close>max(MA10,MA54)；
    且前 ma_surge_filter=15 日内无同型信号（限频）。

    假设：金叉按文档给的 DIF 样式口径实现（快线13>信号8）；
    "突破前期压力"取 close>max(MA10,MA54) 口径（文档给的两口径之一）；
    ma_pullback_filter=10 / ma_surge_days_limit=150 文档未给判定式，
    仅在参数表原样保留、不参与判定。
    """
    p = {**TREND_STRENGTHEN_PARAMS, **(params or {})}
    if len(ctx.df) < p["medium_ma"] + p["ma_surge_filter"] + 2:
        return None
    ema_f = EMA(ctx.C, p["ema_fast"])
    dif = ema_f - EMA(ema_f, p["ema_signal"])
    golden = (dif > 0) & (REF(dif, 1) <= 0)
    pct = ctx.C.pct_change()
    big = pct >= p["daily_gain_threshold"]
    yang = (ctx.C - ctx.O) / ctx.O.replace(0, np.nan) >= p["candle_strength_threshold"]
    vol_up = (ctx.V > 0) & (ctx.V >= REF(ctx.V, 1) * p["volume_surge_ratio"])
    brk = (ctx.C > ctx.ma(p["short_ma"])) & (ctx.C > ctx.ma(p["medium_ma"]))
    sig = golden & big & yang & vol_up & brk
    if not bool(sig.iloc[-1]):
        return None
    # 限频：前15日内不得已有同型信号
    if bool(sig.iloc[-(p["ma_surge_filter"] + 1) : -1].any()):
        return None
    return hit_payload(
        ctx,
        extra={
            "gain_pct": round(float(pct.iloc[-1]) * 100, 2),
        },
    )


# ============ 23. 云阶（cloud_stair） ============

CLOUD_STAIR_PARAMS = {
    "min_up_days": 1,
    "min_down_days": 1,
    "min_wave_gain_pct": 0.3,
    "consolidation_days": 5,
    "min_strong_up_days": 3,
    "breakout_buffer_pct": 0,
    "surge_lookback_days": 15,
    "min_breakout_up_days": 1,
    "breakout_lookback_days": 3,
    "min_consolidation_days": 3,
    "long_high_lookback_days": 60,
    "strong_up_pct_threshold": 4,
    "max_recent_close_range_pct": 0.25,
    "min_recent_close_range_pct": 0.03,
    "min_peak_to_long_high_ratio": 0.95,
    "max_recent_high_low_range_pct": 0.35,
    "min_recent_high_low_range_pct": 0.06,
    "max_consolidation_pullback_pct": 0.18,
    "require_trade_on_selection_date": True,
    "min_breakout_close_to_peak_ratio": 0.95,
    "max_recent_avg_volume_to_peak_ratio": 0.92,
    "max_recent_max_volume_to_peak_ratio": 1.1,
}


@_safe
def compute_cloud_stair(ctx, params=None):
    """云阶：第一波主升 + 缩量横盘 + 最近3日突破确认.

    结构（对候选峰日 p 逐一检验，峰日限定在近 surge_lookback_days=15 日内，
    候选至多约 11 个——规格允许的短窗口循环）：
    1) 主升：近15日窗口内阶段低点(最低 low)到峰日 high 涨幅>=30%，
       低点日~峰日内强上涨日(涨幅>=4%)>=3 天，峰 high>=60日最高 high*0.95
    2) 横盘：峰次日 ~ 选股日前一日，长度>=3 天；收盘极差∈[3%,25%]、
       高低极差∈[6%,35%]、相对峰的最大回撤<=18%、均量<=峰日量*0.92、
       最大量<=峰日量*1.1、至少1个上涨日和1个下跌日（有涨有跌）
    3) 突破：最近3日至少1个上涨日，今日收盘>=峰high*0.95*(1+buffer)
    4) require_trade_on_selection_date=true：今日成交量>0

    假设：横盘段取"峰次日至选股日前一日"，允许与突破观察窗（最近3日）
    重叠至多2日（文档未明确两段是否互斥）；强上涨日统计含阶段低点当日；
    consolidation_days=5 未给判定式、不参与硬判定（硬门槛用 min_consolidation_days=3）；
    突破价条件以 min_breakout_close_to_peak_ratio=0.95 为主、breakout_buffer_pct
    作乘性缓冲叠加。
    """
    p = {**CLOUD_STAIR_PARAMS, **(params or {})}
    n = len(ctx.df)
    if n < p["long_high_lookback_days"] + 5:
        return None
    C = ctx.C.to_numpy(dtype=float)
    H = ctx.H.to_numpy(dtype=float)
    L = ctx.L.to_numpy(dtype=float)
    V = ctx.V.to_numpy(dtype=float)
    if p["require_trade_on_selection_date"] and not (V[-1] > 0):
        return None
    pct = ctx.pct_change().to_numpy(dtype=float)  # 单位：%
    hh_long = np.nanmax(H[-p["long_high_lookback_days"] :])
    if not (hh_long == hh_long):
        return None
    w0 = max(0, n - p["surge_lookback_days"])
    # 峰日范围：近15日内，且峰后横盘段（峰+1 ~ n-2）长度 >= min_consolidation_days
    for peak in range(max(w0, 1), n - 1 - p["min_consolidation_days"]):
        peak_h, peak_v = H[peak], V[peak]
        if not (peak_h == peak_h and peak_v > 0):
            continue
        # 1) 峰接近长期高点
        if peak_h < p["min_peak_to_long_high_ratio"] * hh_long:
            continue
        # 1) 阶段低点 → 峰 涨幅
        lows = L[w0 : peak + 1]
        if not np.isfinite(lows).any():
            continue
        li = w0 + int(np.nanargmin(lows))
        stage_low = L[li]
        if not (stage_low > 0 and peak_h / stage_low - 1 >= p["min_wave_gain_pct"]):
            continue
        # 1) 强上涨日数量（含低点当日）
        seg = pct[li : peak + 1]
        if (
            int(np.nansum(seg >= p["strong_up_pct_threshold"]))
            < p["min_strong_up_days"]
        ):
            continue
        # 2) 横盘段（峰次日 ~ 今日前一日）
        s0, s1 = peak + 1, n - 1
        cs, hs, ls, vs = C[s0:s1], H[s0:s1], L[s0:s1], V[s0:s1]
        cmin, cmax = np.nanmin(cs), np.nanmax(cs)
        if not (cmin > 0):
            continue
        crng = cmax / cmin - 1
        if not (
            p["min_recent_close_range_pct"] <= crng <= p["max_recent_close_range_pct"]
        ):
            continue
        lmin = np.nanmin(ls)
        if not (lmin > 0):
            continue
        hlr = np.nanmax(hs) / lmin - 1
        if not (
            p["min_recent_high_low_range_pct"]
            <= hlr
            <= p["max_recent_high_low_range_pct"]
        ):
            continue
        if 1 - lmin / peak_h > p["max_consolidation_pullback_pct"]:
            continue
        if not (np.nanmean(vs) <= peak_v * p["max_recent_avg_volume_to_peak_ratio"]):
            continue
        if not (np.nanmax(vs) <= peak_v * p["max_recent_max_volume_to_peak_ratio"]):
            continue
        spct = pct[s0:s1]
        if (
            int(np.nansum(spct > 0)) < p["min_up_days"]
            or int(np.nansum(spct < 0)) < p["min_down_days"]
        ):
            continue
        # 3) 突破确认（最近3日）
        bwin = pct[n - p["breakout_lookback_days"] :]
        if int(np.nansum(bwin > 0)) < p["min_breakout_up_days"]:
            continue
        target = (
            peak_h
            * p["min_breakout_close_to_peak_ratio"]
            * (1 + p["breakout_buffer_pct"])
        )
        if not (C[-1] >= target):
            continue
        return hit_payload(
            ctx,
            extra={
                "peak_date": str(ctx.df["date"].iloc[peak]),
                "wave_gain_pct": round((peak_h / stage_low - 1) * 100, 1),
            },
        )
    return None


# ============ 28. 520（ma520） ============

MA520_PARAMS = {"ma_long": 20, "ma_short": 5}


@_safe
def compute_ma520(ctx, params=None):
    """520：昨日 MA5 金叉 MA20，今日阳线收盘突破昨高，且 MA20 上行.

    四条：1) CROSS(MA5,MA20) 发生在昨日  2) 今日 C>O
    3) 今日 C>REF(H,1)  4) 今日 MA20>昨日 MA20。
    """
    p = {**MA520_PARAMS, **(params or {})}
    if len(ctx.df) < p["ma_long"] + 3:
        return None
    ma_s = ctx.ma(p["ma_short"])
    ma_l = ctx.ma(p["ma_long"])
    if not bool(CROSS(ma_s, ma_l).iloc[-2]):
        return None
    c, o = _last(ctx.C), _last(ctx.O)
    h_prev = float(ctx.H.iloc[-2])
    if not (c > o and c > h_prev):
        return None
    ml_t, ml_p = float(ma_l.iloc[-1]), float(ma_l.iloc[-2])
    if not (ml_t == ml_t and ml_t > ml_p):
        return None
    return hit_payload(
        ctx,
        extra={
            "ma5": round(_last(ma_s), 2),
            "ma20": round(ml_t, 2),
        },
    )


# ============ 因子注册表 ============

FACTORS = {
    "angel_devil": {
        "name": "神魔操盘",
        "group": "动量系",
        "min_bars": 80,
        "params": ANGEL_DEVIL_PARAMS,
        "fn": compute_angel_devil,
    },
    "six_veins": {
        "name": "六脉神剑",
        "group": "动量系",
        "min_bars": 40,
        "params": SIX_VEINS_PARAMS,
        "fn": compute_six_veins,
    },
    "wave_band": {
        "name": "波段",
        "group": "动量系",
        "min_bars": 60,
        "params": WAVE_BAND_PARAMS,
        "fn": compute_wave_band,
    },
    "needle_down30": {
        "name": "单针下30",
        "group": "动量系",
        "min_bars": 30,
        "params": NEEDLE_DOWN30_PARAMS,
        "fn": compute_needle_down30,
    },
    "bottom_violent_k": {
        "name": "底部暴力K",
        "group": "动量系",
        "min_bars": 66,
        "params": BOTTOM_VIOLENT_K_PARAMS,
        "fn": compute_bottom_violent_k,
    },
    "trend_strengthen": {
        "name": "趋势转强",
        "group": "动量系",
        "min_bars": 90,
        "params": TREND_STRENGTHEN_PARAMS,
        "fn": compute_trend_strengthen,
    },
    "cloud_stair": {
        "name": "云阶",
        "group": "动量系",
        "min_bars": 70,
        "params": CLOUD_STAIR_PARAMS,
        "fn": compute_cloud_stair,
    },
    "ma520": {
        "name": "520",
        "group": "动量系",
        "min_bars": 25,
        "params": MA520_PARAMS,
        "fn": compute_ma520,
    },
}
