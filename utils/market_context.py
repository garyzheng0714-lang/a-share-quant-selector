"""宏观市场数据包 - 给 AI 荐票的宏观面原料（全部真实数据，非模型编造）

包含：
1. 三大指数技术结构（上证/深成/创业板指：价格位置、均线结构、量能）
2. 行业板块热度（东财：涨跌幅、换手、主力资金净流入；前5/后5 + 按行业查询）

数据源：腾讯行情（指数）+ 东方财富（行业板块）。均有内存缓存，避免频繁请求。
"""
import logging
import time

import requests

logger = logging.getLogger(__name__)

INDEXES = [
    ("sh000001", "上证指数"),
    ("sz399001", "深证成指"),
    ("sz399006", "创业板指"),
]

_cache: dict = {}
_CACHE_TTL = 1800


def _cached(key, fn):
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]
    val = fn()
    _cache[key] = (now, val)
    return val


def _get_with_retry(url, retries: int = 2, backoff: float = 0.5, **kwargs):
    """带轻量重试的 GET：瞬时抖动/超时/5xx 重试 retries 次（间隔 backoff 秒），仍失败才抛出。

    raise_for_status() 让 HTTP 层错误（5xx/限流）也走重试，而不是把错误页
    原样返回给上层去 json() 解析炸掉。
    """
    last_err = None
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, **kwargs)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            last_err = e
            if attempt < retries:
                logger.debug("行情请求失败(第%d次)，%.1fs后重试: %s", attempt + 1, backoff, e)
                time.sleep(backoff)
    raise last_err


def _fetch_index(code: str, days: int = 320) -> list:
    url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
           f"?param={code},day,,,{days},qfq")
    r = _get_with_retry(url, timeout=10)
    data = r.json()["data"][code]
    klines = data.get("qfqday") or data.get("day") or []
    return [{"date": k[0], "close": float(k[2]), "volume": float(k[5])} for k in klines]


def _index_brief(code: str, name: str) -> dict:
    rows = _fetch_index(code)
    closes = [r["close"] for r in rows]
    vols = [r["volume"] for r in rows]
    if len(closes) < 60:
        return {"name": name, "available": False}

    ma20 = sum(closes[-20:]) / 20
    ma60 = sum(closes[-60:]) / 60
    recent5_vol = sum(vols[-5:]) / 5
    vol_pct = round(sum(1 for v in vols[-250:] if v < recent5_vol) / min(len(vols), 250) * 100)
    high250 = max(closes[-250:])
    low250 = min(closes[-250:])

    return {
        "name": name,
        "available": True,
        "close": round(closes[-1], 2),
        "chg_5d": round((closes[-1] / closes[-6] - 1) * 100, 2),
        "chg_20d": round((closes[-1] / closes[-21] - 1) * 100, 2),
        "vs_ma20": round((closes[-1] / ma20 - 1) * 100, 2),
        "vs_ma60": round((closes[-1] / ma60 - 1) * 100, 2),
        "pos_in_year": round((closes[-1] - low250) / (high250 - low250) * 100) if high250 > low250 else 50,
        "vol_percentile": vol_pct,
    }


def get_index_overview() -> list:
    """三大指数技术结构.

    失败条目不进 30 分钟长缓存：只要有指数获取失败，本次结果不缓存，
    下次调用重新拉——避免一次瞬时抖动让宏观数据缺失半小时。
    """
    def fetch():
        out = []
        for code, name in INDEXES:
            try:
                out.append(_index_brief(code, name))
            except Exception as e:
                logger.warning("指数 %s 获取失败: %s", name, e, exc_info=True)
                out.append({"name": name, "available": False, "error": str(e)})
        return out

    now = time.time()
    hit = _cache.get("indexes")
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]
    val = fetch()
    if all(i.get("available") for i in val):
        _cache["indexes"] = (now, val)
    return val


def get_industry_heat() -> dict:
    """东财行业板块热度：{'list': [...], 'by_name': {行业名: {...}}}."""
    def fetch():
        r = _get_with_retry(
            "https://push2.eastmoney.com/api/qt/clist/get",
            params={
                "pn": 1, "pz": 100, "po": 1, "np": 1, "fltt": 2, "invt": 2,
                "fid": "f3", "fs": "m:90+t:2+f:!50",
                "fields": "f12,f14,f3,f8,f62",
            },
            timeout=10,
        )
        diff = (r.json().get("data") or {}).get("diff") or []

        # 涨跌幅/换手缺数（None 或 '-'）的板块直接丢弃，而不是兜成 0——
        # 兜 0 会让 AI prompt 里出现"今日+0%"这种伪造数值（违反诚实原则）；
        # 丢弃后该板块匹配不到，前端/prompt 显示"板块数据未匹配到"，如实。
        items = [{
            "name": d["f14"],
            "chg_pct": d["f3"],
            "turnover": d["f8"],
            "main_inflow_yi": round(d["f62"] / 1e8, 2)
            if isinstance(d.get("f62"), (int, float)) else 0.0,
        } for d in diff
            if isinstance(d.get("f3"), (int, float))
            and isinstance(d.get("f8"), (int, float))]
        return {"list": items, "by_name": {i["name"]: i for i in items}}

    # 空结果（接口降级返回 200+空 data）不进 30 分钟长缓存
    now = time.time()
    hit = _cache.get("industry")
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]
    try:
        val = fetch()
    except Exception as e:
        logger.warning("行业板块获取失败: %s", e, exc_info=True)
        return {"list": [], "by_name": {}, "error": str(e)}
    if val["list"]:
        _cache["industry"] = (now, val)
    return val


def match_industry(industry_name: str, heat: dict):
    """候选票行业名与东财板块名模糊匹配（全等 > 互相包含）."""
    if not industry_name:
        return None
    by_name = heat.get("by_name", {})
    if industry_name in by_name:
        return by_name[industry_name]
    for name, item in by_name.items():
        base = name.rstrip("ⅠⅡⅢ")
        if base and (base in industry_name or industry_name in base):
            return item
    return None


def build_macro_brief() -> str:
    """组装宏观数据包文字（给 AI 的输入，全部为实时真实数据）."""
    lines = ["### 三大指数（真实行情）"]
    for idx in get_index_overview():
        if not idx.get("available"):
            continue
        lines.append(
            f"- {idx['name']} {idx['close']}｜近5日 {idx['chg_5d']:+}%｜近20日 {idx['chg_20d']:+}%"
            f"｜距MA20 {idx['vs_ma20']:+}%｜距MA60 {idx['vs_ma60']:+}%"
            f"｜年内位置 {idx['pos_in_year']}%（0=年内最低 100=最高）"
            f"｜成交热度 {idx['vol_percentile']}分位"
        )

    # 自研板块轮动模型（主数据源，离线计算零依赖；只读缓存不触发重算）
    try:
        from utils.sector_rotation import build_sector_brief, read_cache

        sector_brief = build_sector_brief(read_cache())
        if sector_brief:
            lines.append("")
            lines.append(sector_brief)
    except Exception as e:
        logger.warning("板块轮动 brief 生成失败: %s", e)

    heat = get_industry_heat()
    if heat["list"]:
        top = heat["list"][:5]
        bottom = heat["list"][-5:]
        lines.append("")
        lines.append("### 今日行业板块（东方财富，按涨幅排序）")
        lines.append("领涨: " + "；".join(
            f"{i['name']} {i['chg_pct']:+}%（主力净流入{i['main_inflow_yi']:+}亿）" for i in top))
        lines.append("领跌: " + "；".join(
            f"{i['name']} {i['chg_pct']:+}%" for i in bottom))
    return "\n".join(lines)
