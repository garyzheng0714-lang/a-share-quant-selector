"""个股技术特征包 - 从本地日线数据提取候选票的完整技术面（给 AI 荐票的原料）

不只是 J 值和 B1 分——均线结构、量价关系、位置、波动、知行线距离、周线状态，
让 AI 能做跨维度交叉判断（量价背离、缩量回踩、位置高低），而不是复述页面上已有的数字。
"""

import logging

import pandas as pd

logger = logging.getLogger(__name__)


def extract_features(df: pd.DataFrame) -> dict:
    """从倒序日线数据提取技术特征。数据不足时返回 {}."""
    if df is None or df.empty or len(df) < 60:
        return {}

    up = df.iloc[::-1].reset_index(drop=True)  # 正序
    close = up["close"].astype(float)
    vol = up["volume"].astype(float)
    high = up["high"].astype(float)
    low = up["low"].astype(float)

    c = float(close.iloc[-1])
    ma = {n: float(close.rolling(n).mean().iloc[-1]) for n in (5, 10, 20, 60)}

    # 均线结构
    if ma[5] > ma[10] > ma[20] > ma[60]:
        ma_structure = "多头排列"
    elif ma[5] < ma[10] < ma[20] < ma[60]:
        ma_structure = "空头排列"
    else:
        ma_structure = "均线纠缠"

    # 量能
    v5 = float(vol.tail(5).mean())
    v60 = float(vol.tail(60).mean())
    vol_ratio_5v60 = round(v5 / v60, 2) if v60 > 0 else None

    # 位置与波动
    h60 = float(high.tail(60).max())
    l60 = float(low.tail(60).min())
    amp20 = float(((high - low) / close.shift(1)).tail(20).mean() * 100)

    feats = {
        "close": round(c, 2),
        "chg_5d": round((c / float(close.iloc[-6]) - 1) * 100, 2),
        "chg_20d": round((c / float(close.iloc[-21]) - 1) * 100, 2),
        "chg_60d": round((c / float(close.iloc[-60]) - 1) * 100, 2),
        "ma_structure": ma_structure,
        "vs_ma20": round((c / ma[20] - 1) * 100, 2),
        "vs_ma60": round((c / ma[60] - 1) * 100, 2),
        "vol_5v60": vol_ratio_5v60,
        "dist_high60": round((c / h60 - 1) * 100, 2),
        "dist_low60": round((c / l60 - 1) * 100, 2),
        "amp_20d": round(amp20, 2),
    }

    # 知行线距离（与选股体系一致）
    try:
        from utils.technical import calculate_zhixing_trend

        trend = calculate_zhixing_trend(df)
        st = float(trend["short_term_trend"].iloc[0])
        bb = float(trend["bull_bear_line"].iloc[0])
        feats["vs_short_trend"] = round((c / st - 1) * 100, 2)
        feats["vs_duokong"] = round((c / bb - 1) * 100, 2)
    except Exception as e:
        logger.debug("知行线计算失败: %s", e)

    return feats


def describe_features(f: dict) -> str:
    """特征包转成给 AI 的紧凑文字."""
    if not f:
        return "（本地行情数据不足，无技术特征）"
    parts = [
        f"现价{f['close']}",
        f"近5日{f['chg_5d']:+}%/近20日{f['chg_20d']:+}%/近60日{f['chg_60d']:+}%",
        f"{f['ma_structure']}（距MA20 {f['vs_ma20']:+}%，距MA60 {f['vs_ma60']:+}%）",
        f"量能5日/60日均量比{f['vol_5v60']}" if f.get("vol_5v60") is not None else "",
        f"距60日高点{f['dist_high60']:+}%/低点{f['dist_low60']:+}%",
        f"日均振幅{f['amp_20d']}%",
    ]
    if "vs_short_trend" in f:
        parts.append(
            f"距短期趋势线{f['vs_short_trend']:+}%/距多空线{f['vs_duokong']:+}%"
        )
    return "；".join(p for p in parts if p)
