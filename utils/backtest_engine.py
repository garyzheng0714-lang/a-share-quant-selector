"""历史回测引擎 - 回放"过去每天跑选股"，快速积累战绩样本

原理：
- 所有指标（EMA/MA/KDJ/放量标记等）都是因果计算——某天的值只依赖当天及之前的数据，
  所以每只股票只需计算一次全量指标，再逐日检查选股条件，无未来数据泄漏。
- 选股条件与 BowlReboundStrategy.select_stocks 逐条对齐（有对照测试保证一致）。
- 周线闸门只对通过全部日线条件的候选日运行（与实盘顺序一致，也避免大量重采样）。

收益口径与实盘战绩追踪一致（performance_tracker._evaluate_one）：
T+1 开盘价买入，ret_n = (T+n 收盘 - 买入价) / 买入价。
"""
import logging

import numpy as np
import pandas as pd

from utils.performance_tracker import WINDOWS, _aggregate, _evaluate_one
from utils.technical import weekly_four_ma_bullish

logger = logging.getLogger(__name__)

MIN_BARS = 60  # 与实盘一致：数据不足 60 天的股票不参与


def backtest_stock(code, name, df, strategy, start_date, end_date):
    """对单只股票回放历史，返回信号日列表.

    Args:
        df: 倒序日线数据（read_stock 原始格式）
        strategy: 已配置参数的 BowlReboundStrategy 实例
        start_date/end_date: 回测窗口 'YYYY-MM-DD'

    Returns:
        [{'date', 'code', 'name', 'category', 'close', 'J'}, ...]
    """
    # 名称过滤，与实盘一致
    if name:
        if any(kw in name for kw in ['退', '未知', '退市', '已退']):
            return []
        if name.startswith('ST') or name.startswith('*ST'):
            return []
    if df.empty or len(df) < MIN_BARS:
        return []

    df_ind = strategy.calculate_indicators(df)
    up = df_ind.iloc[::-1].reset_index(drop=True)  # 正序（从早到晚）
    date_str = pd.to_datetime(up['date']).dt.strftime('%Y-%m-%d')

    m = int(strategy.params['M'])
    n_rows = len(up)

    # ---- 向量化的逐日条件（与 select_stocks 逐条对应）----
    valid = (up['volume'] > 0) & up['close'].notna()
    j_sane = up['J'].abs().rolling(30, min_periods=1).mean() <= 80
    trend_above = up['trend_above'].fillna(False)
    j_low = up['j_low'].fillna(False)
    has_key = up['key_candle'].rolling(m, min_periods=1).max().fillna(0).astype(bool)

    # M 天窗口内成交量最大的那天必须是阳线
    # >= 与实盘对齐：select_stocks 是 close < open 才淘汰，平盘(close==open)放行
    vol = up['volume'].to_numpy(dtype=float)
    positive = (up['close'] >= up['open']).to_numpy()
    max_vol_positive = np.zeros(n_rows, dtype=bool)
    for t in range(n_rows):
        lo = max(0, t - m + 1)
        max_vol_positive[t] = positive[lo + int(np.argmax(vol[lo:t + 1]))]

    daily_ok = (
        valid & j_sane & trend_above & j_low & has_key
        & pd.Series(max_vol_positive, index=up.index)
    )

    signals = []
    weekly_gate = strategy.params.get('weekly_gate', True)
    # 次新股闸门对齐实盘：当时数据长度 t+1 < M4(114) 时多空线无效不发信号。
    # weekly_gate 开启时周线闸门（需约300交易日）本就兜住了这段，此处是
    # weekly_gate=False 路径下的对齐兜底。
    min_bars_live = max(MIN_BARS, int(strategy.params.get('M4', 114)))
    for t in np.flatnonzero(daily_ok.to_numpy()):
        if t < min_bars_live - 1:
            continue
        d = date_str.iloc[t]
        if d < start_date or d > end_date:
            continue

        row = up.iloc[t]
        # 分类（优先级与实盘一致），无分类则不选
        if row['fall_in_bowl']:
            category = 'bowl_center'
        elif row['near_duokong']:
            category = 'near_duokong'
        elif row['near_short_trend']:
            category = 'near_short_trend'
        else:
            continue

        # 周线闸门放最后（重采样开销大，只对候选日执行）
        if weekly_gate:
            gate_ok, _ = weekly_four_ma_bullish(up.iloc[:t + 1][['date', 'close']])
            if not gate_ok:
                continue

        signals.append({
            'date': d,
            'code': code,
            'name': name,
            'category': category,
            'close': round(float(row['close']), 2),
            'J': round(float(row['J']), 2),
        })
    return signals


