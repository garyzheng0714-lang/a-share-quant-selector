# 审查整改矩阵

更新时间：2026-07-23。

本矩阵逐项对应审查基线 `8ce1b492d122f72391b7195c9e530acbbc9d1ff2`。这里的“已处理”只表示当前修复工作树有实现和测试证据，不表示代码已经部署，也不替代可信数据重建和生产演练。

状态说明：

- **仓库内已处理**：代码、配置、文档和自动测试已经覆盖。
- **已封堵，外部待办**：代码已停止继续扩大风险，但历史事实或外部系统仍需人工处置。
- **待生产验收**：本地可静态或单元验证，仍必须在 CI/目标主机真实执行。

## P0

| 编号 | 处理结果 | 主要证据 | 状态 |
| --- | --- | --- | --- |
| P0-1 随机行情写入正式数据 | 删除生产 synthetic fallback；上游全失败返回结构化失败；日更只能继承已验证的可信基础快照，全量重建从空 staging 开始；操作状态移出 payload，多出任何未入 manifest 的文件都拒绝发布/读取；任务失败与租约耗尽在同一事务追加不可变 warning/critical 告警事件。 | [akshare_fetcher.py](../utils/akshare_fetcher.py)、[market_ingestion.py](../utils/market_ingestion.py)、[market_snapshot.py](../utils/market_snapshot.py)、[operations_store.py](../utils/operations_store.py)、[test_market_data_contract.py](../tests/test_market_data_contract.py)、[test_market_snapshot.py](../tests/test_market_snapshot.py) | **已封堵，外部待办**：旧数据仍须隔离并可信全量重建，生产通知渠道仍须验收。 |
| P0-2 凭证进入 Git/镜像 | 继续排除本地配置、数据、DB 和日志，不把它们复制进镜像；运行时仍使用 secret file。按个人项目所有者决定，Git 历史密钥扫描不作为 CI 或发布阻断项。 | [.dockerignore](../.dockerignore)、[config.yaml.template](../config/config.yaml.template)、[Dockerfile](../Dockerfile)、[docker-compose.yml](../docker-compose.yml) | **所有者接受，不阻断部署** |
| P0-3 无认证写 API + 公网端口 | 写请求实行 viewer/publisher/admin RBAC、短时 HMAC、nonce 防重放、幂等键、变更原因、持久限流和审计；旧写入口永久 410；Compose 只绑定 localhost。 | [api_security.py](../utils/api_security.py)、[operations_store.py](../utils/operations_store.py)、[web_server.py](../web_server.py)、[docker-compose.yml](../docker-compose.yml)、[test_api_security.py](../tests/test_api_security.py) | **仓库内已处理**；TLS、VPN/反代和防火墙仍需生产验收。 |
| P0-4 `main` 直接部署且来源不绑定 | 删除旧自动部署；CI 与发布分离；人工选择完整 SHA；只构建一次；按 digest 签名扫描，由 runner 复验后通过 SSH 传输，目标主机按内容寻址镜像 ID 校验；生成 SBOM/provenance、签名、Trivy 扫描；正式迁移前停止旧 writer、备份静止账本并在临时副本演练；使用 data/state 双只读 canary 核对候选镜像 ID/SHA/snapshot/只读查询；失败清理 canary，并按所处阶段重启旧服务或回退应用。 | [ci.yml](../.github/workflows/ci.yml)、[release.yml](../.github/workflows/release.yml)、[migration_dry_run.py](../tools/migration_dry_run.py)、[Dockerfile](../Dockerfile)、[operator-runbook.md](operator-runbook.md) | **待生产验收**：必须在 GitHub environment 和目标主机跑通一次完整发布/回滚。 |

## P1

