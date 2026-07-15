"""三度系 - 策略因子实现（源：用户飞书文档 Zxhy 2026-07-12）

包含 5 个因子：
- 22 三度A区（sandu_a_zone）
- 24 三度B区（sandu_b_zone）
- 25 三度洗盘（sandu_washout）
- 26 三度颈位（sandu_neckline）
- 27 三度星线（sandu_star）

每个因子的参数配置值与文档逐字一致；文档含糊处的实现假设写在各函数 docstring。

三度系共用的全局假设（适用于全部 5 个因子）：
- "放量>=X倍"分两种口径：
  1) 窗口级"存在放量/异动"（如"近60日存在放量1.5倍"）——基准取该日
     之前 20 日均量（MA(V,20) 前移一日），且基准量必须 >0；
  2) 单日确认级（反转/突破/黑太阳）——文档明确写了参照物（昨日量或
     洗盘日量）的按文档，未写的统一相对昨日量。
- 上影 = high - max(open, close)；下影 = min(open, close) - low；
  实体 = |close - open|。"上影/实体 <= x"在实体为 0 时视为 False
  （无实体无法确认攻击形态）；星线的"影线/实体 >= x"在实体为 0
  且有影线时视为 True（十字星）。
- 阳线 = close > open；阴线 = close < open；平盘两者都不算。
- 各"前期强势/能量/三阳控三阴"统计窗口一律含当日。
- 压力过滤直接复用 factor_lib 的 top_pressure_safe / gap_pressure_safe /
  trend_pressure_safe；trend_pressure_lookback 参数文档给出但积木未使用
  （factor_lib 按"收盘须站上趋势均线"实现），原样保留在 PARAMS 中。
"""
import numpy as np
import pandas as pd

from strategy.factor_lib import (
    FactorContext, hit_payload,
    top_pressure_safe, gap_pressure_safe, trend_pressure_safe,
    MA, LLV,
)


# ---------------------------------------------------------------- 公共小工具


def _f(s, i=-1):
    """iloc 取值转 float，越界/非数返回 NaN（比较自然 False）."""
    try:
        v = float(s.iloc[i])
    except (IndexError, TypeError, ValueError):
        return float("nan")
    return v


def _vol_base(ctx):
    """窗口级"放量"的基准量：该日之前 20 日均量（严格窗口，前移一日）."""
    return MA(ctx.V, 20).shift(1)


def _candle_parts(ctx):
    """返回 (上影, 下影, 实体) 三个绝对价差序列."""
    upper = ctx.H - np.maximum(ctx.C, ctx.O)
    lower = np.minimum(ctx.C, ctx.O) - ctx.L
    body = (ctx.C - ctx.O).abs()
    return upper, lower, body


def _upper_body_ok(ctx, i, max_ratio):
    """第 i 根（iloc 序号）K 线：上影/实体 <= max_ratio；实体为 0 → False."""
    o, h, c = _f(ctx.O, i), _f(ctx.H, i), _f(ctx.C, i)
    if not (o == o and h == h and c == c):
        return False
    body = abs(c - o)
    if body <= 0:
        return False
    return (h - max(c, o)) / body <= max_ratio


def _pressures_ok(ctx, p):
    """三度系量时空安全：顶部压力 + 下跳缺口压力 + 趋势压力，全过才 True."""
    return (
        top_pressure_safe(ctx, p["top_pressure_lookback"],
                          p["top_pressure_volume_ratio"],
                          p["top_pressure_price_dist"])
        and gap_pressure_safe(ctx, p["gap_pressure_lookback"],
                              p["gap_pressure_volume_min_ratio"])
        and trend_pressure_safe(ctx, p["trend_pressure_ma"])
    )


def _has_surge(ctx, lookback, ratio):
    """近 lookback 日（含当日）是否存在放量日：量 >= 前20日均量*ratio."""
    vb = _vol_base(ctx)
    cond = (vb > 0) & (ctx.V >= vb * ratio)
    return bool(cond.iloc[-lookback:].any())


