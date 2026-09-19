"""神机·生命线因子：容差与力度两条边界（复原自 26 根标记 K 线的核心口径）."""

import numpy as np
import pandas as pd

from strategy.factor_lib import FactorContext
from strategy.factors.shenji_family import compute_shenji_lifeline


def _df(closes):
    closes = np.asarray(closes, dtype=float)
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=len(closes)).strftime("%Y-%m-%d"),
            "open": closes * 0.99,
            "high": closes * 1.01,
            "low": closes * 0.98,
            "close": closes,
            "volume": np.full(len(closes), 1e6),
        }
    )


def _base():
    # 20 根贴着 10.00 的收盘：MA13 ≈ 10，昨日贴线（容差内），今日决定是否触发
    return [10.0] * 20


def test_cross_with_margin_and_gain_hits():
    closes = _base() + [10.30]  # +3.0%，BIAS 约 +2.9%
    hit = compute_shenji_lifeline(FactorContext(_df(closes)))
    assert hit is not None
    assert hit["bias_pct"] > 0.5 and hit["prev_bias_pct"] <= 0.5


def test_within_tolerance_does_not_count_as_above():
    # 昨日已在线上 0.3%（容差内）→ 今日大涨仍算「刚上穿」
    closes = _base() + [10.03, 10.35]
    assert compute_shenji_lifeline(FactorContext(_df(closes))) is not None
    # 昨日在线上 0.8%（超出容差）→ 不是上穿
    closes = _base() + [10.08, 10.40]
    assert compute_shenji_lifeline(FactorContext(_df(closes))) is None


def test_weak_bar_is_filtered():
    closes = _base() + [10.15]  # 上穿 1.5% 但涨幅只有 1.5%
    assert compute_shenji_lifeline(FactorContext(_df(closes))) is None
