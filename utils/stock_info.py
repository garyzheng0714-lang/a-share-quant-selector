"""
股票基本信息管理 - 行业分类、板块归属、主营业务

数据源: akshare (东方财富)
缓存策略: JSON 文件本地缓存，每日最多刷新一次
"""

from __future__ import annotations

import json
import hashlib
import logging
import os
import requests
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from utils.runtime_paths import market_data_dir

logger = logging.getLogger(__name__)

DATA_DIR = market_data_dir()
INDUSTRY_CACHE = DATA_DIR / "stock_industry.json"
PROFILES_CACHE = DATA_DIR / "stock_profiles.json"
MARKET_CAP_CACHE = DATA_DIR / "stock_market_cap.json"
CACHE_TTL = 86400

# 申万历史行业文件同时包含旧版与 2021 版编码。项目首屏只需要
# 稳定的一级行业粒度，因此把历史前缀统一到当前页面使用的中文分类。
SW_LEVEL_ONE_BY_PREFIX = {
    "11": "农林牧渔",
    "21": "采掘",
    "22": "基础化工",
    "23": "钢铁",
    "24": "有色金属",
    "25": "建筑建材",
    "26": "机械设备",
    "27": "电子",
    "28": "汽车",
    "31": "汽车",
    "32": "计算机",
    "33": "家用电器",
    "34": "食品饮料",
    "35": "纺织服饰",
    "36": "轻工制造",
    "37": "医药生物",
    "41": "公用事业",
    "42": "交通运输",
    "43": "房地产",
    "44": "金融服务",
    "45": "商贸零售",
    "46": "社会服务",
    "47": "信息服务",
    "48": "银行",
    "49": "非银金融",
    "51": "综合",
    "61": "建筑材料",
    "62": "建筑装饰",
    "63": "电力设备",
    "64": "机械设备",
    "65": "国防军工",
    "71": "计算机",
    "72": "传媒",
    "73": "通信",
    "74": "煤炭",
    "75": "石油石化",
    "76": "环保",
    "77": "美容护理",
}


def _get_board_by_code(code: str) -> str:
    """根据股票代码判断所属板块."""
    if code.startswith("688") or code.startswith("689"):
        return "科创板"
    if code.startswith("300") or code.startswith("301"):
        return "创业板"
    if code.startswith("60"):
        return "沪市主板"
    if code.startswith("000") or code.startswith("001"):
        return "深市主板"
    if code.startswith("002") or code.startswith("003"):
        return "深市主板"
    return "其他"


def _is_cache_valid(cache_path: Path) -> bool:
    """检查缓存文件是否有效（存在且未过期）."""
    if not cache_path.exists():
        return False
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        ts = data.get("_updated_at", "")
        if not ts:
            return False
        updated = datetime.fromisoformat(ts)
        elapsed = (datetime.now() - updated).total_seconds()
        return elapsed < CACHE_TTL
    except Exception:
        return False


