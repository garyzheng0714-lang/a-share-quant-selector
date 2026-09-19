"""行情抓取：只用腾讯与新浪的公开 HTTP 接口，不依赖 akshare。

- 股票池 + 名称 + 市值：腾讯 qt.gtimg.cn 批量行情（按代码段扫描）
- 日线（前复权）：腾讯 fqkline（web.ifzq / proxy.finance / ifzq 三个入口轮询，带节流）
- 行业：新浪「新浪行业」板块及其成分
任何接口失败都返回空结果，由调用方决定保留旧数据；绝不生成假行情。
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timedelta

import pandas as pd
import requests

logger = logging.getLogger(__name__)

_UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://gu.qq.com/",
}
# 腾讯 K 线有多个入口，主域名对海外 IP 连发几百次后会被 WAF 拦成 501；逐个尝试
_KLINE_HOSTS = (
    "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
    "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get",
    "https://ifzq.gtimg.cn/appstock/app/fqkline/get",
)
# 每次 K 线请求后的节流（秒）；单线程约 4 次/秒，避免触发封禁
_THROTTLE = float(os.environ.get("QUANT_FETCH_THROTTLE", "0.25"))
_EXCLUDE = ("债", "基", "ETF", "LOF", "理财", "信托", "B股", "指数", "退")

# 沪深 A 股代码段（含科创、创业板；不含北交所）
_CODE_RANGES = (
    (600000, 609999),
    (601000, 601999),
    (603000, 603999),
    (605000, 605999),
    (688000, 689999),
    (0, 9999),
    (1000, 1999),
    (2000, 2999),
    (3000, 3999),
    (300000, 309999),
)


def _market(code: str) -> str:
    return ("sh" if code.startswith(("6", "8")) else "sz") + code


def _parse_cap(raw: str) -> float:
    """腾讯市值字段单位为亿，转成元；解析失败返回 0."""
    try:
        return float(str(raw).strip().rstrip("亿")) * 1e8
    except ValueError:
        return 0.0


def fetch_universe(sleep: float = 0.05) -> tuple[dict, dict]:
    """扫描全部代码段，返回 ({code: name}, {code: {circ_mv, total_mv}})."""
    codes = [str(n).zfill(6) for lo, hi in _CODE_RANGES for n in range(lo, hi + 1)]
    names: dict[str, str] = {}
    caps: dict[str, dict] = {}
    for i in range(0, len(codes), 100):
        batch = ",".join(_market(c) for c in codes[i : i + 100])
        try:
            resp = requests.get(f"https://qt.gtimg.cn/q={batch}", headers=_UA, timeout=30)
            resp.raise_for_status()
        except Exception as exc:
            logger.warning("腾讯行情批次 %d 失败: %s", i, exc)
            continue
        for line in resp.text.split(";"):
            if "v_" not in line or "~" not in line:
                continue
            parts = line.split("~")
            if len(parts) < 46:
                continue
            code = line.split("v_", 1)[1].split("=", 1)[0][2:]
            name = parts[1].strip()
            if not name or any(k in name for k in _EXCLUDE):
                continue
            names[code] = name
            circ, total = _parse_cap(parts[44]), _parse_cap(parts[45])
            if total > 0:
                caps[code] = {"circ_mv": circ or total, "total_mv": total}
        time.sleep(sleep)
    return names, caps


def _kline_get(param: str) -> object:
    """按入口顺序请求；返回 JSON，全部失败抛出最后一个异常."""
    last: Exception = RuntimeError("no_kline_host")
    for base in _KLINE_HOSTS:
        try:
            resp = requests.get(f"{base}?param={param}", headers=_UA, timeout=15)
            if resp.status_code != 200:
                raise RuntimeError(f"http_{resp.status_code}")
            return resp.json()
        except Exception as exc:
            last = exc
        finally:
            time.sleep(_THROTTLE)
    raise last


def _parse_klines(payload: object, market_code: str) -> list:
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    if isinstance(data, dict):
        stock = data.get(market_code, {})
        if isinstance(stock, dict):
            return stock.get("qfqday") or stock.get("day") or []
    return []


def _records(klines: list) -> pd.DataFrame:
    rows = [
        {
            "date": str(k[0]),
            "open": float(k[1]),
            "close": float(k[2]),
            "high": float(k[3]),
            "low": float(k[4]),
            "volume": int(float(k[5])),
        }
        for k in klines
        if isinstance(k, list) and len(k) >= 6
    ]
    df = pd.DataFrame(rows)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


def fetch_recent(code: str, days: int = 12) -> pd.DataFrame:
    """最近 N 个交易日的前复权日线（增量更新用）。失败返回空表."""
    market_code = _market(code)
    try:
        payload = _kline_get(f"{market_code},day,,,{min(days, 1000)},qfq")
        return _records(_parse_klines(payload, market_code))
    except Exception as exc:
        logger.debug("增量抓取 %s 失败: %s", code, exc)
        return pd.DataFrame()


def fetch_history(code: str, years: int = 3) -> pd.DataFrame:
    """分页抓取 N 年前复权日线（首次入库用）。窗口不完整返回空表."""
    market_code = _market(code)
    start = (datetime.now() - timedelta(days=365 * years)).strftime("%Y-%m-%d")
    page_size = 640
    cursor = ""
    frames: list[pd.DataFrame] = []
    for _ in range(years * 252 // page_size + 2):
        try:
            payload = _kline_get(f"{market_code},day,,{cursor},{page_size},qfq")
            page = _records(_parse_klines(payload, market_code))
        except Exception as exc:
            logger.debug("历史抓取 %s 失败: %s", code, exc)
            return pd.DataFrame()
        if page.empty:
            break
        frames.append(page)
        earliest = page["date"].min()
        if earliest <= pd.Timestamp(start) or len(page) < page_size:
            break
        cursor = (earliest - timedelta(days=1)).strftime("%Y-%m-%d")
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True).drop_duplicates("date")
    return df[df["date"] >= pd.Timestamp(start)].sort_values("date", ascending=False)


def fetch_industries(sleep: float = 0.05) -> dict:
    """新浪行业板块 → {code: 行业}。失败返回空 dict."""
    headers = {**_UA, "Referer": "https://finance.sina.com.cn/"}
    try:
        resp = requests.get(
            "http://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php",
            headers=headers,
            timeout=20,
        )
        resp.encoding = "gbk"
        match = re.search(r"=\s*(\{.*\})\s*;?\s*$", resp.text, re.S)
        sectors = json.loads(match.group(1)) if match else {}
    except Exception as exc:
        logger.warning("新浪行业列表失败: %s", exc)
        return {}
    mapping: dict[str, str] = {}
    for node, info in sectors.items():
        industry = str(info).split(",")[1] if "," in str(info) else ""
        if not industry:
            continue
        for page in range(1, 20):
            url = (
                "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
                f"Market_Center.getHQNodeData?page={page}&num=100&sort=symbol&asc=1&node={node}"
            )
            try:
                rows = requests.get(url, headers=headers, timeout=20).json() or []
            except Exception:
                break
            if not rows:
                break
            for row in rows:
                code = str(row.get("code", "")).zfill(6)
                if code.isdigit():
                    mapping[code] = industry
            if len(rows) < 100:
                break
            time.sleep(sleep)
    return mapping
