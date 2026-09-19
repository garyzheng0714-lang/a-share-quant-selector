# A 股量化系统：Agent 入口

更新时间：2026-08-14。

## 项目定位

这是个人 A 股研究系统，不是自动交易或收益承诺产品。任何页面、模型、回测和 LLM 文案都必须保留「研究工具，不构成投资建议」的边界。

项目目录为 `/Users/simba/Agentic-Engineering/share`，项目仍活跃。分支、工作树和线上版本都是动态状态，必须现场核对；不得把本地 HEAD 自动等同于线上版本。

## 开始前

```bash
git status --short --branch
```

现有用户工作必须保留：

- 不要 reset、checkout、清理或覆盖未提交文件；
- 不读取、打印或复制 `config/config.yaml` 的值，也不覆盖 `data/`；
- 未经明确授权不执行部署、真实通知、真实 LLM 调用或生产数据更新。

## 事实源

优先级：

1. 当前源码、测试、配置模板和 GitHub workflow；
2. 本文件；
3. [README](README.md) 与 [docs/INDEX](docs/INDEX.md) 中的权威文档；
4. Git 历史用于追溯。

不再使用 WORKLOG、日期化计划、Oracle prompt/review 或 Kiro 截图作为长期记忆。研究结论进入 [模型治理](docs/model-governance.md)，运行边界进入 [已知限制](docs/known-limitations.md)。

## 当前架构

- Python 3.11+、Flask、APScheduler、AkShare、pandas/NumPy/SciPy。
- SQLite 主库在 `data/views.db`，以 WAL 模式保存视图、结果、战绩、决策账本和模型登记。
- React 19、TypeScript、Vite、Tailwind、ECharts、SWR、Zustand。
- Docker Compose 暴露宿主机 18321；GitHub Actions 仅从 `main` 自动部署。

决策链路：

1. 检查完整交易日行情与参考快照；
2. Super B1 生成可复现规则 baseline；
3. T 日收盘生成版本化候选；
4. 只有通过 point-in-time + purged walk-forward 证据的模型才能 active；
5. T+1 08:45 用截止时点公告做风险复核；
6. 保存 `strategy_version`、`feature_version`、`model_version`、`data_version` 与 source refs；
7. LLM 只解释或做引用式事件标签，不选票、不排序、不改写动作。

## 不可破坏的研究边界

- stale market data 必须 fail closed。
- 历史行情抓取器当前违反这一目标：双源失败后可能生成随机数据并写入正式 CSV。修复并从可信来源重建前，不得把 `init`/回补产物用于发布证据。
- `python3 main.py web` 会自动启动 scheduler 和六年股票池回补，当前没有禁用 bootstrap 的 CLI 开关；修复前不能把它当作可信数据目录的只读启动入口。
- `strict_unvalidated_gate` 默认开启；market 模型未验证时只观察。
- 周线四均线当前默认 `shadow`，不能在没有新证据时改成 active。
- 版本化决策在没有已验证质量模型时，不伪造 top-1。
- 预备队/tomorrow watch 已在样本外证伪，只能是观察提示。
- `/api/quant-pick` 的板块综合热度顺序只是旧兼容展示，不是 active policy、买卖动作或已验证 alpha。
- `/api/quant-pick` 当前还把所有云阶命中放进旧字段 `today_buy`，而旧客户端会显示为“今日推荐”；字段迁移和 stale fail-closed 恢复前不可发布。
- 不把市场温度计、板块展示分、LLM 文案或未完成治理复核的研究代理量冒充生产模型。
- 回测必须标明 as-of、T+1 开盘执行、费用、滑点、涨跌停/停牌与历史证券宇宙假设。

## 常用命令

```bash
python3 -m pytest -q

cd frontend
npm run lint
npm run build

cd ..
git diff --check
```

验证结果只以本次命令的真实输出为准。项目 `.venv` 可能没有 pytest；先检查解释器，不要为了文档任务改依赖环境。

CLI 当前仅支持 `init`、`update`、`run`、`track`、`backtest`、`web`。不要恢复旧文档里的 `select` 或 `schedule`。

## 安全

- 不读取或输出 `config/config.yaml` 的值。
- 该文件虽然在 `.gitignore` 中，但仍被 Git 跟踪；轮换与历史清理需要单独审批。
- Dockerfile 当前 `COPY . .` 且没有 `.dockerignore`；补齐严格构建白名单并完成凭证处置前，不得从工作区构建或分发镜像。
- Flask 没有应用层鉴权或 CSRF；显式写接口以及会按需计算并落账/落缓存的 GET 接口只能放在受控网络边界内。
- `deploy.sh` 会 SSH、`rsync --delete`、重建容器；未经明确授权不得执行。
- 不在测试中发送钉钉、调用真实 LLM、更新生产行情或触发生产部署。

## 文档同步

- 改决策层、模型晋升规则或 as-of 口径：同步 `docs/model-governance.md`。
- 改 API、数据流或部署：同步 `docs/architecture.md` 与 runbook。
- 改当前视觉 token 或响应式结构：同步 `DESIGN.md`。
- 稳定研究结论进入权威文档后，删除临时计划和审计材料。

本文件与 [docs/INDEX.md](docs/INDEX.md) 是项目长期记忆入口。

先读具体项目的指令与 README，事实以当前实现为准。
不重复造轮子，优先复用现有代码和成熟工具。
只做必要改动，保护已有工作与敏感数据。
授权范围内直接完成，超出范围再确认。
项目知识维护单一真源，临时进度不写进常驻指令。
在真实入口验证结果，未完成、未验证或受阻如实说明。