def _save_industry_mapping(
    mapping: dict[str, str], cache_path: Path, *, source_id: str
) -> None:
    cache_data = {
        **mapping,
        "_updated_at": datetime.now().isoformat(),
        "_source_id": source_id,
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_path.with_suffix(f".{os.getpid()}.tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(cache_data, handle, ensure_ascii=False, indent=2)
    tmp.replace(cache_path)


def _industry_cache_source(cache_path: Path) -> str:
    try:
        value = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "unknown"
    return str(value.get("_source_id") or "unknown")


def fetch_industry_mapping(
    force: bool = False,
    *,
    data_dir: str | Path | None = None,
    allow_stale_cache: bool = True,
) -> dict[str, str]:
    """获取全部 A 股的行业分类映射: {stock_code: industry_name}.

    通过遍历东方财富行业板块，获取每个板块的成分股，
    构建反向映射。

    Args:
        force: 是否强制刷新缓存

    Returns:
        {stock_code: industry_name} 映射字典
    """
    data_root = Path(data_dir) if data_dir is not None else DATA_DIR
    industry_cache = data_root / "stock_industry.json"
    if not force and _is_cache_valid(industry_cache):
        try:
            with open(industry_cache, "r", encoding="utf-8") as f:
                data = json.load(f)
            mapping = {k: v for k, v in data.items() if not k.startswith("_")}
            if mapping:
                logger.info("从缓存加载行业分类: %d 只股票", len(mapping))
                return mapping
        except Exception:
            pass

    logger.info("开始获取行业分类数据...")
    mapping: dict[str, str] = {}

    try:
        import akshare as ak

        board_df = ak.stock_board_industry_name_em()
        if board_df is not None and not board_df.empty:
            industry_names = board_df["板块名称"].tolist()
            total = len(industry_names)
            logger.info("共 %d 个行业板块，开始获取成分股...", total)

            for i, name in enumerate(industry_names, 1):
                try:
                    cons_df = ak.stock_board_industry_cons_em(symbol=name)
                    if cons_df is not None and not cons_df.empty:
                        for code in cons_df["代码"].tolist():
                            mapping[str(code)] = name

                    if i % 20 == 0 or i == total:
                        logger.info(
                            "  行业分类进度: [%d/%d] 已映射 %d 只股票",
                            i,
                            total,
                            len(mapping),
                        )

                    time.sleep(0.15)
                except Exception as e:
                    logger.debug("获取行业 [%s] 成分股失败: %s", name, e)
                    continue

            if mapping:
                _save_industry_mapping(
                    mapping,
                    industry_cache,
                    source_id="akshare-eastmoney-industry-components",
                )
                logger.info("行业分类缓存已保存: %d 只股票", len(mapping))
                return mapping

    except ImportError:
        logger.error("akshare 未安装，无法获取行业分类")
    except Exception as e:
        logger.error("获取行业分类失败: %s", e)

    # 东财行业接口不可用时，用新浪行业板块成分详情构建完整映射。
    # stock_sector_spot 本身只返回各板块领涨股，覆盖率远不够，必须再拉 detail。
    sina_mapping = _fetch_industry_mapping_sina()
    if len(sina_mapping) >= 3000:
        _save_industry_mapping(
            sina_mapping,
            industry_cache,
            source_id="akshare-sina-sector-detail",
        )
        logger.info("行业分类兜底（新浪成分）: %d 只股票", len(sina_mapping))
        return sina_mapping
    if sina_mapping:
        logger.warning(
            "新浪行业成分映射仅 %d 只，低于可用门槛，不覆盖本地缓存",
            len(sina_mapping),
        )

    sw_mapping = _fetch_industry_mapping_sw_history()
    if len(sw_mapping) >= 3000:
        _save_industry_mapping(
            sw_mapping,
            industry_cache,
            source_id="akshare-swsresearch-industry-history",
        )
        logger.info("行业分类兜底（申万历史）: %d 只股票", len(sw_mapping))
        return sw_mapping
    if sw_mapping:
        logger.warning(
            "申万历史行业映射仅 %d 只，低于可用门槛，不覆盖本地缓存",
            len(sw_mapping),
        )

    if mapping:
        return mapping
    return _load_cached_industry(industry_cache) if allow_stale_cache else {}


def _fetch_industry_mapping_sina() -> dict[str, str]:
    """通过新浪行业板块列表 + 成分详情构建 {code: industry}。"""
    try:
        import akshare as ak

        sina_df = ak.stock_sector_spot(indicator="新浪行业")
    except Exception as e:
        logger.error("新浪行业列表失败: %s", e)
        return {}
    if sina_df is None or sina_df.empty or "label" not in sina_df.columns:
        return {}

    mapping: dict[str, str] = {}
    # 同一 label 可能对应多行领涨股；按 label 去重后拉成分。
    sector_rows = list(
        sina_df.drop_duplicates(subset=["label"])[["label", "板块"]]
        .dropna()
        .itertuples(index=False)
    )
    try:
        import akshare as ak
    except ImportError:
        return {}
    for label, industry_name in sector_rows:
        industry = str(industry_name).strip()
        sector = str(label).strip()
        if not industry or not sector:
            continue
        try:
            detail = ak.stock_sector_detail(sector=sector)
        except Exception as e:
            logger.debug("新浪行业成分 [%s] 失败: %s", sector, e)
            continue
        if detail is None or detail.empty:
            continue
        if "code" not in detail.columns:
            continue
        for raw_code in detail["code"].tolist():
            code = str(raw_code).zfill(6)
            if code.isdigit():
                mapping[code] = industry
        time.sleep(0.05)
    return mapping


def _fetch_industry_mapping_sw_history() -> dict[str, str]:
    """通过申万官方历史分类文件构建最新一级行业映射。

    该源是全量文件，比逐板块、逐个股请求更适合做全市场快照；
    网络端偶发 502/SSL 错误，所以只在这个边界做有限次数重试。
    """
    try:
        import akshare as ak
    except ImportError:
        return {}

    history = None
    for attempt in range(1, 5):
        try:
            history = ak.stock_industry_clf_hist_sw()
            if history is not None and not history.empty:
                break
        except Exception as exc:
            logger.warning("申万历史行业第 %d/4 次获取失败: %s", attempt, exc)
        if attempt < 4:
            time.sleep(float(attempt * 2))

    required = {"symbol", "start_date", "industry_code"}
    if history is None or history.empty or not required.issubset(history.columns):
        return {}

    ordered = history.copy()
    ordered["_symbol"] = (
        ordered["symbol"].astype(str).str.extract(r"(\d{6})", expand=False)
    )
    ordered["_start_date"] = ordered["start_date"].astype(str)
    if "update_time" in ordered.columns:
        ordered["_update_time"] = ordered["update_time"].astype(str)
    else:
        ordered["_update_time"] = ""
    ordered = ordered.dropna(subset=["_symbol"]).sort_values(
        ["_symbol", "_start_date", "_update_time"]
    )
    latest = ordered.drop_duplicates(subset=["_symbol"], keep="last")

    mapping: dict[str, str] = {}
    for _, row in latest.iterrows():
        code = str(row["_symbol"])
        raw_industry_code = str(row["industry_code"]).strip()
        industry = SW_LEVEL_ONE_BY_PREFIX.get(raw_industry_code[:2])
        if len(code) == 6 and code.isdigit() and industry:
            mapping[code] = industry
    return mapping


def _load_cached_industry(cache_path: Path = INDUSTRY_CACHE) -> dict[str, str]:
    """降级：从缓存加载行业映射（即使过期）."""
    if cache_path.exists():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {k: v for k, v in data.items() if not k.startswith("_")}
        except Exception:
            pass
    return {}


def _parse_market_cap(value) -> float:
    """把不同数据源的市值字段统一为元."""
    if value is None:
        return 0
    try:
        if isinstance(value, str):
            text = value.strip().replace(",", "")
            if not text or text in {"-", "--", "nan", "None"}:
                return 0
            if text.endswith("亿"):
                return float(text[:-1]) * 1e8
            if text.endswith("万"):
                return float(text[:-1]) * 1e4
            return float(text)
        number = float(value)
        if number != number:
            return 0
        return number
    except (TypeError, ValueError):
        return 0


def _save_market_caps(
    caps: dict[str, dict],
    cache_path: Path = MARKET_CAP_CACHE,
    *,
    source_id: str = "unknown",
) -> None:
    cache_data = {
        **caps,
        "_updated_at": datetime.now().isoformat(),
        "_source_id": source_id,
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_path.with_suffix(f".{os.getpid()}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache_data, f, ensure_ascii=False)
    tmp.replace(cache_path)


def _market_cap_cache_source(cache_path: Path) -> str:
    try:
        value = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "unknown"
    return str(value.get("_source_id") or "unknown")


def _fetch_market_caps_tencent(stock_codes: list[str]) -> dict[str, dict]:
    """通过腾讯行情接口批量兜底获取总市值，单位统一为元."""
    caps: dict[str, dict] = {}
    if not stock_codes:
        return caps

    batch_size = 100
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    for i in range(0, len(stock_codes), batch_size):
        batch = stock_codes[i : i + batch_size]
        query_codes = [
            f"sh{code}" if code.startswith(("6", "8")) else f"sz{code}"
            for code in batch
        ]
        try:
            url = f"https://qt.gtimg.cn/q={','.join(query_codes)}"
            resp = requests.get(url, timeout=30, headers=headers)
            resp.raise_for_status()
        except Exception as e:
            logger.debug("腾讯市值接口批次 [%d] 获取失败: %s", i, e)
            continue

        for line in resp.text.strip().split(";"):
            if "v_" not in line or "~" not in line:
                continue
            try:
                code_match = line.split("v_", 1)[1].split("=", 1)[0]
                code = code_match[2:]
                parts = line.split("~")
                if len(parts) < 45:
                    continue
                raw_total_mv = str(parts[44]).strip()
                total_mv = _parse_market_cap(raw_total_mv)
                if raw_total_mv and not raw_total_mv.endswith("亿"):
                    total_mv *= 1e8
                if total_mv > 0:
                    caps[code] = {"total_mv": total_mv, "circ_mv": total_mv}
            except Exception:
                continue

        if i and i % 500 == 0:
            logger.info("腾讯市值进度: %d/%d", i, len(stock_codes))
            time.sleep(0.1)

    return caps


def fetch_market_caps(
    force: bool = False,
    stock_codes: Optional[list[str]] = None,
    *,
    data_dir: str | Path | None = None,
    allow_stale_cache: bool = True,
) -> dict[str, dict]:
    """获取全部 A 股的实时市值数据.

    Returns:
        {stock_code: {"total_mv": 总市值, "circ_mv": 流通市值}} (单位: 元)
    """
    requested_codes = [str(code).zfill(6) for code in stock_codes or []]
    data_root = Path(data_dir) if data_dir is not None else DATA_DIR
    market_cap_cache = data_root / "stock_market_cap.json"

    if not force and _is_cache_valid(market_cap_cache):
        try:
            with open(market_cap_cache, "r", encoding="utf-8") as f:
                data = json.load(f)
            caps = {k: v for k, v in data.items() if not k.startswith("_")}
            if caps:
                missing = [
                    code
                    for code in requested_codes
                    if not caps.get(code, {}).get("total_mv")
                ]
                if missing:
                    caps.update(_fetch_market_caps_tencent(missing))
                    previous_source = _market_cap_cache_source(market_cap_cache)
                    source_id = (
                        "tencent:qt.gtimg.cn"
                        if previous_source == "unknown"
                        else f"{previous_source}+tencent:qt.gtimg.cn"
                    )
                    _save_market_caps(
                        caps,
                        market_cap_cache,
                        source_id=source_id,
                    )
                logger.info("从缓存加载市值数据: %d 只股票", len(caps))
                return caps
        except Exception:
            pass

    logger.info("开始获取真实市值数据...")
    caps: dict[str, dict] = {}

    try:
        import akshare as ak

        spot_df = ak.stock_zh_a_spot_em()
        if spot_df is not None and not spot_df.empty:
            for _, row in spot_df.iterrows():
                code = str(row.get("代码", ""))
                total_mv = _parse_market_cap(row.get("总市值", 0))
                circ_mv = _parse_market_cap(row.get("流通市值", 0))
                if code and (total_mv or circ_mv):
                    caps[code] = {
                        "total_mv": total_mv,
                        "circ_mv": circ_mv,
                    }

            if caps:
                missing = [
                    code
                    for code in requested_codes
                    if not caps.get(code, {}).get("total_mv")
                ]
                source_id = "akshare-eastmoney"
                if missing:
                    caps.update(_fetch_market_caps_tencent(missing))
                    source_id = "akshare-eastmoney+tencent:qt.gtimg.cn"
                _save_market_caps(
                    caps,
                    market_cap_cache,
                    source_id=source_id,
                )
                logger.info("市值数据缓存已保存: %d 只股票", len(caps))

    except ImportError:
        logger.error("akshare 未安装，无法获取市值数据")
    except Exception as e:
        logger.error("获取市值数据失败: %s", e)

    if not caps and requested_codes:
        caps = _fetch_market_caps_tencent(requested_codes)
        if caps:
            _save_market_caps(
                caps,
                market_cap_cache,
                source_id="tencent:qt.gtimg.cn",
            )

    if caps:
        return caps
    return _load_cached_market_caps(market_cap_cache) if allow_stale_cache else {}


def _load_cached_market_caps(cache_path: Path = MARKET_CAP_CACHE) -> dict[str, dict]:
    """降级：从缓存加载市值数据."""
    if cache_path.exists():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {k: v for k, v in data.items() if not k.startswith("_")}
        except Exception:
            pass
    return {}


def _content_hash(mapping: dict) -> str:
    clean = {
        key: value for key, value in mapping.items() if not str(key).startswith("_")
    }
    return hashlib.sha256(
        json.dumps(
            clean, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def refresh_reference_metadata(
    data_dir: str | Path,
    stock_codes: list[str],
    trade_date: str,
    *,
    minimum_industry_coverage: float = 0.80,
    minimum_cap_coverage: float = 0.95,
) -> dict:
    """为一个 staging snapshot 获取当日参考数据；失败时不沿用随机旧缓存。

    日更 staging 会从上一版验证快照复制 industry/cap 文件。若东财/新浪实时
    刷新达不到覆盖率，允许在“当前 staging 已有文件仍满足覆盖率”时继承这些
    已验证映射，并在 manifest 标明 inherited-from-staging。
    """
    root = Path(data_dir)
    codes = sorted({str(code).zfill(6) for code in stock_codes})
    # 先快照 staging 里已有的映射，避免 force 刷新写坏文件后无法继承。
    inherited_industries = _load_cached_industry(root / "stock_industry.json")
    inherited_caps = _load_cached_market_caps(root / "stock_market_cap.json")
    industries = fetch_industry_mapping(
        force=True,
        data_dir=root,
        allow_stale_cache=False,
    )
    caps = fetch_market_caps(
        force=True,
        stock_codes=codes,
        data_dir=root,
        allow_stale_cache=False,
    )
    industry_source = _industry_cache_source(root / "stock_industry.json")
    cap_source = _market_cap_cache_source(root / "stock_market_cap.json")
    industry_count, industry_ratio = _coverage_count(codes, industries, kind="industry")
    cap_count, cap_ratio = _coverage_count(codes, caps, kind="market_cap")
    total = len(codes)
    valid = (
        total >= 3000
        and industry_ratio >= minimum_industry_coverage
        and cap_ratio >= minimum_cap_coverage
    )
    if not valid:
        inherited_industry_count, inherited_industry_ratio = _coverage_count(
            codes, inherited_industries, kind="industry"
        )
        inherited_cap_count, inherited_cap_ratio = _coverage_count(
            codes, inherited_caps, kind="market_cap"
        )
        if (
            inherited_industry_ratio >= minimum_industry_coverage
            and inherited_cap_ratio >= minimum_cap_coverage
        ):
            industries = inherited_industries
            caps = inherited_caps
            industry_count = inherited_industry_count
            cap_count = inherited_cap_count
            industry_ratio = inherited_industry_ratio
            cap_ratio = inherited_cap_ratio
            industry_source = "inherited-staging-snapshot"
            cap_source = "inherited-staging-snapshot"
            valid = total >= 3000
            # 把继承结果写回，避免后续读取到 force 刷新留下的残缺文件。
            if industries:
                industry_path = root / "stock_industry.json"
                _save_industry_mapping(
                    industries,
                    industry_path,
                    source_id="inherited-staging-snapshot",
                )
            if caps:
                _save_market_caps(
                    caps,
                    root / "stock_market_cap.json",
                    source_id="inherited-staging-snapshot",
                )
            logger.warning(
                "实时参考数据不足，继承 staging 已有映射 (industry=%.3f cap=%.3f)",
                industry_ratio,
                cap_ratio,
            )
    manifest = {
        "schema_version": "reference-data-v1",
        "as_of": trade_date,
        "captured_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "universe_count": total,
        "industry": {
            "source_id": industry_source,
            "count": industry_count,
            "coverage_ratio": round(industry_ratio, 6),
            "content_hash": _content_hash(industries),
        },
        "market_cap": {
            "source_id": cap_source,
            "count": cap_count,
            "coverage_ratio": round(cap_ratio, 6),
            "content_hash": _content_hash(caps),
        },
        "valid": valid,
    }
    target = root / "reference_data_manifest.json"
    tmp = target.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )
    tmp.replace(target)
    return manifest


def _coverage_count(
    codes: list[str],
    mapping: dict,
    *,
    kind: str,
) -> tuple[int, float]:
    if kind == "industry":
        count = sum(code in mapping and bool(mapping[code]) for code in codes)
    else:
        count = sum(
            code in mapping
            and isinstance(mapping[code], dict)
            and bool(mapping[code].get("circ_mv") or mapping[code].get("total_mv"))
            for code in codes
        )
    total = len(codes)
    return count, (count / total if total else 0.0)


def fetch_stock_profile(code: str) -> Optional[dict]:
    """获取单只股票的详细资料.

    stock_individual_info_em 返回: 股票简称, 行业, 上市时间, 总股本, 流通股, 总市值, 流通市值
    stock_zyjs_ths 返回: 主营业务, 产品名称, 经营范围（同花顺源）
    """
    try:
        import akshare as ak

        info_df = ak.stock_individual_info_em(symbol=code)
        if info_df is None or info_df.empty:
            return None

        info_map = {}
        for _, row in info_df.iterrows():
            key = str(row.get("item", ""))
            val = str(row.get("value", ""))
            info_map[key] = val

        industry_mapping = fetch_industry_mapping()
        industry = industry_mapping.get(code, info_map.get("行业", "未知"))

        business = ""
        try:
            zyjs_df = ak.stock_zyjs_ths(symbol=code)
            if zyjs_df is not None and not zyjs_df.empty:
                biz_parts = []
                if "主营业务" in zyjs_df.columns:
                    biz_val = str(zyjs_df.iloc[0]["主营业务"])
                    if biz_val and biz_val != "nan":
                        biz_parts.append(biz_val)
                if "产品名称" in zyjs_df.columns:
                    prod_val = str(zyjs_df.iloc[0]["产品名称"])
                    if prod_val and prod_val != "nan":
                        biz_parts.append(f"产品: {prod_val}")
                business = "；".join(biz_parts)
        except Exception:
            pass

        return {
            "code": code,
            "name": info_map.get("股票简称", ""),
            "industry": industry,
            "board": _get_board_by_code(code),
            "business": business,
            "listing_date": info_map.get("上市时间", ""),
            "total_shares": info_map.get("总股本", ""),
            "circ_shares": info_map.get("流通股", ""),
        }
    except Exception as e:
        logger.error("获取股票 [%s] 资料失败: %s", code, e)
        return None


def get_stock_profile_cached(code: str) -> dict:
    """获取单只股票资料（带缓存）.

    优先从 profiles 缓存读取，缓存未命中则实时获取并写入缓存。

    Returns:
        股票资料字典，至少包含 industry 和 board
    """
    profiles = _load_profiles_cache()
    if code in profiles:
        return profiles[code]

    profile = fetch_stock_profile(code)
    if profile:
        profiles[code] = profile
        _save_profiles_cache(profiles)
        return profile

    industry_mapping = fetch_industry_mapping()
    return {
        "code": code,
        "name": "",
        "industry": industry_mapping.get(code, "未知"),
        "board": _get_board_by_code(code),
        "business": "",
        "listing_date": "",
        "total_shares": "",
        "circ_shares": "",
    }


def _load_profiles_cache() -> dict[str, dict]:
    """加载 profiles 缓存."""
    if PROFILES_CACHE.exists():
        try:
            with open(PROFILES_CACHE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {k: v for k, v in data.items() if not k.startswith("_")}
        except Exception:
            pass
    return {}


def _save_profiles_cache(profiles: dict[str, dict]) -> None:
    """保存 profiles 缓存."""
    cache_data = {**profiles, "_updated_at": datetime.now().isoformat()}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(PROFILES_CACHE, "w", encoding="utf-8") as f:
        json.dump(cache_data, f, ensure_ascii=False)


def get_industry_summary(industry_mapping: Optional[dict] = None) -> list[dict]:
    """获取行业统计摘要.

    Returns:
        按股票数量降序排列的行业列表:
        [{"name": "半导体", "count": 120}, ...]
    """
    if industry_mapping is None:
        industry_mapping = fetch_industry_mapping()

    counter: dict[str, int] = {}
    for industry in industry_mapping.values():
        counter[industry] = counter.get(industry, 0) + 1

    return sorted(
        [{"name": k, "count": v} for k, v in counter.items()],
        key=lambda x: x["count"],
        reverse=True,
    )
