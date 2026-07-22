"""旧「明天盯着」回测（仅供历史复现，不是发布证据）。

背景：主页把「明天盯着」摆在核心位置（大涨后横盘蓄势完成，只差最后一根突破K线，
收盘站上突破线那天就是买点），但这个规则**从来没被回测过**——云阶本身验过，
"云阶的预备状态"没验过。规矩是自己定的：凡是要上线的规则，必须先过样本外这关。

要回答三个问题：
1. **突破率**：进了预备队之后，未来 N 天内真的突破的比例是多少？
   如果只有 10%，那"天天盯"就是 90% 的时间在白盯——功能该砍。
2. **等突破买 vs 抢跑买**：
   - 等突破（现在主页教的做法）：突破日次日开盘买
   - 抢跑（预备日就买）：预备日次日开盘买，不等突破确认
   哪个收益高？如果抢跑更好，"明天盯着"就该改成"今天就买"。
3. **突破了到底赚不赚**：突破后买入的收益，和基准比有没有超额？

方法与同目录 `resonance_backtest.py` 一致：T+1 开盘买入、持有 N 天收盘卖出，
样本内 / 样本外两段互不重叠的历史都要过，只在一段有效 = 过拟合噪音。

该脚本使用旧的收盘退出口径，不符合当前 `a-share-eod-open-open-v3`，
因此已从生产 tools 移出。
"""

import argparse
import json
import random
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from strategy.factor_lib import FactorContext  # noqa: E402
from strategy.factors.momentum_family import compute_cloud_stair  # noqa: E402
from research.legacy.isolation import legacy_path  # noqa: E402
from utils.csv_manager import CSVManager  # noqa: E402
from utils.quant_pick import _cloud_stair_pending  # noqa: E402

HOLD_WINDOWS = (1, 5, 10)
MAX_WAIT_DAYS = 10  # 进预备队后最多盯 10 个交易日，还不突破就算作废


def _one_stock(args):
    """单只股票：找出所有"预备日"，追踪它后来突破了没、买了赚不赚.

    返回 [{date, code, gap_pct, broke_out, wait_days, chase_ret_N, breakout_ret_N}]
    """
    csv_manager, code, name, date_range = args
    lo, hi = date_range
    try:
        df = csv_manager.read_stock(code)
        if df is None or df.empty or len(df) < 200:
            return []
        if len(df) > 1 and str(df["date"].iloc[0]) > str(df["date"].iloc[-1]):
            df = df.iloc[::-1].reset_index(drop=True)

        dates = df["date"].astype(str).str[:10].to_numpy()
        opens = df["open"].astype(float).to_numpy()
        closes = df["close"].astype(float).to_numpy()
        n = len(dates)

        out = []
        for i in range(180, n - 1):
            d = dates[i]
            if d < lo or d > hi:
                continue

            sub = df.iloc[: i + 1]
            ctx = FactorContext(sub)
            try:
                pend = _cloud_stair_pending(ctx)
            except Exception:
                continue
            if not pend:
                continue

            # 抢跑买入：预备日的次日开盘（不等突破确认）
            chase_buy = opens[i + 1]
            if not (chase_buy > 0):
                continue

            rec = {
                "date": d,
                "code": code,
                "name": name,
                "gap_pct": pend.get("gap_pct"),
                "broke_out": False,
                "wait_days": None,
            }
            for w in HOLD_WINDOWS:
                j = i + w
                rec[f"chase_ret_{w}"] = (
                    round(float((closes[j] - chase_buy) / chase_buy * 100), 2)
                    if j < n
                    else None
                )

            # 往后最多盯 MAX_WAIT_DAYS 天，看云阶信号（突破确认）有没有真的出现。
            # 用 compute_cloud_stair 而不是"close >= target"手算：必须和线上
            # 真正推票的那套判据完全同源，否则测的是另一个东西。
            for k in range(1, MAX_WAIT_DAYS + 1):
                bi = i + k
                if bi >= n - 1:
                    break
                bsub = df.iloc[: bi + 1]
                try:
                    if not compute_cloud_stair(FactorContext(bsub)):
                        continue
                except Exception:
                    continue

                # 突破确认 → 次日开盘买入
                b_buy = opens[bi + 1]
                if not (b_buy > 0):
                    break
                rec["broke_out"] = True
                rec["wait_days"] = k
                for w in HOLD_WINDOWS:
                    j = bi + w
                    rec[f"breakout_ret_{w}"] = (
                        round(float((closes[j] - b_buy) / b_buy * 100), 2)
                        if j < n
                        else None
                    )
                break

            out.append(rec)
        return out
    except Exception:
        return []


def _stats(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    win = sum(1 for v in vals if v > 0) / len(vals) * 100
    return {
        "n": len(vals),
        "win": round(win, 1),
        "avg": round(sum(vals) / len(vals), 2),
    }


def _summarize(records, label):
    total = len(records)
    if total == 0:
        return {"label": label, "n_signals": 0}

    broke = [r for r in records if r["broke_out"]]
    waits = [r["wait_days"] for r in broke if r["wait_days"]]

    res = {
        "label": label,
        "n_signals": total,
        "breakout_rate": round(len(broke) / total * 100, 1),
        "avg_wait_days": round(sum(waits) / len(waits), 1) if waits else None,
        "chase": {},  # 预备日就抢跑买
        "breakout": {},  # 等突破确认了再买
    }
    for w in HOLD_WINDOWS:
        res["chase"][f"ret_{w}"] = _stats([r.get(f"chase_ret_{w}") for r in records])
        res["breakout"][f"ret_{w}"] = _stats(
            [r.get(f"breakout_ret_{w}") for r in broke]
        )
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=0, help="随机抽样N只股票（0=全市场）")
    ap.add_argument("--limit", type=int, default=0, help="只跑前N只（调试用）")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    # 与 factor_track_record.json 完全相同的两段窗口——换了窗口就没法跟既有结论比
    WINDOWS = {
        "in": ("2026-03-13", "2026-06-10"),
        "oos": ("2025-12-10", "2026-03-13"),
    }

    data_dir = legacy_path(None, "data")
    output = legacy_path(args.out, "outputs/pending_backtest.json")
    cm = CSVManager(data_dir, resolve_snapshot=False, writable=False)
    with (data_dir / "stock_names.json").open(encoding="utf-8") as f:
        names = json.load(f)

    codes = sorted(names)
    if args.sample and args.sample < len(codes):
        random.seed(42)  # 固定种子：与既有回测同一批抽样口径，可复现
        codes = sorted(random.sample(codes, args.sample))
    if args.limit:
        codes = codes[: args.limit]

    print(
        f"[预备队回测] {len(codes)} 只股票 × 2 段窗口，workers={args.workers}",
        flush=True,
    )

    result = {"windows": {}, "note": ""}
    for wkey, (lo, hi) in WINDOWS.items():
        tasks = [(cm, c, names[c], (lo, hi)) for c in codes]
        records = []
        done = 0
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            for res in ex.map(_one_stock, tasks, chunksize=8):
                records.extend(res)
                done += 1
                if done % 250 == 0:
                    print(
                        f"  [{wkey}] {done}/{len(codes)} 只，累计 {len(records)} 个预备信号",
                        flush=True,
                    )
        result["windows"][wkey] = _summarize(records, f"{lo} ~ {hi}")
        print(
            f"[{wkey}] 完成: {json.dumps(result['windows'][wkey], ensure_ascii=False)}",
            flush=True,
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 已写入 {output}", flush=True)


if __name__ == "__main__":
    main()
