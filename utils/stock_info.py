"""
股票基本信息管理 - 行业分类、板块归属、主营业务

数据源: akshare (东方财富)
缓存策略: JSON 文件本地缓存，每日最多刷新一次
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"
INDUSTRY_CACHE = DATA_DIR / "stock_industry.json"
PROFILES_CACHE = DATA_DIR / "stock_profiles.json"
MARKET_CAP_CACHE = DATA_DIR / "stock_market_cap.json"
CACHE_TTL = 86400


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


def fetch_industry_mapping(force: bool = False) -> dict[str, str]:
    """获取全部 A 股的行业分类映射: {stock_code: industry_name}.

    通过遍历东方财富行业板块，获取每个板块的成分股，
    构建反向映射。

    Args:
        force: 是否强制刷新缓存

    Returns:
        {stock_code: industry_name} 映射字典
    """
    if not force and _is_cache_valid(INDUSTRY_CACHE):
        try:
            with open(INDUSTRY_CACHE, "r", encoding="utf-8") as f:
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
        if board_df is None or board_df.empty:
            logger.warning("获取行业板块名称失败")
            return _load_cached_industry()

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
            cache_data = {**mapping, "_updated_at": datetime.now().isoformat()}
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with open(INDUSTRY_CACHE, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            logger.info("行业分类缓存已保存: %d 只股票", len(mapping))

    except ImportError:
        logger.error("akshare 未安装，无法获取行业分类")
    except Exception as e:
        logger.error("获取行业分类失败: %s", e)

    return mapping if mapping else _load_cached_industry()


def _load_cached_industry() -> dict[str, str]:
    """降级：从缓存加载行业映射（即使过期）."""
    if INDUSTRY_CACHE.exists():
        try:
            with open(INDUSTRY_CACHE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {k: v for k, v in data.items() if not k.startswith("_")}
        except Exception:
            pass
    return {}


def fetch_market_caps(force: bool = False) -> dict[str, dict]:
    """获取全部 A 股的实时市值数据.

    Returns:
        {stock_code: {"total_mv": 总市值, "circ_mv": 流通市值}} (单位: 元)
    """
    if not force and _is_cache_valid(MARKET_CAP_CACHE):
        try:
            with open(MARKET_CAP_CACHE, "r", encoding="utf-8") as f:
                data = json.load(f)
            caps = {k: v for k, v in data.items() if not k.startswith("_")}
            if caps:
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
                total_mv = row.get("总市值", 0)
                circ_mv = row.get("流通市值", 0)
                if code and (total_mv or circ_mv):
                    caps[code] = {
                        "total_mv": float(total_mv) if total_mv else 0,
                        "circ_mv": float(circ_mv) if circ_mv else 0,
                    }

            if caps:
                cache_data = {**caps, "_updated_at": datetime.now().isoformat()}
                DATA_DIR.mkdir(parents=True, exist_ok=True)
                with open(MARKET_CAP_CACHE, "w", encoding="utf-8") as f:
                    json.dump(cache_data, f, ensure_ascii=False)
                logger.info("市值数据缓存已保存: %d 只股票", len(caps))

    except ImportError:
        logger.error("akshare 未安装，无法获取市值数据")
    except Exception as e:
        logger.error("获取市值数据失败: %s", e)

    return caps if caps else _load_cached_market_caps()


def _load_cached_market_caps() -> dict[str, dict]:
    """降级：从缓存加载市值数据."""
    if MARKET_CAP_CACHE.exists():
        try:
            with open(MARKET_CAP_CACHE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {k: v for k, v in data.items() if not k.startswith("_")}
        except Exception:
            pass
    return {}


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
