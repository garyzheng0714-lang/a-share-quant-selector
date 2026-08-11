"""通用策略票级复盘：每日命中持久账本 + 隔日/持有路径/卖点统计。

口径（与生产执行模型一致）：
- 选出日 T = 因子信号收盘日
- 买入 = T+1 开盘（含滑点/费用见 evaluate_trade）
- 隔日涨跌 = T 收盘 → 次日收盘
- 持有至今 = T+1 开盘 → 最新收盘（毛收益）
- 持有窗口 ret_n = evaluate_trade(hold_days=n) 净收益
- path = 入场后逐日浮盈路径（最多 20 个交易日）

数据：
1. data/strategy_pick_ledgers/{strategy}.json —— 全策略持久账本（不随 factor_cache 12 日滚动删除）
2. data/factor_cache/*.json —— 现有缓存补齐
3. 兼容旧云阶账本 data/cloud_stair_pick_ledger.json
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from utils.execution_model import (
    DEFAULT_EXECUTION_POLICY,
    evaluate_trade,
    load_exchange_sessions,
)
from utils.factor_scan import CACHE_DIR, DATA_DIR

logger = logging.getLogger(__name__)

HOLD_WINDOWS = (1, 5, 10, 20)
PATH_SESSIONS = 20
LEDGER_DIR = DATA_DIR / "strategy_pick_ledgers"
LEGACY_CLOUD_LEDGER = DATA_DIR / "cloud_stair_pick_ledger.json"
LEDGER_VERSION = 1
_ledger_lock = threading.Lock()

# 命中里额外保留的信号字段（有则写入，便于弹窗展示）
_SIGNAL_EXTRA_KEYS = (
    "J",
    "RSI",
    "pct_change",
    "volume_ratio",
    "wave_gain_pct",
    "peak_date",
    "industry",
    "cap_yi",
    "detail",
    "reason",
    "stage",
)


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
    return (
        daily.sort_values("date")
        .drop_duplicates("date", keep="last")
        .reset_index(drop=True)
    )


def _strategy_meta(strategy: str) -> tuple[str, str]:
    try:
        from strategy.factors import FACTOR_REGISTRY

        meta = FACTOR_REGISTRY.get(strategy) or {}
        name = str(meta.get("name") or strategy)
        group = str(meta.get("group") or "")
        return name, group
    except Exception:
        return strategy, ""


def _ledger_path(strategy: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in strategy)
    return LEDGER_DIR / f"{safe}.json"


def _hit_to_pick(strategy: str, pick_date: str, hit: dict) -> dict | None:
    code = str(hit.get("code") or "").strip()
    if not code or len(pick_date) != 10:
        return None
    extras = {}
    for key in _SIGNAL_EXTRA_KEYS:
        if key in hit and hit.get(key) is not None:
            extras[key] = hit.get(key)
    return {
        "strategy": strategy,
        "pick_date": pick_date,
        "code": code,
        "name": str(hit.get("name") or code),
        "signal_close": _finite(hit.get("close")),
        "signal_pct_change": _finite(hit.get("pct_change")),
        "industry": str(hit.get("industry") or extras.get("industry") or ""),
        "signal": extras,
    }


def _read_ledger(strategy: str) -> list[dict]:
    path = _ledger_path(strategy)
    rows: list[dict] = []
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            picks = payload.get("picks") if isinstance(payload, dict) else None
            if isinstance(picks, list):
                rows.extend(p for p in picks if isinstance(p, dict))
        except Exception as exc:
            logger.warning("策略账本读取失败 %s: %s", strategy, exc)

    # 兼容旧云阶单文件账本
    if strategy == "cloud_stair" and LEGACY_CLOUD_LEDGER.exists():
        try:
            legacy = json.loads(LEGACY_CLOUD_LEDGER.read_text(encoding="utf-8"))
            for row in legacy.get("picks") or []:
                if isinstance(row, dict):
                    rows.append(row)
        except Exception as exc:
            logger.warning("旧云阶账本读取失败: %s", exc)

    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        pick = _hit_to_pick(
            strategy,
            str(row.get("pick_date") or "")[:10],
            row if "code" in row else row,
        )
        # row 已是 pick 形态时也走一遍规范化
        if pick is None and row.get("code"):
            pick = _hit_to_pick(strategy, str(row.get("pick_date") or "")[:10], row)
        if not pick:
            continue
        key = (pick["pick_date"], pick["code"])
        if key in seen:
            continue
        seen.add(key)
        out.append(pick)
    return out


def _write_ledger(strategy: str, picks: list[dict]) -> None:
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    path = _ledger_path(strategy)
    merged: dict[tuple[str, str], dict] = {}
    for row in picks:
        merged[(row["pick_date"], row["code"])] = row
    ordered = sorted(merged.values(), key=lambda r: (r["pick_date"], r["code"]))
    name, group = _strategy_meta(strategy)
    payload = {
        "version": LEDGER_VERSION,
        "strategy": strategy,
        "strategy_name": name,
        "group": group,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "pick_count": len(ordered),
        "picks": ordered,
    }
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def record_strategy_hits(strategy: str, trade_date: str, bucket: dict | None) -> int:
    """扫描落盘后：把某策略当日命中写入持久账本。"""
    if not strategy or not isinstance(bucket, dict):
        return 0
    date = str(trade_date or "")[:10]
    if len(date) != 10:
        return 0
    incoming = []
    for hit in bucket.get("hits") or []:
        if not isinstance(hit, dict):
            continue
        pick = _hit_to_pick(strategy, date, hit)
        if pick:
            incoming.append(pick)
    if not incoming:
        return 0
    with _ledger_lock:
        existing = _read_ledger(strategy)
        merged = {(p["pick_date"], p["code"]): p for p in existing}
        for pick in incoming:
            merged[(pick["pick_date"], pick["code"])] = pick
        _write_ledger(strategy, list(merged.values()))
    return len(incoming)


def record_strategy_scan_results(trade_date: str, results: dict | None) -> int:
    """写入当日全部策略命中（在 factor_cache 滚动清理前调用）。"""
    if not isinstance(results, dict):
        return 0
    total = 0
    for strategy, bucket in results.items():
        if strategy.startswith("_"):
            continue
        total += record_strategy_hits(str(strategy), trade_date, bucket)
    return total


def _iter_cache_hits(strategy: str, cache_dir: Path | None = None) -> list[dict]:
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
        except Exception:
            continue
        results = (
            payload.get("results")
            if isinstance(payload.get("results"), dict)
            else payload
        )
        if not isinstance(results, dict):
            continue
        bucket = results.get(strategy)
        if not isinstance(bucket, dict):
            continue
        for hit in bucket.get("hits") or []:
            if not isinstance(hit, dict):
                continue
            pick = _hit_to_pick(strategy, pick_date, hit)
            if not pick:
                continue
            key = (pick["pick_date"], pick["code"])
            if key in seen:
                continue
            seen.add(key)
            picks.append(pick)
    return picks


def seed_strategy_from_cache(strategy: str, cache_dir: Path | None = None) -> int:
    cache_picks = _iter_cache_hits(strategy, cache_dir)
    if not cache_picks:
        return 0
    with _ledger_lock:
        existing = _read_ledger(strategy)
        merged = {(p["pick_date"], p["code"]): p for p in existing}
        added = 0
        for pick in cache_picks:
            key = (pick["pick_date"], pick["code"])
            if key not in merged:
                added += 1
            merged[key] = pick
        _write_ledger(strategy, list(merged.values()))
    return added


def iter_strategy_hits(strategy: str, cache_dir: Path | None = None) -> list[dict]:
    """只读合并持久账本与当前缓存；HTTP GET 不得隐式补种写盘。"""
    merged: dict[tuple[str, str], dict] = {}
    for pick in _read_ledger(strategy):
        merged[(pick["pick_date"], pick["code"])] = pick
    for pick in _iter_cache_hits(strategy, cache_dir):
        merged[(pick["pick_date"], pick["code"])] = pick
    picks = list(merged.values())
    picks.sort(key=lambda row: (row["pick_date"], row["code"]), reverse=True)
    return picks


def _window_trade(
    daily: pd.DataFrame,
    pick_date: str,
    hold_days: int,
    trading_sessions: list[str],
) -> dict:
    result = evaluate_trade(
        daily,
        pick_date,
        hold_days=hold_days,
        trading_sessions=trading_sessions,
        policy=DEFAULT_EXECUTION_POLICY,
    )
    if not result.get("available"):
        return {
            "net_return": None,
            "max_gain": None,
            "max_drawdown": None,
            "exit_date": None,
            "exit_price": None,
            "gross_return": None,
            "reason": result.get("reason"),
        }
    return {
        "net_return": _finite(result.get("net_return")),
        "max_gain": _finite(result.get("max_gain")),
        "max_drawdown": _finite(result.get("max_drawdown")),
        "exit_date": result.get("exit_date"),
        "exit_price": _finite(result.get("exit_price")),
        "gross_return": _finite(result.get("gross_return")),
        "reason": result.get("reason") or result.get("execution_status"),
    }


def _build_path(daily: pd.DataFrame, entry_i: int, entry_open: float) -> list[dict]:
    if not entry_open or entry_open <= 0:
        return []
    dates = daily["date"].astype(str).str[:10]
    end = min(entry_i + PATH_SESSIONS, len(daily))
    path = []
    for i in range(entry_i, end):
        open_ = _finite(daily.iloc[i]["open"])
        high = _finite(daily.iloc[i]["high"])
        low = _finite(daily.iloc[i]["low"])
        close = _finite(daily.iloc[i]["close"])
        path.append(
            {
                "session": i - entry_i + 1,
                "date": str(dates.iloc[i]),
                "open_ret": round((open_ / entry_open - 1) * 100, 2)
                if open_ is not None
                else None,
                "high_ret": round((high / entry_open - 1) * 100, 2)
                if high is not None
                else None,
                "low_ret": round((low / entry_open - 1) * 100, 2)
                if low is not None
                else None,
                "close_ret": round((close / entry_open - 1) * 100, 2)
                if close is not None
                else None,
                "close": close,
            }
        )
    return path


def enrich_pick(
    csv_manager,
    pick: dict,
    *,
    strategy: str,
    strategy_name: str,
    daily_cache: dict[str, pd.DataFrame] | None = None,
    trading_sessions: list[str] | None = None,
) -> dict:
    code = pick["code"]
    pick_date = pick["pick_date"]
    if daily_cache is not None:
        if code not in daily_cache:
            daily_cache[code] = _normalize_daily(csv_manager.read_stock(code))
        daily = daily_cache[code]
    else:
        daily = _normalize_daily(csv_manager.read_stock(code))
    if trading_sessions is None:
        trading_sessions = load_exchange_sessions(getattr(csv_manager, "data_dir", ""))

    row = {
        **pick,
        "strategy": strategy,
        "strategy_name": strategy_name,
        "entry_date": None,
        "entry_price": None,
        "entry_gap_pct": None,
        "next_day_chg": None,
        "next_open_chg": None,
        "ret_to_date": None,
        "mfe_to_date": None,
        "mae_to_date": None,
        "holding_sessions_to_date": None,
        "as_of": None,
        "status": "no_price",
        "windows": {},
        "path": [],
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
    if signal_close and signal_close > 0 and entry_open is not None:
        row["entry_gap_pct"] = round((entry_open / signal_close - 1) * 100, 2)
        row["next_open_chg"] = row["entry_gap_pct"]
    if signal_close and signal_close > 0 and entry_close is not None:
        row["next_day_chg"] = round((entry_close / signal_close - 1) * 100, 2)

    windows = {}
    for hold in HOLD_WINDOWS:
        trade = _window_trade(daily, pick_date, hold, trading_sessions)
        windows[f"ret_{hold}"] = trade
        row[f"ret_{hold}"] = trade["net_return"]
        row[f"max_gain_{hold}"] = trade["max_gain"]
        row[f"max_dd_{hold}"] = trade["max_drawdown"]
        row[f"exit_date_{hold}"] = trade["exit_date"]
    row["windows"] = windows

    if entry_open and entry_open > 0:
        row["path"] = _build_path(daily, entry_i, entry_open)
        if row["path"]:
            highs = [
                p["high_ret"] for p in row["path"] if p.get("high_ret") is not None
            ]
            lows = [p["low_ret"] for p in row["path"] if p.get("low_ret") is not None]
            if highs:
                row["mfe_to_date"] = max(highs)
            if lows:
                row["mae_to_date"] = min(lows)

    latest_i = len(daily) - 1
    latest_close = _finite(daily.iloc[latest_i]["close"])
    if (
        entry_open
        and entry_open > 0
        and latest_close is not None
        and latest_i >= entry_i
    ):
        row["ret_to_date"] = round((latest_close / entry_open - 1) * 100, 2)
        row["holding_sessions_to_date"] = int(latest_i - entry_i + 1)
        row["as_of"] = str(dates.iloc[latest_i])
        row["latest_close"] = latest_close
        row["status"] = "tracking" if latest_i == entry_i else "open"
        if latest_i - entry_i >= max(HOLD_WINDOWS):
            row["status"] = "complete"
    else:
        row["status"] = "entry_unavailable"
    return row


def _agg_window(values: list[float | None]) -> dict:
    nums = [v for v in values if v is not None]
    if not nums:
        return {
            "count": 0,
            "win_rate": None,
            "avg": None,
            "median": None,
            "best": None,
            "worst": None,
        }
    sorted_nums = sorted(nums)
    mid = len(sorted_nums) // 2
    if len(sorted_nums) % 2:
        median = round(sorted_nums[mid], 2)
    else:
        median = round((sorted_nums[mid - 1] + sorted_nums[mid]) / 2, 2)
    wins = sum(1 for v in nums if v > 0)
    return {
        "count": len(nums),
        "win_rate": round(wins / len(nums) * 100, 1),
        "avg": round(sum(nums) / len(nums), 2),
        "median": median,
        "best": round(max(nums), 2),
        "worst": round(min(nums), 2),
    }


def _by_pick_date(picks: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for pick in picks:
        groups.setdefault(pick["pick_date"], []).append(pick)
    out = []
    for date in sorted(groups.keys()):
        bucket = groups[date]
        out.append(
            {
                "pick_date": date,
                "count": len(bucket),
                "next_day": _agg_window([p.get("next_day_chg") for p in bucket]),
                "to_date": _agg_window([p.get("ret_to_date") for p in bucket]),
                "ret_5": _agg_window([p.get("ret_5") for p in bucket]),
            }
        )
    return out


def summarize_picks(picks: list[dict]) -> dict:
    next_day = _agg_window([p.get("next_day_chg") for p in picks])
    to_date = _agg_window([p.get("ret_to_date") for p in picks])
    windows = {
        f"ret_{n}": _agg_window([p.get(f"ret_{n}") for p in picks])
        for n in HOLD_WINDOWS
    }
    mfe = _agg_window([p.get("mfe_to_date") for p in picks])
    mae = _agg_window([p.get("mae_to_date") for p in picks])

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
                "median": agg["median"],
                "count": agg["count"],
            }
        )
    best = (
        max(scored, key=lambda item: (item["avg"], item["win_rate"] or 0))
        if scored
        else None
    )

    holding_days = [
        p.get("holding_sessions_to_date")
        for p in picks
        if isinstance(p.get("holding_sessions_to_date"), int)
    ]
    avg_holding = (
        round(sum(holding_days) / len(holding_days), 1) if holding_days else None
    )

    # 按持有至今收益排序的极值票，方便一眼看见贡献/拖累
    ranked = [p for p in picks if p.get("ret_to_date") is not None]
    ranked.sort(key=lambda p: p["ret_to_date"], reverse=True)
    top = [
        {
            "code": p["code"],
            "name": p["name"],
            "pick_date": p["pick_date"],
            "ret_to_date": p["ret_to_date"],
            "next_day_chg": p.get("next_day_chg"),
        }
        for p in ranked[:3]
    ]
    bottom = [
        {
            "code": p["code"],
            "name": p["name"],
            "pick_date": p["pick_date"],
            "ret_to_date": p["ret_to_date"],
            "next_day_chg": p.get("next_day_chg"),
        }
        for p in ranked[-3:][::-1]
    ]

    return {
        "pick_count": len(picks),
        "next_day": next_day,
        "to_date": to_date,
        "windows": windows,
        "mfe": mfe,
        "mae": mae,
        "recommended_hold": best,
        "avg_holding_sessions_observed": avg_holding,
        "by_date": _by_pick_date(picks),
        "top_picks": top,
        "bottom_picks": bottom,
        "execution_note": (
            "次日开盘买入近似；隔日=信号收盘→次日收盘；"
            "T+n 净收益含成本；路径为入场后逐日浮盈。"
        ),
    }


def build_strategy_review(
    csv_manager, strategy: str, *, limit: int = 300, include_path: bool = True
) -> dict:
    name, group = _strategy_meta(strategy)
    raw = iter_strategy_hits(strategy)
    if not raw:
        return {
            "available": False,
            "reason": "strategy_cache_empty",
            "strategy": strategy,
            "strategy_name": name,
            "group": group,
            "picks": [],
            "summary": summarize_picks([]),
        }

    capped = raw[: max(1, min(int(limit), 1000))]
    daily_cache: dict[str, pd.DataFrame] = {}
    trading_sessions = load_exchange_sessions(getattr(csv_manager, "data_dir", ""))
    picks = [
        enrich_pick(
            csv_manager,
            pick,
            strategy=strategy,
            strategy_name=name,
            daily_cache=daily_cache,
            trading_sessions=trading_sessions,
        )
        for pick in capped
    ]
    if not include_path:
        for pick in picks:
            pick["path"] = []

    dates = sorted({p["pick_date"] for p in picks})
    return {
        "available": True,
        "strategy": strategy,
        "strategy_name": name,
        "group": group,
        "picks": picks,
        "summary": summarize_picks(picks),
        "date_span": {"from": dates[0], "to": dates[-1]} if dates else None,
        "cache_dates": len({p["pick_date"] for p in raw}),
        "truncated": len(raw) > len(capped),
        "total_cached_picks": len(raw),
    }


def list_strategy_catalog(cache_dir: Path | None = None) -> list[dict]:
    """策略目录：有多少历史票、最近选出日——供前端秒切选择器。"""
    from strategy.factors import FACTOR_REGISTRY, GROUP_ORDER

    catalog = []
    for key, meta in FACTOR_REGISTRY.items():
        hits = iter_strategy_hits(key, cache_dir)
        dates = sorted({h["pick_date"] for h in hits})
        catalog.append(
            {
                "key": key,
                "name": meta.get("name") or key,
                "group": meta.get("group") or "",
                "pick_count": len(hits),
                "date_span": {"from": dates[0], "to": dates[-1]} if dates else None,
                "has_data": bool(hits),
            }
        )
    catalog.sort(
        key=lambda item: (
            GROUP_ORDER.index(item["group"]) if item["group"] in GROUP_ORDER else 99,
            0 if item["has_data"] else 1,
            -item["pick_count"],
            item["name"],
        )
    )
    return catalog


def build_review_bundle(csv_manager, *, limit: int = 300) -> dict:
    """一次拉齐目录 + 全部有数据策略的复盘（供浏览器本地缓存秒切）。"""
    catalog = list_strategy_catalog()
    reviews: dict[str, dict] = {}
    for item in catalog:
        if not item["has_data"]:
            continue
        reviews[item["key"]] = build_strategy_review(
            csv_manager, item["key"], limit=limit, include_path=True
        )
    return {
        "available": bool(reviews),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "catalog": catalog,
        "reviews": reviews,
        "default_strategy": next(
            (c["key"] for c in catalog if c["key"] == "cloud_stair" and c["has_data"]),
            next((c["key"] for c in catalog if c["has_data"]), "cloud_stair"),
        ),
    }