def _yang_stats_ok(ctx, lookback, min_ratio, cluster_window=None,
                   cluster_min_ratio=None, vol_min_ratio=None):
    """三阳控三阴三件套（窗口含当日）：

    1) 近 lookback 日阳线占比 >= min_ratio；
    2) 近 cluster_window 日阳线聚集占比 >= cluster_min_ratio（可选）；
    3) 近 lookback 日阳线均量/阴线均量 >= vol_min_ratio（可选；
       窗口内无阴线视为通过，无阳线视为不通过）。
    """
    c = ctx.C.iloc[-lookback:]
    o = ctx.O.iloc[-lookback:]
    v = ctx.V.iloc[-lookback:]
    yang = c > o
    if float(yang.mean()) < min_ratio:
        return False
    if cluster_window is not None:
        if float(yang.iloc[-cluster_window:].mean()) < cluster_min_ratio:
            return False
    if vol_min_ratio is not None:
        vy = v[yang]
        vn = v[c < o]
        if vy.empty:
            return False
        if not vn.empty:
            vnm = float(vn.mean())
            if vnm > 0 and float(vy.mean()) / vnm < vol_min_ratio:
                return False
    return True


# ---------------------------------------------------------------- 22 三度A区


SANDU_A_ZONE_PARAMS = {
    "ma_combo_large": (10, 30, 60),
    "ma_combo_small": (5, 10, 20),
    "yidong_lookback": 20,
    "sanyang_lookback": 60,
    "trend_pressure_ma": 60,
    "ma_cluster_max_pct": 0.06,
    "ma_upturn_lookback": 5,
    "a_zone_breakout_pct": 1.8,
    "yidong_price_min_pct": 3,
    "gap_pressure_lookback": 60,
    "sanyang_vol_min_ratio": 1.15,
    "top_pressure_lookback": 120,
    "sanyang_cluster_window": 10,
    "sanyang_count_min_ratio": 0.55,
    "top_pressure_price_dist": 0.15,
    "trend_pressure_lookback": 120,
    "yidong_consecutive_days": 1,
    "sanyang_cluster_min_ratio": 0.6,
    "top_pressure_volume_ratio": 2,
    "yidong_volume_surge_ratio": 1.6,
    "gap_pressure_volume_min_ratio": 1.5,
    "yidong_max_upper_shadow_ratio": 0.35,
}


def compute_sandu_a_zone(ctx, params=None):
    """三度A区：量时空安全 + 三阳控三阴 + 量价异动 + 均线粘合翘头 + A区突破.

    假设：
    - 量价异动的"放量1.6倍"基准 = 该日之前20日均量（全局假设1）；
      "连续>=1日"用满足日的连续段长度 >= yidong_consecutive_days 判定，
      异动可发生在含当日的近20日内。
    - 均线粘合 = 当日 MA10/30/60 三线离散度 (max/min-1) <= 6%；
      "近5日翘头" = 三条均线当日值均高于各自 5 日前的值。
    - "MA5/10/20多头" = 当日 MA5 > MA10 > MA20（多头排列）。
    """
    p = {**SANDU_A_ZONE_PARAMS, **(params or {})}
    try:
        n = len(ctx.C)
        if n < 140:
            return None
        if not _pressures_ok(ctx, p):
            return None
        # 三阳控三阴
        if not _yang_stats_ok(ctx, p["sanyang_lookback"],
                              p["sanyang_count_min_ratio"],
                              p["sanyang_cluster_window"],
                              p["sanyang_cluster_min_ratio"],
                              p["sanyang_vol_min_ratio"]):
            return None
        # 量价异动：近20日存在连续 k 日的（涨幅>=3% & 放量1.6倍 & 上影受控）
        pct = ctx.pct_change()
        vb = _vol_base(ctx)
        upper, _, body = _candle_parts(ctx)
        shadow_ratio = upper / body.replace(0, np.nan)   # 实体0 → NaN → False
        cond = (
            (pct >= p["yidong_price_min_pct"])
            & (vb > 0) & (ctx.V >= vb * p["yidong_volume_surge_ratio"])
            & (shadow_ratio <= p["yidong_max_upper_shadow_ratio"])
        )
        k = int(p["yidong_consecutive_days"])
        runs = cond.astype(float).rolling(k, min_periods=k).sum() >= k
        if not bool(runs.iloc[-p["yidong_lookback"]:].any()):
            return None
        # 均线粘合归位 + 近5日翘头
        mas = [ctx.ma(m) for m in p["ma_combo_large"]]
        vals = [_f(s) for s in mas]
        if any(v != v or v <= 0 for v in vals):
            return None
        spread = max(vals) / min(vals) - 1
        if spread > p["ma_cluster_max_pct"]:
            return None
        ul = int(p["ma_upturn_lookback"])
        for s in mas:
            prev = _f(s, -1 - ul)
            if not (prev == prev and _f(s) > prev):
                return None
        # A区确认：当日涨幅>=1.8% 且 MA5/10/20 多头排列
        if not (_f(pct) >= p["a_zone_breakout_pct"]):
            return None
        small = [_f(ctx.ma(m)) for m in p["ma_combo_small"]]
        if any(v != v for v in small):
            return None
        if not (small[0] > small[1] > small[2]):
            return None
        return hit_payload(ctx, extra={"ma_spread_pct": round(spread * 100, 2)})
    except Exception:
        return None


