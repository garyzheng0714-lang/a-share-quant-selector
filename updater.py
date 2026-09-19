"""盘后更新：抓日线 → 刷新股票池/市值/行业 → 全因子扫描。

    python updater.py              # 立即跑一轮
    python updater.py --init       # 首次入库（按 --years 抓历史，默认 3 年）
    python updater.py --scan-only  # 不抓行情，只用本地数据扫描
    python updater.py --loop       # 常驻：工作日 15:35（Asia/Shanghai）跑一轮；启动时若落后也补一轮

只有一个进程在写数据；Web 服务只读。行情源失败就保留旧数据并如实记录，不造数。
"""

from __future__ import annotations

import argparse
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo

from utils import fetch, scan
from utils.store import Store

logger = logging.getLogger("updater")
TZ = ZoneInfo("Asia/Shanghai")


def refresh_universe(store: Store) -> int:
    names, caps = fetch.fetch_universe()
    if len(names) < 3000:
        logger.warning("股票池抓取只得到 %d 只，保留旧数据", len(names))
        return 0
    store.save_json("stock_names.json", names)
    if caps:
        store.save_json("stock_market_cap.json", caps)
    logger.info("股票池 %d 只，市值 %d 只", len(names), len(caps))
    return len(names)


def refresh_industries(store: Store, max_age_days: float = 7) -> None:
    if store.json_age_days("stock_industry.json") < max_age_days:
        return
    mapping = fetch.fetch_industries()
    if len(mapping) < 1000:
        logger.warning("行业映射只得到 %d 条，保留旧数据", len(mapping))
        return
    store.save_json("stock_industry.json", mapping)
    logger.info("行业映射 %d 条", len(mapping))


def update_bars(store: Store, codes: list[str], *, init: bool, years: int, workers: int) -> dict:
    """增量（或首次全量）更新日线；返回 {updated, failed, skipped}."""
    stats = {"updated": 0, "failed": 0, "skipped": 0}

    def one(code: str) -> str:
        if init or store.read_stock(code, nrows=1).empty:
            df = fetch.fetch_history(code, years=years)
            if df.empty:
                return "failed"
            store.write_stock(code, df)
            return "updated"
        df = fetch.fetch_recent(code, days=12)
        if df.empty:
            return "failed"
        store.update_stock(code, df)
        return "updated"

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, result in enumerate(pool.map(one, codes), 1):
            stats[result] += 1
            if i % 500 == 0:
                logger.info("日线进度 %d/%d %s", i, len(codes), stats)
    logger.info("日线更新完成 %s", stats)
    return stats


def run_once(store: Store, *, init: bool = False, years: int = 3, scan_only: bool = False) -> dict:
    started = time.time()
    if not scan_only:
        refresh_universe(store)
        refresh_industries(store)
        codes = sorted(store.names()) if store.names() else store.list_stocks()
        workers = int(os.environ.get("QUANT_FETCH_WORKERS", "4"))
        update_bars(store, codes, init=init, years=years, workers=workers)
    result = scan.scan(store)
    logger.info(
        "本轮完成，耗时 %.0fs：%s",
        time.time() - started,
        result.get("trade_date") or result.get("reason"),
    )
    return result


def loop(store: Store, run_at: str) -> None:
    hour, minute = (int(x) for x in run_at.split(":"))
    done_for = ""
    latest_scan = (scan.cache_dates(store) or [""])[0]
    while True:
        now = datetime.now(TZ)
        today = now.strftime("%Y-%m-%d")
        due = now.weekday() < 5 and (now.hour, now.minute) >= (hour, minute)
        stale_at_start = not latest_scan or latest_scan < store.latest_date()
        if (due and done_for != today) or stale_at_start:
            try:
                result = run_once(store)
                latest_scan = result.get("trade_date") or latest_scan
            except Exception as exc:  # 单轮失败不退出常驻进程
                logger.exception("本轮更新失败: %s", exc)
            done_for = today
        time.sleep(60)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--init", action="store_true", help="首次全量抓历史")
    parser.add_argument("--years", type=int, default=3)
    parser.add_argument("--scan-only", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--run-at", default=os.environ.get("QUANT_RUN_AT", "15:35"))
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    store = Store()
    if args.loop:
        loop(store, args.run_at)
    else:
        run_once(store, init=args.init, years=args.years, scan_only=args.scan_only)


if __name__ == "__main__":
    main()
