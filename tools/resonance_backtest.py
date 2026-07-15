"""共振假设回测 - 验证"一只票同时命中多个策略因子 → 胜率更高"是否成立

用户 2026-07-13 提出该假设。这是假设不是事实，必须用真实历史数据验证后再决定
要不要把它做成产品功能——否则就是又造一个"看起来聪明但历史证明没用"的榜。

关键陷阱（必须在统计里区分）：
28 个因子里大量同源——超卖B1/白线B1/黄线B1/金叉踩黄/娜娜图/SuperB1/TePu 的内核
都包含同一套"少妇策略"（价格稳定+BBI上升+KDJ超卖+DIF>0）。它们同时命中是数学上的
必然，不是独立证据。所以本回测同时给出两种口径：
  - n_factors：总命中因子数（用户直觉口径）
  - n_families：独立逻辑家族数（去掉同源重复后的"真共振"口径）

收益口径与现有战绩完全一致：信号日 T 收盘出信号 → T+1 开盘价买入 →
ret_n = (T+n 收盘 - T+1 开盘) / T+1 开盘 * 100。

用法（生产容器内）：
    python tools/resonance_backtest.py --days 60 --out data/resonance_backtest.json
"""
import argparse
import json
import logging
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from strategy.factor_lib import FactorContext  # noqa: E402
from strategy.factors import FACTOR_REGISTRY  # noqa: E402
from utils.csv_manager import CSVManager  # noqa: E402

logging.basicConfig(level=logging.WARNING)

# 独立逻辑家族划分：同一家族内的因子共享核心判据，同时命中≈重复计数
# （依据各因子实现里实际调用的积木，不是按展示分组分的）
FAMILY_OF = {
    # 少妇系：内核都含 adaptive_trend_selector（价格稳定+BBI+KDJ超卖+DIF>0）
    "oversold_b1": "少妇系", "kdj_cross": "少妇系", "tepu": "少妇系",
    "super_b1_factor": "少妇系", "zx_white_b1": "少妇系", "zx_yellow_b1": "少妇系",
    "cross_step_yellow": "少妇系", "nana_chart": "少妇系",
    # 超卖系：只吃 KDJ 超卖/BBI，不含完整少妇四件套
    "fill_pit": "超卖系", "ticket_refill": "超卖系", "needle_down30": "超卖系",
    # 知行结构系：白线/黄线/砖型结构
    "new_b2": "知行结构", "zx_brick": "知行结构", "brick_b1": "知行结构",
    "zx_pullback_brick": "知行结构", "double_line": "知行结构",
    # 动量系：均线/EMA/共振类
    "angel_devil": "动量", "six_veins": "动量", "wave_band": "动量",
    "ma520": "动量", "trend_strengthen": "动量",
    # 底部反转系
    "bottom_violent_k": "底部反转", "cloud_stair": "底部反转",
    # 三度系：量时空结构
    "sandu_a_zone": "三度", "sandu_b_zone": "三度", "sandu_washout": "三度",
    "sandu_neckline": "三度", "sandu_star": "三度",
}

WINDOWS = (1, 5, 10, 20)


def _one_stock(args):
    """单只股票：对每个信号日截断计算28因子，关联后续收益.

    返回 [{date, code, factors: [...], ret_1/5/10/20, max_dd}]
    """
    csv_manager, code, name, signal_dates = args
    try:
        df = csv_manager.read_stock(code)
        if df is None or df.empty or len(df) < 200:
            return []
        if len(df) > 1 and str(df["date"].iloc[0]) > str(df["date"].iloc[-1]):
            df = df.iloc[::-1].reset_index(drop=True)
        dates = df["date"].astype(str).str[:10].to_numpy()
        opens = df["open"].astype(float).to_numpy()
        closes = df["close"].astype(float).to_numpy()

        pos = {d: i for i, d in enumerate(dates)}
        out = []
        for sd in signal_dates:
            i = pos.get(sd)
            if i is None or i < 180:
                continue
            # 必须有 T+1 开盘价才能模拟买入
            if i + 1 >= len(dates):
                continue
            buy = opens[i + 1]
            if not (buy > 0):
                continue

            sub = df.iloc[: i + 1]
            ctx = FactorContext(sub)
            fired = []
            for key, meta in FACTOR_REGISTRY.items():
                if len(sub) < meta["min_bars"]:
                    continue
                try:
                    if meta["fn"](ctx):
                        fired.append(key)
                except Exception:
                    continue
            if not fired:
                continue

            rec = {"date": sd, "code": code, "name": name, "factors": fired}
            for w in WINDOWS:
                j = i + w
                rec[f"ret_{w}"] = (
                    round(float((closes[j] - buy) / buy * 100), 2)
                    if j < len(closes) else None
                )
            # 最大回撤（T+1..T+20 相对买入价）
            end = min(i + 20, len(closes) - 1)
            if end > i:
                seg = closes[i + 1: end + 1]
                rec["max_dd"] = round(float((seg.min() - buy) / buy * 100), 2)
            else:
                rec["max_dd"] = None
            out.append(rec)
        return out
    except Exception:
        return []


