# Legacy research only

本目录保存修复前的 BowlRebound、旧 `views/results/performance`、
旧收盘退出口径的共振/预备队/排序回测入口，
仅用于复现实验，不属于生产决策、发布或战绩证据链。

- 不得连接生产账本或覆盖 `CURRENT_SNAPSHOT`。
- 输出必须写到独立的临时研究目录。
- 结果不得标记为 active/validated，也不得用于生产发布审批。
- 正式训练、回放和模拟盘统一使用 `a-share-eod-open-open-v5` 执行政策。

旧 CLI 文件是实验档案，不承诺与当前生产数据契约兼容。它默认拒绝运行，必须同时设置
`ALLOW_LEGACY_RESEARCH=1` 和仓库外的绝对路径 `LEGACY_RESEARCH_ROOT`。
它会强制把数据、旧 views 账本和回测产物写到该隔离目录。默认不发送通知；
如需研究通知，还必须显式设置 `ALLOW_LEGACY_NOTIFICATIONS=1`，且配置文件必须位于隔离目录内。
同目录的共振、预备队和排序脚本也共用这个路径门禁：默认从
`LEGACY_RESEARCH_ROOT/data` 读数据，向 `LEGACY_RESEARCH_ROOT/outputs` 写结果；
`--out` / `--ins` / `--oos` 不允许逃出该根目录。

旧 CLI 依赖的 `schedule` / `fastdtw` / `matplotlib` 不再进入生产锁文件和生产镜像。
如确需复现旧实验，应在仓库外的独立虚拟环境安装它们；示例参数见
`strategy_params.example.yaml`，复制到 `LEGACY_RESEARCH_ROOT/strategy_params.yaml`
后再运行。
