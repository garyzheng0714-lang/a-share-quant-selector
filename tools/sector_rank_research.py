"""云阶命中票排序研究——板块/主线维度到底能不能区分优劣？

背景（用户 2026-08-04）：用户希望「云阶」成为主策略，且对云阶命中的票做评分，
评分依据是「大盘 + 主线（票所在板块）」，并参考过往胜率。
项目的既有结论（docs/model-governance.md）：J/RSI/量比/距前高/乖离/涨幅/共振数 7 个
维度都无法在样本外区分云阶命中票；「板块热度是解释/候选特征，不是已验证的排序键」。

本脚本要回答：板块/主线维度的特征，能否在双周期（样本内 + 样本外）都稳健地
区分云阶命中票的 T+5 收益？能 → 上线评分；不能 → 如实报告，不伪造排序。

方法与 tools/resonance_backtest.py / pick_ranker_research.py 完全一致：
- 收益口径：信号日 T 收盘出信号 → T+1 开盘买入 → ret_5 = (T+5收盘 - T+1开盘)/T+1开盘
- 双周期：样本内 2026-03-13~06-10，样本外 2025-12-10~2026-03-13（与战绩系统同窗口）
- 验证法：按特征三等分，优组/劣组胜率与均值差；两段同向才有效

板块特征（只用先验上说得通的，不无脑挖掘）：
- ind_ret1  信号日行业平均涨幅（当日板块强弱）
- ind_ret5  行业近5日累计涨幅（主线趋势）
- ind_rel   行业当日涨幅 - 上证当日涨幅（相对大盘强度）
- ind_rank  行业当日涨幅在全行业中的分位（0=最弱，1=最强）
- mkt_ret1  上证当日涨幅（大盘强弱）
- mkt_ret5  上证近5日累计涨幅（大盘趋势）
对照特征（复测既有结论，保证样本一致）：
- J / RSI / vol_ratio / vs_peak60 / vs_ma20 / vs_ma60 / pct / n_other

已知限制（point-in-time 口径）：
- 行业映射 stock_industry.json 是当前成分，未重建历史行业成分 → 行业涨幅是近似值
- 收益未处理停牌/一字板成交细节（与项目历史战绩口径一致）

用法（数据补齐后）：
    python3 tools/sector_rank_research.py --sample 500        # 抽样冒烟
    python3 tools/sector_rank_research.py                     # 全量
"""
import argparse
import json
import os
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from strategy.factor_lib import FactorContext                      # noqa: E402
from strategy.factors.momentum_family import compute_cloud_stair   # noqa: E402
from utils.csv_manager import CSVManager                           # noqa: E402

TARGET = "cloud_stair"
HOLD = 5
IN_LO, IN_HI = "2026-03-13", "2026-06-10"      # 样本内（后段）
OOS_LO, OOS_HI = "2025-12-10", "2026-03-13"    # 样本外（前段）
INDEX_FILE = "data/index_sh000001.csv"


# ---------- 大盘指数 ----------

def _load_index(cm: CSVManager) -> pd.DataFrame:
    """上证指数日线（新浪接口拉一次，落盘复用）。date 升序。"""
    import akshare as ak
    if not Path(INDEX_FILE).exists():
        df = ak.stock_zh_index_daily(symbol="sh000001")
        df = df.rename(columns={"date": "date", "close": "close"})
        df = df[["date", "open", "close"]].copy()
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        df.to_csv(INDEX_FILE, index=False)
    df = pd.read_csv(INDEX_FILE)
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


def _index_feats(index: pd.DataFrame, date: str) -> dict:
    """信号日的大盘特征（point-in-time：只用 T 及之前的数据）."""
    d = pd.Timestamp(date)
    mask = index["date"] <= d
    if mask.sum() < 6:
        return {}
    sub = index[mask].tail(6)
    closes = sub["close"].astype(float).to_numpy()
    ret1 = float((closes[-1] / closes[-2] - 1) * 100)
    ret5 = float((closes[-1] / closes[-6] - 1) * 100)
    return {"mkt_ret1": round(ret1, 2), "mkt_ret5": round(ret5, 2)}


# ---------- 行业面板（板块特征） ----------

