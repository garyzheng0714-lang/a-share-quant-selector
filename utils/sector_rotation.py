"""板块轮动量化模型 —— 热度分 + 接力潜力分

回答两个问题：
1. 现在谁最热？（热度分：相对强度35 + 成交额热度25 + 广度25 + 持续性15 − 集中度惩罚）
2. 谁可能接力？（潜力分：强度加速35 + 成交额加速25 + 广度加速25 + 位置15 − 过热惩罚，
   且当前热度须在 45~70 之间——不能太冷也不能已高潮）

全部指标由本地日线 CSV + 行业映射离线计算，零外部接口依赖。
⚠️ CSV 的 amount 列全为 0，成交额用 close×volume×100 近似；
   占比型指标（行业额÷全市场额）分子分母同为近似，系统偏差抵消。
"""

import hashlib
import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from utils.artifact_integrity import artifact_is_valid, seal_artifact
from utils.decision_versions import cache_identity
from utils.market_filter import is_main_board
from utils.market_snapshot import read_snapshot_metadata

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
CACHE_FILE = DATA_DIR / "sector_rotation_cache.json"

NROWS = 50  # 输出6日热度序列 + 最长回看21日 + 指标窗口20日 ≈ 47 行
SERIES_DAYS = 6  # 热度序列长度（今天 + 回看，用于 Δ3 与持续性）
MIN_MEMBERS = 8  # 行业有效成分股下限，太小的行业噪声大
MIN_ROWS = 47  # 个股最少完整行数（次新股跳过）
TOP_N = 8
SECTOR_CACHE_VERSION = 4

_lock = threading.Lock()

STAGES = [
    (90, "极热"),
    (80, "主线候选"),
    (65, "热门"),
    (50, "升温"),
    (30, "观察"),
    (0, "冷门"),
]


def _stage(score: float) -> str:
    for th, name in STAGES:
        if score >= th:
            return name
    return "冷门"


def _load_universe(csv_manager=None) -> dict:
    """主板、非ST/退市股票的 {code: industry}."""
    data_root = getattr(csv_manager, "base_data_dir", DATA_DIR)
    snapshot_id = getattr(csv_manager, "snapshot_id", None)
    industry_map, _ = read_snapshot_metadata(
        "stock_industry.json", data_root, snapshot_id=snapshot_id
    )
    names, _ = read_snapshot_metadata(
        "stock_names.json", data_root, snapshot_id=snapshot_id
    )
    if not isinstance(industry_map, dict) or not isinstance(names, dict):
        return {}
    out = {}
    for code, industry in industry_map.items():
        if not is_main_board(code) or not industry:
            continue
        name = names.get(code, "")
        if "ST" in name or "退" in name or "*" in name:
            continue
        out[code] = industry
    return out