| 编号 | 处理结果 | 主要证据 | 状态 |
| --- | --- | --- | --- |
| P1-1 freshness 样本太少 | freshness 只接受已验证不可变快照，交易日必须精确等于预期完成日，覆盖率至少 98%，锚定股/来源/质量门全部满足；未来和过期都拒绝。 | [data_freshness.py](../utils/data_freshness.py)、[test_data_freshness.py](../tests/test_data_freshness.py) | **仓库内已处理** |
| P1-2 股票池失败误报 HTTP 成功 | HTTP 成功必须来自本次有效响应；缓存仅作为显式 stale LKG；小内置名单不再进入生产成功路径；股票池骤减触发阻断，新上市/复牌标的进入后台 bootstrap，退市/停牌必须有同日证券状态证据。 | [akshare_fetcher.py](../utils/akshare_fetcher.py)、[test_market_data_contract.py](../tests/test_market_data_contract.py) | **仓库内已处理** |
| P1-3 日更成功但未到目标日期 | provenance 记录实际落盘起止日、行数、source trade date；校验使用实际文件尾日；只有经当日证券状态证明的停牌/退市才可分类为非交易，新股不会被无声忽略；旧日、未来日、缺行和 schema 变化都失败关闭。 | [market_snapshot.py](../utils/market_snapshot.py)、[test_market_data_contract.py](../tests/test_market_data_contract.py)、[test_market_snapshot.py](../tests/test_market_snapshot.py) | **仓库内已处理** |
| P1-4 只有单文件原子替换 | 全市场写入 staging，完整校验后发布内容寻址快照并原子切换指针；读取器一次请求固定一个 snapshot；日更和全量重建共享跨进程 writer lock。 | [market_snapshot.py](../utils/market_snapshot.py)、[csv_manager.py](../utils/csv_manager.py)、[market_ingestion.py](../utils/market_ingestion.py)、[test_ingestion_concurrency.py](../tests/test_ingestion_concurrency.py) | **仓库内已处理** |
| P1-5 历史时点/幸存者/复权前视 | 参考资料只能从已校验市场快照重建，禁止倒签；训练 schema 同时保存 feature/reference snapshot ID，二者不一致即拒绝；证券状态必须从同日 `security_status.json` 完整验证，不再只用名称猜 ST/停复牌/退市；Super B1 改为按不可变日快照追加 PIT 特征分片，当前前复权历史只能补成熟标签，不能反向制造特征。历史不足时明确记为预热且 `trained=false`。 | [reference_snapshots.py](../utils/reference_snapshots.py)、[hierarchical_walk_forward.py](../tools/hierarchical_walk_forward.py)、[self_evolution.py](../utils/self_evolution.py)、[test_hierarchical_walk_forward.py](../tests/test_hierarchical_walk_forward.py) | **代码闭环已处理**；训练仍需随每日快照自然累积至 21 个月，期间不对外宣称自进化已完成。 |
| P1-6 两条生产策略链分叉 | Super B1 成为唯一生产 baseline；生产策略包不导出/注册 BowlRebound；动态旧注册器默认拒绝；旧 CLI 要双重显式开关、仓库外目录和独立 DB；生产中的旧 views/results/LLM 选股 CRUD 实现已移除，兼容 Web 入口固定 410。 | [strategy/__init__.py](../strategy/__init__.py)、[view_manager.py](../views/view_manager.py)、[daily_pick.py](../utils/daily_pick.py)、[legacy README](../research/legacy/README.md)、[test_legacy_isolation.py](../tests/test_legacy_isolation.py) | **仓库内已处理** |
| P1-7 `as_of` 只记录不约束读取 | CSVManager 在构造时绑定单一 snapshot；决策读取前和落账前都复验全部文件 hash；live/replay 都用绑定的 manager 和显式 as-of；规则/板块/因子派生产物的内容 hash 也随决策落账；损坏不是“无信号”。 | [csv_manager.py](../utils/csv_manager.py)、[artifact_integrity.py](../utils/artifact_integrity.py)、[hierarchical_decision.py](../utils/hierarchical_decision.py)、[decision_replay.py](../utils/decision_replay.py)、[test_decision_replay.py](../tests/test_decision_replay.py) | **仓库内已处理** |
| P1-8 盘前处理过期收盘决策 | 盘前只接受当前 expected trade date、同一 snapshot、同一策略版本和明确 close run ID；幂等身份绑定 exact close run。 | [hierarchical_decision.py](../utils/hierarchical_decision.py)、[test_hierarchical_decision.py](../tests/test_hierarchical_decision.py) | **仓库内已处理** |
| P1-9 删除不可成交训练样本 | entry unbuyable 与 exit unsellable 分层保留，收益标签未定义时不伪造收益；风险标签和成熟度独立记录。 | [hierarchical_walk_forward.py](../tools/hierarchical_walk_forward.py)、[execution_model.py](../utils/execution_model.py)、[test_hierarchical_walk_forward.py](../tests/test_hierarchical_walk_forward.py) | **仓库内已处理** |
| P1-10 shadow 可直接 active | 研究调用只能登记 shadow/rejected；服务器复验五个组件、哈希、source refs、前向观察、reviewer/工单；双人审批后以一个完整 policy 事件原子激活，旧单层 promotion 禁用；注册、验证、发布证据由 DB trigger 防改/删，回退只能指向激活时预批的上一 policy 且仍需双人。 | [decision_ledger.py](../utils/decision_ledger.py)、[runtime_schema.py](../utils/runtime_schema.py)、[test_decision_ledger.py](../tests/test_decision_ledger.py)、[model-governance.md](model-governance.md) | **仓库内已处理** |
| P1-11 调度器非单例、无日级幂等 | 独立 worker 使用有硬容量上限的持久任务队列、租约、心跳和稳定业务幂等键；queued 可由 admin 原子取消，running 不做假取消；每次尝试单独落账，可重试失败指数退避，过期租约先记录失败再接管并生成告警；scheduler leader 使用数据库租约并每 30 秒对账，收盘/盘前任务绑定交易日和执行窗口；重启/并发提交仍只产生一个任务。 | [operations_store.py](../utils/operations_store.py)、[task_submission.py](../utils/task_submission.py)、[worker.py](../worker.py)、[test_operations_store.py](../tests/test_operations_store.py) | **仓库内已处理** |
| P1-12 缓存只按日期 | 统一缓存身份包含 snapshot ID、策略版本、完整 Git SHA、universe/reference hash 和缓存 schema；同日修正或代码变化必然换键；Super B1、板块、因子和市场温度计的规范内容 SHA-256 必须通过，旧/被改缓存失效，实际摘要进入决策证据。 | [decision_versions.py](../utils/decision_versions.py)、[artifact_integrity.py](../utils/artifact_integrity.py)、[sector_rotation.py](../utils/sector_rotation.py)、[test_cached_artifact_integrity.py](../tests/test_cached_artifact_integrity.py) | **仓库内已处理** |
| P1-13 版本号漏依赖 | 策略版本覆盖动态策略/因子、执行模型、决策配置、数据契约、walk-forward、锁文件和前端 lock；测试验证依赖内容变化会改变版本。 | [decision_versions.py](../utils/decision_versions.py)、[test_decision_versions.py](../tests/test_decision_versions.py) | **仓库内已处理** |
| P1-14 模拟账户恒等式对账/仓位上限 | 现金从 cash events、持仓从 fills/lots/closures、NAV 从独立价格重建；缺价格停止日结；单股仓位扣除现有持仓；同快照同日 NAV/委托业务幂等且 worker 竞争安全；fill/NAV 显式绑定快照和执行版本。 | [paper_trading.py](../utils/paper_trading.py)、[test_paper_trading.py](../tests/test_paper_trading.py)、[test_paper_properties.py](../tests/test_paper_properties.py) | **仓库内已处理**；真实逐笔成交仍不在日线模拟能力内。 |
| P1-15 成交模型不一致 | 回放、训练、T+1/T+5 outcome、performance、决策和模拟盘统一使用 `a-share-eod-open-open-v5`；持有和延迟窗口按已绑定快照的交易所会话轴推进，个股停牌缺 bar 不得跳到复牌日代替成交；每条 outcome/fill/NAV 保存快照和执行版本；统一处理 T+1、100 股、停牌、涨跌停、滑点、最低佣金、印花税、过户费和延期卖出。 | [execution_model.py](../utils/execution_model.py)、[self_evolution.py](../utils/self_evolution.py)、[paper_trading.py](../utils/paper_trading.py)、[policy_engine.py](../utils/policy_engine.py)、[test_execution_model.py](../tests/test_execution_model.py) | **仓库内已处理** |