# ---------------------------------------------------------------- 24 三度B区


SANDU_B_ZONE_PARAMS = {
    "ma_support_pct": 0.03,
    "ma_support_list": (10, 30, 60),
    "pullback_max_pct": 0.14,
    "reversal_pct_min": 2.2,
    "pullback_max_days": 20,
    "trend_pressure_ma": 60,
    "prior_surge_lookback": 60,
    "gap_pressure_lookback": 120,
    "prior_surge_price_min": 4,
    "prior_surge_yang_days": 2,
    "reversal_volume_ratio": 1.2,
    "top_pressure_lookback": 180,
    "top_pressure_price_dist": 0.12,
    "trend_pressure_lookback": 120,
    "prior_surge_volume_ratio": 1.5,
    "reversal_max_upper_shadow": 0.3,
    "top_pressure_volume_ratio": 1.8,
    "pullback_volume_shrink_ratio": 0.5,
    "gap_pressure_volume_min_ratio": 1.3,
}


def compute_sandu_b_zone(ctx, params=None):
    """三度B区：前期异动介入 → 健康缩量回调至均线支撑 → 反转确认.

    假设：
    - "异动段" = 单个异动日 d（当日涨幅>=4% 且 量>=前20日均量*1.5）及其
      前后各一日组成的 3 日窗；"异动区内阳线>=2天"= 该 3 日窗内阳线数 >=
      prior_surge_yang_days；异动段均量 = 该 3 日窗均量。取近60日
      （不含当日）内最后一个异动日。
    - 回调高点 = 异动日至昨日间收盘最高日；回调段 = 高点次日到昨日，
      至少 1 天；回调幅度按收盘价计算。
    - "距关键均线<=3%" = 当日最低价相对当日 MA、或昨日收盘相对昨日 MA，
      与 MA10/30/60 任一的偏离绝对值 <= 3%。
    """
    p = {**SANDU_B_ZONE_PARAMS, **(params or {})}
    try:
        n = len(ctx.C)
        if n < 200:
            return None
        if not _pressures_ok(ctx, p):
            return None
        pct = ctx.pct_change()
        vb = _vol_base(ctx)
        yang3 = (ctx.C > ctx.O).astype(float).rolling(
            3, min_periods=1, center=True).sum()
        surge = (
            (pct >= p["prior_surge_price_min"])
            & (vb > 0) & (ctx.V >= vb * p["prior_surge_volume_ratio"])
            & (yang3 >= p["prior_surge_yang_days"])
        )
        sa = surge.fillna(False).to_numpy()
        t = n - 1
        lo = max(1, t - int(p["prior_surge_lookback"]))
        cand = np.where(sa[lo:t])[0]
        if cand.size == 0:
            return None
        d = lo + int(cand[-1])                       # 最后一个异动日
        surge_vol = float(ctx.V.iloc[max(0, d - 1): d + 2].mean())
        if not surge_vol > 0:
            return None
        # 回调结构：异动后高点 → 缩量回调
        c_arr = ctx.C.to_numpy(dtype=float)
        h = d + int(np.argmax(c_arr[d:t]))           # 异动日..昨日 收盘最高
        if t - h > int(p["pullback_max_days"]):
            return None
        if h > t - 2:                                # 至少 1 天真实回调
            return None
        peak = c_arr[h]
        if not peak > 0:
            return None
        pull = c_arr[h + 1: t]
        if (peak - float(pull.min())) / peak > p["pullback_max_pct"]:
            return None
        pull_vol = float(ctx.V.iloc[h + 1: t].mean())
        if not pull_vol <= surge_vol * p["pullback_volume_shrink_ratio"]:
            return None
        # 关键均线支撑
        prev_close = _f(ctx.C, -2)
        today_low = _f(ctx.L, -1)
        support = False
        for m in p["ma_support_list"]:
            ma_s = ctx.ma(m)
            mv_t, mv_p = _f(ma_s, -1), _f(ma_s, -2)
            if mv_t == mv_t and mv_t > 0 and \
                    abs(today_low / mv_t - 1) <= p["ma_support_pct"]:
                support = True
                break
            if mv_p == mv_p and mv_p > 0 and \
                    abs(prev_close / mv_p - 1) <= p["ma_support_pct"]:
                support = True
                break
        if not support:
            return None
        # B区A点反转确认
        if not (_f(pct) >= p["reversal_pct_min"]):
            return None
        v_t, v_p = _f(ctx.V, -1), _f(ctx.V, -2)
        if not (v_p > 0 and v_t >= v_p * p["reversal_volume_ratio"]):
            return None
        if not _upper_body_ok(ctx, -1, p["reversal_max_upper_shadow"]):
            return None
        pullback_pct = (peak - float(pull.min())) / peak
        return hit_payload(ctx, extra={
            "pullback_pct": round(pullback_pct * 100, 2),
            "pullback_days": int(t - h),
        })
    except Exception:
        return None


