"""
CSV 数据管理工具
"""

import os
import re
import threading
import pandas as pd
from pathlib import Path

from utils.runtime_paths import market_data_dir


class MarketDataReadError(RuntimeError):
    """已存在的行情文件无法解析；不得降级成“无信号”。"""


class CSVManager:
    """CSV 文件管理器；每个实例在创建时绑定单个快照。"""

    def __init__(self, data_dir, *, resolve_snapshot=True, writable=None):
        self.base_data_dir = market_data_dir(data_dir)
        if writable is not False:
            self.base_data_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir = self.base_data_dir
        self.resolve_snapshot = bool(resolve_snapshot)
        self.snapshot_id: str | None = None
        self.snapshot_error: str | None = None
        self._explicit_writable = writable
        self.read_only = writable is False
        self._resolve_snapshot_once()

    def _resolve_snapshot_once(self) -> None:
        """只在创建时解析指针，防止一次扫描中混读两个快照。"""
        if not self.resolve_snapshot:
            return
        try:
            from utils.market_snapshot import load_current_market_snapshot

            current = load_current_market_snapshot(
                self.base_data_dir, verify_files=False
            )
        except Exception as exc:
            current = {
                "available": False,
                "reason": f"snapshot_resolution_failed:{type(exc).__name__}",
            }
        if current.get("available"):
            self.snapshot_id = current["snapshot_id"]
            self.data_dir = Path(current["payload_dir"])
            self.read_only = True
            return
        self.snapshot_error = str(current.get("reason") or "snapshot_unavailable")
        if self.read_only:
            # Read-only callers must never fall back to legacy mutable CSV files.
            self.data_dir = self.base_data_dir / "market_snapshots" / ".unavailable"

    def get_stock_path(self, stock_code):
        """获取股票CSV文件路径"""
        # 按股票代码前两位分目录，避免单目录文件过多
        prefix = stock_code[:2] if len(stock_code) >= 2 else stock_code
        subdir = self.data_dir / prefix
        return subdir / f"{stock_code}.csv"

    def read_stock(self, stock_code, nrows=None):
        """读取股票数据.

        Args:
            stock_code: 股票代码
            nrows: 限制读取行数（None 表示全部读取）
        """
        path = self.get_stock_path(stock_code)
        if not path.exists():
            return pd.DataFrame()

        if path.stat().st_size == 0:
            raise MarketDataReadError(f"empty_market_file:{stock_code}")

        try:
            df = pd.read_csv(path, parse_dates=["date"], nrows=nrows)
            return df
        except Exception as e:
            raise MarketDataReadError(
                f"unreadable_market_file:{stock_code}:{type(e).__name__}"
            ) from e

    def write_stock(self, stock_code, df):
        """写入股票数据（自动去重排序）"""
        if self.read_only:
            raise PermissionError("published market snapshots are immutable")
        path = self.get_stock_path(stock_code)

        # 去重：按日期去重，保留最后出现的
        df = df.drop_duplicates(subset=["date"], keep="last")

        # 按日期倒序排列（最新在前）
        df = df.sort_values("date", ascending=False)

        # 确保目录存在
        path.parent.mkdir(parents=True, exist_ok=True)

        # 原子替换，避免后台全量回补与前台扫描并发时读到半截 CSV。
        tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
        df.to_csv(tmp, index=False)
        tmp.replace(path)
        return path

    def update_stock(self, stock_code, new_df):
        """增量更新股票数据"""
        existing_df = self.read_stock(stock_code)

        if existing_df.empty:
            return self.write_stock(stock_code, new_df)

        # 合并数据
        combined = pd.concat([existing_df, new_df], ignore_index=True)
        return self.write_stock(stock_code, combined)

    def list_all_stocks(self):
        """列出所有已保存的股票代码"""
        stocks = []
        for csv_file in self.data_dir.rglob("*.csv"):
            stock_code = csv_file.stem
            # data 下还会有训练集、回测结果等 CSV，不能把它们当股票代码请求行情。
            if re.fullmatch(r"\d{6}", stock_code):
                stocks.append(stock_code)
        return sorted(stocks)

    def get_stock_count(self):
        """获取已保存的股票数量"""
        return len(self.list_all_stocks())

    def stock_exists(self, stock_code):
        """检查股票数据是否存在"""
        return self.get_stock_path(stock_code).exists()