## 规则、模型与 API 专项

| 原报告条目 | 处理结果 | 证据 |
| --- | --- | --- |
| 周线门槛研究/生产不一致 | 周线函数统一；shadow 模式只记录不改动作；OOS policy manifest 与 runtime 同源。 | [technical.py](../utils/technical.py)、[policy_engine.py](../utils/policy_engine.py)、[test_weekly_four_ma.py](../tests/test_weekly_four_ma.py)、[test_policy_engine.py](../tests/test_policy_engine.py) |
| 最后验证折阈值用于全量模型 | 最后 3 个月独立 purge 校准；折叠阈值仅作为诊断，中位数报告与最终发布阈值分开。 | [hierarchical_walk_forward.py](../tools/hierarchical_walk_forward.py)、[model-governance.md](model-governance.md) |
| 优化失败退化成零系数 | 记录收敛、迭代、梯度、缺失率和系数范数；独立校准报告 Brier/ECE/校准曲线，并用 PSI+缺失桶和扩展时间窗系数稳定性作发布门禁；失败/单一类别不可发布。 | [probability_model.py](../utils/probability_model.py)、[hierarchical_walk_forward.py](../tools/hierarchical_walk_forward.py)、[test_probability_model.py](../tests/test_probability_model.py)、[test_hierarchical_walk_forward.py](../tests/test_hierarchical_walk_forward.py) |
| bootstrap 精度不足 | 固定 10,000 次；同时报告日期簇、股票簇和日期×股票双向簇、Monte Carlo 误差与预注册比较。 | [hierarchical_walk_forward.py](../tools/hierarchical_walk_forward.py)、[test_hierarchical_walk_forward.py](../tests/test_hierarchical_walk_forward.py) |
| “市场模型”语义被夸大 | model card 明确它是 B1 信号日候选质量门，不是通用市场预测。 | [hierarchical_walk_forward.py](../tools/hierarchical_walk_forward.py)、[model-governance.md](model-governance.md) |
| 涨跌停固定 10% | 支持 ST 5%、创业板/科创板 20%、北交所 30%、历史制度和上市初期方向规则；证券状态无法证明时拒绝成交。 | [execution_model.py](../utils/execution_model.py)、[test_execution_model.py](../tests/test_execution_model.py)、[test_paper_trading.py](../tests/test_paper_trading.py) |
| GET 有写副作用 | GET 只读已经发布的账本和 worker 缓存，不扫描、不训练、不调 LLM、不写 cache/ledger；受保护 GET 只做 token 校验，不写 rate-limit、nonce 或审计表。 | [web_server.py](../web_server.py)、[api_security.py](../utils/api_security.py)、[test_get_read_only.py](../tests/test_get_read_only.py)、[test_api_security.py](../tests/test_api_security.py) |
| 综合排名混合日期 | 当前结果必须同时匹配 expected date、snapshot、strategy/data version 和 decision run；旧 performance 不再混入。 | [quant_pick_api.py](../views/quant_pick_api.py)、[performance_api.py](../views/performance_api.py)、[test_quant_comment_api.py](../tests/test_quant_comment_api.py) |
| 健康检查过重 | `/healthz` 常数级；`/readyz` 才检查 freshness/leader；`/api/stats` 只读摘要，不遍历全市场。 | [web_server.py](../web_server.py)、[architecture.md](architecture.md) |
| 异步任务只在内存 | 任务、每次 attempt、租约、退避重试、调度 leader、幂等、限流、nonce、审计和告警全部持久化；队列有硬容量上限，queued 可安全取消，SQLite 锁显式重试，不回退内存。 | [operations_store.py](../utils/operations_store.py)、[operations_api.py](../views/operations_api.py)、[worker.py](../worker.py)、[test_operations_store.py](../tests/test_operations_store.py) |