def _universe_fingerprint(universe=None, csv_manager=None) -> str:
    """行业成分映射指纹；映射变化时旧板块榜不能继续命中缓存。"""
    current = universe if universe is not None else _load_universe(csv_manager)
    payload = json.dumps(
        sorted(current.items()), ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def _panel_one(csv_manager, code: str, industry: str):
    """处理单只股票，返回其日级长表分片；数据不合格返回 None。

    纯只读 CSV + 各自构造 DataFrame，无共享可变状态，可安全并行调用。
    """
    df = csv_manager.read_stock(code, nrows=NROWS)
    if len(df) < MIN_ROWS:
        return None
    df = df.sort_values("date").reset_index(drop=True)  # CSV 是倒序存储
    close = pd.to_numeric(df["close"], errors="coerce")
    volume = pd.to_numeric(df["volume"], errors="coerce")
    if close.isna().any() or (close <= 0).any():
        return None
    ret1 = close.pct_change().clip(-0.11, 0.11)
    part = pd.DataFrame(
        {
            "date": df["date"].dt.strftime("%Y-%m-%d"),
            "industry": industry,
            "ret1": ret1,
            "above_ma10": (close > close.rolling(10).mean()).astype(float),
            "new_high20": (close >= close.rolling(20).max()).astype(float),
            "amount": close * volume.fillna(0) * 100,
        }
    )
    # 只保留衍生列完整的行（前 20 行是窗口预热）
    return part.iloc[20:]


def _build_panel(csv_manager, universe: dict) -> pd.DataFrame:
    """全市场个股日级长表: date, industry, ret1, above_ma10, new_high20, amount.

    逐只读 CSV 是纯 IO 密集（原单线程约 27s），用线程池并行加速；
    executor.map 保持 universe 的输入顺序，concat 后行序与串行完全一致，
    因此下游聚合的数值结果 bit-level 不变。
    """
    if not universe:
        return pd.DataFrame()
    workers = min(16, max(1, len(universe)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        frames = [
            part
            for part in executor.map(
                lambda item: _panel_one(csv_manager, item[0], item[1]),
                universe.items(),
            )
            if part is not None
        ]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).dropna(subset=["ret1"])


def _top3_concentration(s: pd.Series) -> float:
    """龙头集中度：前3只涨幅之和 ÷ 行业涨幅之和，越高越像龙头绑架（集中度惩罚用）。

    稳健性处理：仅当行业当日平均涨幅显著(>0.5%，与 _heat_on 的 hot_day 门槛完全一致)时才计比值。
    平均涨幅不显著时行业没真涨，分母（涨幅和）接近0会让比值爆表污染，直接返回0（不惩罚）。
    门槛保证进入除法时 sum = mean*n > 0.005 > 0，从根上杜绝除零，无需 clip 兜脆弱的边界。
    因下游 penalty 同样只在 hot_day 时使用 top3_share，此改动不影响任何会被实际使用的惩罚值
    （mean>0.5% 区间与原口径 bit-level 完全一致），仅消除了病态区间的极端值污染。
    """
    if s.mean() <= 0.005:
        return 0.0
    return float(np.clip(s.nlargest(3).sum() / s.sum(), 0, 1.5))


def _aggregate(panel: pd.DataFrame):
    """行业×日期指标面板 + 市场×日期序列。"""
    g = panel.groupby(["date", "industry"])
    ind = pd.DataFrame(
        {
            "n": g["ret1"].size(),
            "ret": g["ret1"].mean(),
            "amt": g["amount"].sum(),
            "adv": g["ret1"].apply(lambda s: (s > 0).mean() * 100),
            "ma10r": g["above_ma10"].mean() * 100,
            "nh20r": g["new_high20"].mean() * 100,
            "top3_share": g["ret1"].apply(_top3_concentration),
        }
    ).reset_index()

    mkt = (
        panel.groupby("date")
        .agg(mkt_ret=("ret1", "mean"), mkt_amt=("amount", "sum"))
        .reset_index()
    )

    # 交易日历：出现股票数 ≥ 峰值 50% 的日期（剔除零星脏日期）
    counts = panel.groupby("date")["ret1"].size()
    valid_dates = sorted(counts[counts >= counts.max() * 0.5].index)
    ind = ind[ind["date"].isin(valid_dates)]
    mkt = mkt[mkt["date"].isin(valid_dates)]

    # 行业等权指数 / 市场等权指数（用于 k 日涨幅）
    ind = ind.sort_values(["industry", "date"])
    ind["idx"] = ind.groupby("industry")["ret"].transform(lambda s: (1 + s).cumprod())
    mkt = mkt.sort_values("date")
    mkt["mkt_idx"] = (1 + mkt["mkt_ret"]).cumprod()
    return ind, mkt, valid_dates


def _pivot(ind: pd.DataFrame, col: str) -> pd.DataFrame:
    return ind.pivot(index="industry", columns="date", values=col)


def _rank_pct(s: pd.Series) -> pd.Series:
    return s.rank(pct=True) * 100


def _kday_rel(idx_p: pd.DataFrame, mkt: pd.DataFrame, date: str, k: int) -> pd.Series:
    """行业 k 日涨幅 − 市场 k 日涨幅（百分点）."""
    dates = list(idx_p.columns)
    i = dates.index(date)
    prev = dates[i - k]
    ind_chg = (idx_p[date] / idx_p[prev] - 1) * 100
    m = mkt.set_index("date")["mkt_idx"]
    mkt_chg = (m[date] / m[prev] - 1) * 100
    return ind_chg - mkt_chg


def _heat_on(pivots: dict, mkt: pd.DataFrame, date: str) -> pd.DataFrame:
    """某交易日全部行业的热度分。"""
    idx_p, amt_p, ret_p = pivots["idx"], pivots["amt"], pivots["ret"]
    dates = list(idx_p.columns)
    i = dates.index(date)

    rs = (
        _rank_pct(_kday_rel(idx_p, mkt, date, 5)) * 0.5
        + _rank_pct(_kday_rel(idx_p, mkt, date, 10)) * 0.3
        + _rank_pct(_kday_rel(idx_p, mkt, date, 20)) * 0.2
    )

    m_amt = mkt.set_index("date")["mkt_amt"]
    share = amt_p.div(m_amt, axis=1)
    last3, last20 = dates[i - 2 : i + 1], dates[i - 19 : i + 1]
    turn_ratio = share[last3].mean(axis=1) / share[last20].mean(axis=1)
    turn = _rank_pct(turn_ratio)

    breadth = (
        pivots["adv"][date] * 0.4
        + pivots["ma10r"][date] * 0.4
        + pivots["nh20r"][date] * 0.2
    )

    persist = pd.Series(0.0, index=idx_p.index)
    for d in dates[i - 4 : i + 1]:
        day_ret = ret_p[d]
        persist += (day_ret >= day_ret.quantile(0.8)).astype(float) * 20

    top3 = pivots["top3_share"][date]
    penalty = pd.Series(0.0, index=idx_p.index)
    hot_day = ret_p[date] > 0.005  # 行业当日涨幅 >0.5% 才谈集中度
    penalty[hot_day & (top3 > 0.75)] = 20
    penalty[hot_day & (top3 > 0.60) & (top3 <= 0.75)] = 10
    penalty[hot_day & (top3 > 0.40) & (top3 <= 0.60)] = 5

    heat = rs * 0.35 + turn * 0.25 + breadth * 0.25 + persist * 0.15 - penalty
    return pd.DataFrame(
        {
            "heat": heat.clip(0, 100),
            "rs": rs,
            "turn_ratio": turn_ratio,
            "breadth": breadth,
            "ma10r": pivots["ma10r"][date],
        }
    )


def _pos_score(pos: float) -> float:
    """距 20 日高点位置评分：已转强但还没涨到天上最优。"""
    if pos >= 1.0:
        return 45.0  # 当日即20日新高，已在高潮
    if pos >= 0.98:
        return 70.0
    if pos >= 0.92:
        return 100.0  # 距高点 2%~8%，理想接力位
    if pos >= 0.85:
        return 75.0
    return 40.0  # 还太深，转强不足


def _relay_on(
    pivots: dict, mkt: pd.DataFrame, date: str, heat: pd.Series
) -> pd.DataFrame:
    """某交易日全部行业的接力潜力分。"""
    idx_p, amt_p = pivots["idx"], pivots["amt"]
    dates = list(idx_p.columns)
    i = dates.index(date)

    rel3_now = _kday_rel(idx_p, mkt, date, 3)
    rel3_prev = _kday_rel(idx_p, mkt, dates[i - 3], 3)
    rs_accel_raw = rel3_now - rel3_prev
    rs_accel = _rank_pct(rs_accel_raw)

    m_amt = mkt.set_index("date")["mkt_amt"]
    share = amt_p.div(m_amt, axis=1)
    turn_accel_raw = share[dates[i - 2 : i + 1]].mean(axis=1) / share[
        dates[i - 12 : i - 2]
    ].mean(axis=1)
    turn_accel = _rank_pct(turn_accel_raw)

    breadth_accel_raw = pivots["ma10r"][date] - pivots["ma10r"][dates[i - 5]]
    breadth_accel = _rank_pct(breadth_accel_raw)

    pos = idx_p[date] / idx_p[dates[i - 19 : i + 1]].max(axis=1)
    pos_s = pos.apply(_pos_score)

    score = rs_accel * 0.35 + turn_accel * 0.25 + breadth_accel * 0.25 + pos_s * 0.15

    # 过热惩罚：已经在高潮的不是"下一棒"
    chg5 = (idx_p[date] / idx_p[dates[i - 5]] - 1) * 100
    score[chg5.rank(pct=True) > 0.95] -= 10
    turn20 = share[dates[i - 2 : i + 1]].mean(axis=1) / share[
        dates[i - 19 : i + 1]
    ].mean(axis=1)
    score[turn20 > 2] -= 5
    score[pivots["ma10r"][date] > 85] -= 5

    return pd.DataFrame(
        {
            "relay": score.clip(0, 100),
            "heat": heat,
            "rs_accel_raw": rs_accel_raw,
            "turn_accel_raw": turn_accel_raw,
            "breadth_accel_raw": breadth_accel_raw,
            "pos": pos,
        }
    )


def _relay_reasons(row) -> list:
    out = []
    if row["rs_accel_raw"] > 0:
        out.append("相对强度由弱转强")
    if row["turn_accel_raw"] > 1.1:
        out.append("资金占比升温")
    if row["breadth_accel_raw"] > 10:
        out.append(f"广度扩散+{row['breadth_accel_raw']:.0f}pp")
    if 0.92 <= row["pos"] < 0.98:
        out.append("距20日高点2%~8%理想位")
    return out or ["综合加速度领先"]


def compute_sector_rotation(csv_manager) -> dict:
    """全量计算：近 6 日热度序列 + 今日接力潜力。耗时约 5~20 秒。"""
    t0 = time.time()
    universe = _load_universe(csv_manager)
    panel = _build_panel(csv_manager, universe)
    if panel.empty:
        return {"available": False, "reason": "本地数据不足，无法计算板块热度"}

    ind, mkt, valid_dates = _aggregate(panel)
    if len(valid_dates) < 27:
        return {"available": False, "reason": f"有效交易日不足({len(valid_dates)}<27)"}

    # 成分股不足的行业剔除（按最新日）
    latest = valid_dates[-1]
    ok_inds = ind[(ind["date"] == latest) & (ind["n"] >= MIN_MEMBERS)]["industry"]
    ind = ind[ind["industry"].isin(ok_inds)]

    pivots = {
        c: _pivot(ind, c)
        for c in ["idx", "amt", "ret", "adv", "ma10r", "nh20r", "top3_share"]
    }

    series_dates = valid_dates[-SERIES_DAYS:]
    heats = {d: _heat_on(pivots, mkt, d) for d in series_dates}
    today_heat = heats[latest]
    delta3 = today_heat["heat"] - heats[series_dates[-4]]["heat"]

    hot = []
    for name, row in (
        today_heat.sort_values("heat", ascending=False).head(TOP_N).iterrows()
    ):
        d3 = float(delta3.get(name, 0))
        hot.append(
            {
                "name": name,
                "score": round(float(row["heat"]), 1),
                "delta3": round(d3, 1),
                "stage": _stage(row["heat"]),
                "trend": "up" if d3 >= 8 else ("down" if d3 <= -8 else "flat"),
                "breadth_ma10": round(float(row["ma10r"])),
                "turn_ratio": round(float(row["turn_ratio"]), 2),
            }
        )

    relay_df = _relay_on(pivots, mkt, latest, today_heat["heat"])
    eligible = relay_df[
        (relay_df["heat"] >= 45) & (relay_df["heat"] <= 70) & (relay_df["relay"] >= 55)
    ]
    relay = []
    for name, row in (
        eligible.sort_values("relay", ascending=False).head(TOP_N).iterrows()
    ):
        relay.append(
            {
                "name": name,
                "score": round(float(row["relay"]), 1),
                "heat": round(float(row["heat"]), 1),
                "reasons": _relay_reasons(row),
            }
        )

    # 全行业热度：hot/relay 只给前 8 名，但每只推荐票都要能查到自己行业的冷热，
    # 否则冷门行业的票在界面上是一片空白（"化妆品" 查不到分 = 看不出顺不顺风）
    ranked = today_heat.sort_values("heat", ascending=False)
    total = int(len(ranked))
    heat_map = {}
    for i, (name, row) in enumerate(ranked.iterrows(), start=1):
        heat_map[name] = {
            "score": round(float(row["heat"]), 1),
            "delta3": round(float(delta3.get(name, 0)), 1),
            "stage": _stage(row["heat"]),
            "rank": i,
            "total": total,
            "relative_strength": round(float(row["rs"]), 1),
            "turn_ratio": round(float(row["turn_ratio"]), 2),
            "breadth": round(float(row["breadth"]), 1),
            "breadth_ma10": round(float(row["ma10r"]), 1),
            "heat_series": [
                round(float(heats[date].loc[name, "heat"]), 1) for date in series_dates
            ],
        }

    result = {
        "available": True,
        "trade_date": latest,
        "computed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "cache_version": SECTOR_CACHE_VERSION,
        "series_dates": series_dates,
        "elapsed_sec": round(time.time() - t0, 1),
        "stocks": int(panel[panel["date"] == latest].shape[0]),
        "industries": int(len(ok_inds)),
        "hot": hot,
        "relay": relay,
        "heat_map": heat_map,
        "universe_fingerprint": _universe_fingerprint(universe),
        **cache_identity(csv_manager, "sector_rotation", SECTOR_CACHE_VERSION),
    }
    logger.info(
        "板块轮动计算完成: %s 行业 / %s 只票 / %.1fs",
        result["industries"],
        result["stocks"],
        result["elapsed_sec"],
    )
    return result


def _read_valid_cache(csv_manager):
    """读缓存，同时校验它是不是当前结构（缺 heat_map = 旧版本写的，必须重算）."""
    if not CACHE_FILE.exists():
        return None
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            cached = json.load(f)
    except Exception:
        return None
    if (
        not cached.get("available")
        or not artifact_is_valid(cached)
        or not cached.get("heat_map")
        or cached.get("cache_version") != SECTOR_CACHE_VERSION
    ):
        return None
    identity = cache_identity(csv_manager, "sector_rotation", SECTOR_CACHE_VERSION)
    if (
        not identity.get("cache_key")
        or cached.get("cache_key") != identity["cache_key"]
    ):
        return None
    if cached.get("universe_fingerprint") != _universe_fingerprint(
        csv_manager=csv_manager
    ):
        return None
    return cached


def get_sector_rotation(csv_manager, force: bool = False) -> dict:
    """带文件缓存：数据日期没变、且缓存结构是当前版本，就直接用缓存。"""
    if not force:
        cached = _read_valid_cache(csv_manager)
        if cached:
            return cached
    with _lock:
        # 双检：并发未命中时，排队等锁的请求在前一个算完后直接吃现成缓存，
        # 避免每个请求都完整重算一遍（单次 5~20 秒）
        if not force:
            cached = _read_valid_cache(csv_manager)
            if cached:
                return cached
        result = compute_sector_rotation(csv_manager)
        if result.get("available"):
            tmp = None
            try:
                result = seal_artifact(result)
                CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
                tmp = CACHE_FILE.with_suffix(f".{os.getpid()}.tmp")
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(result, f, ensure_ascii=False)
                tmp.replace(CACHE_FILE)
            except Exception as e:
                logger.warning("板块热度缓存写入失败: %s", e)
                if tmp is not None:
                    try:
                        tmp.unlink(missing_ok=True)
                    except OSError:
                        logger.warning("板块临时缓存清理失败: %s", tmp)
                return {
                    "available": False,
                    "reason": "sector_cache_write_failed",
                    "trade_date": result.get("trade_date"),
                }
        return result


def read_cached_sector_rotation(csv_manager) -> dict:
    """只读且校验当前快照缓存；绝不在请求链路中触发重算或写文件。"""
    cached = _read_valid_cache(csv_manager)
    if cached:
        return cached
    return {
        "available": False,
        "reason": "sector_snapshot_not_ready",
        "retry_via": "daily_close_pipeline",
    }


def read_cache(csv_manager=None) -> dict:
    """兼容只读入口；有 manager 时同时校验 snapshot/cache identity。"""
    if csv_manager is not None:
        return read_cached_sector_rotation(csv_manager)
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"available": False, "reason": "sector_snapshot_not_ready"}


def _latest_data_date(csv_manager) -> str:
    """用几只大盘股探测本地数据的最新交易日。"""
    latest = ""
    for code in ("600030", "600036", "000001", "600519"):
        df = csv_manager.read_stock(code, nrows=1)
        if not df.empty:
            d = df["date"].dt.strftime("%Y-%m-%d").iloc[0]
            latest = max(latest, d)
    return latest


def build_sector_brief(data: dict) -> str:
    """给 AI 荐票的板块轮动文字段（自研模型，非外部接口）。"""
    if not data.get("available"):
        return ""
    lines = [f"### 板块轮动（自研量化模型，{data['trade_date']} 收盘口径）"]
    if data["hot"]:
        trend_txt = {"up": "升温中", "down": "退潮中", "flat": "平稳"}
        lines.append(
            "当前最热: "
            + "；".join(
                f"{h['name']}(热度{h['score']:.0f}·{h['stage']}·{trend_txt[h['trend']]})"
                for h in data["hot"][:5]
            )
        )
    if data["relay"]:
        lines.append(
            "潜在接力: "
            + "；".join(
                f"{r['name']}(潜力{r['score']:.0f}: {'/'.join(r['reasons'][:2])})"
                for r in data["relay"][:5]
            )
        )
    else:
        lines.append("潜在接力: 暂无满足条件的板块（要求热度45~70且加速度领先）")
    lines.append(
        "注：热度看『绝对值+变化方向』——高分但退潮中的板块是在卖点而非买点；"
        "候选票若属于最热或接力板块，属加分项（趁大势）。"
    )
    return "\n".join(lines)