# ---------------------------------------------------------------- 25 三度洗盘


SANDU_WASHOUT_PARAMS = {
    "pos_ma_list": (5, 10, 20, 30, 60),
    "prior_lookback": 60,
    "prior_yang_ratio": 0.55,
    "reversal_min_pct": 2.5,
    "wash_yin_max_pct": -0.5,
    "wash_yin_min_pct": -7,
    "pos_ma_nearby_pct": 0.05,
    "prior_surge_ratio": 1.5,
    "trend_pressure_ma": 60,
    "pos_prior_high_pct": 0.04,
    "wash_volume_shrink": 0.75,
    "black_sun_open_ratio": 1.02,
    "black_sun_close_ratio": 0.98,
    "gap_pressure_lookback": 120,
    "reversal_volume_ratio": 1.2,
    "top_pressure_lookback": 150,
    "wash_max_lower_shadow": 0.15,
    "wash_upper_shadow_min": 1,
    "black_sun_volume_ratio": 1.2,
    "pos_prior_high_lookback": 30,
    "top_pressure_price_dist": 0.12,
    "trend_pressure_lookback": 120,
    "reversal_max_upper_shadow": 0.3,
    "top_pressure_volume_ratio": 1.8,
    "gap_pressure_volume_min_ratio": 1.3,
}


