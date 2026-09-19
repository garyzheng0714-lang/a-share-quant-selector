"""生命线系因子 - 神机信号（第三方指标反推，2026-09 复原）.

来源：公众号「神机队长」14 篇文章、26 根被标记 K 线 + 435 根同图未标记 K 线的
逐根核对（日线 / 60 分钟 / 30 分钟 / 15 分钟四个周期口径一致）。复原结论：

- 「生命线」= MA(CLOSE,13)，像素级拟合四张图误差 0.004–0.037，远优于其他周期。
- 触发 = 收盘从生命线下方穿到上方，带 0.5% 容差（贴线 ±0.5% 内既不算上方也不算刚上穿）。
- 力度 = 当根涨幅 > 2%（成交量过滤已被 15 分钟样本证伪）。

461 根样本上只剩 2 个分钟级例外（数据源差异范围内）。它是滞后的趋势跟随触发，
不是预测信号，战绩评级走 factor_track_record 同一套流程，未验证前只作观察。
"""

from strategy.factor_lib import _last, hit_payload
from strategy.factors.momentum_family import _safe

SHENJI_PARAMS = {"ma_period": 13, "tolerance_pct": 0.5, "min_gain_pct": 2.0}


@_safe
def compute_shenji_lifeline(ctx, params=None):
    """神机信号：收盘带容差上穿 13 日生命线，且当日涨幅超过 2%.

    三条：1) BIAS13 = (C/MA13-1)*100 > tolerance
    2) 昨日 BIAS13 <= tolerance（昨日不在线上，含贴线容差）
    3) 当日涨幅 > min_gain_pct。
    """
    p = {**SHENJI_PARAMS, **(params or {})}
    n = int(p["ma_period"])
    if len(ctx.df) < n + 2:
        return None
    ma = ctx.ma(n)
    bias = (ctx.C / ma - 1) * 100
    b_t, b_p = float(bias.iloc[-1]), float(bias.iloc[-2])
    if not (b_t == b_t and b_p == b_p):
        return None
    tol = float(p["tolerance_pct"])
    if not (b_t > tol and b_p <= tol):
        return None
    pct = _last(ctx.pct_change())
    if not (pct == pct and pct > float(p["min_gain_pct"])):
        return None
    return hit_payload(
        ctx,
        extra={
            "ma13": round(_last(ma), 2),
            "bias_pct": round(b_t, 2),
            "prev_bias_pct": round(b_p, 2),
        },
    )


FACTORS = {
    "shenji_lifeline": {
        "name": "神机·生命线",
        "group": "生命线系",
        "min_bars": 20,
        "params": SHENJI_PARAMS,
        "fn": compute_shenji_lifeline,
    },
}
