"""把 data/ 导出成网页直接读的静态 JSON：网站放在 GitHub Pages，没有后端。

    python export_static.py --out frontend/dist/d      # 发布用（见 .github/workflows/site.yml）
    python export_static.py --out frontend/public/d    # 本地开发：npm run dev 直接读

产出（--out 目录下）：
    stats.json          最新行情日、最新扫描日、股票数
    factors.json        因子清单、常用组合（带最新扫描日命中数）、有扫描结果的交易日
    hits.json           每个扫描日每个因子命中的代码：网页据此算「且/或」组合和连命中天数
    scan/{date}.json    当日每个因子的命中明细（带行业、流通市值）+ 命中股近 20 日收盘
    stock/{code}.json   个股简介 + 日 K（近 200 根）+ 周 K + 近 60 个扫描日的因子命中

只读 data/，不抓行情、不扫描；data/ 只有 updater.py 写。
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import time
from pathlib import Path

from strategy.factors import FACTOR_REGISTRY, GROUP_ORDER, PLAIN_DESC, PRESETS
from utils import scan
from utils.kline import build_kline
from utils.store import Store

logger = logging.getLogger("export")

DAILY_BARS = 200
WEEKLY_ROWS = 2000
SPARK_BARS = 20
SIGNAL_DATES = 60


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))


def _decorate(store: Store, hit: dict) -> dict:
    return {**hit, "industry": store.industries().get(hit["code"], ""), "cap_yi": store.cap_yi(hit["code"])}


def _factors(caches: dict[str, dict], dates: list[str]) -> dict:
    trade_date = dates[0] if dates else ""
    cache = caches.get(trade_date, {})

    def codes(key):
        bucket = cache.get(key)
        return None if bucket is None else {h["code"] for h in bucket.get("hits", [])}

    factors = []
    for key, meta in FACTOR_REGISTRY.items():
        doc = (meta["fn"].__doc__ or "").strip().splitlines()
        desc = doc[0].split("：", 1)[-1].strip() if doc else ""
        hits = codes(key)
        factors.append(
            {
                "key": key,
                "name": meta["name"],
                "group": meta["group"],
                "desc": desc,
                "plain": PLAIN_DESC.get(key, desc),
                "today_hits": None if hits is None else len(hits),
            }
        )
    factors.sort(key=lambda f: GROUP_ORDER.index(f["group"]) if f["group"] in GROUP_ORDER else 99)

    presets = []
    for preset in PRESETS:
        if not all(k in FACTOR_REGISTRY for k in preset["keys"]):
            continue
        sets = [codes(k) for k in preset["keys"]]
        hits = None if any(s is None for s in sets) else len(scan.compose_codes(sets, preset["join"]))
        presets.append({**preset, "today_hits": hits})

    return {
        "factors": factors,
        "presets": presets,
        "groups": GROUP_ORDER,
        "trade_date": trade_date,
        "recent_dates": dates,
    }


def export(store: Store, out: Path) -> dict:
    started = time.time()
    if out.exists():
        shutil.rmtree(out)
    dates = scan.cache_dates(store)
    caches = {d: scan.load_cache(store, d) for d in dates}
    names = store.names()
    codes = store.list_stocks()

    _write(
        out / "stats.json",
        {"latest_date": store.latest_date(), "scan_date": dates[0] if dates else None, "stock_count": len(codes)},
    )
    _write(out / "factors.json", _factors(caches, dates))
    _write(
        out / "hits.json",
        {
            "dates": dates,
            "hits": {
                d: {k: [h["code"] for h in b.get("hits", [])] for k, b in caches[d].items()} for d in dates
            },
        },
    )

    signals: dict[str, list] = {}
    for d in dates[:SIGNAL_DATES]:
        for key, bucket in caches[d].items():
            category = FACTOR_REGISTRY.get(key, {}).get("name", key)
            for h in bucket.get("hits", []):
                signals.setdefault(h["code"], []).append({"date": d, "category": category})

    hit_codes = {h["code"] for c in caches.values() for b in c.values() for h in b.get("hits", [])}
    spark: dict[str, list] = {}
    for code in codes:
        frame = store.read_stock(code, nrows=WEEKLY_ROWS)
        if frame.empty:
            continue
        if code in hit_codes:
            spark[code] = [round(float(v), 2) for v in frame["close"].head(SPARK_BARS).tolist()[::-1]]
        name = names.get(code, "未知")
        kline = {}
        for period, rows, label in (("daily", DAILY_BARS, "今日涨跌"), ("weekly", WEEKLY_ROWS, "本周涨跌")):
            kline[period] = {
                "success": True,
                "code": code,
                "name": name,
                "period": period,
                "change_label": label,
                "signals": signals.get(code, []),
                **build_kline(frame.head(rows).copy(), period),
            }
        _write(
            out / "stock" / f"{code}.json",
            {
                "profile": {
                    "code": code,
                    "name": name,
                    "industry": store.industries().get(code, ""),
                    "cap_yi": store.cap_yi(code),
                    "latest_date": str(frame["date"].iloc[0])[:10],
                },
                **kline,
            },
        )

    for d in dates:
        factors = {
            key: {"hits": [_decorate(store, h) for h in b.get("hits", [])], "total_scanned": b.get("total_scanned", 0)}
            for key, b in caches[d].items()
        }
        day_codes = {h["code"] for b in caches[d].values() for h in b.get("hits", [])}
        _write(out / "scan" / f"{d}.json", {"factors": factors, "spark": {c: spark[c] for c in day_codes if c in spark}})

    summary = {"stocks": len(codes), "scan_dates": len(dates), "seconds": round(time.time() - started)}
    logger.info("导出完成 %s → %s", summary, out)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    export(Store(), args.out)


if __name__ == "__main__":
    main()