def compute_sandu_washout(ctx, params=None):
    """三度洗盘：前期强势 + 昨日关键位洗盘K线（三选一）+ 今日强势反转.

    假设：
    - 中大阴线的"缩量<=前均量*0.75"：前均量 = 洗盘日（昨日）之前 5 日均量。
    - 长上影：昨日上影/实体 >= 1；实体为 0 且有上影时视为满足（十字长影）。
    - 黑太阳的"放量>=1.2倍" = 昨日量 >= 前日量*1.2。
    - "关键位置"按昨日判定：昨日收盘距 MA5/10/20/30/60（昨日值）任一
      偏离绝对值 <= 5%，或距近 30 日（截至昨日）最高价偏离绝对值 <= 4%。
    - 今日反转的放量基准 = 洗盘日（昨日）成交量（文档明确）。
    """
    p = {**SANDU_WASHOUT_PARAMS, **(params or {})}
    try:
        n = len(ctx.C)
        if n < 170:
            return None
        if not _pressures_ok(ctx, p):
            return None
        # 前期强势：近60日阳线占比 + 存在放量
        if not _yang_stats_ok(ctx, p["prior_lookback"], p["prior_yang_ratio"]):
            return None
        if not _has_surge(ctx, p["prior_lookback"], p["prior_surge_ratio"]):
            return None
        # 昨日洗盘K线（三选一）
        pct = ctx.pct_change()
        o_p, h_p, l_p, c_p = (_f(ctx.O, -2), _f(ctx.H, -2),
                              _f(ctx.L, -2), _f(ctx.C, -2))
        v_p, v_pp, c_pp = _f(ctx.V, -2), _f(ctx.V, -3), _f(ctx.C, -3)
        if not all(x == x for x in (o_p, h_p, l_p, c_p, v_p)):
            return None
        body_p = abs(c_p - o_p)
        upper_p = h_p - max(c_p, o_p)
        lower_p = min(c_p, o_p) - l_p
        pct_p = _f(pct, -2)
        wash_type = None
        # 1) 中大阴线：必须是阴线(close<open)、跌幅[-7,-0.5]、下影/实体<=0.15、缩量
        #    低开高走的阳线是承接形态不是洗盘——规格的"阴线"是形态要件
        if c_p < o_p and p["wash_yin_min_pct"] <= pct_p <= p["wash_yin_max_pct"]:
            vol_ma5 = _f(MA(ctx.V, 5).shift(1), -2)   # 昨日之前5日均量
            if (body_p > 0 and lower_p / body_p <= p["wash_max_lower_shadow"]
                    and vol_ma5 == vol_ma5 and vol_ma5 > 0
                    and v_p <= vol_ma5 * p["wash_volume_shrink"]):
                wash_type = "mid_yin"
        # 2) 长上影：上影/实体>=1（实体0且有上影 → 满足）
        if wash_type is None and upper_p > 0 and (
                body_p <= 0 or upper_p / body_p >= p["wash_upper_shadow_min"]):
            wash_type = "long_upper"
        # 3) 黑太阳：高开1.02、收盘<=开盘*0.98、放量1.2倍
        if wash_type is None and c_pp == c_pp and v_pp == v_pp:
            if (c_pp > 0 and o_p >= c_pp * p["black_sun_open_ratio"]
                    and c_p <= o_p * p["black_sun_close_ratio"]
                    and v_pp > 0 and v_p >= v_pp * p["black_sun_volume_ratio"]):
                wash_type = "black_sun"
        if wash_type is None:
            return None
        # 洗盘发生在关键位置（按昨日）
        near = False
        for m in p["pos_ma_list"]:
            mv = _f(ctx.ma(m), -2)
            if mv == mv and mv > 0 and \
                    abs(c_p / mv - 1) <= p["pos_ma_nearby_pct"]:
                near = True
                break
        if not near:
            lb = int(p["pos_prior_high_lookback"])
            hh = float(ctx.H.iloc[-(lb + 1):-1].max())   # 截至昨日的30日前高
            if hh > 0 and abs(c_p / hh - 1) <= p["pos_prior_high_pct"]:
                near = True
        if not near:
            return None
        # 今日强势反转
        if not (_f(pct) >= p["reversal_min_pct"]):
            return None
        v_t = _f(ctx.V, -1)
        if not (v_p > 0 and v_t >= v_p * p["reversal_volume_ratio"]):
            return None
        if not _upper_body_ok(ctx, -1, p["reversal_max_upper_shadow"]):
            return None
        return hit_payload(ctx, extra={"wash_type": wash_type})
    except Exception:
        return None


