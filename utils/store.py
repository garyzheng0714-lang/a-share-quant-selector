"""本地行情存储：每只股票一个 CSV（最新在前），元数据为 JSON。

目录布局（`QUANT_DATA_DIR`，默认 ./data）：
    {前两位}/{code}.csv         日线 date,open,close,high,low,volume
    stock_names.json            {code: name}
    stock_industry.json         {code: industry}
    stock_market_cap.json       {code: {"circ_mv": 元, "total_mv": 元}}
    factor_cache/{date}.json    当日全因子命中（见 utils/scan.py）
没有数据库，没有快照层；读写都是普通文件，任何一步坏了直接报错，不伪造数据。
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path

import pandas as pd

ANCHOR_CODES = ("000001", "600030", "600036", "600519")
_CODE_RE = re.compile(r"^\d{6}$")


class Store:
    def __init__(self, data_dir: str | Path | None = None):
        self.data_dir = Path(data_dir or os.environ.get("QUANT_DATA_DIR", "data"))
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._json_cache: dict[str, tuple[float, dict]] = {}

    # ---- 日线 ----

    def stock_path(self, code: str) -> Path:
        return self.data_dir / code[:2] / f"{code}.csv"

    def read_stock(self, code: str, nrows: int | None = None) -> pd.DataFrame:
        path = self.stock_path(code)
        if not path.exists() or path.stat().st_size == 0:
            return pd.DataFrame()
        return pd.read_csv(path, parse_dates=["date"], nrows=nrows)

    def write_stock(self, code: str, df: pd.DataFrame) -> Path:
        path = self.stock_path(code)
        path.parent.mkdir(parents=True, exist_ok=True)
        df = df.drop_duplicates(subset=["date"], keep="last").sort_values(
            "date", ascending=False
        )
        tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
        df.to_csv(tmp, index=False)
        tmp.replace(path)
        return path

    def update_stock(self, code: str, new_df: pd.DataFrame) -> Path:
        old = self.read_stock(code)
        if old.empty:
            return self.write_stock(code, new_df)
        return self.write_stock(code, pd.concat([old, new_df], ignore_index=True))

    def list_stocks(self) -> list[str]:
        return sorted(
            p.stem for p in self.data_dir.glob("*/*.csv") if _CODE_RE.match(p.stem)
        )

    def latest_date(self) -> str:
        """锚点股最新日期的最大值；没有数据返回空串."""
        dates = []
        for code in ANCHOR_CODES:
            df = self.read_stock(code, nrows=1)
            if not df.empty:
                dates.append(str(df["date"].iloc[0])[:10])
        return max(dates) if dates else ""

    def stock_date(self, code: str) -> str:
        df = self.read_stock(code, nrows=1)
        return str(df["date"].iloc[0])[:10] if not df.empty else ""

    # ---- 元数据 JSON ----

    def load_json(self, name: str) -> dict:
        path = self.data_dir / name
        if not path.exists():
            return {}
        mtime = path.stat().st_mtime
        cached = self._json_cache.get(name)
        if cached and cached[0] == mtime:
            return cached[1]
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self._json_cache[name] = (mtime, data)
        return data

    def save_json(self, name: str, data: dict) -> None:
        path = self.data_dir / name
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        tmp.replace(path)
        self._json_cache.pop(name, None)

    def json_age_days(self, name: str) -> float:
        path = self.data_dir / name
        if not path.exists():
            return float("inf")
        return (time.time() - path.stat().st_mtime) / 86400

    def names(self) -> dict:
        return self.load_json("stock_names.json")

    def industries(self) -> dict:
        return self.load_json("stock_industry.json")

    def caps(self) -> dict:
        return self.load_json("stock_market_cap.json")

    def cap_yi(self, code: str) -> float | None:
        item = self.caps().get(code)
        if isinstance(item, dict):
            cap = item.get("circ_mv") or item.get("total_mv")
            if isinstance(cap, (int, float)) and cap > 0:
                return round(cap / 1e8, 1)
        return None
