"""午盘盘中信号回测——「11:30 出信号、13:00 开盘买入」到底靠不靠谱？

背景（用户 2026-08-04）：希望每天拉 2 次数据，午盘休盘时用上午数据选票，
午盘开盘（13:00）买入。但云阶的历史战绩（T+5 样本外 49.3%/+1.11%）全部是
「收盘确认」口径；盘中确认的胜率从未验证过。按项目规矩：先过样本外这关再上线。

数据：腾讯 60 分钟线（tools/fetch_min60.py 拉取，2025-10 起，800 根/只）重建
「11:30 时点」的盘中状态：
- 盘中 K 线（T 日）：O=上午首根开盘，H/L=上午两根最高/最低，C=11:30 价，V=上午累计量
- 买入价：13:00 开盘 = 下午首根（1400）的开盘价
- 卖出价：T+5 日线收盘

信号判据与线上完全同源（compute_cloud_stair），只把「今日 K 线」换成盘中 K 线。
对照：同股票池重扫收盘版（T+1 开盘买入）——盘中版 vs 收盘版胜率差异即答案。

用法：python3 tools/intraday_backtest.py [--sample N] [--workers N]
"""
import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from strategy.factor_lib import FactorContext                      # noqa: E402
from strategy.factors.momentum_family import compute_cloud_stair   # noqa: E402
from utils.csv_manager import CSVManager                           # noqa: E402

HOLD = 5
IN_LO, IN_HI = "2026-03-13", "2026-06-10"
OOS_LO, OOS_HI = "2025-12-10", "2026-03-13"
MIN60_DIR = Path("data/min60")


def _load_min60(code: str) -> pd.DataFrame:
    """60 分钟线 → {date: {o, c, h, l, v, open1300}}（date 为 YYYY-MM-DD）."""
    f = MIN60_DIR / f"{code}.csv"
    if not f.exists():
        return None
    df = pd.read_csv(f)
    if df.empty:
        return None
    df["day"] = df["dt"].astype(str).str[:8]
    df["time"] = df["dt"].astype(str).str[8:]
    out = {}
    for day, g in df.groupby("day"):
        g = g.sort_values("time")
        am = g[g["time"] <= "1130"]
        if len(am) < 2:
            continue
        pm = g[g["time"] == "1400"]
        rec = {
            "o": float(am["open"].iloc[0]),
            "c": float(am["close"].iloc[-1]),
            "h": float(am["high"].max()),
            "l": float(am["low"].min()),
            "v": float(am["volume"].sum()),
            "open1300": float(pm["open"].iloc[0]) if not pm.empty else None,
        }
        out[f"{day[:4]}-{day[4:6]}-{day[6:]}"] = rec
    return out


def _scan_one(args):
    """单只股票：盘中版 + 收盘版双口径扫描."""
    cm, code, lo, hi = args
    try:
        df = cm.read_stock(code)
        if df is None or df.empty or len(df) < 200:
            return []
        if len(df) > 1 and str(df["date"].iloc[0]) > str(df["date"].iloc[-1]):
            df = df.iloc[::-1].reset_index(drop=True)
        m60 = _load_min60(code)
        dates = df["date"].astype(str).str[:10].to_numpy()
        closes = df["close"].astype(float).to_numpy()
        opens = df["open"].astype(float).to_numpy()
        n = len(dates)
        out = []
        for i in range(180, n - 1):
            d = dates[i]
            if d < lo or d > hi:
                continue
            # 盘中口径：只测分钟线覆盖的交易日
            rec60 = m60.get(d) if m60 is not None else None
            if rec60 is not None and rec60.get("open1300"):
                sub = df.iloc[:i].copy()
                sub = pd.concat([
                    sub,
                    pd.DataFrame([{
                        "date": pd.Timestamp(d), "open": rec60["o"], "close": rec60["c"],
                        "high": rec60["h"], "low": rec60["l"], "volume": rec60["v"],
                        "amount": 0.0, "turnover": 0.0, "market_cap": 0.0,
                    }]),
                ], ignore_index=True)
                try:
                    if compute_cloud_stair(FactorContext(sub)):
                        j = i + HOLD
                        if j < n and closes[j] > 0:
                            ret = round(float((closes[j] - rec60["open1300"]) / rec60["open1300"] * 100), 2)
                            out.append({"code": code, "date": d, "ret": ret, "kind": "intraday"})
                except Exception:
                    pass
            # 收盘口径：同日对比基准（T+1 开盘买入）
            sub = df.iloc[: i + 1]
            try:
                if compute_cloud_stair(FactorContext(sub)):
                    j = i + HOLD
                    if j < n and opens[i + 1] > 0:
                        ret = round(float((closes[j] - opens[i + 1]) / opens[i + 1] * 100), 2)
                        out.append({"code": code, "date": d, "ret": ret, "kind": "close"})
            except Exception:
                pass
        return out
    except Exception:
        return []


def _stats(records):
    if not records:
        return None
    rets = [r["ret"] for r in records]
    return {
        "n": len(rets),
        "win": round(sum(1 for v in rets if v > 0) / len(rets) * 100, 1),
        "avg": round(float(np.mean(rets)), 2),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--workers", type=int, default=0)
    args = ap.parse_args()
    import os
    workers = args.workers or max(1, (os.cpu_count() or 4) - 1)

    cm = CSVManager("data")
    names = json.load(open("data/stock_names.json", encoding="utf-8"))
    codes = sorted(set(names) & {f.stem for f in MIN60_DIR.glob("*.csv")})
    if args.sample:
        rng = np.random.default_rng(42)
        codes = sorted(rng.choice(codes, size=min(args.sample, len(codes)), replace=False))
    print(f"股票池: {len(codes)} 只（有分钟线）")

    tasks = [(cm, c, OOS_LO, OOS_HI) for c in codes]
    tasks += [(cm, c, IN_LO, IN_HI) for c in codes]
    all_records = []
    done = 0
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for res in ex.map(_scan_one, tasks, chunksize=20):
            all_records.extend(res)
            done += 1
            if done % 800 == 0:
                print(f"  [{done}/{len(tasks)}] 信号 {len(all_records)} 条 ({time.time()-t0:.0f}s)", flush=True)

    for label, lo, hi in (("样本外", OOS_LO, OOS_HI), ("样本内", IN_LO, IN_HI)):
        in_w = [r for r in all_records if lo <= r["date"] <= hi]
        intra = _stats([r for r in in_w if r["kind"] == "intraday"])
        close = _stats([r for r in in_w if r["kind"] == "close"])
        print(f"\n=== {label}（{lo} ~ {hi}）===")
        print(f"收盘版（T+1开盘买）: {close}")
        print(f"盘中版（13:00开盘买）: {intra}")
        if intra and close:
            print(f"盘中/收盘 信号数: {intra['n']}/{close['n']} | "
                  f"胜率差: {intra['win']-close['win']:+.1f}pp | 均值差: {intra['avg']-close['avg']:+.2f}pp")


if __name__ == "__main__":
    main()
