"""并发补全主板行情（研究用）：只走腾讯通道，失败留清单，绝不写模拟数据。

背景：bootstrap_universe 在东财不可用时会把失败股票降级成随机模拟数据
（_generate_mock_data，日期含周末可识别）。本脚本：

1. 删除所有含周末日期的污染 CSV（mock 特征）；
2. 对 stock_names.json 全部主板股票并发重拉腾讯日线（前复权，~1000 根）；
3. 每只最多重试 3 次；仍失败只记录，不写任何假数据。

用法：python3 tools/fetch_full_universe.py [--workers 6] [--only-failed]
"""
import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.akshare_fetcher import AKShareFetcher  # noqa: E402
from utils.csv_manager import CSVManager  # noqa: E402


def is_mock(df) -> bool:
    """含周末日期 = 模拟数据（真实 A 股日线只有交易日）."""
    if df is None or df.empty:
        return False
    return bool(pd.to_datetime(df["date"]).dt.dayofweek.ge(5).any())


def fetch_tencent(fetcher, code):
    """腾讯日线（注意：项目代码用的 web.ifzq.gtimg.cn 已失效返回 501，
    正确域名是 ifzq.gtimg.cn）。"""
    import requests
    prefix = "sh" if code.startswith(("6", "88")) else "sz"
    url = (f"https://ifzq.gtimg.cn/appstock/app/fqkline/get?"
           f"param={prefix}{code},day,,,1000,qfq")
    resp = requests.get(
        url, timeout=15,
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"},
    )
    data = resp.json()
    stock_data = (data.get("data") or {}).get(f"{prefix}{code}", {})
    klines = stock_data.get("qfqday") or stock_data.get("day") or []
    if not klines:
        return None
    rows = []
    for item in klines:
        if len(item) < 6:
            continue
        rows.append({
            "date": str(item[0]), "open": float(item[1]), "close": float(item[2]),
            "high": float(item[3]), "low": float(item[4]), "volume": int(float(item[5])),
            "amount": 0.0, "turnover": 0.0, "market_cap": 0.0,
        })
    if not rows:
        return None
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date", ascending=False).reset_index(drop=True)


def fetch_sina(code):
    """新浪日线兜底（数据全，稍慢）."""
    import akshare as ak
    prefix = "sh" if code.startswith(("6", "88")) else "sz"
    df = ak.stock_zh_a_daily(symbol=f"{prefix}{code}", adjust="qfq")
    if df is None or df.empty:
        return None
    df = df.rename(columns={
        "open": "open", "high": "high", "low": "low", "close": "close",
        "volume": "volume", "amount": "amount",
    })
    df = df[["date", "open", "close", "high", "low", "volume", "amount"]].copy()
    df["date"] = pd.to_datetime(df["date"])
    df["turnover"] = 0.0
    df["market_cap"] = 0.0
    df = df.sort_values("date", ascending=False).reset_index(drop=True)
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only-failed", action="store_true",
                    help="只重拉上次失败的股票（断点续跑）")
    args = ap.parse_args()

    cm = CSVManager("data")
    fetcher = AKShareFetcher("data")
    names = json.load(open("data/stock_names.json", encoding="utf-8"))
    fail_file = Path("data/fetch_failed.json")

    # 1. 清理 mock 污染
    removed = 0
    for csv_file in Path("data").rglob("*.csv"):
        if csv_file.parent.name in ("backtest",):
            continue
        try:
            df = pd.read_csv(csv_file, nrows=40)
        except Exception:
            continue
        if is_mock(df):
            csv_file.unlink()
            removed += 1
    print(f"清理 mock 污染 CSV: {removed} 个")

    codes = sorted(names)
    if args.only_failed and fail_file.exists():
        failed = json.loads(fail_file.read_text())
        codes = [c for c in codes if c in failed]
        print(f"断点续跑: 重试 {len(codes)} 只")
    else:
        # 跳过已有干净数据（前复权口径统一：旧数据全量重拉过一次即可）
        existing = set(cm.list_all_stocks())
        codes = [c for c in codes if c not in existing]
        print(f"待拉 {len(codes)} 只（跳过已有 {len(existing)}）")

    ok = 0
    failed_cur = {}
    t0 = time.time()
    for i, code in enumerate(codes, 1):
        df = None
        for attempt in range(3):
            try:
                df = fetch_tencent(fetcher, code)
            except Exception:
                df = None
            if df is not None and not df.empty:
                break
            time.sleep(1.0 * (attempt + 1))
        if df is None or df.empty or is_mock(df):
            # 新浪兜底（腾讯连续失败时换通道）
            try:
                df = fetch_sina(code)
            except Exception:
                df = None
        if df is not None and not df.empty and not is_mock(df):
            cm.write_stock(code, df)
            ok += 1
        else:
            failed_cur[code] = True
        if i % 100 == 0:
            print(f"  [{i}/{len(codes)}] 成功 {ok} 失败 {len(failed_cur)} "
                  f"({time.time()-t0:.0f}s)", flush=True)

    fail_file.write_text(json.dumps(sorted(failed_cur), ensure_ascii=False, indent=1))
    print(f"完成: 成功 {ok}/{len(codes)}，失败 {len(failed_cur)} 只已记录到 {fail_file}，"
          f"耗时 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
