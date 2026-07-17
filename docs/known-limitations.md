# 已知限制

更新时间：2026-07-17。

## 发布状态

- Git 分支、工作区或历史 WORKLOG 都不能证明线上版本；必须核对部署 workflow、线上 Git SHA、健康检查与页面状态。

## 安全

- `config/config.yaml` 虽被 `.gitignore` 排除，但仍是 tracked 文件。2026-07-17 的只报布尔结果扫描确认：当前文件与 HEAD 中都存在非占位的 secret-like 值。必须轮换相关凭证、停止跟踪并清理/评估 Git 历史；在轮换完成前按已泄露处理。本文件不记录任何值。
- Flask 默认监听 `0.0.0.0`，Compose 映射 18321；应用没有登录、权限、CSRF 或请求签名。
- 数据更新、决策、调度器和视图写接口都可能被网络调用，必须依赖防火墙、私网或认证反向代理。
- `deploy.sh` 有远端 SSH 与 `rsync --delete`，不能作为无审核的一键操作。

## 模型与数据

- Super B1 是规则 baseline，不是收益保证。
- 周线闸门默认 shadow；市场/板块/风险/质量模型只有满足严格 source refs 才能 active。
- 历史证券宇宙、行业成分、公告正文/精确发布时间、交易费用和可成交性数据仍不完整。
- 旧回测中的胜率/超额受样本、幸存者偏差、多重检验和交易成本影响。
- tomorrow watch 已被样本外证伪，只能作为观察提示。
- 外部行情、东财公告、交易日历与 LLM 都可能不可用；系统必须降级而不是猜测。
- 完整 policy 仍需要至少 21 个真实有信号月份、统计功效和前向观察；当前数据不足时只能登记 shadow，不能宣称已自我提升。
- 模拟账户从新账本启用后才开始积累成交与净值；早期样本很少，不能用短期盈亏评估算法有效性。
- 当前模拟成交依赖日线可执行性近似，无法还原开盘集合竞价队列、盘中临停或逐笔冲击成本。

## 工程

- Python 项目内 `.venv` 没有 pytest；当前验证使用系统 `python3`。
- 前端没有独立自动化测试脚本；当前质量门禁是 ESLint 与 TypeScript/Vite build。
- ECharts 生产 chunk 约 574 kB，超过 Vite 500 kB 警告阈值。
- `views/views.db` 是 0 字节误产物，本轮已移出项目；主库实际在 `data/views.db`。
- `strategy/pattern_library.py`、`utils/kline_chart_fast.py` 与旧图表测试仍含 `/root/quant-csv` 历史绝对路径；当前主部署目录是 `/opt/a-share-quant`，这些遗留辅助路径未在本轮文档任务中重构。
