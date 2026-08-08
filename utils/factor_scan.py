"""策略因子全市场扫描引擎 - 一次读CSV多策略共算（第三期核心）

28 个策略因子若逐策略全市场扫描（28 × 5000 只 × 读CSV）根本跑不动。
本引擎的关键设计：每只股票读一次 CSV、建一个 FactorContext（同参指标缓存），
把"本次请求的策略集"一口气全算——扫描成本从 O(策略数×股票数×IO)
降到 O(股票数×IO + 股票数×策略数×纯计算)。

缓存：data/factor_cache/{trade_date}.json，按策略分桶，支持增量补算
（同一日期先扫了 A 策略，再请求 B 策略时只算 B 并合并进缓存文件）。

date 参数只用于 research-only 缓存：把当前绑定 snapshot 中的行情截断到 <= date。
它不是历史 PIT 快照或发布证据。截断后最后一根 K 线日期 != date 的股票
（当日停牌/断更）直接跳过——旧信号不能冒充该日信号。

口径与 super_b1_scan 保持一致：ST/退市名称过滤、锚点股定 trade_date、
任一文件或因子计算异常都返回 available:false 且不写缓存，
防止损坏数据被伪装成“未命中”；主板过滤留给 API 层。
"""

import json
import logging
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from utils.artifact_integrity import artifact_is_valid, seal_artifact
from utils.decision_versions import cache_identity

logger = logging.getLogger(__name__)

# 交易日必须是纯日期格式——date 来自 HTTP 参数，直接拼文件名，
# 不校验会被 "../stock_names" 之类的输入注入成任意路径写（review 确认的真实漏洞）
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

DATA_DIR = Path(__file__).parent.parent / "data"
CACHE_DIR = DATA_DIR / "factor_cache"
MAX_CACHE_FILES = 12  # 只保留最近若干个交易日的缓存文件
CACHE_SCHEMA_VERSION = 3
ANCHOR_CODES = ("000001", "600030", "600036", "600519")
_lock = threading.Lock()


def _latest_data_date(csv_manager) -> str:
    dates = []
    for code in ANCHOR_CODES:
        try:
            df = csv_manager.read_stock(code, nrows=1)
            if not df.empty:
                dates.append(str(df["date"].iloc[0])[:10])
        except Exception:
            continue
    return max(dates) if dates else ""


def recent_trade_dates(csv_manager, limit=60) -> list:
    """最近的交易日列表（新→旧），供前端日期导航。锚点股日期并集."""
    seen = set()
    for code in ANCHOR_CODES:
        try:
            df = csv_manager.read_stock(code, nrows=limit)
            for d in df["date"].astype(str).str[:10]:
                seen.add(d)
        except Exception:
            continue
    return sorted(seen, reverse=True)[:limit]


def _normalize(df):
    """CSV → 正序、float 化。返回 None 表示不可用."""
    if df is None or df.empty or len(df) < 30:
        return None
    d = df
    if len(d) > 1 and str(d["date"].iloc[0]) > str(d["date"].iloc[-1]):
        d = d.iloc[::-1].reset_index(drop=True)
    return d


def _scan_one(args):
    """单只股票跑一组策略。返回 (code, {strategy: hit}, error, valid).

    valid=False 表示该股在目标日没有可用K线（停牌/断更/数据未覆盖），
    与"计算了但无命中"必须区分——全市场 valid 全 0 说明该日期本身没数据，
    不能伪装成"当日全部策略 0 命中"的正常空态。
    """
    csv_manager, code, name, strategies, registry, date = args
    try:
        df = _normalize(csv_manager.read_stock(code))
        if df is None:
            return code, {}, False, False
        dates = df["date"].astype(str).str[:10]
        if date:
            mask = dates <= date
            if not mask.any():
                return code, {}, False, False
            df = df[mask].reset_index(drop=True)
            dates = dates[mask].reset_index(drop=True)
        last_date = dates.iloc[-1]
        # 目标日没有这根K线（停牌/断更）→ 不产出信号
        target = date or ""
        if target and last_date != target:
            return code, {}, False, False

        from strategy.factor_lib import FactorContext

        ctx = FactorContext(df)
        out = {}
        calculation_failed = False
        for key in strategies:
            meta = registry[key]
            if len(df) < meta["min_bars"]:
                continue
            try:
                hit = meta["fn"](ctx)
            except Exception as e:  # 任一计算错误都使本次全市场产物失效
                logger.warning("因子 %s 计算 %s 失败: %s", key, code, e)
                calculation_failed = True
                break
            if hit:
                hit["code"] = code
                hit["name"] = name
                hit["date"] = last_date
                out[key] = hit
        if calculation_failed:
            return code, {}, True, False
        return code, out, False, True
    except Exception as e:
        logger.warning("因子扫描 %s 失败: %s", code, e)
        return code, {}, True, False


