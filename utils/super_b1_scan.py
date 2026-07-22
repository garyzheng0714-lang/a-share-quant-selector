"""超级B1全市场扫描 - 文件缓存 + 并行读取（缓存模式与 sector_rotation 一致）

独立模块：不写旧 results/performance 表，只发布与当前 snapshot 绑定的候选缓存；
正式表现统计只读取 canonical decision outcomes。

诚实原则落地（2026-07-12 review 修正）：
- 市值从 data/stock_market_cap.json 取 circ_mv（真流通市值=FINANCE(40)同口径），
  缺该票时退 total_mv，再退 CSV market_cap 列；仍缺失的票计数上报，不静默吞掉
- trade_date 统一用锚点股探测（多只取 max），命中里日期≠trade_date 的陈旧信号
  （停牌/断更股的旧K线）一律丢弃并计数——旧信号绝不能被当成今天的信号
- 任一扫描异常都返回 available:false 且不写缓存，损坏行情或代码错误
  不能伪装成"今日无信号"的正常空态
"""

import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from utils.artifact_integrity import artifact_is_valid, seal_artifact
from utils.decision_versions import cache_identity
from utils.market_snapshot import read_snapshot_metadata

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"
CACHE_FILE = DATA_DIR / "super_b1_cache.json"
CACHE_SCHEMA_VERSION = 5
_lock = threading.Lock()

# 需要的K线根数：MA114 预热 + EXIST(...,200) 回看 + 余量
NROWS = 400

# 数据日期锚点股（多只取 max，单只停牌不会把基准带歪）
ANCHOR_CODES = ("000001", "600030", "600036", "600519")


def _load_cap_map(csv_manager) -> dict:
    """{code: 市值(元)}，circ_mv 优先、退 total_mv。文件缺失返回空 dict."""
    raw, _ = read_snapshot_metadata(
        "stock_market_cap.json",
        getattr(csv_manager, "base_data_dir", DATA_DIR),
        snapshot_id=getattr(csv_manager, "snapshot_id", None),
    )
    if not isinstance(raw, dict):
        return {}
    out = {}
    for code, v in raw.items():
        if not isinstance(v, dict):
            continue
        cap = v.get("circ_mv") or v.get("total_mv")
        if isinstance(cap, (int, float)) and cap > 0:
            out[code] = float(cap)
    return out


def _scan_one(args):
    """返回 (hit|None, error: bool, cap_missing: bool)."""
    csv_manager, code, name, cap = args
    try:
        df = csv_manager.read_stock(code, nrows=NROWS)
        if df.empty:
            return None, False, False
        from strategy.super_b1 import compute_super_b1

        hit = compute_super_b1(df, code, market_cap=cap)
        if hit and hit.get("cap_missing"):
            return None, False, True
        if hit:
            from utils.technical import weekly_four_ma_bullish

            weekly_passed, weekly_detail = weekly_four_ma_bullish(df)
            hit["weekly"] = {"passed": weekly_passed, **weekly_detail}
            hit["code"] = code
            hit["name"] = name
        return hit, False, False
    except Exception as e:
        logger.warning("超级B1扫描 %s 失败: %s", code, e)
        return None, True, False


def _latest_data_date(csv_manager) -> str:
    """全局最新交易日：多只锚点股取 max（镜像 sector_rotation 的做法）."""
    dates = []
    for code in ANCHOR_CODES:
        try:
            df = csv_manager.read_stock(code, nrows=1)
            if not df.empty:
                dates.append(str(df["date"].iloc[0])[:10])
        except Exception:
            continue
    return max(dates) if dates else ""


def compute_scan(csv_manager, stock_names: dict) -> dict:
    """全市场扫描。返回 {available, trade_date, total_scanned, hits, ...统计}."""
    codes = [c for c in csv_manager.list_all_stocks() if c.isdigit() and len(c) == 6]
    if not codes:
        return {"available": False, "reason": "本地无行情数据"}

    trade_date = _latest_data_date(csv_manager)
    cap_map = _load_cap_map(csv_manager)

    invalid_kw = ("退", "未知", "退市", "已退")
    tasks = []
    for code in codes:
        name = stock_names.get(code, "")
        if any(kw in name for kw in invalid_kw) or name.startswith(("ST", "*ST")):
            continue
        tasks.append((csv_manager, code, name, cap_map.get(code)))

    hits, errors, cap_missing, stale = [], 0, 0, 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        for hit, err, missing in ex.map(_scan_one, tasks):
            if err:
                errors += 1
            elif missing:
                cap_missing += 1
            elif hit:
                if trade_date and hit["date"] != trade_date:
                    stale += 1  # 停牌/断更股的旧K线信号，不能冒充今天
                else:
                    hits.append(hit)

    if errors:
        logger.error("超级B1扫描存在异常: %d/%d 只失败，不写缓存", errors, len(tasks))
        return {
            "available": False,
            "reason": f"扫描异常（{errors}/{len(tasks)} 只失败）",
        }

    hits.sort(key=lambda h: (h["J"], h["code"]))  # J 越低越超卖，排前面
    if errors or cap_missing or stale:
        logger.warning(
            "超级B1扫描统计: 失败 %d / 缺市值 %d / 陈旧信号丢弃 %d（共 %d 只）",
            errors,
            cap_missing,
            stale,
            len(tasks),
        )
    return {
        "available": True,
        "schema_version": CACHE_SCHEMA_VERSION,
        "trade_date": trade_date,
        "total_scanned": len(tasks),
        "hits": hits,
        "errors": errors,
        "cap_missing": cap_missing,
        "stale_dropped": stale,
        "cap_note": "流通市值取自市值缓存(circ_mv)，缺失票以总市值近似",
        **cache_identity(csv_manager, "super_b1", CACHE_SCHEMA_VERSION),
    }


def read_cached_super_b1(csv_manager) -> dict:
    """读取与当前 snapshot/策略版本绑定的扫描产物，不缺省重算。"""
    if not CACHE_FILE.exists():
        return {
            "available": False,
            "reason": "super_b1_snapshot_not_ready",
            "retry_via": "daily_close_pipeline",
        }
    try:
        with open(CACHE_FILE, encoding="utf-8") as handle:
            cached = json.load(handle)
    except (OSError, json.JSONDecodeError):
        cached = {}
    identity = cache_identity(csv_manager, "super_b1", CACHE_SCHEMA_VERSION)
    valid = bool(
        cached.get("available")
        and artifact_is_valid(cached)
        and cached.get("schema_version") == CACHE_SCHEMA_VERSION
        and identity.get("cache_key")
        and cached.get("cache_key") == identity.get("cache_key")
    )
    if valid:
        return cached
    return {
        "available": False,
        "reason": "super_b1_snapshot_not_ready",
        "retry_via": "daily_close_pipeline",
    }


def get_super_b1(csv_manager, stock_names: dict, force: bool = False) -> dict:
    """带文件缓存：数据日期没变就直接用缓存（含双检锁防并发重算）."""
    if not force:
        cached = read_cached_super_b1(csv_manager)
        if cached.get("available"):
            return cached
    with _lock:
        if not force:
            cached = read_cached_super_b1(csv_manager)
            if cached.get("available"):
                return cached
        result = compute_scan(csv_manager, stock_names)
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
                logger.warning("超级B1缓存写入失败: %s", e)
                if tmp is not None:
                    try:
                        tmp.unlink(missing_ok=True)
                    except OSError:
                        logger.warning("超级B1临时缓存清理失败: %s", tmp)
                return {
                    "available": False,
                    "reason": "super_b1_cache_write_failed",
                    "trade_date": result.get("trade_date"),
                }
        return result
