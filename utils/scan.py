"""全市场因子扫描：每只股票读一次 CSV，所有因子共用一个 FactorContext。

结果写到 data/factor_cache/{date}.json：
    {key: {"hits": [{code, name, date, close, pct_change, J, RSI, ...}], "total_scanned": n}}
只保留最近 MAX_CACHE_FILES 个交易日，供「连续命中天数」回溯。
"""

from __future__ import annotations

import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from utils.store import Store

logger = logging.getLogger(__name__)

MAX_CACHE_FILES = 40
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _tradable(name: str) -> bool:
    """ST、*ST、退市股不进选股池."""
    return not (name.startswith(("ST", "*ST")) or "退" in name)


def cache_dir(store: Store) -> Path:
    return store.data_dir / "factor_cache"


def cache_dates(store: Store) -> list[str]:
    """已有缓存的交易日（新→旧）."""
    return sorted(
        (p.stem for p in cache_dir(store).glob("*.json") if _DATE_RE.match(p.stem)),
        reverse=True,
    )


def load_cache(store: Store, date: str) -> dict:
    if not _DATE_RE.match(date or ""):
        return {}
    path = cache_dir(store) / f"{date}.json"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_cache(store: Store, date: str, results: dict) -> None:
    directory = cache_dir(store)
    directory.mkdir(parents=True, exist_ok=True)
    tmp = directory / f"{date}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False)
    tmp.replace(directory / f"{date}.json")
    for old in cache_dates(store)[MAX_CACHE_FILES:]:
        (directory / f"{old}.json").unlink(missing_ok=True)


def _scan_one(store: Store, code: str, name: str, target: str, registry: dict):
    """返回 {key: hit}；该股当日无 K 线返回 None."""
    from strategy.factor_lib import FactorContext

    try:
        df = store.read_stock(code)
    except Exception as exc:
        logger.warning("读取 %s 失败: %s", code, exc)
        return None
    if df.empty or len(df) < 30:
        return None
    df = df.iloc[::-1].reset_index(drop=True)
    dates = df["date"].astype(str).str[:10]
    if target:
        mask = dates <= target
        if not mask.any():
            return None
        df = df[mask].reset_index(drop=True)
        dates = dates[mask].reset_index(drop=True)
    last_date = dates.iloc[-1]
    if target and last_date != target:
        return None
    ctx = FactorContext(df)
    out = {}
    for key, meta in registry.items():
        if len(df) < meta["min_bars"]:
            continue
        try:
            hit = meta["fn"](ctx)
        except Exception as exc:
            logger.warning("因子 %s 计算 %s 失败: %s", key, code, exc)
            continue
        if hit:
            hit.update(code=code, name=name, date=last_date)
            out[key] = hit
    return out


def scan(store: Store, date: str = "", workers: int | None = None) -> dict:
    """扫描全部因子并写缓存。返回 {available, trade_date, results, reason?}."""
    from strategy.factors import FACTOR_REGISTRY

    trade_date = date or store.latest_date()
    if not trade_date:
        return {"available": False, "reason": "本地无行情数据"}
    names = store.names()
    codes = [c for c in store.list_stocks() if _tradable(names.get(c, ""))]
    workers = workers or int(os.environ.get("QUANT_SCAN_WORKERS", "2"))
    buckets: dict[str, list] = {k: [] for k in FACTOR_REGISTRY}
    valid = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for hits in pool.map(
            lambda c: _scan_one(
                store, c, names.get(c, ""), trade_date, FACTOR_REGISTRY
            ),
            codes,
        ):
            if hits is None:
                continue
            valid += 1
            for key, hit in hits.items():
                buckets[key].append(hit)
    if valid == 0:
        return {"available": False, "reason": f"{trade_date} 无有效行情数据"}
    results = {}
    for key, hits in buckets.items():
        hits.sort(
            key=lambda h: (h.get("J") if h.get("J") is not None else 999, h["code"])
        )
        results[key] = {"hits": hits, "total_scanned": len(codes)}
    _save_cache(store, trade_date, results)
    logger.info(
        "因子扫描完成 %s：%d 只，命中 %s",
        trade_date,
        valid,
        {k: len(v["hits"]) for k, v in results.items()},
    )
    return {"available": True, "trade_date": trade_date, "results": results}


def compose_codes(sets: list[set], join: str) -> set:
    """and=交集，or=并集."""
    if not sets:
        return set()
    out = set(sets[0])
    for s in sets[1:]:
        out = out & set(s) if join == "and" else out | set(s)
    return out
