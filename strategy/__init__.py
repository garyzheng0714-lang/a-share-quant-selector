"""生产策略包。

生产决策只通过 ``utils.policy_engine`` 调用 Super B1。旧 BowlRebound 源码仅供
显式开启的隔离研究入口使用，源码也已移至 ``research/legacy``，
不在这里导出或自动注册。
"""

STRATEGIES: dict[str, type] = {}

__all__ = ["STRATEGIES"]
