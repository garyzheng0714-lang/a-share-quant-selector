"""板块过滤模块 - 按股票代码前缀过滤交易板块

用户只有沪深主板交易权限，选股结果需要筛掉无权限板块：
- 创业板：300 / 301 / 302 开头（深交所，需单独开通权限）
- 科创板：688 / 689 开头（上交所，50万门槛）
- 北交所：4 / 8 / 920 开头

沪深主板代码前缀：
- 60 开头：上海主板（600/601/603/605）
- 00 开头：深圳主板（000/001，含已并入主板的原中小板 002/003）

配置开关：config/strategy_params.yaml 的 MarketFilter.main_board_only（默认 true）
"""

from pathlib import Path

import yaml

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "strategy_params.yaml"

MAIN_BOARD_PREFIXES = ("60", "00")


def is_main_board(code) -> bool:
    """判断股票代码是否属于沪深主板."""
    return str(code).startswith(MAIN_BOARD_PREFIXES)


def main_board_only() -> bool:
    """读取配置：是否只保留沪深主板（读不到配置时默认开启，宁严勿松）."""
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return bool(cfg.get("MarketFilter", {}).get("main_board_only", True))
    except Exception:
        return True
