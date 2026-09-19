"""全市场 60 分钟线拉取（午盘回测用）——腾讯 mkline 接口，一次 800 根（约 200 交易日）.

存 data/min60/{code}.csv，列：dt, open, close, high, low, volume。
串行 + 3 线程并发（腾讯对并发敏感，宁慢勿被限流）。
"""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OUT_DIR = Path("data/min60")
OUT_DIR.mkdir(parents=True, exist_ok=True)
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"}


def fetch_one(code):
    prefix = "sh" if code.startswith(("6", "88")) else "sz"
    url = f"https://ifzq.gtimg.cn/appstock/app/kline/mkline?param={prefix}{code},m60,,800"
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=15, headers=HEADERS)
            k = (r.json().get("data") or {}).get(f"{prefix}{code}", {}).get("m60") or []
            if len(k) < 100:
                time.sleep(1.0 * (attempt + 1))
                continue
            rows = [{
                "dt": x[0], "open": float(x[1]), "close": float(x[2]),
                "high": float(x[3]), "low": float(x[4]), "volume": int(float(x[5])),
            } for x in k if len(x) >= 6]
            df = pd.DataFrame(rows)
            df.to_csv(OUT_DIR / f"{code}.csv", index=False)
            return code, True
        except Exception:
            time.sleep(1.0 * (attempt + 1))
    return code, False


def main():
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    names = json.load(open("data/stock_names.json", encoding="utf-8"))
    codes = sorted(names)
    existing = {f.stem for f in OUT_DIR.glob("*.csv")}
    todo = [c for c in codes if c not in existing]
    print(f"待拉 {len(todo)} 只（已有 {len(existing)}）", flush=True)
    ok = failed = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fetch_one, c): c for c in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            code, success = fut.result()
            if success:
                ok += 1
            else:
                failed += 1
            if i % 200 == 0:
                print(f"  [{i}/{len(todo)}] 成功 {ok} 失败 {failed} ({time.time()-t0:.0f}s)", flush=True)
    print(f"完成: 成功 {ok} 失败 {failed}，总耗时 {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