def _cache_path(trade_date: str) -> Path:
    if not _DATE_RE.match(trade_date or ""):
        raise ValueError(f"非法交易日: {trade_date!r}")
    return CACHE_DIR / f"{trade_date}.json"


def _load_cache_envelope(trade_date: str, csv_manager=None) -> dict:
    p = _cache_path(trade_date)
    if p.exists():
        try:
            with open(p, encoding="utf-8") as f:
                payload = json.load(f)
            if not artifact_is_valid(payload):
                return {}
            if csv_manager is not None:
                expected = cache_identity(
                    csv_manager, "factor_scan", CACHE_SCHEMA_VERSION
                )
                if payload.get("_cache_key") != expected.get("cache_key"):
                    return {}
            return payload
        except Exception:
            pass
    return {}


def _load_cache(trade_date: str, csv_manager=None) -> dict:
    envelope = _load_cache_envelope(trade_date, csv_manager)
    if csv_manager is None:
        return envelope
    return envelope.get("results") or {}


def _save_cache(trade_date: str, data: dict, csv_manager) -> bool:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        # 原子写：快路径读缓存不持锁，直接写目标文件会让并发读者读到半截 JSON
        target = _cache_path(trade_date)
        tmp = target.with_suffix(f".{os.getpid()}.tmp")
        identity = cache_identity(csv_manager, "factor_scan", CACHE_SCHEMA_VERSION)
        payload = seal_artifact(
            {
                "_cache_schema_version": CACHE_SCHEMA_VERSION,
                "_cache_key": identity.get("cache_key"),
                "_cache_identity": identity,
                "results": data,
            }
        )
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, target)
    except Exception as e:
        logger.warning("因子缓存写入失败: %s", e)
        if tmp is not None:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                logger.warning("因子临时缓存清理失败: %s", tmp)
        return False

    # 全策略复盘账本：滚动清理前落盘，避免 12 日缓存窗口抹掉历史命中
    try:
        from utils.strategy_review import record_strategy_scan_results

        record_strategy_scan_results(trade_date, data)
    except Exception as exc:
        logger.warning("策略复盘账本写入失败: %s", exc)

    # 滚动清理旧缓存
    files = sorted(CACHE_DIR.glob("*.json"))
    for old in files[:-MAX_CACHE_FILES]:
        try:
            old.unlink()
        except Exception:
            pass
    return True


def compute_scan(
    csv_manager,
    stock_names: dict,
    strategies: list,
    date: str = "",
    trade_date: str = "",
) -> dict:
    """全市场扫描指定策略集。返回 {available, trade_date, results: {key: {...}}}.

    trade_date 由调用方传入统一口径（get_factor_hits 已探测过）——若在此重新探测，
    等锁期间数据更新会导致内外两个日期不一致，扫描结果写进错误日期的缓存文件。
    """
    from strategy.factors import FACTOR_REGISTRY

    registry = FACTOR_REGISTRY
    strategies = [s for s in strategies if s in registry]
    if not strategies:
        return {"available": False, "reason": "未知策略"}

    codes = [c for c in csv_manager.list_all_stocks() if c.isdigit() and len(c) == 6]
    if not codes:
        return {"available": False, "reason": "本地无行情数据"}

    trade_date = trade_date or date or _latest_data_date(csv_manager)
    if not trade_date:
        return {"available": False, "reason": "无法确定交易日"}

    invalid_kw = ("退", "未知", "退市", "已退")
    # 最新日与历史日统一按 trade_date 截断计算：截断后末根K线 != trade_date 的
    # 股票（停牌/断更/等锁期间数据超前更新）一律跳过，陈旧信号无从混入
    target = date or trade_date
    tasks = []
    for code in codes:
        name = stock_names.get(code, "")
        if any(kw in name for kw in invalid_kw) or name.startswith(("ST", "*ST")):
            continue
        tasks.append((csv_manager, code, name, strategies, registry, target))

    buckets = {k: [] for k in strategies}
    errors = valid_n = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        for _code, hits, err, valid in ex.map(_scan_one, tasks):
            if err:
                errors += 1
                continue
            if valid:
                valid_n += 1
            for key, hit in hits.items():
                buckets[key].append(hit)

    if errors:
        logger.error("因子扫描存在异常: %d/%d 失败，不写缓存", errors, len(tasks))
        return {
            "available": False,
            "reason": f"扫描异常（{errors}/{len(tasks)} 只失败）",
        }
    if valid_n == 0:
        # 该日期全市场没有任何有效K线（未来日期/周末/数据未更新）——
        # 必须显式报错，绝不能伪装成"当日全部策略 0 命中"写入缓存
        return {
            "available": False,
            "reason": f"{target} 无有效行情数据（非交易日或数据未更新）",
        }

    results = {}
    for key in strategies:
        hits = buckets[key]
        hits.sort(
            key=lambda h: (h.get("J") if h.get("J") is not None else 999, h["code"])
        )
        results[key] = {
            "hits": hits,
            "total_scanned": len(tasks),
            "errors": errors,
        }
    logger.info(
        "因子扫描完成: date=%s 策略=%s 命中=%s 失败=%d",
        trade_date,
        strategies,
        {k: len(v["hits"]) for k, v in results.items()},
        errors,
    )
    return {"available": True, "trade_date": trade_date, "results": results}