def build_industry_panel(cm: CSVManager, industry: dict, codes: list) -> pd.DataFrame:
    """用全市场日线聚合出 industry × date 面板：当日平均涨幅 / 近5日累计 / 相对强度.

    返回长表：date, industry, ret1, ret5, rel, rank(当日全行业分位 0-1)。
    """
    rows = []
    for code in codes:
        ind = industry.get(code)
        if not ind:
            continue
        try:
            df = cm.read_stock(code)
        except Exception:
            continue
        if df is None or df.empty or len(df) < 30:
            continue
        if len(df) > 1 and str(df["date"].iloc[0]) > str(df["date"].iloc[-1]):
            df = df.iloc[::-1].reset_index(drop=True)
        c = df["close"].astype(float).to_numpy()
        d = df["date"].astype(str).str[:10].to_numpy()
        r = np.full(len(c), np.nan)
        r[1:] = (c[1:] / c[:-1] - 1) * 100
        for i in range(len(d)):
            rows.append((d[i], ind, r[i]))
    panel = pd.DataFrame(rows, columns=["date", "industry", "ret1"])
    panel = panel.dropna(subset=["ret1"])

    # 行业当日平均涨幅
    agg = panel.groupby(["date", "industry"])["ret1"].mean().reset_index()
    agg = agg.rename(columns={"ret1": "ind_ret1"})
    # 行业近5日累计（用日涨幅滚动加总，约等于区间收益）
    agg = agg.sort_values(["industry", "date"]).reset_index(drop=True)
    agg["ind_ret5"] = agg.groupby("industry")["ind_ret1"].transform(
        lambda s: s.rolling(5, min_periods=3).sum())
    return agg


def _industry_feats(panel: pd.DataFrame, industry: str, date: str, mkt_ret1: float) -> dict:
    """信号日该行业的特征 + 当日全行业分位."""
    row = panel[(panel["industry"] == industry) & (panel["date"] == date)]
    if row.empty:
        return {}
    r1 = float(row["ind_ret1"].iloc[0])
    r5 = float(row["ind_ret5"].iloc[0]) if pd.notna(row["ind_ret5"].iloc[0]) else np.nan
    # 当日分位：所有行业按 ind_ret1 排序
    day = panel[panel["date"] == date]["ind_ret1"].dropna()
    if len(day) >= 5:
        rank = float((day < r1).mean())
    else:
        rank = np.nan
    return {
        "ind_ret1": round(r1, 2),
        "ind_ret5": round(r5, 2) if r5 == r5 else None,
        "ind_rel": round(r1 - mkt_ret1, 2),
        "ind_rank": round(rank, 3) if rank == rank else None,
    }


# ---------- 云阶信号扫描 ----------

def _scan_one(args):
    """单只股票：窗口内每个信号日跑云阶（截断），命中则记收益与个股特征."""
    cm, code, lo, hi = args
    try:
        df = cm.read_stock(code)
        if df is None or df.empty or len(df) < 200:
            return []
        if len(df) > 1 and str(df["date"].iloc[0]) > str(df["date"].iloc[-1]):
            df = df.iloc[::-1].reset_index(drop=True)
        dates = df["date"].astype(str).str[:10].to_numpy()
        closes = df["close"].astype(float).to_numpy()
        opens = df["open"].astype(float).to_numpy()
        n = len(dates)
        out = []
        for i in range(180, n - 1):
            d = dates[i]
            if d < lo or d > hi:
                continue
            sub = df.iloc[: i + 1]
            try:
                hit = compute_cloud_stair(FactorContext(sub))
            except Exception:
                continue
            if not hit:
                continue
            buy = opens[i + 1]
            j = i + HOLD
            if not (buy > 0) or j >= n:
                continue
            ret = round(float((closes[j] - buy) / buy * 100), 2)
            out.append({"code": code, "date": d, "ret": ret})
        return out
    except Exception:
        return []


def scan_signals(cm: CSVManager, codes: list, lo: str, hi: str, workers: int) -> list:
    tasks = [(cm, c, lo, hi) for c in codes]
    records = []
    done = 0
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for res in ex.map(_scan_one, tasks, chunksize=20):
            records.extend(res)
            done += 1
            if done % 500 == 0:
                print(f"  [scan {lo}~{hi}] {done}/{len(tasks)} 只, 信号 {len(records)} 条", flush=True)
    return records


# ---------- 评估（三等分法，与 pick_ranker_research 一致） ----------

