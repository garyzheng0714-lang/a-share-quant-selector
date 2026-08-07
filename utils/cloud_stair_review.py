"""云阶历史复盘：以「票」为核心回看每日命中与持有期收益。

口径（与生产执行模型一致）：
- 选出日 T = 因子信号收盘日
- 买入 = T+1 开盘（近似，含滑点/费用见 evaluate_trade）
- 隔日涨跌 = T+1 当日涨跌幅（相对 T 收盘），回答「选出来第二天怎么走」
- 持有至今 = T+1 开盘买入 → 最新可得收盘卖出的净收益
- 持有窗口 ret_n = evaluate_trade(hold_days=n) 的净收益

数据来源：
1. data/cloud_stair_pick_ledger.json —— 持久账本（不被 factor_cache 12 日滚动清理抹掉）
2. data/factor_cache/*.json —— 现有缓存补齐（旧扁平 / 密封 envelope 都读）

扫描写入 factor_cache 时会同步 upsert 账本，保证复盘样本可随交易日累积。
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from utils.execution_model import DEFAULT_EXECUTION_POLICY, evaluate_trade
from utils.factor_scan import CACHE_DIR, DATA_DIR

logger = logging.getLogger(__name__)

STRATEGY_KEY = "cloud_stair"
STRATEGY_NAME = "云阶"
HOLD_WINDOWS = (1, 5, 10, 20)
LEDGER_PATH = DATA_DIR / "cloud_stair_pick_ledger.json"
LEDGER_VERSION = 1
_ledger_lock = threading.Lock()


def _finite(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _normalize_daily(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    daily = frame.copy()
    daily["date"] = daily["date"].astype(str).str[:10]
    daily = daily.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    return daily


def _load_bucket(payload: dict) -> dict | None:
    if not isinstance(payload, dict):
        return None
    results = payload.get("results") if isinstance(payload.get("results"), dict) else payload
    if not isinstance(results, dict):
        return None
    bucket = results.get(STRATEGY_KEY)
    return bucket if isinstance(bucket, dict) else None


def _hit_to_pick(pick_date: str, hit: dict) -> dict | None:
    code = str(hit.get("code") or "").strip()
    if not code or len(pick_date) != 10:
        return None
    return {
        "pick_date": pick_date,
        "code": code,
        "name": str(hit.get("name") or code),
        "signal_close": _finite(hit.get("close")),
        "signal_pct_change": _finite(hit.get("pct_change")),
        "industry": hit.get("industry") or "",
        "peak_date": str(hit.get("peak_date") or "")[:10] or None,
        "wave_gain_pct": _finite(hit.get("wave_gain_pct")),
    }


def _read_ledger(path: Path | None = None) -> list[dict]:
    ledger = Path(path or LEDGER_PATH)
    if not ledger.exists():
        return []
    try:
        payload = json.loads(ledger.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("云阶账本读取失败: %s", exc)
        return []
    picks = payload.get("picks") if isinstance(payload, dict) else None
    if not isinstance(picks, list):
        return []
    out: list[dict] = []
    for row in picks:
        if not isinstance(row, dict):
            continue
        pick = _hit_to_pick(str(row.get("pick_date") or "")[:10], row)
        if pick:
            out.append(pick)
    return out


def _write_ledger(picks: list[dict], path: Path | None = None) -> None:
    ledger = Path(path or LEDGER_PATH)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    # 按选出日+代码去重，旧记录被新扫描覆盖字段
    merged: dict[tuple[str, str], dict] = {}
    for row in picks:
        key = (row["pick_date"], row["code"])
        merged[key] = row
    ordered = sorted(merged.values(), key=lambda r: (r["pick_date"], r["code"]))
    payload = {
        "version": LEDGER_VERSION,
        "strategy": STRATEGY_KEY,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "pick_count": len(ordered),
        "picks": ordered,
    }
    tmp = ledger.with_suffix(f".{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, ledger)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def record_cloud_stair_hits(trade_date: str, bucket: dict | None) -> int:
    """扫描落盘后调用：把当日云阶命中写入持久账本。返回新增/更新条数。"""
    if not isinstance(bucket, dict):
        return 0
    date = str(trade_date or "")[:10]
    if len(date) != 10:
        return 0
    incoming: list[dict] = []
    for hit in bucket.get("hits") or []:
        pick = _hit_to_pick(date, hit if isinstance(hit, dict) else {})
        if pick:
            incoming.append(pick)
    with _ledger_lock:
        existing = _read_ledger()
        before = {(p["pick_date"], p["code"]): p for p in existing}
        for pick in incoming:
            before[(pick["pick_date"], pick["code"])] = pick
        # 当日若命中为空，也保留「扫过」痕迹不删旧票；只 upsert 有票的日子
        _write_ledger(list(before.values()))
    return len(incoming)


def seed_ledger_from_factor_cache(cache_dir: Path | None = None) -> int:
    """把仍留在 factor_cache 的云阶命中灌进账本（一次性补种）。"""
    cache_picks = _iter_factor_cache_hits(cache_dir)
    if not cache_picks:
        return 0
    with _ledger_lock:
        existing = _read_ledger()
        merged = {(p["pick_date"], p["code"]): p for p in existing}
        added = 0
        for pick in cache_picks:
            key = (pick["pick_date"], pick["code"])
            if key not in merged:
                added += 1
            merged[key] = pick
        _write_ledger(list(merged.values()))
    return added


def _iter_factor_cache_hits(cache_dir: Path | None = None) -> list[dict]:
    root = Path(cache_dir or CACHE_DIR)
    if not root.exists():
        return []
    picks: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for path in sorted(root.glob("*.json")):
        pick_date = path.stem
        if len(pick_date) != 10:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("云阶复盘：无法读取缓存 %s: %s", path.name, exc)
            continue
        bucket = _load_bucket(payload)
        if not bucket:
            continue
        for hit in bucket.get("hits") or []:
            pick = _hit_to_pick(pick_date, hit if isinstance(hit, dict) else {})
            if not pick:
                continue
            key = (pick["pick_date"], pick["code"])
            if key in seen:
                continue
            seen.add(key)
            picks.append(pick)
    return picks


def iter_cached_cloud_stair_hits(cache_dir: Path | None = None) -> list[dict]:
    """合并持久账本 + 当前 factor_cache，按选出日新→旧。"""
    # 现有缓存先补种进账本，避免滚动清理前的样本只活在内存一次
    try:
        seed_ledger_from_factor_cache(cache_dir)
    except Exception as exc:
        logger.warning("云阶账本补种失败: %s", exc)

    merged: dict[tuple[str, str], dict] = {}
    for pick in _read_ledger():
        merged[(pick["pick_date"], pick["code"])] = pick
    for pick in _iter_factor_cache_hits(cache_dir):
        merged[(pick["pick_date"], pick["code"])] = pick

    picks = list(merged.values())
    picks.sort(key=lambda row: (row["pick_date"], row["code"]), reverse=True)
    return picks


def _window_return(daily: pd.DataFrame, pick_date: str, hold_days: int) -> float | None:
    result = evaluate_trade(
        daily,
        pick_date,
        hold_days=hold_days,
        policy=DEFAULT_EXECUTION_POLICY,
    )
    if not result.get("available"):
        return None
    return _finite(result.get("net_return"))


def enrich_pick(csv_manager, pick: dict) -> dict:
    """为单条命中补齐隔日涨跌、持有窗口与持有至今收益。"""
    code = pick["code"]
    pick_date = pick["pick_date"]
    daily = _normalize_daily(csv_manager.read_stock(code))
    row = {
        **pick,
        "strategy": STRATEGY_KEY,
        "strategy_name": STRATEGY_NAME,
        "entry_date": None,
        "entry_price": None,
        "next_day_chg": None,
        "ret_to_date": None,
        "holding_sessions_to_date": None,
        "status": "no_price",
        "ret_1": None,
        "ret_5": None,
        "ret_10": None,
        "ret_20": None,
        "execution_policy_version": DEFAULT_EXECUTION_POLICY.version,
    }
    if daily.empty:
        return row

    dates = daily["date"].astype(str).str[:10]
    hits = daily.index[dates == pick_date].tolist()
    if not hits:
        row["status"] = "signal_missing"
        return row
    signal_i = hits[-1]
    entry_i = signal_i + 1
    if entry_i >= len(daily):
        row["status"] = "awaiting_next_session"
        return row

    entry_open = _finite(daily.iloc[entry_i]["open"])
    entry_close = _finite(daily.iloc[entry_i]["close"])
    signal_close = _finite(daily.iloc[signal_i]["close"]) or pick.get("signal_close")
    row["entry_date"] = str(dates.iloc[entry_i])
    row["entry_price"] = entry_open
    row["signal_close"] = signal_close
    if signal_close and signal_close > 0 and entry_close is not None:
        # 隔日涨跌：选出日收盘 → 次日收盘，直观回答「第二天涨了还是跌了」
        row["next_day_chg"] = round((entry_close / signal_close - 1) * 100, 2)

    for hold in HOLD_WINDOWS:
        row[f"ret_{hold}"] = _window_return(daily, pick_date, hold)

    latest_i = len(daily) - 1
    latest_close = _finite(daily.iloc[latest_i]["close"])
    if entry_open and entry_open > 0 and latest_close is not None and latest_i >= entry_i:
        # 持有至今：次日开盘买入 → 最新收盘（毛收益，便于对照「拿到现在」）
        row["ret_to_date"] = round((latest_close / entry_open - 1) * 100, 2)
        row["holding_sessions_to_date"] = int(latest_i - entry_i + 1)
        row["as_of"] = str(dates.iloc[latest_i])
        row["status"] = "tracking" if latest_i == entry_i else "open"
        if latest_i - entry_i >= max(HOLD_WINDOWS):
            row["status"] = "complete"
    else:
        row["status"] = "entry_unavailable"
    return row


def _agg_window(values: list[float | None]) -> dict:
    nums = [v for v in values if v is not None]
    if not nums:
        return {"count": 0, "win_rate": None, "avg": None}
    wins = sum(1 for v in nums if v > 0)
    return {
        "count": len(nums),
        "win_rate": round(wins / len(nums) * 100, 1),
        "avg": round(sum(nums) / len(nums), 2),
    }


def summarize_picks(picks: list[dict]) -> dict:
    """从明细汇总：隔日表现、持有窗口、建议卖点。"""
    next_day = _agg_window([p.get("next_day_chg") for p in picks])
    to_date = _agg_window([p.get("ret_to_date") for p in picks])
    windows = {f"ret_{n}": _agg_window([p.get(f"ret_{n}") for p in picks]) for n in HOLD_WINDOWS}

    scored = []
    for n in HOLD_WINDOWS:
        agg = windows[f"ret_{n}"]
        if agg["count"] <= 0 or agg["avg"] is None:
            continue
        scored.append(
            {
                "hold_sessions": n,
                "label": f"T+{n}",
                "avg": agg["avg"],
                "win_rate": agg["win_rate"],
                "count": agg["count"],
            }
        )
    best = None
    if scored:
        # 先比平均收益，再比胜率——回答「大概拿几天更合适」
        best = max(scored, key=lambda item: (item["avg"], item["win_rate"] or 0))

    holding_days = [
        p.get("holding_sessions_to_date")
        for p in picks
        if isinstance(p.get("holding_sessions_to_date"), int)
    ]
    avg_holding = round(sum(holding_days) / len(holding_days), 1) if holding_days else None

    return {
        "pick_count": len(picks),
        "next_day": next_day,
        "to_date": to_date,
        "windows": windows,
        "recommended_hold": best,
        "avg_holding_sessions_observed": avg_holding,
        "execution_note": (
            "买入按选出日次日开盘近似成交；隔日涨跌按选出日收盘到次日收盘；"
            "持有窗口净收益含手续费/印花税/滑点近似。"
        ),
    }


def build_cloud_stair_review(csv_manager, *, limit: int = 200) -> dict:
    """组装云阶复盘 API 载荷。"""
    raw = iter_cached_cloud_stair_hits()
    if not raw:
        return {
            "available": False,
            "reason": "cloud_stair_cache_empty",
            "strategy": STRATEGY_KEY,
            "strategy_name": STRATEGY_NAME,
            "picks": [],
            "summary": summarize_picks([]),
        }

    capped = raw[: max(1, min(int(limit), 500))]
    picks = [enrich_pick(csv_manager, pick) for pick in capped]
    dates = sorted({p["pick_date"] for p in picks})
    return {
        "available": True,
        "strategy": STRATEGY_KEY,
        "strategy_name": STRATEGY_NAME,
        "picks": picks,
        "summary": summarize_picks(picks),
        "date_span": {"from": dates[0], "to": dates[-1]} if dates else None,
        "cache_dates": len({p["pick_date"] for p in raw}),
        "truncated": len(raw) > len(capped),
        "total_cached_picks": len(raw),
    }