def get_factor_hits(
    csv_manager,
    stock_names: dict,
    strategies: list,
    date: str = "",
    force: bool = False,
) -> dict:
    """带缓存入口：请求的策略里缓存缺哪个就补算哪个（增量合并）.

    Returns:
        {available, trade_date, results: {key: {hits, total_scanned, errors}}}
    """
    latest = _latest_data_date(csv_manager)
    if date:
        # date 来自 HTTP 参数：必须是纯日期格式（防路径注入）且不晚于最新数据日
        # （未来日期只会产出空缓存文件，还会挤占滚动清理配额）
        if not _DATE_RE.match(date):
            return {"available": False, "reason": "日期格式不合法"}
        if latest and date > latest:
            return {"available": False, "reason": f"{date} 尚无行情数据"}
    trade_date = date or latest
    if not trade_date:
        return {"available": False, "reason": "无法确定交易日"}

    # 快路径不进锁：全市场扫描可能耗时数分钟，缓存命中的请求绝不能被它排队
    if not force:
        cache = _load_cache(trade_date, csv_manager)
        if all(s in cache for s in strategies):
            return {
                "available": True,
                "trade_date": trade_date,
                "results": {s: cache[s] for s in strategies},
            }

    with _lock:
        # 双检：等锁期间别人可能已算完。force 也不清缓存——单策略 force 重扫
        # 若清空整份缓存，会把其余 27 个策略的预热结果一起抹掉
        cache = _load_cache(trade_date, csv_manager)
        missing = (
            list(strategies) if force else [s for s in strategies if s not in cache]
        )
        if missing:
            scan = compute_scan(
                csv_manager,
                stock_names,
                missing,
                date=date if date else "",
                trade_date=trade_date,
            )
            if not scan.get("available"):
                return scan
            cache.update(scan["results"])
            if not _save_cache(trade_date, cache, csv_manager):
                return {"available": False, "reason": "factor_cache_write_failed"}

    results = {s: cache[s] for s in strategies if s in cache}
    if not results:
        return {"available": False, "reason": "扫描无结果"}
    return {"available": True, "trade_date": trade_date, "results": results}


def read_cached_factor_hits(csv_manager, strategies: list, date: str = "") -> dict:
    """只读因子缓存；HTTP GET 不得因缓存缺失触发全市场扫描。"""
    latest = _latest_data_date(csv_manager)
    if date and (not _DATE_RE.fullmatch(date) or (latest and date > latest)):
        return {"available": False, "reason": "invalid_or_future_date"}
    trade_date = date or latest
    if not trade_date:
        return {"available": False, "reason": "无法确定交易日"}
    envelope = _load_cache_envelope(trade_date, csv_manager)
    cache = envelope.get("results") or {}
    results = {key: cache[key] for key in strategies if key in cache}
    return {
        "available": bool(results),
        "reason": None if results else "factor_snapshot_not_ready",
        "trade_date": trade_date,
        "results": results,
        "cache_key": envelope.get("_cache_key"),
        "artifact_content_hash": envelope.get("artifact_content_hash"),
    }


def prewarm_all(csv_manager, stock_names: dict) -> dict:
    """16:00 定时任务预热：全部策略一次算完（一次IO跑28策略）."""
    from strategy.factors import FACTOR_REGISTRY

    return get_factor_hits(
        csv_manager, stock_names, list(FACTOR_REGISTRY.keys()), force=True
    )
