"""旧「今日一票」排序研究（仅供历史复现）。

背景：双周期体检证明「云阶」是唯一在 T+1/T+5 都稳健的短线因子（用户偏好短线）。
但云阶每天可能命中好几只，必须有依据地排序，不能拍脑袋。

方法（防过拟合是第一原则——共振假设就是死在没做样本外）：
1. 只测有先验逻辑的特征，不做无脑特征挖掘
2. 样本内（3-6月）找候选特征 → 样本外（12-3月）验证
3. 样本外站不住的，一律不用；若全都站不住，就诚实地说"无法有效区分"

它依赖旧共振回测产物，不得用作当前策略发布证据。
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from strategy.factor_lib import FactorContext  # noqa: E402
from research.legacy.isolation import legacy_path  # noqa: E402
from utils.csv_manager import CSVManager  # noqa: E402

TARGET = "cloud_stair"  # 唯一的短线稳健因子
HOLD = 5  # 短线：持有5个交易日


def features_for(df, i):
    """信号日 i 的特征（只用先验上说得通的，不乱挖）."""
    sub = df.iloc[max(0, i - 319) : i + 1].reset_index(drop=True)
    if len(sub) < 180:
        return None
    ctx = FactorContext(sub)
    c = float(sub["close"].iloc[-1])
    v = sub["volume"].astype(float)
    h = sub["high"].astype(float)
    _, _, j = ctx.kdj()
    ma20 = float(ctx.ma(20).iloc[-1])
    ma60 = float(ctx.ma(60).iloc[-1])
    v5 = float(v.iloc[-6:-1].mean())
    peak60 = float(h.iloc[-61:-1].max())
    f = {
        "J": float(j.iloc[-1]),
        "RSI": float(ctx.rsi_tdx(6).iloc[-1]),
        # 放量倍数：突破日的量能确认强度
        "vol_ratio": float(v.iloc[-1]) / v5 if v5 > 0 else np.nan,
        # 距60日高点：刚破前高 vs 已经飞很远
        "vs_peak60": c / peak60 - 1 if peak60 > 0 else np.nan,
        # 距MA20/MA60：乖离越大越容易回踩
        "vs_ma20": c / ma20 - 1 if ma20 > 0 else np.nan,
        "vs_ma60": c / ma60 - 1 if ma60 > 0 else np.nan,
        "pct": float(ctx.pct_change().iloc[-1]),
    }
    return {k: (val if val == val else None) for k, val in f.items()}


def build(records, cm, label):
    """给该窗口里所有 TARGET 命中信号补特征."""
    rows = []
    by_code = {}
    for r in records:
        if TARGET in r["factors"] and r.get(f"ret_{HOLD}") is not None:
            by_code.setdefault(r["code"], []).append(r)
    for code, rs in by_code.items():
        try:
            df = cm.read_stock(code)
        except Exception:
            continue
        if df is None or df.empty:
            continue
        if len(df) > 1 and str(df["date"].iloc[0]) > str(df["date"].iloc[-1]):
            df = df.iloc[::-1].reset_index(drop=True)
        pos = {d: i for i, d in enumerate(df["date"].astype(str).str[:10])}
        for r in rs:
            i = pos.get(r["date"])
            if i is None:
                continue
            f = features_for(df, i)
            if not f:
                continue
            f.update(
                {
                    "code": code,
                    "date": r["date"],
                    "ret": r[f"ret_{HOLD}"],
                    "n_other": len(r["factors"]) - 1,
                    "cap": r.get("cap"),
                }
            )
            rows.append(f)
    d = pd.DataFrame(rows)
    print(f"{label}: {len(d)} 条云阶信号带特征")
    return d


def evaluate(df, feat, label, reverse=False):
    """按特征三等分，看高低分组的 T+5 收益差（reverse=True 表示越小越好）."""
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
        "feat": feat,
        "dir": "小者优" if reverse else "大者优",
        "good_win": round((good > 0).mean() * 100, 1),
        "good_avg": round(float(good.mean()), 2),
        "good_n": len(good),
        "bad_win": round((bad > 0).mean() * 100, 1),
        "bad_avg": round(float(bad.mean()), 2),
        "bad_n": len(bad),
        "spread": round(float(good.mean() - bad.mean()), 2),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ins", default=None)
    parser.add_argument("--oos", default=None)
    args = parser.parse_args()
    data_dir = legacy_path(None, "data")
    ins_path = legacy_path(args.ins, "outputs/resonance_backtest.json")
    oos_path = legacy_path(args.oos, "outputs/resonance_oos.json")
    cm = CSVManager(data_dir, resolve_snapshot=False, writable=False)
    with ins_path.open(encoding="utf-8") as handle:
        ins = json.load(handle)["records"]
    with oos_path.open(encoding="utf-8") as handle:
        oos = json.load(handle)["records"]
    d_in = build(ins, cm, "样本内")
    d_oos = build(oos, cm, "样本外")

    print(
        f"\n云阶整体 T+{HOLD}: 样本内 胜率{(d_in.ret > 0).mean() * 100:.1f}% 均值{d_in.ret.mean():+.2f}% | "
        f"样本外 胜率{(d_oos.ret > 0).mean() * 100:.1f}% 均值{d_oos.ret.mean():+.2f}%"
    )

    FEATS = [
        ("J", True),
        ("J", False),
        ("RSI", True),
        ("RSI", False),
        ("vol_ratio", False),
        ("vs_peak60", True),
        ("vs_peak60", False),
        ("vs_ma20", True),
        ("vs_ma20", False),
        ("vs_ma60", True),
        ("vs_ma60", False),
        ("pct", True),
        ("pct", False),
        ("n_other", False),
    ]
    print(
        f"\n{'特征':<12}{'方向':<7}{'样本内 优组胜率/均值':>24}{'样本外 优组胜率/均值':>24}   两段都优?"
    )
    winners = []
    for feat, rev in FEATS:
        a = evaluate(d_in, feat, "in", rev)
        b = evaluate(d_oos, feat, "oos", rev)
        if not a or not b:
            continue
        # "有效" = 优组均值 > 劣组均值，且两段都成立
        ok = a["spread"] > 0 and b["spread"] > 0
        if ok:
            winners.append((a["spread"] + b["spread"], feat, rev, a, b))
        mark = "✅" if ok else ""
        print(
            f"{feat:<12}{a['dir']:<7}"
            f"{a['good_win']:>8}% {a['good_avg']:>+7}% (差{a['spread']:+.2f})"
            f"{b['good_win']:>10}% {b['good_avg']:>+7}% (差{b['spread']:+.2f})   {mark}"
        )

    print("\n=== 两段都有效的排序特征 ===")
    if not winners:
        print(
            "  无——云阶命中的票之间无法有效区分，只能按其他维度（如板块热度）做次要排序"
        )
    for sp, feat, rev, a, b in sorted(winners, reverse=True):
        print(
            f"  {feat}（{'小者优' if rev else '大者优'}）: "
            f"样本内优组 {a['good_win']}%/{a['good_avg']}% vs 劣组 {a['bad_win']}%/{a['bad_avg']}%；"
            f"样本外优组 {b['good_win']}%/{b['good_avg']}% vs 劣组 {b['bad_win']}%/{b['bad_avg']}%"
        )


if __name__ == "__main__":
    main()