def run_backtest(csv_manager, stock_names, start_date, end_date,
                 strategy_params, ignore_cap=False, max_stocks=None,
                 progress=True):
    """全市场（本地已有数据的股票）回放 + 收益回填 + 汇总.

    Args:
        stock_names: {code: name}，用于 ST/退市过滤
        ignore_cap: 数据缺市值（market_cap 全 0）时置 True，跳过市值条件并在报告注明
        max_stocks: 限制回测股票数（调试用）

    Returns:
        (signals: list[dict], summary: dict)
    """
    from strategy.bowl_rebound import BowlReboundStrategy
    from utils.market_filter import is_main_board, main_board_only

    strategy = BowlReboundStrategy(dict(strategy_params))
    cap = strategy.params['CAP']

    codes = csv_manager.list_all_stocks()
    if main_board_only():
        codes = [c for c in codes if is_main_board(c)]
    if max_stocks:
        codes = codes[:max_stocks]

    signals = []
    for i, code in enumerate(codes, 1):
        df = csv_manager.read_stock(code)
        if df.empty:
            continue
        if ignore_cap:
            df = df.copy()
            df['market_cap'] = cap + 1  # 使市值条件恒真，等效于跳过
        name = stock_names.get(code, '')
        try:
            signals += backtest_stock(code, name, df, strategy, start_date, end_date)
        except Exception as e:
            logger.error("回测 %s 失败: %s", code, e)
        if progress and (i % 25 == 0 or i == len(codes)):
            print(f"  回放进度 [{i}/{len(codes)}]，累计信号 {len(signals)} 个")

    # ---- 收益回填（复用实盘口径）----
    by_code = {}
    for s in signals:
        by_code.setdefault(s['code'], []).append(s)
    for code, items in by_code.items():
        df = csv_manager.read_stock(code)
        daily = df[['date', 'open', 'high', 'low', 'close']].copy()
        daily['date'] = pd.to_datetime(daily['date']).dt.strftime('%Y-%m-%d')
        if len(daily) > 1 and daily['date'].iloc[0] > daily['date'].iloc[-1]:
            daily = daily.iloc[::-1].reset_index(drop=True)
        for s in items:
            fields = _evaluate_one(daily, s['date'])
            for k in ['buy_price', 'max_gain', 'max_drawdown', 'days_tracked', 'status']:
                s[k] = fields.get(k)
            for w in WINDOWS:
                s[f'ret_{w}'] = fields.get(f'ret_{w}')

    evaluated = [s for s in signals if s.get('days_tracked')]
    by_category, by_year = {}, {}
    for s in evaluated:
        by_category.setdefault(s['category'], []).append(s)
        by_year.setdefault(s['date'][:4], []).append(s)

    summary = {
        'start_date': start_date,
        'end_date': end_date,
        'stocks_scanned': len(codes),
        'total_signals': len(signals),
        'evaluated_signals': len(evaluated),
        'ignore_cap': ignore_cap,
        'params': dict(strategy.params),
        'overall': _aggregate(evaluated),
        'by_category': {k: _aggregate(v) for k, v in sorted(by_category.items())},
        'by_year': {k: _aggregate(v) for k, v in sorted(by_year.items())},
    }
    return signals, summary


def format_report(summary: dict) -> str:
    """把回测汇总渲染成 Markdown 报告."""
    lines = [
        "# 碗口反弹策略 历史回测报告",
        "",
        f"- 回测区间: {summary['start_date']} ~ {summary['end_date']}",
        f"- 扫描股票: {summary['stocks_scanned']} 只（沪深主板）",
        f"- 产生信号: {summary['total_signals']} 个，其中 {summary['evaluated_signals']} 个有后续行情可评估",
        f"- 买入口径: 信号次日开盘价买入；收益为 T+n 收盘相对买入价",
    ]
    if summary['ignore_cap']:
        lines.append("- ⚠️ 本次回测**未启用市值门槛条件**（本地数据缺市值字段），"
                     "与实盘条件存在差异，正式结论以服务器全量数据回测为准")
    p = summary['params']
    lines += [
        f"- 关键参数: N={p['N']} M={p['M']} J_VAL={p['J_VAL']} "
        f"weekly_gate={p.get('weekly_gate')} duokong_pct={p['duokong_pct']} short_pct={p['short_pct']}",
        "",
    ]

    def table(agg):
        rows = ["| 持有期 | 样本数 | 胜率 | 平均收益 |", "|---|---|---|---|"]
        for w in WINDOWS:
            a = agg[f'ret_{w}']
            if a['count']:
                rows.append(f"| T+{w} | {a['count']} | {a['win_rate']}% | {a['avg']:+.2f}% |")
            else:
                rows.append(f"| T+{w} | 0 | - | - |")
        return rows

    lines += ["## 总体表现", ""] + table(summary['overall']) + [""]
    cat_names = {'bowl_center': '🥣 回落碗中', 'near_duokong': '📊 靠近多空线',
                 'near_short_trend': '📈 靠近短期趋势线'}
    lines.append("## 按分类")
    for cat, agg in summary['by_category'].items():
        lines += ["", f"### {cat_names.get(cat, cat)}", ""] + table(agg)
    lines.append("")
    lines.append("## 按年份（检验策略是否在某些年份失效）")
    for year, agg in summary['by_year'].items():
        lines += ["", f"### {year}", ""] + table(agg)
    lines += ["", "> 注: 同一股票可能连续多日出信号（与实盘一致），样本间存在相关性；",
              "> 收益未扣除交易成本，亦未与同期大盘基准对比。"]
    return "\n".join(lines)