## 架构、数据库和交付门禁

- Web、worker、一次性 migration 已分离。普通业务连接只校验 schema，不隐式建表；决策侧 schema v6、操作侧 schema v7 还会校验不可变 trigger；见 [runtime_schema.py](../utils/runtime_schema.py) 和 [test_runtime_schema.py](../tests/test_runtime_schema.py)。
- 决策结果不再 `UPSERT` 覆盖；按候选股保留序号化观测，用“快照 ID + 业务内容”的 SHA-256 幂等去重，读取时校验哈希，数据库 trigger 拒绝更新和删除；旧的无快照结果保留为 `legacy-unverified` 但不进入 canonical 统计；见 [decision_ledger.py](../utils/decision_ledger.py) 和 [test_decision_ledger.py](../tests/test_decision_ledger.py)。
- 生产 Web 单进程多线程运行，对市场数据 volume 物理只读；行情/决策只有一个业务 writer，operations DB 的 Web/worker 短事务由 SQLite 串行化，两个账本都放在独立 state volume；见 [docker-compose.yml](../docker-compose.yml)。
- SQLite 在线备份包含完整性检查、文件大小和 SHA-256 manifest；正式迁移前还会在一次性数据库副本上执行完整 migration/predeploy；恢复是人工受控动作；见 [backup_databases.py](../tools/backup_databases.py)、[migration_dry_run.py](../tools/migration_dry_run.py)、[test_database_backup.py](../tests/test_database_backup.py) 和 [test_migration_dry_run.py](../tests/test_migration_dry_run.py)。
- 后端门禁包含 lint、format、mypy、全量测试和覆盖率；前端包含 lint、测试、构建和 npm audit；安全门包含 pip-audit、Bandit、Hadolint 和 Trivy；见 [ci.yml](../.github/workflows/ci.yml)。
- 扫描遇到任一损坏行情文件即整体失败，不再以“少量错误容忍”发布部分结果；见 [test_scan_fail_closed.py](../tests/test_scan_fail_closed.py)。
- 运行告警以不可变事件写入操作账本，viewer 可通过只读 `/api/alerts` 消费，`readyz` 暴露 24 小时计数；外部通知送达和响应仍需目标环境验收；见 [operations_api.py](../views/operations_api.py) 和 [operator-runbook.md](operator-runbook.md)。