# ---------------------------------------------------------------- 26 三度颈位


SANDU_NECKLINE_PARAMS = {
    "surge_ratio": 1.4,
    "max_rally_pct": 0.5,
    "breach_pct_min": 2,
    "ma_cluster_max": 0.07,
    "yang_ratio_min": 0.55,
    "energy_lookback": 90,
    "breach_vol_ratio": 1.3,
    "min_consolidation": 12,
    "neckline_lookback": 120,
    "neckline_min_dist": 20,
    "trend_pressure_ma": 60,
    "max_single_leg_pct": 0.35,
    "neckline_tolerance": 0.03,
    "gap_pressure_lookback": 120,
    "top_pressure_lookback": 150,
    "breach_max_upper_shadow": 0.3,
    "top_pressure_price_dist": 0.12,
    "trend_pressure_lookback": 120,
    "neckline_pullback_min_pct": 0.03,
    "top_pressure_volume_ratio": 1.8,
    "gap_pressure_volume_min_ratio": 1.3,
}


def compute_sandu_neckline(ctx, params=None):
    """三度颈位：颈位结构 + 前期能量 + 充分整理 + 均线归位 + 放量突破.

    假设：
    - 颈位 = 近120日最高价日（平最高取最近一次）；"与低点/当前间隔>=20天"
      = 颈位日距当前 >= 20 天，且与窗口最低价日间隔 >= 20 天。
    - "颈位前后回撤>=3%" = 颈位日之前与之后的窗口内最低价均 <=
      颈位*(1-3%)（确认为显著局部高点）；颈位为窗口首根时不成立。
    - 均线归位的均线组文档未给，沿用三度A区大均线组 MA10/30/60，
      当日离散度 (max/min-1) <= 7%。
    - 突破放量基准 = 昨日量（*1.3）。
    - "整体涨幅<=50%" = 当日收盘 / 近120日最低收盘 - 1 <= 50%；
      "单段涨幅<=35%" = 近120日内任一日的 close/LLV(close,20)-1
      最大值 <= 35%（以20日滚动低点近似"一段拉升"）。
    """
    p = {**SANDU_NECKLINE_PARAMS, **(params or {})}
    try:
        n = len(ctx.C)
        if n < 170:
            return None
        if not _pressures_ok(ctx, p):
            return None
        t = n - 1
        lb = int(p["neckline_lookback"])
        # 颈位窗口截至昨日（不含当日）：若含当日，突破日自身的新高会成为
        # 新"颈位"，close>neck 的真突破在数学上永不可达——突破越真越必被拒
        # （review 数值复现确认的高危缺陷，2026-07-13 修复）
        h_arr = ctx.H.to_numpy(dtype=float)[-(lb + 1):-1]
        l_arr = ctx.L.to_numpy(dtype=float)[-(lb + 1):-1]
        if np.isnan(h_arr).any() or np.isnan(l_arr).any():
            return None
        neck = float(h_arr.max())
        p_rel = int(np.where(h_arr == neck)[0][-1])      # 平局取最近
        p_abs = (t - len(h_arr)) + p_rel
        if t - p_abs < int(p["neckline_min_dist"]):
            return None
        b_rel = int(np.where(l_arr == l_arr.min())[0][-1])
        if abs(p_rel - b_rel) < int(p["neckline_min_dist"]):
            return None
        # 颈位前后回撤 >= 3%
        pull_line = neck * (1 - p["neckline_pullback_min_pct"])
        if p_rel == 0:
            return None
        if not (float(l_arr[:p_rel].min()) <= pull_line):
            return None
        if not (float(l_arr[p_rel + 1:].min()) <= pull_line):
            return None
        # 充分整理：颈位后 >= 12 天（min_dist=20 已覆盖，仍显式检查）
        if t - p_abs < int(p["min_consolidation"]):
            return None
        # 前期强势能量：近90日放量1.4倍 + 阳线占比>=0.55
        if not _has_surge(ctx, p["energy_lookback"], p["surge_ratio"]):
            return None
        if not _yang_stats_ok(ctx, p["energy_lookback"], p["yang_ratio_min"]):
            return None
        # 均线归位：MA10/30/60 离散 <= 7%
        vals = [_f(ctx.ma(m)) for m in (10, 30, 60)]
        if any(v != v or v <= 0 for v in vals):
            return None
        if max(vals) / min(vals) - 1 > p["ma_cluster_max"]:
            return None
        # 放量突破颈位
        pct = ctx.pct_change()
        if not (_f(pct) >= p["breach_pct_min"]):
            return None
        v_t, v_p = _f(ctx.V, -1), _f(ctx.V, -2)
        if not (v_p > 0 and v_t >= v_p * p["breach_vol_ratio"]):
            return None
        close = _f(ctx.C)
        if not (close > neck * (1 - p["neckline_tolerance"])):
            return None
        if not _upper_body_ok(ctx, -1, p["breach_max_upper_shadow"]):
            return None
        # 涨幅约束：整体 <= 50%，单段 <= 35%
        c_min = float(ctx.C.iloc[-lb:].min())
        if not (c_min > 0 and close / c_min - 1 <= p["max_rally_pct"]):
            return None
        leg = ctx.C / LLV(ctx.C, 20) - 1
        if not (float(leg.iloc[-lb:].max()) <= p["max_single_leg_pct"]):
            return None
        return hit_payload(ctx, extra={
            "neckline": round(neck, 2),
            "days_since_neck": int(t - p_abs),
        })
    except Exception:
        return None


