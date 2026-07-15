"""市场温度计 - 量化"人声鼎沸 / 无人问津"，回答"今天适不适合出手"

三个独立指标（不做玄学加权综合分，各自展示 + 人话结论，诚实优先）：

1. 市场热度（人声指标）：上证指数近 5 日日均成交量在过去 250 日中的百分位（0-100）
   - >= 80 且近 20 日明显上涨 → 过热（"人声鼎沸"，谨慎追高）
   - <= 20 → 冰点（"无人问津"，机会酝酿区）
2. 大盘趋势：收盘价与 MA20 / MA60 的位置关系（多头 / 空头 / 震荡）
3. 策略适应度：最近 60 天信号的 T+5 滚动胜率（数据源：实盘战绩表，不足则用最新回测明细）
   —— 直接回答"这套策略最近灵不灵"（回测发现 2026 年策略失效，此指标就是失效预警器）

数据源：腾讯行情接口（本地已验证可用）；拉取结果缓存 1 小时。
"""
import json
import logging
import time
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

INDEX_CODE = "sh000001"  # 上证指数
_CACHE = {"ts": 0.0, "data": None}
_CACHE_TTL = 3600

BACKTEST_DIR = Path(__file__).parent.parent / "data" / "backtest"


def _fetch_index_daily(days=320):
    """拉上证指数日线 [date, open, close, high, low, volume]，带 1 小时缓存."""
    now = time.time()
    if _CACHE["data"] and now - _CACHE["ts"] < _CACHE_TTL:
        return _CACHE["data"]
    url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
           f"?param={INDEX_CODE},day,,,{days},qfq")
    r = requests.get(url, timeout=10)
    data = r.json()["data"][INDEX_CODE]
    klines = data.get("qfqday") or data.get("day") or []
    rows = [
        {"date": k[0], "close": float(k[2]), "volume": float(k[5])}
        for k in klines
    ]
    _CACHE["ts"], _CACHE["data"] = now, rows
    return rows


def _market_heat(rows):
    """成交量热度百分位 + 近20日涨幅 + 趋势结构."""
    closes = [r["close"] for r in rows]
    vols = [r["volume"] for r in rows]

    recent5 = sum(vols[-5:]) / 5
    history = vols[-250:]
    percentile = round(sum(1 for v in history if v < recent5) / len(history) * 100)

    chg_20d = round((closes[-1] / closes[-21] - 1) * 100, 2) if len(closes) > 21 else 0.0

    ma20 = sum(closes[-20:]) / 20
    ma60 = sum(closes[-60:]) / 60 if len(closes) >= 60 else ma20
    if closes[-1] > ma20 > ma60:
        trend = "bull"
    elif closes[-1] < ma20 < ma60:
        trend = "bear"
    else:
        trend = "sideways"

    if percentile >= 80 and chg_20d > 3:
        level = "hot"       # 人声鼎沸
    elif percentile <= 20:
        level = "cold"      # 无人问津
    else:
        level = "normal"

    return {
        "volume_percentile": percentile,
        "chg_20d": chg_20d,
        "trend": trend,
        "level": level,
        "index_close": closes[-1],
        "index_date": rows[-1]["date"],
    }


def _strategy_fitness():
    """最近 60 天信号的 T+5 滚动胜率. 实盘战绩优先，样本不足用最新回测明细."""
    MIN_SAMPLES = 20
    rows = []
    source = None

    try:
        from utils.performance_tracker import get_records
        live = [r for r in get_records(limit=2000)
                if r.get("ret_5") is not None]
        # 多视图重叠时同一 (run_date, code) 在 performance 表有多行，
        # 去重防止重叠票被重复计权、扭曲胜率
        dedup = {}
        for r in live:
            dedup.setdefault((r["run_date"], r["code"]), r)
        live = list(dedup.values())
        if live:
            latest = max(r["run_date"] for r in live)
            cutoff = _shift_date(latest, -90)  # 60 个交易日 ≈ 90 个日历日
            rows = [r["ret_5"] for r in live if r["run_date"] >= cutoff]
            source = "live"
    except Exception as e:
        logger.warning("读取实盘战绩失败: %s", e)

    if len(rows) < MIN_SAMPLES and BACKTEST_DIR.exists():
        import csv
        files = sorted(BACKTEST_DIR.glob("signals_*.csv"))
        if files:
            with open(files[-1], encoding="utf-8") as f:
                sig = [r for r in csv.DictReader(f) if r.get("ret_5")]
            if sig:
                latest = max(r["date"] for r in sig)
                cutoff = _shift_date(latest, -90)
                rows = [float(r["ret_5"]) for r in sig if r["date"] >= cutoff]
                source = "backtest"

    if len(rows) < MIN_SAMPLES:
        return {"available": False, "reason": f"近期样本不足（{len(rows)} < {MIN_SAMPLES}）"}

    win_rate = round(sum(1 for v in rows if v > 0) / len(rows) * 100, 1)
    return {
        "available": True,
        "source": source,
        "samples": len(rows),
        "win_rate_t5": win_rate,
        "status": "failing" if win_rate < 40 else ("weak" if win_rate < 50 else "healthy"),
    }


def _shift_date(date_str, days):
    from datetime import datetime, timedelta
    return (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")


def _conclusion(heat, fitness):
    """人话结论（确定性规则，不用 LLM）。优先级：策略失效 > 市场过热 > 冰点 > 正常."""
    if fitness.get("available") and fitness["status"] == "failing":
        return ("caution",
                f"⚠️ 策略近期失效中：最近{fitness['samples']}个信号 T+5 胜率仅 "
                f"{fitness['win_rate_t5']}%。建议轻仓或观望，等胜率回到 50% 以上再出手。")
    if heat["level"] == "hot":
        return ("caution",
                f"🔥 市场过热：成交热度处于一年内第 {heat['volume_percentile']} 百分位，"
                f"近20日大盘涨 {heat['chg_20d']}%。人声鼎沸时宜减仓兑现，不宜追高。")
    if heat["level"] == "cold":
        return ("opportunity",
                f"🧊 市场冰点：成交热度仅第 {heat['volume_percentile']} 百分位。"
                f"无人问津处多机会，可留意周线转强的票。")
    if fitness.get("available") and fitness["status"] == "weak":
        return ("neutral",
                f"市场温度正常，但策略近期胜率偏弱（{fitness['win_rate_t5']}%），出手宜谨慎控制仓位。")
    return ("normal", "✅ 市场温度正常，策略状态健康，可按体系正常操作。")


def get_thermometer() -> dict:
    """温度计主入口。返回市场热度 + 趋势 + 策略适应度 + 人话结论."""
    try:
        rows = _fetch_index_daily()
        if len(rows) < 60:
            return {"available": False, "reason": "指数数据不足"}
        heat = _market_heat(rows)
    except Exception as e:
        logger.error("拉取指数数据失败: %s", e)
        return {"available": False, "reason": f"指数数据获取失败: {e}"}

    fitness = _strategy_fitness()
    signal, text = _conclusion(heat, fitness)
    return {
        "available": True,
        "heat": heat,
        "fitness": fitness,
        "signal": signal,       # caution / opportunity / neutral / normal
        "conclusion": text,
    }
