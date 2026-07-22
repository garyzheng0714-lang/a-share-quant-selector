"""量化今日一票 - 用数据说话，不靠 AI 主观发挥

用户 2026-07-13：「今日一票应结合所有策略因子做系统性计算，只推1-3只，
我只需要傻瓜式知道今天买哪个、明天观察哪个。」

设计依据（全部来自 12 万条历史信号的双周期回测，见 WORKLOG 第四期）：
1. **不做共振加权**——"命中多个因子=胜率高"已被证伪（样本内+3.82%，样本外-0.87%，
   方向翻转）。任何把因子分数相加的模型都是在放大噪音。
2. **只用经双周期验证的短线因子**——28 个因子里，只有「云阶」在 T+1 与 T+5 上
   两段互不重叠的历史都跑赢基准（T+5：样本内 56.0%/+2.72%，样本外 49.3%/+1.11%）。
   其余因子要么只在某段行情灵，要么长期亏钱。
3. **不假装能精准挑一只**——测过 J/RSI/放量/距前高/乖离/涨幅/共振数 7 个维度，
   没有任何一个能在两段历史里可靠区分云阶命中票的优劣（看似有效的两个，优组胜率
   反而更低、样本外收益差≈0）。所以命中多只时如实说明"无法区分优劣"，
   不编造一个假精度的排名。
4. **今天没有就是没有**——好机会稀缺，空仓是常态。硬凑一只是对用户的不负责。

输出两档：
- today_buy：云阶今日命中（突破已确认）→ 今天可以买
- tomorrow_watch：云阶预备队（主升+缩量横盘都到位，只差最后一根突破K线）
  → **仅作预告，不是买入信号**（见下）

⚠️ 2026-07-14 历史补测（现隔离于 research/legacy，非当前发布证据）：
预备队这个规则**没通过样本外检验**，此前"收盘站上突破线那天就是买点"的说法是错的：
- 10 天内真突破率仅 37%（样本内 37.6% / 样本外 36.8%，倒是很稳定）
- "等突破确认了再买"：样本内持有5天 胜率 52.0%、超额 +2.12% → 样本外 胜率 **39.3%**、
  超额 **-0.86%**（比基准低 12 个百分点）。方向翻转 = 过拟合，与"共振假设"同一个死法。
- "预备日就抢跑买"：样本外超额虽为正(+0.25%)，但胜率 46.0% **低于基准 51.4%**，
  靠少数暴涨拉均值——与用户"要高胜率"的诉求相悖。
反直觉的发现：**"离突破线越近"不等于"越好"**。用 gap<=5% 筛出来的这批，恰恰是云阶
信号里较差的一批（样本外 39.3% vs 云阶整体 49.3%）。
故 tomorrow_watch 保留为"明天可能进买入名单"的心理预告，前端明确标注"不是买入信号"。
"""

import logging

import numpy as np

from strategy.factor_lib import FactorContext
from strategy.factors.momentum_family import CLOUD_STAIR_PARAMS

logger = logging.getLogger(__name__)

CORE_FACTOR = "cloud_stair"  # 唯一经双周期验证的短线因子

# 该因子的历史真实战绩（写死在此供展示——数据来自 factor_track_record.json，
# 前端展示以 API 下发的 track 为准，这里只作为兜底文案）
CORE_TRACK = {
    "name": "云阶",
    "hold_days": 5,
    "in_win": 56.0,
    "in_excess": 2.72,
    "oos_win": 49.3,
    "oos_excess": 1.11,
}