# ---------------------------------------------------------------- 27 三度星线


SANDU_STAR_PARAMS = {
    "pos_ma_list": (5, 10, 20, 30, 60),
    "max_rally_pct": 0.6,
    "pos_nearby_pct": 0.07,
    "prior_lookback": 60,
    "breakout_pct_min": 1.8,
    "prior_yang_ratio": 0.55,
    "max_close_vs_ma60": 1.25,
    "star_body_max_pct": 0.2,
    "star_platform_max": 6,
    "star_platform_min": 2,
    "star_shadow_ratio": 1.5,
    "trend_pressure_ma": 60,
    "attack_star_gap_min": 0.005,
    "prior_cluster_window": 10,
    "gap_pressure_lookback": 120,
    "top_pressure_lookback": 150,
    "prior_cluster_min_ratio": 0.5,
    "prior_yang_volume_ratio": 1.05,
    "top_pressure_price_dist": 0.12,
    "trend_pressure_lookback": 120,
    "breakout_max_upper_shadow": 0.35,
    "breakout_volume_min_ratio": 1.2,
    "top_pressure_volume_ratio": 1.8,
    "gap_pressure_volume_min_ratio": 1.3,
}


def compute_sandu_star(ctx, params=None):
    """三度星线：关键位星线平台 + 前期能量 + 位置安全 + 突破/攻击星线确认.

    假设：
    - 星线判定：实体/振幅 <= 0.2 且 (上影+下影)/实体 >= 1.5；实体为 0
      且有振幅时视为星线（十字星）；一字板（振幅 0）不算星线。
    - 星线平台 = 截至昨日的连续星线天数 ∈ [2, 6]（连续超过 6 天视为
      平台过长，不满足）。
    - "平台在关键均线附近" = 昨日收盘距 MA5/10/20/30/60（昨日值）任一
      偏离绝对值 <= 7%。
    - "整体涨幅<=60%" = 当日收盘 / 近60日最低收盘 - 1 <= 60%。
    - 突破放量基准 = 昨日量（*1.2）。
    - 攻击星线 = 当日本身为星线 且 开盘 >= 昨收*1.005（跳空高开），
      贴合"攻击星线"命名，比文档括号字面（仅跳空）略严。
    """
    p = {**SANDU_STAR_PARAMS, **(params or {})}
    try:
        n = len(ctx.C)
        if n < 170:
            return None
        if not _pressures_ok(ctx, p):
            return None
        # 星线序列（向量化）
        upper, lower, body = _candle_parts(ctx)
        rng = (ctx.H - ctx.L)
        body_ratio = body / rng.replace(0, np.nan)       # 一字板 → False
        shadow_ratio = (upper + lower) / body.replace(0, np.nan)
        star = (body_ratio <= p["star_body_max_pct"]) & (
            (shadow_ratio >= p["star_shadow_ratio"])
            | ((body == 0) & (rng > 0))
        )
        sa = star.fillna(False).to_numpy()
        # 平台：截至昨日连续星线天数 ∈ [min, max]
        run = 0
        i = n - 2
        cap = int(p["star_platform_max"])
        while i >= 0 and sa[i]:
            run += 1
            i -= 1
            if run > cap:
                break
        if not (int(p["star_platform_min"]) <= run <= cap):
            return None
        # 平台位于关键均线附近（按昨日收盘）
        c_p = _f(ctx.C, -2)
        near = False
        for m in p["pos_ma_list"]:
            mv = _f(ctx.ma(m), -2)
            if mv == mv and mv > 0 and \
                    abs(c_p / mv - 1) <= p["pos_nearby_pct"]:
                near = True
                break
        if not near:
            return None
        # 前期强势能量：阳占比 + 阳线聚集 + 阳阴量比
        if not _yang_stats_ok(ctx, p["prior_lookback"], p["prior_yang_ratio"],
                              p["prior_cluster_window"],
                              p["prior_cluster_min_ratio"],
                              p["prior_yang_volume_ratio"]):
            return None
        # 位置安全：close/MA60 <= 1.25、整体涨幅 <= 60%
        close = _f(ctx.C)
        ma60 = _f(ctx.ma(60))
        if not (ma60 == ma60 and ma60 > 0 and
                close / ma60 <= p["max_close_vs_ma60"]):
            return None
        c_min = float(ctx.C.iloc[-p["prior_lookback"]:].min())
        if not (c_min > 0 and close / c_min - 1 <= p["max_rally_pct"]):
            return None
        # 确认：平台突破 或 攻击星线
        pct = ctx.pct_change()
        v_t, v_p = _f(ctx.V, -1), _f(ctx.V, -2)
        breakout = (
            _f(pct) >= p["breakout_pct_min"]
            and v_p > 0 and v_t >= v_p * p["breakout_volume_min_ratio"]
            and _upper_body_ok(ctx, -1, p["breakout_max_upper_shadow"])
        )
        attack = bool(sa[-1]) and c_p > 0 and \
            _f(ctx.O) >= c_p * (1 + p["attack_star_gap_min"])
        if not (breakout or attack):
            return None
        return hit_payload(ctx, extra={
            "platform_days": int(run),
            "confirm": "breakout" if breakout else "attack_star",
        })
    except Exception:
        return None


# ---------------------------------------------------------------- 因子注册表


FACTORS = {
    "sandu_a_zone": {
        "name": "三度A区", "group": "三度系", "min_bars": 140,
        "params": SANDU_A_ZONE_PARAMS, "fn": compute_sandu_a_zone,
    },
    "sandu_b_zone": {
        "name": "三度B区", "group": "三度系", "min_bars": 200,
        "params": SANDU_B_ZONE_PARAMS, "fn": compute_sandu_b_zone,
    },
    "sandu_washout": {
        "name": "三度洗盘", "group": "三度系", "min_bars": 170,
        "params": SANDU_WASHOUT_PARAMS, "fn": compute_sandu_washout,
    },
    "sandu_neckline": {
        "name": "三度颈位", "group": "三度系", "min_bars": 170,
        "params": SANDU_NECKLINE_PARAMS, "fn": compute_sandu_neckline,
    },
    "sandu_star": {
        "name": "三度星线", "group": "三度系", "min_bars": 170,
        "params": SANDU_STAR_PARAMS, "fn": compute_sandu_star,
    },
}