def _agg(records, key_fn, label):
    """按分桶键聚合胜率/均值/回撤."""
    buckets = defaultdict(list)
    for r in records:
        buckets[key_fn(r)].append(r)
    rows = []
    for k in sorted(buckets):
        rs = buckets[k]
        row = {"bucket": k, "n_signals": len(rs)}
        for w in WINDOWS:
            vals = [r[f"ret_{w}"] for r in rs if r.get(f"ret_{w}") is not None]
            if vals:
                row[f"win_{w}"] = round(sum(1 for v in vals if v > 0) / len(vals) * 100, 1)
                row[f"avg_{w}"] = round(float(np.mean(vals)), 2)
                row[f"n_{w}"] = len(vals)
            else:
                row[f"win_{w}"] = None
                row[f"avg_{w}"] = None
                row[f"n_{w}"] = 0
        dds = [r["max_dd"] for r in rs if r.get("max_dd") is not None]
        row["avg_dd"] = round(float(np.mean(dds)), 2) if dds else None
        rows.append(row)
    return {"label": label, "rows": rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=60, help="回测信号日数量")
    ap.add_argument("--skip", type=int, default=21, help="跳过最近N日（留T+20回填空间）")
    ap.add_argument("--limit", type=int, default=0, help="只跑前N只股票（调试用）")
    ap.add_argument("--sample", type=int, default=0,
                    help="随机抽N只（固定种子，无偏；服务器2核跑全量要5小时）")
    ap.add_argument("--out", default="data/resonance_backtest.json")
    args = ap.parse_args()

    cm = CSVManager("data")
    names = json.load(open("data/stock_names.json", encoding="utf-8"))

    # 交易日历：用锚点股（取并集后排序）
    cal = set()
    for anchor in ("000001", "600030", "600036", "600519"):
        try:
            d = cm.read_stock(anchor, nrows=200)
            cal.update(d["date"].astype(str).str[:10].tolist())
        except Exception:
            continue
    cal = sorted(cal, reverse=True)
    # 跳过最近 skip 天（这些信号还没有完整 T+20），再取 days 天
    signal_dates = cal[args.skip: args.skip + args.days]
    print(f"信号日区间: {signal_dates[-1]} ~ {signal_dates[0]}（{len(signal_dates)}天）")

    codes = [c for c in cm.list_all_stocks() if c.isdigit() and len(c) == 6]
    invalid_kw = ("退", "未知", "退市", "已退")
    tasks = []
    for code in codes:
        nm = names.get(code, "")
        if any(k in nm for k in invalid_kw) or nm.startswith(("ST", "*ST")):
            continue
        tasks.append((cm, code, nm, signal_dates))
    if args.sample and args.sample < len(tasks):
        rng = np.random.default_rng(42)      # 固定种子：可复现
        idx = rng.choice(len(tasks), size=args.sample, replace=False)
        tasks = [tasks[i] for i in sorted(idx)]
    if args.limit:
        tasks = tasks[: args.limit]
    print(f"股票数: {len(tasks)}，预计 {len(tasks) * len(signal_dates) * 8 / 1000 / 60 / 8:.0f} 分钟")

    t0 = time.time()
    records = []
    done = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        for res in ex.map(_one_stock, tasks):
            records.extend(res)
            done += 1
            if done % 500 == 0:
                print(f"  [{done}/{len(tasks)}] 信号 {len(records)} 条 "
                      f"({time.time() - t0:.0f}s)", flush=True)

    print(f"\n扫描完成: {len(records)} 条信号，{time.time() - t0:.0f}s")
    if not records:
        print("无信号，退出")
        return

    for r in records:
        r["n_factors"] = len(r["factors"])
        r["n_families"] = len({FAMILY_OF.get(f, f) for f in r["factors"]})

    def bucket_n(v):
        return "1" if v == 1 else "2" if v == 2 else "3" if v == 3 else \
               "4-5" if v <= 5 else "6+"

    result = {
        "signal_dates": [signal_dates[-1], signal_dates[0]],
        "n_stocks": len(tasks),
        "n_signals": len(records),
        "by_n_factors": _agg(records, lambda r: bucket_n(r["n_factors"]),
                             "按命中因子总数（含同源重复）"),
        "by_n_families": _agg(records, lambda r: bucket_n(r["n_families"]),
                              "按独立逻辑家族数（真共振口径）"),
        "by_single_factor": _agg(
            [r for r in records if r["n_factors"] == 1],
            lambda r: r["factors"][0], "单因子命中时各因子的独立战绩"),
        "baseline": _agg(records, lambda _: "全体信号", "全体基准"),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({**result, "records": records}, f, ensure_ascii=False)

    # 控制台摘要
    for section in ("baseline", "by_n_factors", "by_n_families"):
        s = result[section]
        print(f"\n=== {s['label']} ===")
        print(f"{'档位':<8}{'样本':>7}{'T+1胜率':>9}{'T+1均值':>9}"
              f"{'T+5胜率':>9}{'T+5均值':>9}{'T+20胜率':>10}{'T+20均值':>10}{'均回撤':>8}")
        for row in s["rows"]:
            print(f"{row['bucket']:<8}{row['n_signals']:>7}"
                  f"{str(row['win_1']):>9}{str(row['avg_1']):>9}"
                  f"{str(row['win_5']):>9}{str(row['avg_5']):>9}"
                  f"{str(row['win_20']):>10}{str(row['avg_20']):>10}"
                  f"{str(row['avg_dd']):>8}")
    print(f"\n结果已写入 {args.out}")


if __name__ == "__main__":
    main()
