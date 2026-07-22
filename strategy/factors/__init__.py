"""策略因子注册表 - 聚合 4 个 family 文件的全部因子.

FACTOR_REGISTRY: {key: {"name", "group", "min_bars", "params", "fn"}}
fn(ctx: FactorContext, params=None) -> dict | None
"""

from strategy.factors.b1_family import FACTORS as _b1
from strategy.factors.zhixing_family import FACTORS as _zx
from strategy.factors.momentum_family import FACTORS as _mo
from strategy.factors.sandu_family import FACTORS as _sd

FACTOR_REGISTRY = {}
for _m in (_b1, _zx, _mo, _sd):
    for _k, _v in _m.items():
        if _k in FACTOR_REGISTRY:
            raise ValueError(f"因子 key 冲突: {_k}")
        FACTOR_REGISTRY[_k] = _v

# 前端分组展示顺序
GROUP_ORDER = ["B1系", "知行系", "动量系", "三度系"]

# 每个因子的大白话说明（面向无编程基础的用户，一句话讲清"这个公式在等什么"）。
# 技术口径见各 compute 函数 docstring；这里只负责说人话。
PLAIN_DESC = {
    "oversold_b1": "趋势向上的票短线跌过了头，等它弹回来",
    "kdj_cross": "趋势向上，K线J线双双上穿D线的启动信号",
    "tepu": "近期放量突破过的强势票，回调到了超卖位",
    "super_b1_factor": "先出现过B1信号，又横盘缩量，今天再回调一下——找更低的接点",
    "fill_pit": "股价爬回历史高点的坑口附近，且短线超卖",
    "ticket_refill": "主力线一直高位、散户线被洗到低位后拉回",
    "new_b2": "温和趋势里突然放量大涨3.7%以上的启动日",
    "zx_white_b1": "站上知行白线且贴着白线的B1买点",
    "zx_yellow_b1": "回踩到知行黄线附近的B1买点",
    "zx_brick": "砖型指标由绿转红的拐点，且红比昨天的绿更有力",
    "double_line": "在白线黄线之间缩量整理，等变盘向上",
    "brick_b1": "多头环境+砖型转红+J值低位的B1预备信号",
    "cross_step_yellow": "白线金叉黄线后，第一次回踩黄线不破",
    "nana_chart": "放量启动→缩量到地量→小阴小阳，洗盘接近尾声",
    "zx_pullback_brick": "趋势中回踩之后，短线指标重新转强",
    "angel_devil": "天使线上穿魔鬼线的进攻信号",
    "six_veins": "六个指标同一天全部转多，且是第一天共振",
    "wave_band": "波段指标拐头向上的买点（信号较宽，参考为主）",
    "needle_down30": "散户线一针扎到30以下、主力线稳稳站在85以上",
    "bottom_violent_k": "底部区域突然放出翻倍量的大阳线",
    "trend_strengthen": "主力潜伏之后，接近涨停的放量大阳线突破",
    "cloud_stair": "第一波大涨→缩量横盘不破位→再次突破前高",
    "ma520": "5日线金叉20日线的次日，阳线确认并创昨日新高",
    "sandu_a_zone": "资金推动后进入攻击结构（条件极苛刻，出现即重视）",
    "sandu_b_zone": "强势启动后健康缩量回调到支撑位，今天放量反转",
    "sandu_washout": "关键位置被凶狠洗盘，今天强势收复",
    "sandu_neckline": "充分整理后放量突破颈位压力",
    "sandu_star": "关键位置连续星线蓄势，今天向上发力",
}