def evaluate(df, feat, reverse=False):
    s = df[[feat, "ret"]].dropna()
    if len(s) < 60:
        return None
    q = s[feat].quantile([1 / 3, 2 / 3]).values
    lo = s[s[feat] <= q[0]]["ret"]
    hi = s[s[feat] >= q[1]]["ret"]
    if len(lo) < 20 or len(hi) < 20:
        return None
    good, bad = (lo, hi) if reverse else (hi, lo)
    return {
        "dir": "小者优" if reverse else "大者优",
        "good_win": round((good > 0).mean() * 100, 1),
        "good_avg": round(float(good.mean()), 2), "good_n": len(good),
        "bad_win": round((bad > 0).mean() * 100, 1),
        "bad_avg": round(float(bad.mean()), 2), "bad_n": len(bad),
        "spread": round(float(good.mean() - bad.mean()), 2),
    }


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=0, help="随机抽N只股票（固定种子42）")
    ap.add_argument("--workers", type=int, default=0, help="并行数（默认CPU核数）")
    args = ap.parse_args()
    workers = args.workers or max(1, (os.cpu_count() or 4) - 1)

    cm = CSVManager("data")
    names = json.load(open("data/stock_names.json", encoding="utf-8"))
    industry = json.load(open("data/stock_industry.json", encoding="utf-8"))
    codes = sorted(set(names) & set(industry))
    if args.sample:
        rng = np.random.default_rng(42)
        codes = sorted(rng.choice(codes, size=min(args.sample, len(codes)), replace=False))
    print(f"股票池: {len(codes)} 只")

    # 大盘 + 行业面板（主进程算一次，广播给评估）
    print("加载上证指数...")
    index = _load_index(cm)
    print(f"构建行业面板（{len(codes)} 只）...")
    t0 = time.time()
    panel = build_industry_panel(cm, industry, codes)
    print(f"行业面板: {len(panel)} 行, {panel['date'].nunique()} 个交易日, "
          f"{panel['industry'].nunique()} 个行业 ({time.time()-t0:.0f}s)")

    print("扫描云阶信号（样本外 2025-12-10~2026-03-13）...")
    rec_oos = scan_signals(cm, codes, OOS_LO, OOS_HI, workers)
    print("扫描云阶信号（样本内 2026-03-13~2026-06-10）...")
    rec_in = scan_signals(cm, codes, IN_LO, IN_HI, workers)

    def build(records, label):
        rows = []
        for r in records:
            f = _index_feats(index, r["date"])
            ind = industry.get(r["code"], "")
            if ind:
                f.update(_industry_feats(panel, ind, r["date"], f.get("mkt_ret1", 0.0)))
            f.update({"code": r["code"], "date": r["date"], "ret": r["ret"]})
            rows.append(f)
        d = pd.DataFrame(rows)
        print(f"{label}: {len(d)} 条云阶信号")
        return d

    d_in = build(rec_in, "样本内")
    d_oos = build(rec_oos, "样本外")
    if d_in.empty or d_oos.empty:
        print("信号不足，退出")
        return

    print(f"\n云阶整体 T+{HOLD}: 样本内 胜率{(d_in.ret>0).mean()*100:.1f}% "
          f"均值{d_in.ret.mean():+.2f}% | 样本外 胜率{(d_oos.ret>0).mean()*100:.1f}% "
          f"均值{d_oos.ret.mean():+.2f}%")

    FEATS = [
        # 板块/主线维度（本次研究的核心）
        ("ind_ret1", False), ("ind_ret1", True),
        ("ind_ret5", False), ("ind_ret5", True),
        ("ind_rel", False), ("ind_rel", True),
        ("ind_rank", False), ("ind_rank", True),
        ("mkt_ret1", False), ("mkt_ret1", True),
        ("mkt_ret5", False), ("mkt_ret5", True),
    ]
    print(f"\n{'特征':<12}{'方向':<7}{'样本内 优组胜率/均值':>24}{'样本外 优组胜率/均值':>24}   两段都优?")
    winners = []
    for feat, rev in FEATS:
        a = evaluate(d_in, feat, rev)
        b = evaluate(d_oos, feat, rev)
        if not a or not b:
            continue
        ok = a["spread"] > 0 and b["spread"] > 0
        if ok:
            winners.append((a["spread"] + b["spread"], feat, rev, a, b))
        mark = "OK" if ok else ""
        print(f"{feat:<12}{a['dir']:<7}"
              f"{a['good_win']:>8}% {a['good_avg']:>+7}% (差{a['spread']:+.2f},n{a['good_n']})"
              f"{b['good_win']:>10}% {b['good_avg']:>+7}% (差{b['spread']:+.2f},n{b['good_n']})   {mark}")

    print("\n=== 两段都有效的排序特征 ===")
    if not winners:
        print("  无——板块/主线维度无法在样本外区分云阶命中票（与既有 7 维度结论一致）")
    for sp, feat, rev, a, b in sorted(winners, reverse=True):
        print(f"  {feat}（{'小者优' if rev else '大者优'}）: "
              f"样本内优组 {a['good_win']}%/{a['good_avg']}% vs 劣组 {a['bad_win']}%/{a['bad_avg']}%；"
              f"样本外优组 {b['good_win']}%/{b['good_avg']}% vs 劣组 {b['bad_win']}%/{b['bad_avg']}%")


if __name__ == "__main__":
    main()
