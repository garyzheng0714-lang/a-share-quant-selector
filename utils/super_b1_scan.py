"""超级B1全市场扫描 - 文件缓存 + 并行读取（缓存模式与 sector_rotation 一致）

独立模块：不写 results/performance 表（避免污染碗口策略的战绩统计），
只产出展示用的信号清单。战绩独立追踪属第二期，待用户拍板。

诚实原则落地（2026-07-12 review 修正）：
- 市值从 data/stock_market_cap.json 取 circ_mv（真流通市值=FINANCE(40)同口径），
  缺该票时退 total_mv，再退 CSV market_cap 列；仍缺失的票计数上报，不静默吞掉
- trade_date 统一用锚点股探测（多只取 max），命中里日期≠trade_date 的陈旧信号
  （停牌/断更股的旧K线）一律丢弃并计数——旧信号绝不能被当成今天的信号
- 扫描失败比例超过 20% 时返回 available:false 且不写缓存（系统性故障必须显式暴露，
  不能伪装成"今日无信号"的正常空态）
"""
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"
CACHE_FILE = DATA_DIR / "super_b1_cache.json"
CAP_FILE = DATA_DIR / "stock_market_cap.json"
CACHE_SCHEMA_VERSION = 3
_lock = threading.Lock()

# 需要的K线根数：MA114 预热 + EXIST(...,200) 回看 + 余量
NROWS = 400

# 数据日期锚点股（多只取 max，单只停牌不会把基准带歪）
ANCHOR_CODES = ("000001", "600030", "600036", "600519")


def _load_cap_map() -> dict:
    """{code: 市值(元)}，circ_mv 优先、退 total_mv。文件缺失返回空 dict."""
    if not CAP_FILE.exists():
        return {}
    try:
        with open(CAP_FILE, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:
        logger.warning("市值缓存读取失败: %s", e)
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
    cap_map = _load_cap_map()

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

    if tasks and errors > len(tasks) * 0.2:
        logger.error("超级B1扫描系统性异常: %d/%d 只失败，不写缓存", errors, len(tasks))
        return {"available": False, "reason": f"扫描异常（{errors}/{len(tasks)} 只失败）"}

    hits.sort(key=lambda h: (h["J"], h["code"]))  # J 越低越超卖，排前面
    if errors or cap_missing or stale:
        logger.warning(
            "超级B1扫描统计: 失败 %d / 缺市值 %d / 陈旧信号丢弃 %d（共 %d 只）",
            errors, cap_missing, stale, len(tasks),
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
    }


def get_super_b1(csv_manager, stock_names: dict, force: bool = False) -> dict:
    """带文件缓存：数据日期没变就直接用缓存（含双检锁防并发重算）."""
    def _fresh_cache():
        if CACHE_FILE.exists():
            try:
                with open(CACHE_FILE, encoding="utf-8") as f:
                    cached = json.load(f)
                if (
                    cached.get("available")
                    and cached.get("schema_version") == CACHE_SCHEMA_VERSION
                    and cached.get("trade_date") == _latest_data_date(csv_manager)
                ):
                    return cached
            except Exception:
                pass
        return None

    if not force:
        cached = _fresh_cache()
        if cached:
            return cached
    with _lock:
        if not force:
            cached = _fresh_cache()
            if cached:
                return cached
        result = compute_scan(csv_manager, stock_names)
        if result.get("available"):
            try:
                with open(CACHE_FILE, "w", encoding="utf-8") as f:
                    json.dump(result, f, ensure_ascii=False)
            except Exception as e:
                logger.warning("超级B1缓存写入失败: %s", e)
        return result