def _cloud_stair_pending(ctx, params=None):
    """云阶预备队：主升 + 缩量横盘全部到位，唯独还没突破.

    与 compute_cloud_stair 完全同源（同一组参数、同一套结构判据），
    只把最后一步「突破确认」反过来：今日收盘 **未达** 突破线，
    但距离突破线不超过 5%（太远的没有明天就突破的可能，是噪音）。

    返回 {gap_pct: 距突破线还差百分之几, target: 突破价, peak_date, wave_gain_pct}
    """
    p = {**CLOUD_STAIR_PARAMS, **(params or {})}
    n = len(ctx.df)
    if n < p["long_high_lookback_days"] + 5:
        return None
    C = ctx.C.to_numpy(dtype=float)
    H = ctx.H.to_numpy(dtype=float)
    L = ctx.L.to_numpy(dtype=float)
    V = ctx.V.to_numpy(dtype=float)
    if not (V[-1] > 0):
        return None
    pct = ctx.pct_change().to_numpy(dtype=float)
    hh_long = np.nanmax(H[-p["long_high_lookback_days"] :])
    if not (hh_long == hh_long):
        return None
    w0 = max(0, n - p["surge_lookback_days"])

    for peak in range(max(w0, 1), n - 1 - p["min_consolidation_days"]):
        peak_h, peak_v = H[peak], V[peak]
        if not (peak_h == peak_h and peak_v > 0):
            continue
        if peak_h < p["min_peak_to_long_high_ratio"] * hh_long:
            continue
        lows = L[w0 : peak + 1]
        if not np.isfinite(lows).any():
            continue
        li = w0 + int(np.nanargmin(lows))
        stage_low = L[li]
        if not (stage_low > 0 and peak_h / stage_low - 1 >= p["min_wave_gain_pct"]):
            continue
        seg = pct[li : peak + 1]
        if (
            int(np.nansum(seg >= p["strong_up_pct_threshold"]))
            < p["min_strong_up_days"]
        ):
            continue
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

        # 唯一的差别：还没突破，但离突破线很近（<=5%）
        target = (
            peak_h
            * p["min_breakout_close_to_peak_ratio"]
            * (1 + p["breakout_buffer_pct"])
        )
        c = C[-1]
        if c >= target:  # 已突破 → 归今日买入，不在观察名单
            return None
        gap = target / c - 1
        if gap > 0.05:  # 差得太远，明天不可能突破
            continue
        return {
            "gap_pct": round(gap * 100, 2),
            "target": round(float(target), 2),
            "peak_date": str(ctx.df["date"].iloc[peak]),
            "wave_gain_pct": round((peak_h / stage_low - 1) * 100, 1),
        }
    return None


def scan_pending(csv_manager, stock_names, trade_date, codes=None):
    """全市场扫云阶预备队（明日观察名单）."""
    from concurrent.futures import ThreadPoolExecutor

    from utils.market_filter import is_main_board, main_board_only

    if codes is None:
        codes = [
            c for c in csv_manager.list_all_stocks() if c.isdigit() and len(c) == 6
        ]
    if main_board_only():
        codes = [c for c in codes if is_main_board(c)]
    invalid_kw = ("退", "未知", "退市", "已退")
    tasks = []
    for code in codes:
        nm = stock_names.get(code, "")
        if any(k in nm for k in invalid_kw) or nm.startswith(("ST", "*ST")):
            continue
        tasks.append((code, nm))

    def _one(item):
        code, nm = item
        try:
            df = csv_manager.read_stock(code)
            if df is None or df.empty or len(df) < 200:
                return None
            if len(df) > 1 and str(df["date"].iloc[0]) > str(df["date"].iloc[-1]):
                df = df.iloc[::-1].reset_index(drop=True)
            last = str(df["date"].iloc[-1])[:10]
            if trade_date and last != trade_date:
                return None  # 停牌/断更，旧K线不算数
            r = _cloud_stair_pending(FactorContext(df))
            if not r:
                return None
            r.update(
                {
                    "code": code,
                    "name": nm,
                    "close": round(float(df["close"].iloc[-1]), 2),
                }
            )
            return r
        except Exception as e:
            logger.warning("预备队扫描 %s 失败: %s", code, e)
            return None

    out = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for r in ex.map(_one, tasks):
            if r:
                out.append(r)
    out.sort(key=lambda x: x["gap_pct"])  # 离突破最近的排前面
    return out
