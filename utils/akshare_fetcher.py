"""
A股数据抓取模块 - 使用 akshare / 直接HTTP请求
"""

import akshare as ak
import pandas as pd
from datetime import datetime, timedelta
import time
import sys
from pathlib import Path
import json
import requests
import os
import hashlib
import re

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.csv_manager import CSVManager
from utils.data_contracts import FetchResult, MarketDataUnavailable


MIN_UNIVERSE_SIZE = 3000
MIN_EXCHANGE_DELISTED_CODES = 100


def _codes_hash(codes) -> str:
    canonical = json.dumps(sorted(set(codes)), separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


# 设置请求会话
session = requests.Session()
session.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/javascript, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://quote.eastmoney.com/",
        "Connection": "keep-alive",
    }
)


class AKShareFetcher:
    """AKShare 数据抓取器"""

    def __init__(self, data_dir="data", *, state_dir: str | Path | None = None):
        self.csv_manager = CSVManager(data_dir)
        self.full_data_dir = Path(data_dir)
        self.state_dir = (
            Path(state_dir) if state_dir is not None else self.full_data_dir
        )
        self.stock_names_file = Path(data_dir) / "stock_names.json"
        self.universe_manifest_file = Path(data_dir) / "universe_manifest.json"
        self.security_status_file = Path(data_dir) / "security_status.json"
        self.provenance_file = Path(data_dir) / "ingestion_provenance.json"
        self.bootstrap_state_file = self.state_dir / "universe_bootstrap.json"
        self.universe_refresh_status = {
            "fresh": False,
            "reason": "universe_refresh_not_attempted",
        }

    def _load_local_stock_names(self):
        """从本地文件加载股票名称"""
        if self.stock_names_file.exists():
            try:
                with open(self.stock_names_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (OSError, json.JSONDecodeError):
                pass
        return {}

    def _save_stock_names(
        self, stock_dict, source: str, *, exclusions: dict | None = None
    ):
        """保存可审计的 last-known-good 股票池及其版本元数据。"""
        if len(stock_dict) < MIN_UNIVERSE_SIZE:
            raise ValueError("universe_below_minimum_size")
        self.stock_names_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.stock_names_file.with_suffix(f".{os.getpid()}.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(stock_dict, f, ensure_ascii=False, indent=2)
        tmp.replace(self.stock_names_file)
        canonical = json.dumps(
            stock_dict,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        manifest = {
            "schema_version": "universe-v1",
            "captured_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "source": source,
            "count": len(stock_dict),
            "expected_minimum_size": MIN_UNIVERSE_SIZE,
            "stale": False,
            "content_hash": hashlib.sha256(canonical).hexdigest(),
        }
        if exclusions:
            manifest["exclusions"] = exclusions
        manifest_tmp = self.universe_manifest_file.with_suffix(f".{os.getpid()}.tmp")
        manifest_tmp.write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        manifest_tmp.replace(self.universe_manifest_file)

    def _universe_size_is_safe(self, candidate: dict, previous: dict) -> bool:
        """阻断虽高于绝对下限、但相对上一版异常骤降的股票池。"""
        if len(candidate) < MIN_UNIVERSE_SIZE:
            return False
        if len(previous) < MIN_UNIVERSE_SIZE:
            return True
        maximum_drop = float(os.environ.get("QUANT_MAX_UNIVERSE_DROP_RATIO", "0.10"))
        return len(candidate) >= len(previous) * (1 - maximum_drop)

    def _mark_universe_stale(self, reason: str) -> None:
        """保留 LKG 内容，但显式记录本次刷新失败。"""
        try:
            manifest = json.loads(
                self.universe_manifest_file.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            return
        manifest.update(
            {
                "stale": True,
                "last_refresh_attempt_at": datetime.now()
                .astimezone()
                .isoformat(timespec="seconds"),
                "last_refresh_error": reason,
            }
        )
        tmp = self.universe_manifest_file.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        tmp.replace(self.universe_manifest_file)

    def _save_security_status(
        self,
        stock_dict: dict[str, str],
        suspension_frame: pd.DataFrame,
        trade_date: str,
    ) -> None:
        """将交易所日历对应的停牌分类作为独立、可校验证据。"""
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", trade_date):
            raise ValueError("security_status_trade_date_invalid")
        suspended: dict[str, dict] = {}
        code_column = next(
            (name for name in ("代码", "股票代码") if name in suspension_frame),
            None,
        )
        # 有效的“当日无停牌”响应仍应带有稳定列定义；无列空表更像
        # 上游 schema 变化/异常降级，不得据此把全市场标成“已验证正常交易”。
        if code_column is None:
            raise ValueError("suspension_schema_missing_code")
        if not suspension_frame.empty:
            for _, row in suspension_frame.iterrows():
                code = str(row.get(code_column) or "").split(".", 1)[0].zfill(6)
                if code in stock_dict:
                    suspended[code] = {
                        "reason": str(row.get("停牌原因") or "").strip() or None,
                        "planned_resume_at": str(row.get("预计复牌时间") or "").strip()
                        or None,
                    }
        securities = {
            code: {
                "status": "suspended" if code in suspended else "active",
                "verified": True,
                "as_of": trade_date,
                "source_id": "akshare:stock_tfp_em",
                "is_st": "ST" in str(name).upper().replace("＊", "*"),
                **(suspended.get(code) or {}),
            }
            for code, name in sorted(stock_dict.items())
        }
        canonical = json.dumps(
            securities,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        payload = {
            "schema_version": "security-status-v1",
            "as_of": trade_date,
            "captured_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "source_id": "akshare:stock_tfp_em",
            "count": len(securities),
            "suspended_count": len(suspended),
            "content_hash": hashlib.sha256(canonical).hexdigest(),
            "securities": securities,
        }
        tmp = self.security_status_file.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
        tmp.replace(self.security_status_file)

    @staticmethod
    def _exchange_delisted_codes() -> tuple[set[str], dict]:
        """从沪深交易所名单排除已终止上市证券。"""
        sources = (
            (
                "akshare:stock_info_sh_delist",
                ak.stock_info_sh_delist(symbol="全部"),
                "公司代码",
            ),
            (
                "akshare:stock_info_sz_delist",
                ak.stock_info_sz_delist(symbol="终止上市公司"),
                "证券代码",
            ),
        )
        combined: set[str] = set()
        by_source = {}
        for source_id, frame, code_column in sources:
            if code_column not in frame:
                raise ValueError(f"delisted_schema_missing_code:{source_id}")
            codes = {
                str(value).split(".", 1)[0].zfill(6)
                for value in frame[code_column]
                if re.fullmatch(r"\d{1,6}(?:\.0)?", str(value))
            }
            if not codes:
                raise ValueError(f"delisted_source_empty:{source_id}")
            combined.update(codes)
            by_source[source_id] = {"count": len(codes)}
        if len(combined) < MIN_EXCHANGE_DELISTED_CODES:
            raise ValueError("delisted_universe_below_minimum_size")
        return combined, {
            "schema_version": "exchange-delisted-catalog-v1",
            "reason": "exchange_delisted",
            "count": len(combined),
            "content_hash": _codes_hash(combined),
            "sources": by_source,
        }

    def _load_provenance(self) -> dict:
        if not self.provenance_file.exists():
            return {"schema_version": "ingestion-provenance-v1", "stocks": {}}
        try:
            payload = json.loads(self.provenance_file.read_text(encoding="utf-8"))
            if payload.get("schema_version") == "ingestion-provenance-v1":
                payload.setdefault("stocks", {})
                return payload
        except Exception:
            pass
        return {"schema_version": "ingestion-provenance-v1", "stocks": {}}

    def _verified_security_statuses(self, trade_date: str) -> dict[str, dict]:
        try:
            payload = json.loads(self.security_status_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        securities = payload.get("securities")
        if not isinstance(securities, dict):
            return {}
        canonical = json.dumps(
            securities,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        if (
            payload.get("schema_version") != "security-status-v1"
            or payload.get("as_of") != trade_date
            or payload.get("source_id") != "akshare:stock_tfp_em"
            or payload.get("count") != len(securities)
            or payload.get("content_hash") != hashlib.sha256(canonical).hexdigest()
        ):
            return {}
        return securities

    def _record_fetch_provenance(
        self,
        stock_code: str,
        fetch: FetchResult,
        persisted: pd.DataFrame,
        *,
        full_history: bool,
    ) -> None:
        """为成功落盘的真实数据记录来源，不为失败或合成数据造记录。"""
        if not fetch.success or fetch.synthetic or persisted.empty:
            raise ValueError(
                "only successful non-synthetic fetches may record provenance"
            )
        dates = pd.to_datetime(persisted["date"], errors="coerce").dropna()
        if dates.empty:
            raise ValueError("persisted data has no valid dates")
        payload = self._load_provenance()
        previous = (payload.get("stocks") or {}).get(stock_code, {})
        actual_start = dates.min().strftime("%Y-%m-%d")
        actual_end = dates.max().strftime("%Y-%m-%d")
        history_start = (
            actual_start
            if full_history
            else previous.get("history_coverage_start") or actual_start
        )
        history_source = (
            fetch.source
            if full_history
            else previous.get("history_source_id") or fetch.source
        )
        payload["stocks"][stock_code] = {
            "source_id": fetch.source,
            "fetched_at": fetch.fetched_at,
            "adjustment": "qfq",
            "source_trade_date": actual_end,
            "provider_returned_latest_date": fetch.returned_latest_date,
            "requested_start": fetch.requested_start,
            "requested_end": fetch.requested_end,
            "persisted_start": actual_start,
            "persisted_end": actual_end,
            "rows": len(persisted),
            "synthetic": False,
            "history_coverage_start": history_start,
            "history_source_id": history_source,
        }
        payload["updated_at"] = (
            datetime.now().astimezone().isoformat(timespec="seconds")
        )
        tmp = self.provenance_file.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(
            json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ),
            encoding="utf-8",
        )
        tmp.replace(self.provenance_file)

    def ensure_akshare_history_anchor(
        self,
        completed_cutoff: str,
        *,
        years: int = 6,
        candidates: tuple[str, ...] = ("600519", "600036", "600030", "000001"),
    ) -> dict:
        """确保快照中至少有一只活跃股的全历史来自 AkShare。"""
        provenance = self._load_provenance().get("stocks") or {}
        universe = set(self._main_board_universe())
        source_set = {
            item.get(source_key)
            for code, item in provenance.items()
            if code in universe
            if isinstance(item, dict)
            for source_key in ("source_id", "history_source_id")
            if item.get(source_key) in {"tencent", "akshare"}
        }
        if {"tencent", "akshare"}.issubset(source_set):
            return {"success": True, "updated": False, "source_set": sorted(source_set)}

        failures = []
        for attempt in range(2):
            for code in candidates:
                if code not in universe or not self.csv_manager.stock_exists(code):
                    continue
                fetch = self._fetch_stock_history_akshare(code, years=years)
                frame = fetch.data.copy() if fetch.success else pd.DataFrame()
                if not frame.empty:
                    frame = frame[
                        pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d")
                        <= completed_cutoff
                    ].copy()
                latest = (
                    pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d").max()
                    if not frame.empty and "date" in frame
                    else None
                )
                if fetch.success and latest == completed_cutoff:
                    self.csv_manager.write_stock(code, frame)
                    self._record_fetch_provenance(code, fetch, frame, full_history=True)
                    updated_source_set = source_set | {"akshare"}
                    return {
                        "success": {"tencent", "akshare"}.issubset(updated_source_set),
                        "updated": True,
                        "code": code,
                        "source_set": sorted(updated_source_set),
                    }
                failures.append(
                    {
                        "code": code,
                        "reason": fetch.reason,
                        "returned_latest_date": latest,
                    }
                )
            if attempt == 0:
                time.sleep(2)
        return {
            "success": False,
            "reason": "akshare_history_anchor_unavailable",
            "attempts": failures,
            "source_set": sorted(source_set),
        }

    def _fetch_stock_list_http(self):
        """使用腾讯接口获取股票列表 - 覆盖5000+只A股"""
        try:
            stocks = {}

            # A股完整代码范围定义 - 分批次获取以加快速度
            # 沪市主板：600-609开头
            sh_ranges = []
            for prefix in range(600, 610):  # 600-609
                sh_ranges.append((f"{prefix}000", f"{prefix}999"))
            # 添加其他沪市段
            sh_ranges.extend(
                [
                    ("601000", "601999"),  # 601
                    ("603000", "603999"),  # 603
                    ("605000", "605999"),  # 605
                    ("688000", "689999"),  # 科创板688-689
                ]
            )

            # 深市完整范围
            sz_ranges = [
                ("000001", "009999"),  # 000开头全部
                ("001000", "001999"),  # 001
                ("002000", "002999"),  # 002中小板
                ("003000", "003999"),  # 003
                ("300000", "309999"),  # 创业板300-309
            ]

            print("\n  正在通过腾讯接口获取股票列表...")
            print("  覆盖全部A股代码范围，约5000+只...")
            print("  这可能需要10-15分钟时间，请耐心等待...")

            # 分批查询，每次最多100只
            batch_size = 100
            all_codes = []

            # 生成密集的代码列表 - 步长改为1，覆盖几乎所有可能代码
            # 步长1可以获取最大数量的股票
            step = 1  # 步长1覆盖100%代码

            # 沪市 - 全覆盖
            for start, end in sh_ranges:
                for code_num in range(int(start), int(end) + 1, step):
                    code = str(code_num).zfill(6)
                    all_codes.append(code)

            # 深市 - 全覆盖
            for start, end in sz_ranges:
                for code_num in range(int(start), int(end) + 1, step):
                    code = str(code_num).zfill(6)
                    all_codes.append(code)

            print(f"  计划查询 {len(all_codes)} 个代码 (步长{step})...")
            print("  预计可获取 3000-5000+ 只有效股票...")
            print("  提示: 首次获取需要约5-10分钟，请耐心等待...")

            total_batches = (len(all_codes) + batch_size - 1) // batch_size
            print(f"  总共 {total_batches} 批次，开始查询...")

            # 分批查询
            for i in range(0, len(all_codes), batch_size):
                batch = all_codes[i : i + batch_size]
                batch_num = i // batch_size + 1

                query_codes_list = []
                for c in batch:
                    if c.startswith("6") or c.startswith("8"):
                        query_codes_list.append(f"sh{c}")
                    elif c.startswith("0") or c.startswith("3"):
                        query_codes_list.append(f"sz{c}")

                if not query_codes_list:
                    continue

                query_codes = ",".join(query_codes_list)
                url = f"https://qt.gtimg.cn/q={query_codes}"

                try:
                    resp = requests.get(
                        url,
                        timeout=30,
                        headers={
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                        },
                    )
                    resp.raise_for_status()

                    lines = resp.text.strip().split(";")
                    for line in lines:
                        if "v_" in line and "~" in line:
                            parts = line.split("~")
                            if len(parts) >= 45:  # 确保数据完整
                                code_match = (
                                    line.split("v_")[1].split("=")[0]
                                    if "v_" in line
                                    else ""
                                )
                                if code_match:
                                    code = code_match[2:]
                                    name = parts[1] if len(parts) > 1 else ""

                                    # 过滤条件
                                    exclude_keywords = [
                                        "债",
                                        "基",
                                        "ETF",
                                        "LOF",
                                        "理财",
                                        "信托",
                                        "B股",
                                        "指数",
                                    ]

                                    # 检查是否退市或异常
                                    # 腾讯接口字段：
                                    # parts[1]=名称, parts[2]=代码, parts[3]=最新价, parts[4]=昨收, parts[5]=今开
                                    # parts[32]=状态, parts[33]=最高价, parts[34]=最低价

                                    is_valid = True

                                    # 1. 名称过滤
                                    if (
                                        not name
                                        or name == '""'
                                        or any(x in name for x in exclude_keywords)
                                    ):
                                        is_valid = False

                                    # 2. 退市股票过滤 - 名称中包含"退"字
                                    if "退" in name:
                                        is_valid = False

                                    # 3. ST股票过滤（可选）
                                    # if 'ST' in name:
                                    #     is_valid = False

                                    # 价格/成交量为 0 可能是合法停牌，不得藉此
                                    # 从 universe 删除。状态由独立的停复牌日历证明。

                                    if is_valid:
                                        stocks[code] = name

                    if batch_num % 20 == 0 or batch_num == 1:
                        print(
                            f"    进度: {batch_num}/{total_batches} 批次, 已获取 {len(stocks)} 只股票..."
                        )

                    time.sleep(0.1)  # 轻微限速

                except Exception:
                    continue

            if stocks:
                print(f"  ✓ 通过腾讯接口获取: {len(stocks)} 只股票")
                return stocks

            print("  HTTP 股票列表返回空结果")
            return {}
        except Exception as e:
            print(f"  HTTP获取失败: {e}")
            return {}

    def get_all_stock_codes(self, max_retries=3):
        """获取所有A股股票代码（过滤债基、ETF、ST等）"""
        print("正在获取A股股票列表...")
        previous = self._load_local_stock_names()

        # 方法1: 直接HTTP请求
        for attempt in range(max_retries):
            try:
                print(f"  尝试HTTP直连 (第{attempt + 1}/{max_retries}次)...")
                stocks = self._fetch_stock_list_http()
                if stocks:
                    # 过滤
                    filtered = {}
                    code_pattern = r"^(00|30|60|68|88)\d{4}$"
                    exclude_keywords = [
                        "债",
                        "基",
                        "ETF",
                        "LOF",
                        "基金",
                        "理财",
                        "信托",
                        "B股",
                        "指数",
                        "国债",
                        "企债",
                        "转债",
                        "回购",
                        "R-",
                        "GC",
                    ]

                    for code, name in stocks.items():
                        if not pd.Series([code]).str.match(code_pattern).iloc[0]:
                            continue
                        if any(kw in name for kw in exclude_keywords):
                            continue
                        filtered[code] = name

                    if self._universe_size_is_safe(filtered, previous):
                        print(f"✓ HTTP获取成功: {len(filtered)} 只A股股票")
                        self._save_stock_names(filtered, source="tencent")
                        self.universe_refresh_status = {
                            "fresh": True,
                            "source": "tencent",
                            "count": len(filtered),
                        }
                        return filtered
                    if filtered:
                        print(
                            f"  HTTP 股票列表 {len(filtered)} 只，"
                            "未通过绝对/相对缩水安全门"
                        )
            except Exception as e:
                print(f"  HTTP失败: {e}")
                time.sleep(1)

        # 方法2: akshare
        for attempt in range(max_retries):
            try:
                print(f"  尝试akshare (第{attempt + 1}/{max_retries}次)...")

                sh_df = ak.stock_sh_a_spot_em()
                sz_df = ak.stock_sz_a_spot_em()

                all_stocks = pd.concat(
                    [sh_df[["代码", "名称"]], sz_df[["代码", "名称"]]]
                )
                all_stocks = all_stocks.drop_duplicates(subset=["代码"])

                code_pattern = r"^(00|30|60|68|88)\d{4}$"
                all_stocks = all_stocks[all_stocks["代码"].str.match(code_pattern)]

                exclude_keywords = [
                    "债",
                    "基",
                    "ETF",
                    "LOF",
                    "基金",
                    "理财",
                    "信托",
                    "B股",
                    "指数",
                    "国债",
                    "企债",
                    "转债",
                    "回购",
                    "R-",
                    "GC",
                ]
                for keyword in exclude_keywords:
                    all_stocks = all_stocks[
                        ~all_stocks["名称"].str.contains(keyword, na=False)
                    ]

                stock_dict = dict(zip(all_stocks["代码"], all_stocks["名称"]))
                if self._universe_size_is_safe(stock_dict, previous):
                    print(f"✓ akshare获取成功: {len(stock_dict)} 只A股股票")
                    self._save_stock_names(stock_dict, source="akshare")
                    self.universe_refresh_status = {
                        "fresh": True,
                        "source": "akshare",
                        "count": len(stock_dict),
                    }
                    return stock_dict
                print(
                    f"  akshare 股票列表 {len(stock_dict)} 只，"
                    "未通过绝对/相对缩水安全门"
                )

            except Exception as e:
                print(f"  akshare失败: {e}")
                time.sleep(2**attempt)

        # 只允许使用足够完整的 last-known-good，绝不伪造小股票池。
        print("\n网络连接失败，尝试加载本地缓存...")
        local_stocks = self._load_local_stock_names()
        if len(local_stocks) >= MIN_UNIVERSE_SIZE:
            print(f"✓ 从本地缓存加载: {len(local_stocks)} 只股票")
            self._mark_universe_stale("all_live_universe_sources_failed")
            self.universe_refresh_status = {
                "fresh": False,
                "reason": "using_stale_last_known_good",
                "count": len(local_stocks),
            }
            return local_stocks
        raise MarketDataUnavailable(
            "all_universe_sources_failed_and_no_valid_last_known_good"
        )

    def _fetch_stock_history_http(self, stock_code, years=6):
        """使用腾讯接口获取股票历史数据"""
        try:
            import requests

            # 判断市场前缀
            if stock_code.startswith("6") or stock_code.startswith("88"):
                market_code = "sh" + stock_code
            else:
                market_code = "sz" + stock_code

            # 腾讯财经接口 - 获取日K线数据
            # 腾讯接口最多返回约1000条数据，所以分批获取或限制年限
            max_days = min(years * 365, 1000)  # 最多1000天
            url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={market_code},day,,,{max_days},qfq"

            resp = requests.get(
                url,
                timeout=15,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Referer": "https://stock.finance.qq.com/",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, (dict, list)):
                return None

            # 解析腾讯返回的数据（处理不同返回格式）
            data_level = data.get("data", {})

            # data_level 可能是 dict 或 list（大数据量时）
            if isinstance(data_level, dict):
                stock_data = data_level.get(market_code, {})
                if isinstance(stock_data, dict):
                    klines = stock_data.get("qfqday", []) or stock_data.get("day", [])
                else:
                    klines = []
            elif isinstance(data_level, list) and len(data_level) > 0:
                # 大数据量时返回列表，第一项是代码，第二项是数据
                # 找到对应股票代码的数据
                klines = []
                for item in data_level:
                    if (
                        isinstance(item, list)
                        and len(item) >= 2
                        and item[0] == market_code
                    ):
                        # item[1] 是K线数据
                        if isinstance(item[1], list):
                            klines = item[1]
                        break
            else:
                klines = []

            if klines:
                records = []
                for item in klines:
                    # 腾讯格式: [日期, 开盘, 收盘, 最高, 最低, 成交量, ...]
                    # 注意: item[6] 可能是分红信息(dict)而不是成交额
                    if len(item) >= 6 and isinstance(item, list):
                        # 跳过分红信息，只取前6个字段
                        # 注意：腾讯接口返回的是 [日期, 开盘, 收盘, 最高, 最低, 成交量]
                        records.append(
                            {
                                "date": str(item[0]),
                                "open": float(item[1]),
                                "close": float(item[2]),
                                "high": float(item[3]),  # 最高
                                "low": float(item[4]),  # 最低
                                "volume": int(float(item[5])),
                                "amount": 0,  # 腾讯接口不直接提供成交额
                                "turnover": 0,  # 腾讯接口没有换手率
                            }
                        )

                if records:
                    df = pd.DataFrame(records)
                    df["date"] = pd.to_datetime(df["date"])
                    df = df.sort_values("date", ascending=False)
                    return df

            return None
        except Exception as e:
            print(f"  HTTP获取历史数据失败: {e}")
            return None

    def _fetch_stock_history_akshare(self, stock_code, years=6) -> FetchResult:
        """直接从 AkShare 获取历史数据，可作为日期过期时的备用源。"""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365 * years)
        try:
            start_str = start_date.strftime("%Y%m%d")
            end_str = end_date.strftime("%Y%m%d")

            df = ak.stock_zh_a_hist(
                symbol=stock_code,
                period="daily",
                start_date=start_str,
                end_date=end_str,
                adjust="qfq",
            )

            if df is not None and not df.empty:
                df = df.rename(
                    columns={
                        "日期": "date",
                        "开盘": "open",
                        "最高": "high",
                        "最低": "low",
                        "收盘": "close",
                        "成交量": "volume",
                        "成交额": "amount",
                        "换手率": "turnover",
                    }
                )
                df = df[
                    [
                        "date",
                        "open",
                        "high",
                        "low",
                        "close",
                        "volume",
                        "amount",
                        "turnover",
                    ]
                ]
                df["date"] = pd.to_datetime(df["date"])
                df = df.sort_values("date", ascending=False)
                return FetchResult.ok(
                    df,
                    source="akshare",
                    requested_start=start_date.strftime("%Y-%m-%d"),
                    requested_end=end_date.strftime("%Y-%m-%d"),
                )
            failure = "akshare:empty"
        except Exception as exc:
            print("  akshare获取失败")
            failure = f"akshare:{type(exc).__name__}"

        return FetchResult.failure(
            source="akshare",
            reason="source_failed",
            requested_start=start_date.strftime("%Y-%m-%d"),
            requested_end=end_date.strftime("%Y-%m-%d"),
            details={"failures": [failure]},
        )

    def fetch_stock_history(self, stock_code, years=6) -> FetchResult:
        """
        抓取单只股票历史数据
        前复权，按日期倒序排列
        """
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365 * years)
        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")
        failures = []

        # 方法1: 直接HTTP请求
        try:
            df = self._fetch_stock_history_http(stock_code, years)
            if df is not None and not df.empty:
                print(f"✓ (HTTP获取 {len(df)}条)")
                return FetchResult.ok(
                    df,
                    source="tencent",
                    requested_start=start_str,
                    requested_end=end_str,
                )
            print("  HTTP返回空数据，尝试akshare...")
            failures.append("tencent:empty")
        except Exception as exc:
            print(f"  HTTP异常: {exc}，尝试akshare...")
            failures.append(f"tencent:{type(exc).__name__}")

        # 方法2: akshare
        fallback = self._fetch_stock_history_akshare(stock_code, years=years)
        if fallback.success:
            return fallback
        failures.extend(fallback.details.get("failures") or [fallback.reason])

        return FetchResult.failure(
            source="tencent+akshare",
            reason="all_sources_failed",
            requested_start=start_date.strftime("%Y-%m-%d"),
            requested_end=end_date.strftime("%Y-%m-%d"),
            details={"failures": failures},
        )

    def fetch_stock_update(self, stock_code, days=10) -> FetchResult:
        """
        抓取近期数据用于增量更新
        优化：直接指定天数，避免计算误差
        """
        requested_end = datetime.now().strftime("%Y-%m-%d")
        requested_start = (datetime.now() - timedelta(days=days + 2)).strftime(
            "%Y-%m-%d"
        )
        failures = []
        try:
            # 判断市场前缀
            if stock_code.startswith("6") or stock_code.startswith("88"):
                market_code = "sh" + stock_code
            else:
                market_code = "sz" + stock_code

            # 腾讯接口：直接指定获取天数（最多1000天）
            # 多取2天确保覆盖周末节假日
            fetch_days = min(days + 2, 1000)
            url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={market_code},day,,,{fetch_days},qfq"

            resp = requests.get(
                url,
                timeout=15,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Referer": "https://stock.finance.qq.com/",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, (dict, list)):
                raise ValueError("unexpected_tencent_json_schema")

            # 解析数据
            data_level = data.get("data", {})
            klines = []

            if isinstance(data_level, dict):
                stock_data = data_level.get(market_code, {})
                if isinstance(stock_data, dict):
                    klines = stock_data.get("qfqday", []) or stock_data.get("day", [])
            elif isinstance(data_level, list) and len(data_level) > 0:
                for item in data_level:
                    if (
                        isinstance(item, list)
                        and len(item) >= 2
                        and item[0] == market_code
                    ):
                        if isinstance(item[1], list):
                            klines = item[1]
                        break

            if klines:
                records = []
                for item in klines:
                    if len(item) >= 6 and isinstance(item, list):
                        # 腾讯格式: [日期, 开盘, 收盘, 最高, 最低, 成交量]
                        records.append(
                            {
                                "date": str(item[0]),
                                "open": float(item[1]),
                                "close": float(item[2]),
                                "high": float(item[3]),  # 最高
                                "low": float(item[4]),  # 最低
                                "volume": int(float(item[5])),
                                "amount": 0,
                                "turnover": 0,
                            }
                        )

                if records:
                    df = pd.DataFrame(records)
                    df["date"] = pd.to_datetime(df["date"])
                    df = df.sort_values("date", ascending=False)
                    return FetchResult.ok(
                        df,
                        source="tencent",
                        requested_start=requested_start,
                        requested_end=requested_end,
                    )

            failures.append("tencent:empty")
        except Exception as e:
            print(f"  获取更新数据失败: {e}")
            failures.append(f"tencent:{type(e).__name__}")

        try:
            df = ak.stock_zh_a_hist(
                symbol=stock_code,
                period="daily",
                start_date=requested_start.replace("-", ""),
                end_date=requested_end.replace("-", ""),
                adjust="qfq",
            )
            if df is not None and not df.empty:
                df = df.rename(
                    columns={
                        "日期": "date",
                        "开盘": "open",
                        "最高": "high",
                        "最低": "low",
                        "收盘": "close",
                        "成交量": "volume",
                        "成交额": "amount",
                        "换手率": "turnover",
                    }
                )
                required = [
                    "date",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "amount",
                    "turnover",
                ]
                if set(required).issubset(df.columns):
                    df = df[required].copy()
                    df["date"] = pd.to_datetime(df["date"])
                    df = df.sort_values("date", ascending=False)
                    return FetchResult.ok(
                        df,
                        source="akshare",
                        requested_start=requested_start,
                        requested_end=requested_end,
                    )
            failures.append("akshare:empty_or_schema_invalid")
        except Exception as exc:
            failures.append(f"akshare:{type(exc).__name__}")

        return FetchResult.failure(
            source="tencent+akshare",
            reason="all_sources_failed",
            requested_start=requested_start,
            requested_end=requested_end,
            details={"failures": failures},
        )

    def init_full_data(self, max_stocks=None, skip_failed=True):
        """
        首次全量抓取
        :param max_stocks: 限制抓取数量（用于测试）
        :param skip_failed: 是否跳过之前失败的股票
        """
        stock_dict = self.get_all_stock_codes()

        if not stock_dict:
            print("无法获取股票列表")
            return

        stock_codes = list(stock_dict.keys())

        # 加载之前失败的股票列表
        failed_stocks_file = self.state_dir / "failed_stocks.json"
        failed_stocks = set()
        if skip_failed and failed_stocks_file.exists():
            try:
                with open(failed_stocks_file, "r", encoding="utf-8") as f:
                    failed_stocks = set(json.load(f))
                print(f"  将跳过 {len(failed_stocks)} 只之前获取失败的股票")
                # 从列表中移除失败的股票
                stock_codes = [c for c in stock_codes if c not in failed_stocks]
            except (OSError, json.JSONDecodeError):
                pass

        if max_stocks:
            stock_codes = stock_codes[:max_stocks]

        total = len(stock_codes)
        success = 0
        failed = 0
        failed_list = []

        print(f"\n开始抓取 {total} 只股票的6年历史数据...")
        print("=" * 60)

        for i, code in enumerate(stock_codes, 1):
            print(f"[{i}/{total}] 抓取 {code} {stock_dict.get(code, '')} ...", end=" ")

            fetch = self.fetch_stock_history(code, years=6)
            df = fetch.data if fetch.success else pd.DataFrame()

            if not df.empty:
                # 数据校验 - 检查是否有有效价格数据
                if len(df) < 10:  # 数据太少，可能是新股或数据异常
                    print(f"⚠ 数据太少({len(df)}条)")
                    failed_list.append(code)
                elif df["close"].mean() <= 0:  # 价格异常
                    print("⚠ 价格异常")
                    failed_list.append(code)
                else:
                    self.csv_manager.write_stock(code, df)
                    self._record_fetch_provenance(code, fetch, df, full_history=True)
                    print(f"✓ ({len(df)}条)")
                    success += 1
            else:
                print(f"✗ 失败 ({fetch.reason})")
                failed += 1
                failed_list.append(code)

            # 限速，避免请求过快
            if i % 10 == 0:
                time.sleep(1)

        # 保存失败的股票列表
        if failed_list:
            try:
                failed_stocks_file.parent.mkdir(parents=True, exist_ok=True)
                with open(failed_stocks_file, "w", encoding="utf-8") as f:
                    json.dump(failed_list, f)
                print(
                    f"\n  已保存 {len(failed_list)} 只获取失败的股票到 failed_stocks.json"
                )
            except Exception as e:
                print(f"\n  保存失败列表出错: {e}")

        print("=" * 60)
        print(f"完成! 成功: {success}, 失败: {failed}")
        if failed_list and not max_stocks:
            print("提示: 再次运行 init 命令可跳过失败股票，专注于成功获取的数据")
        return {
            "success": failed == 0,
            "total": total,
            "written": success,
            "failed": failed,
            "failed_codes": failed_list,
        }

    def _main_board_universe(self) -> dict:
        from utils.market_filter import is_main_board, main_board_only

        stock_dict = self._load_local_stock_names()
        if len(stock_dict) < 3000:
            stock_dict = self.get_all_stock_codes()
        return {
            code: name
            for code, name in stock_dict.items()
            if not main_board_only() or is_main_board(code)
        }

    def refresh_stock_universe(self, trade_date: str | None = None) -> dict:
        """刷新当前A股名单；失败时保留本地名单，绝不把完整缓存降级成内置小表。"""
        previous = self._load_local_stock_names()
        failure_reason = "live_universe_source_failed"
        try:
            frames = [ak.stock_sh_a_spot_em(), ak.stock_sz_a_spot_em()]
            all_stocks = pd.concat(
                [frame[["代码", "名称", "最新价", "昨收"]] for frame in frames],
                ignore_index=True,
            )
            all_stocks = all_stocks.drop_duplicates(subset=["代码"])
            all_stocks["代码"] = all_stocks["代码"].astype(str).str.zfill(6)
            code_pattern = r"^(00|30|60|68|88)\d{4}$"
            all_stocks = all_stocks[all_stocks["代码"].str.match(code_pattern)]
            excluded = ("债", "基", "ETF", "LOF", "基金", "B股", "指数", "转债", "回购")
            mask = ~all_stocks["名称"].astype(str).apply(
                lambda name: any(word in name for word in excluded)
            )
            special_non_equity = all_stocks["名称"].astype(str).str.contains("转换")
            latest_price = pd.to_numeric(all_stocks["最新价"], errors="coerce")
            previous_close = pd.to_numeric(all_stocks["昨收"], errors="coerce")
            not_yet_traded = latest_price.isna() & previous_close.isna()
            fresh = dict(
                zip(
                    all_stocks.loc[mask, "代码"],
                    all_stocks.loc[mask, "名称"].astype(str),
                )
            )
            if self._universe_size_is_safe(fresh, previous):
                delisted_codes, delisted_catalog = self._exchange_delisted_codes()
                eligible_codes = set(fresh)
                applied_delisted = eligible_codes & delisted_codes
                special_codes = (
                    set(all_stocks.loc[mask & special_non_equity, "代码"])
                    - applied_delisted
                )
                pending_codes = (
                    set(all_stocks.loc[mask & not_yet_traded, "代码"])
                    - applied_delisted
                    - special_codes
                )
                excluded_codes = applied_delisted | pending_codes | special_codes
                fresh = {
                    code: name
                    for code, name in fresh.items()
                    if code not in excluded_codes
                }
                if len(fresh) < MIN_UNIVERSE_SIZE:
                    raise ValueError("active_universe_below_minimum_after_exclusions")
                exclusion_evidence = {
                    "schema_version": "universe-exclusions-v1",
                    "count": len(excluded_codes),
                    "content_hash": _codes_hash(excluded_codes),
                    "categories": {
                        "exchange_delisted": {
                            "count": len(applied_delisted),
                            "content_hash": _codes_hash(applied_delisted),
                            "catalog": delisted_catalog,
                        },
                        "not_yet_traded": {
                            "count": len(pending_codes),
                            "content_hash": _codes_hash(pending_codes),
                            "source_id": "akshare:stock_sh_sz_a_spot_em",
                        },
                        "non_equity_special": {
                            "count": len(special_codes),
                            "content_hash": _codes_hash(special_codes),
                            "rule": "name_contains:转换",
                        },
                    },
                }
                if trade_date:
                    suspension_frame = ak.stock_tfp_em(date=trade_date.replace("-", ""))
                    self._save_security_status(fresh, suspension_frame, trade_date)
                self._save_stock_names(
                    fresh,
                    source="akshare",
                    exclusions=exclusion_evidence,
                )
                self.universe_refresh_status = {
                    "fresh": True,
                    "source": "akshare",
                    "count": len(fresh),
                    "excluded_count": len(excluded_codes),
                    "excluded_delisted_count": len(applied_delisted),
                    "excluded_pending_count": len(pending_codes),
                    "excluded_special_count": len(special_codes),
                }
                return fresh
            failure_reason = "universe_shrink_exceeded"
        except Exception as exc:
            print(f"  刷新股票名单失败: {exc}，继续使用本地完整名单")
            failure_reason = f"live_universe_source_failed:{type(exc).__name__}"
        self._mark_universe_stale(failure_reason)
        self.universe_refresh_status = {
            "fresh": False,
            "reason": failure_reason,
            "count": len(previous),
        }
        return previous if len(previous) >= MIN_UNIVERSE_SIZE else {}

    def _load_bootstrap_state(self) -> dict:
        if self.bootstrap_state_file.exists():
            try:
                return json.loads(self.bootstrap_state_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"attempts": {}, "short_history": {}, "failures": {}}

    def _save_bootstrap_state(self, state: dict) -> None:
        state["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        self.bootstrap_state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.bootstrap_state_file.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(self.bootstrap_state_file)

    def universe_coverage(self, universe=None) -> dict:
        """分别报告行情覆盖与可训练覆盖，避免把次新股误报为数据缺失。"""
        universe = universe or self._main_board_universe()
        state = self._load_bootstrap_state()
        short_history = state.get("short_history") or {}
        existing = set(self.csv_manager.list_all_stocks())
        covered = trainable = 0
        for code in universe:
            if code not in existing:
                continue
            rows = len(self.csv_manager.read_stock(code, nrows=220))
            covered += int(rows >= 1)
            trainable += int(rows >= 220)
        total = len(universe)
        ineligible = len([c for c in short_history if c in universe])
        eligible = max(total - ineligible, 0)
        return {
            "universe_count": total,
            "covered_count": covered,
            "coverage_ratio": round(covered / total, 4) if total else 0.0,
            "trainable_count": trainable,
            "trainable_eligible_count": eligible,
            "trainable_ratio": round(trainable / eligible, 4) if eligible else 0.0,
            "short_history_count": ineligible,
            "remaining_count": max(total - covered, 0),
            "failure_count": len(state.get("failures") or {}),
            "updated_at": state.get("updated_at"),
        }

    def bootstrap_universe(
        self,
        max_stocks=None,
        years: int = 6,
        refresh_universe: bool = False,
        missing_only: bool = False,
    ) -> dict:
        """完整回补主板股票池；每只完成后写检查点，进程中断可继续。"""
        from utils.data_freshness import expected_completed_trade_date

        if refresh_universe:
            self.refresh_stock_universe()
        universe = self._main_board_universe()
        completed_cutoff = expected_completed_trade_date(
            data_dir=self.full_data_dir,
            allow_unpublished_calendar=True,
        )
        if not completed_cutoff:
            return {
                "failed": 1,
                "reason": "trading_calendar_unavailable",
                "target_date": None,
            }
        security_statuses = self._verified_security_statuses(completed_cutoff)

        def legal_non_trading(code: str) -> bool:
            status = security_statuses.get(code) or {}
            return bool(
                status.get("verified") is True
                and status.get("as_of") == completed_cutoff
                and status.get("source_id") == "akshare:stock_tfp_em"
                and status.get("status") in {"suspended", "delisted"}
            )

        state = self._load_bootstrap_state()
        attempts = state.setdefault("attempts", {})
        failures = state.setdefault("failures", {})
        short_history = state.setdefault("short_history", {})
        for mapping in (failures, short_history):
            for code in list(mapping):
                if code not in universe:
                    mapping.pop(code, None)
        existing = set(self.csv_manager.list_all_stocks())
        queue = []
        for code in sorted(universe):
            if code not in existing:
                queue.append(code)
                continue
            if missing_only:
                continue
            latest = self.csv_manager.read_stock(code, nrows=1)
            if not latest.empty and str(latest.iloc[0]["date"])[:10] > completed_cutoff:
                complete = self.csv_manager.read_stock(code)
                complete = complete[
                    pd.to_datetime(complete["date"]).dt.strftime("%Y-%m-%d")
                    <= completed_cutoff
                ].copy()
                if not complete.empty:
                    self.csv_manager.write_stock(code, complete)
            latest = self.csv_manager.read_stock(code, nrows=1)
            latest_date = str(latest.iloc[0]["date"])[:10] if not latest.empty else None
            if latest_date != completed_cutoff:
                if not legal_non_trading(code):
                    queue.append(code)
                continue
            rows = len(self.csv_manager.read_stock(code, nrows=220))
            if rows < 220 and code not in short_history:
                queue.append(code)
        if max_stocks is not None:
            queue = queue[: max(0, max_stocks)]

        added = trainable_added = failed = 0
        state.update(
            {"status": "running", "universe_count": len(universe), "current": None}
        )
        self._save_bootstrap_state(state)

        def persisted_frame(result: FetchResult) -> tuple[pd.DataFrame, str | None]:
            frame = result.data.copy() if result.success else pd.DataFrame()
            if not frame.empty:
                frame = frame[
                    pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d")
                    <= completed_cutoff
                ].copy()
            latest = (
                pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d").max()
                if not frame.empty and "date" in frame
                else None
            )
            return frame, latest

        for index, code in enumerate(queue, start=1):
            state["current"] = code
            attempts[code] = int(attempts.get(code, 0)) + 1
            fetch = self.fetch_stock_history(code, years=years)
            frame, latest = persisted_frame(fetch)
            if (
                not legal_non_trading(code)
                and fetch.success
                and fetch.source == "tencent"
                and latest != completed_cutoff
            ):
                print(
                    f"  腾讯数据截止 {latest or '空'}，"
                    f"未覆盖 {completed_cutoff}，改用 AkShare 复核..."
                )
                fallback = self._fetch_stock_history_akshare(code, years=years)
                fallback_frame, fallback_latest = persisted_frame(fallback)
                if fallback.success and fallback_latest == completed_cutoff:
                    fetch = fallback
                    frame = fallback_frame
                    latest = fallback_latest
            rows = len(frame)
            acceptable = bool(
                rows >= 1 and (latest == completed_cutoff or legal_non_trading(code))
            )
            if acceptable:
                self.csv_manager.write_stock(code, frame)
                self._record_fetch_provenance(code, fetch, frame, full_history=True)
                added += 1
                trainable_added += int(rows >= 220)
                failures.pop(code, None)
                if rows < 220:
                    short_history[code] = rows
                else:
                    short_history.pop(code, None)
            elif legal_non_trading(code) and rows == 0:
                # 当日已核实停牌/退市的无历史标的可以在 snapshot
                # 中明确分类为非交易，不伪造空 K 线。
                short_history[code] = 0
                failures.pop(code, None)
            else:
                failed += 1
                failures[code] = {
                    "attempts": attempts[code],
                    "rows": rows,
                    "source": fetch.source,
                    "reason": (
                        "returned_latest_date_mismatch"
                        if rows and latest != completed_cutoff
                        else fetch.reason
                    ),
                    "returned_latest_date": latest,
                    "requested_date": completed_cutoff,
                }
            state["processed_this_run"] = index
            self._save_bootstrap_state(state)
            if index % 10 == 0:
                time.sleep(0.1)

        coverage = self.universe_coverage(universe)
        state.update(
            {
                "status": "complete" if coverage["remaining_count"] == 0 else "partial",
                "completed_through_date": completed_cutoff,
                "current": None,
                "last_run_attempted": len(queue),
                "last_run_added": added,
                "last_run_failed": failed,
            }
        )
        self._save_bootstrap_state(state)
        failure_reason_counts: dict[str, int] = {}
        for code, item in failures.items():
            if code not in universe or not isinstance(item, dict):
                continue
            reason = str(item.get("reason") or "unknown")
            failure_reason_counts[reason] = failure_reason_counts.get(reason, 0) + 1
        return {
            **coverage,
            "attempted": len(queue),
            "added": added,
            "trainable_added": trainable_added,
            "failed": failed,
            "failure_reason_counts": dict(sorted(failure_reason_counts.items())),
            "status": state["status"],
        }

    def expand_universe(self, max_new: int = 50, years: int = 2) -> dict:
        """兼容旧调用；新实现同样具备断点与覆盖率口径。"""
        return self.bootstrap_universe(max_stocks=max_new, years=years)

    def daily_update(self, max_stocks=None):
        """
        每日增量更新 - 只获取实际需要的天数
        优化：使用快速缓存机制，避免重复读取已更新的股票
        修复：盘中执行时不会将盘中数据误存为收盘数据
        """
        from datetime import datetime
        from utils.data_freshness import expected_completed_trade_date

        # 日更必须以完整股票名单为准。缺历史的票交给后台 bootstrap，已有文件全部增量更新。
        universe = self._main_board_universe()
        existing_stocks = [
            code for code in sorted(universe) if self.csv_manager.stock_exists(code)
        ]

        if not existing_stocks:
            print("没有找到已有数据，请先执行 init")
            return

        if max_stocks:
            existing_stocks = existing_stocks[:max_stocks]

        total = len(existing_stocks)
        updated = 0
        failed = 0
        skipped = 0
        archived = 0
        classified_non_trading = 0
        stock_results = []

        print(f"\n开始更新 {total} 只股票的数据...")
        print("=" * 60)

        current_time = datetime.now().time()
        cutoff_str = expected_completed_trade_date(
            data_dir=self.full_data_dir,
            allow_unpublished_calendar=True,
        )
        if not cutoff_str:
            return {
                "failed": 1,
                "reason": "trading_calendar_unavailable",
                "target_date": None,
            }
        security_statuses = self._verified_security_statuses(cutoff_str)

        def legal_non_trading(code: str) -> bool:
            status = security_statuses.get(code) or {}
            return bool(
                status.get("verified") is True
                and status.get("as_of") == cutoff_str
                and status.get("source_id") == "akshare:stock_tfp_em"
                and status.get("status") in {"suspended", "delisted"}
            )

        completed_cutoff = datetime.strptime(cutoff_str, "%Y-%m-%d").date()
        market_data_complete_time = datetime.strptime("15:05", "%H:%M").time()
        is_after_market_data_complete = current_time >= market_data_complete_time
        if not is_after_market_data_complete:
            print(
                f"⚠️ 当前时间 {current_time.strftime('%H:%M')}，今天行情尚未达完整时点；"
                f"本次严格更新到 {cutoff_str}"
            )

        # 快速缓存：检查上次更新记录
        update_cache_file = self.state_dir / ".update_cache.json"
        update_cache_file.parent.mkdir(parents=True, exist_ok=True)
        update_cache = {}
        if update_cache_file.exists():
            try:
                with open(update_cache_file, "r", encoding="utf-8") as f:
                    update_cache = json.load(f)
            except (OSError, json.JSONDecodeError):
                update_cache = {}

        def local_date_issues(codes: list[str]) -> dict[str, str]:
            issues = {}
            for code in codes:
                latest = self.csv_manager.read_stock(code, nrows=1)
                if latest.empty or "date" not in latest:
                    if not legal_non_trading(code):
                        issues[code] = "missing_or_unreadable"
                    continue
                persisted = str(latest.iloc[0]["date"])[:10]
                if persisted != cutoff_str and not legal_non_trading(code):
                    issues[code] = persisted
            return issues

        # 缓存只是优化，不是完整性证据；必须重新核对本地日期。
        cache_date = update_cache.get("completed_through_date")
        if cache_date == cutoff_str and not max_stocks:
            cached_issues = local_date_issues(existing_stocks)
            if not cached_issues:
                print(f"✓ 已完成截至 {cache_date} 的收盘数据更新，无需重复更新")
                print("=" * 60)
                return {
                    "target_date": cutoff_str,
                    "updated": 0,
                    "failed": 0,
                    "cached": True,
                    "validated_count": len(existing_stocks),
                }
            print(f"  更新缓存失效：{len(cached_issues)} 只股票未到目标日期")

        # 预筛选：快速检查哪些股票需要更新（只读取第一行）
        stocks_to_update = []
        print("  正在检查股票更新状态...")

        for code in existing_stocks:
            if legal_non_trading(code):
                skipped += 1
                classified_non_trading += 1
                stock_results.append(
                    {
                        "code": code,
                        "requested_date": cutoff_str,
                        "returned_latest_date": None,
                        "persisted_latest_date": None,
                        "source": "akshare:stock_tfp_em",
                        "row_count": 0,
                        "validation_status": "classified_non_trading",
                        "error_code": None,
                    }
                )
                continue
            # 快速读取：只读CSV第一行（最新日期）
            path = self.csv_manager.get_stock_path(code)
            if not path.exists():
                stocks_to_update.append((code, 30))  # 默认取30天
                continue

            try:
                # 只读取第一行（header + 第一行数据）
                df_quick = pd.read_csv(path, nrows=1)
                if df_quick.empty:
                    stocks_to_update.append((code, 30))
                    continue

                latest_date = pd.to_datetime(df_quick.iloc[0]["date"]).date()
                days_needed = (completed_cutoff - latest_date).days

                if days_needed > 0:
                    days_to_fetch = min(days_needed + 2, 60)
                    stocks_to_update.append((code, days_to_fetch))
                elif days_needed == 0:
                    # 收盘后首次执行时重新拉取当天最终数据；盘中截止日已完整则跳过。
                    if is_after_market_data_complete and cache_date != cutoff_str:
                        stocks_to_update.append((code, 2))
                    else:
                        skipped += 1
                else:
                    skipped += 1
            except Exception:
                stocks_to_update.append((code, 30))

        need_update = len(stocks_to_update)
        print(
            f"  需要更新: {need_update} 只, 已最新/合法无交易: {skipped} 只, "
            f"明确分类: {classified_non_trading} 只"
        )

        if need_update == 0:
            issues = local_date_issues(existing_stocks)
            if not max_stocks and not issues:
                update_cache["completed_through_date"] = cutoff_str
                with open(update_cache_file, "w", encoding="utf-8") as f:
                    json.dump(update_cache, f)
            if issues:
                print(f"✗ 本地数据未通过目标日期校验: {len(issues)} 只")
            else:
                print("✓ 所有数据已是最新")
            print("=" * 60)
            return {
                "target_date": cutoff_str,
                "updated": 0,
                "failed": len(issues),
                "skipped": skipped,
                "archived": archived,
                "classified_non_trading": classified_non_trading,
                "cached": False,
                "validation_failures": issues,
            }

        print(f"\n开始更新 {need_update} 只股票...")
        print("=" * 60)

        for i, (code, days_to_fetch) in enumerate(stocks_to_update, 1):
            print(
                f"[{i}/{need_update}] 更新 {code} (需获取 {days_to_fetch} 天数据)...",
                end=" ",
            )

            # 重新读取现有数据以获取旧记录数
            existing_df = self.csv_manager.read_stock(code)
            old_count = len(existing_df)

            fetch = self.fetch_stock_update(code, days=days_to_fetch)
            df = fetch.data if fetch.success else pd.DataFrame()

            if not df.empty:
                # 腾讯接口盘中会包含今天的实时 K 线；未收盘时必须截掉。
                df = df[pd.to_datetime(df["date"]).dt.date <= completed_cutoff].copy()
            returned_dates = (
                pd.to_datetime(df["date"], errors="coerce").dropna()
                if not df.empty
                else pd.Series(dtype="datetime64[ns]")
            )
            returned_latest = (
                returned_dates.max().strftime("%Y-%m-%d")
                if not returned_dates.empty
                else None
            )
            if not df.empty and returned_latest == cutoff_str:
                self.csv_manager.update_stock(code, df)
                new_df = self.csv_manager.read_stock(code)
                self._record_fetch_provenance(code, fetch, new_df, full_history=False)
                new_count = len(new_df)
                added = new_count - old_count
                print(f"✓ (新增 {added} 条)")
                updated += 1
                persisted_latest = (
                    str(new_df.iloc[0]["date"])[:10] if not new_df.empty else None
                )
                stock_results.append(
                    {
                        "code": code,
                        "requested_date": cutoff_str,
                        "returned_latest_date": returned_latest,
                        "persisted_latest_date": persisted_latest,
                        "source": fetch.source,
                        "row_count": fetch.rows,
                        "validation_status": "valid"
                        if persisted_latest == cutoff_str
                        else "invalid",
                        "error_code": None
                        if persisted_latest == cutoff_str
                        else "persisted_date_mismatch",
                    }
                )
            else:
                reason = (
                    fetch.reason
                    if not fetch.success
                    else "returned_latest_date_mismatch"
                )
                print(f"✗ 失败 ({reason}, latest={returned_latest})")
                failed += 1
                current = self.csv_manager.read_stock(code, nrows=1)
                stock_results.append(
                    {
                        "code": code,
                        "requested_date": cutoff_str,
                        "returned_latest_date": returned_latest,
                        "persisted_latest_date": (
                            str(current.iloc[0]["date"])[:10]
                            if not current.empty
                            else None
                        ),
                        "source": fetch.source,
                        "row_count": fetch.rows,
                        "validation_status": "invalid",
                        "error_code": reason,
                    }
                )

            if i % 10 == 0:
                time.sleep(0.1)  # 降低限速

        validation_failures = local_date_issues(existing_stocks)
        # 失败或本地日期不匹配时都不写“已完成”缓存。
        if failed == 0 and not validation_failures and not max_stocks:
            update_cache["completed_through_date"] = cutoff_str
            with open(update_cache_file, "w", encoding="utf-8") as f:
                json.dump(update_cache, f)

        print("=" * 60)
        print(
            f"完成! 更新成功: {updated}, 跳过: {skipped}, 历史归档: {archived}, 失败: {failed}"
        )
        return {
            "target_date": cutoff_str,
            "updated": updated,
            "skipped": skipped,
            "archived": archived,
            "classified_non_trading": classified_non_trading,
            "failed": len(
                set(validation_failures)
                | {
                    row["code"]
                    for row in stock_results
                    if row["validation_status"]
                    not in {"valid", "classified_non_trading"}
                }
            ),
            "cached": False,
            "validation_failures": validation_failures,
            "stocks": stock_results,
        }