## 仍然阻止上线的外部条件

以下事项无法由本地改代码代替。在全部完成并留下可核对证据前，对外推荐、真实交易和无人值守模拟盘仍是 No-Go：

1. 真实性存疑的旧 `data/`、训练集、模型和回测结果已隔离；用可信来源全量重建并完成人工抽样对账。
2. GitHub 的服务器连接配置和目标主机权限可用；完整 SHA→digest 发布及回滚演练成功。
3. 在目标磁盘执行过备份恢复、上游全失败、进程中断、磁盘满、SQLite locked 和双 worker 竞争演练；监控确实告警。
4. 至少 6 个真实独立前向月、统计功效、完整 policy 验证和双人审批已经落账；否则模型只能 shadow/baseline-only。

## 当前工作树最后验证

以下结果均在 2026-07-23 对当前未提交修复工作树重新执行，不是较早提交或局部测试结果。

| 门禁 | 当前结果 |
| --- | --- |
| 后端全量测试与覆盖率 | 全新 Python 3.11.15 + 两份 hash 锁定依赖：**251 passed + 9 subtests passed**，13 个指定核心模块覆盖率 **86.71%**（门槛 75%） |
| Ruff / mypy / Bandit / pip-audit | Ruff check/format 通过；mypy 11 个契约模块通过；Bandit 高危扫描通过；Python 锁定依赖无已知漏洞。 |
| 前端 lint / test / build / npm audit | ESLint 通过；**2 passed**；TypeScript + Vite 生产构建通过；`npm audit` **0 vulnerabilities**（ECharts chunk 警告已列入已知限制） |
| Compose/workflow 静态校验 | 2 份 Compose + 2 份 GitHub workflow 均可解析；19 个 action 引用均锁定 40 位 SHA；Python/Node 基础镜像 digest 与 registry 核对一致 |
| 首次部署状态冒烟 | 全新临时状态目录中，空备份 → 决策侧 schema v6 / 操作侧 schema v7 显式迁移 → 只读 predeploy 通过；`/healthz` 与 `/api/version` 均返回 200，告警表及不可变 trigger 复验通过 |
| Docker 镜像 smoke / 发布回滚 | 本机无 Docker daemon，必须由 CI/目标主机验收 |
