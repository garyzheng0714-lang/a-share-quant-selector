# 运维手册

更新时间：2026-08-14。

## 本地运行

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config/config.yaml.template config/config.yaml
```

当前没有只启动只读后端的受支持命令：`python3 main.py web --port 18321` 会同时启动 scheduler 和六年股票池回补。回补可能在真实行情双源失败后写入随机 OHLCV，所以修复 fallback 并提供禁用 bootstrap 的开关前，不得在可信或发布数据目录执行该命令。

已有独立、受控的测试 API 时，可只启动前端：

```bash
cd frontend
npm ci
npm run dev
```

开发界面位于 `http://127.0.0.1:3000`，Vite 默认把 `/api` 代理到受控后端 `127.0.0.1:18321`。真实配置不得提交、打印或复制进报告。若只验证 UI，可设置 `VITE_API_BASE` 指向受控测试 API。

关键环境变量：

| 变量 | 默认值 / 合法值 | 说明 |
| --- | --- | --- |
| `DECISION_HIERARCHY_ENABLED` | 默认 `true`；`0/false/no/off` 关闭 | 是否启用版本化分层决策 |
| `DECISION_STRICT_GATE` | 默认 `true` | 未验证 market 模型时是否强制只观察 |
| `DECISION_PREOPEN_EVENTS` | 默认 `true` | 是否执行盘前事件复核 |
| `DECISION_WEEKLY_GATE_MODE` | `off/shadow/active`，默认 `shadow`；非法值回落为 `shadow` | 周线闸门模式 |
| `ARK_API_KEY` / `ANTHROPIC_API_KEY` | 无默认值 | 对应配置文件值优先于环境变量；缺失时 LLM 解释停用 |
| `VITE_API_BASE` | 默认同源 | 前端 API 根路径；Vite 开发代理目标是 18321 |

## 验证

`pytest` 不在 `requirements.txt` 中，新环境需先单独安装：

```bash
python3 -m pip install pytest
python3 -m pytest -q

cd frontend
npm run lint
npm run build

cd ..
git diff --check
```

手机视口工具：

```bash
node frontend/scripts/mobile-shot.mjs \
  http://127.0.0.1:3000 /tmp/quant-mobile \
  /sectors,/stocks,/review
```

该脚本依赖本机 Google Chrome 与 `puppeteer-core`，输出目录必须在仓库外。

## 运行检查

- `GET /api/stats`：进程、股票数、视图和 scheduler。
- `GET /api/data/coverage`：行情 universe 覆盖。
- `GET /api/super-b1`：缓存新鲜时读取 JSON；缓存缺失或过期时会全量扫描并写缓存，不是纯查询。
- `GET /api/decision/latest`：最新版本化决策；行情新鲜但缺少当前版本 run 时会现场生成并追加账本，不是纯查询。
- `GET /api/decision/system-status`：行情时效、决策候选数、active policy、模拟盘、AI 和每日演进的统一状态。
- `GET /api/quant-pick`：沿用旧响应形状，但 `today_buy` 现在承载全部云阶命中，不等于账本 `buy`；旧客户端仍会显示为“今日推荐”，且特定状态下接口也可能生成收盘决策。该组合当前不可发布。
- 决策不可用时先检查 `freshness`、数据日期、baseline、active model 与 reason codes。
- LLM 未配置只影响解释；不应阻断规则账本。
- `daily_auto_promotion` 必须始终为 `false`；如果出现自动晋级迹象，立即停止 scheduler 并保全账本。

显式写接口、上述 read-through GET、`force=1` 扫描、Super B1 和板块缓存重算都可能改变数据或运行状态。调用前需要备份 `data/views.db` 并确认网络边界。

SQLite 使用 WAL。备份前先停止 scheduler 和其他写入方，完成 checkpoint，再用 SQLite 备份命令写到仓库外；写入期间只复制 `data/views.db` 可能漏掉 `-wal` 中的数据：

```bash
sqlite3 data/views.db "PRAGMA wal_checkpoint(FULL);"
sqlite3 data/views.db ".backup '/absolute/backup/views.db'"
```

## Docker

当前 Dockerfile 使用 `COPY . .`，仓库却没有 `.dockerignore`。在加入严格构建白名单并完成已跟踪凭证的处置前，以下构建步骤属于发布阻断项：不得从含 `config/config.yaml`、`data/`、`.venv/`、`frontend/node_modules/` 或 `.git/` 的工作区构建或分发镜像。

```bash
docker compose up -d --build
docker compose logs --tail 100
curl -fsS http://127.0.0.1:18321/api/stats
```

`quant-data` volume 保存行情、快照和 SQLite。重建容器前确认 volume 存在；不要用空本地目录覆盖它。

## 自动部署

`.github/workflows/deploy.yml` 会在 `main` push 后自动运行，也支持 `workflow_dispatch` 手工触发；部署脚本始终取 `origin/main`。它会：

1. 在远端 `/opt/a-share-quant` fetch/reset `origin/main`；
2. 构建并重启 Compose；
3. 等待 `/api/stats`；
4. 更新行情并要求 freshness 通过；
5. 生成收盘决策与参考数据；
6. API 或数据刷新失败时退出并打印有限日志。

候选分支必须先合并到 `main` 才可能进入这条部署链路。不能用本地 HEAD 推断线上版本。

常驻服务由周一至周五 cron 触发，不是交易所日历本身；触发后仍须由 freshness 和交易日门禁决定是否继续。任务顺序是：

1. 16:00 更新行情与 point-in-time 快照；
2. 处理前一盘前登记的模拟委托，写入成交/拒绝/延期，计算净值并对账；
3. 刷新规则候选、战绩、板块与因子；
4. 回填演进数据并只登记 shadow 完整 policy；
5. 生成收盘决策并记录 AI 是否调用及原因；
6. 下一交易日 08:45 复核公告风险，并登记下一开盘模拟委托。

部署后首次启动只会建立模拟账户；首个净值日和首笔成交要等日任务按交易日运行。不得手工补造历史成交。

`deploy.sh` 是独立的手工部署入口，包含 `rsync --delete` 与远端 Docker 操作。执行前必须明确核对目标主机、目录、config 备份、volume 与回滚点。

## 回滚

1. 记录当前 Git SHA、容器镜像、行情日期与 `data/views.db` 备份。
2. 将 `main` 恢复到已知良好提交并重新走 workflow，或在远端明确 checkout 该提交后重建。
3. 不回滚/覆盖数据 volume，除非数据库格式不兼容且已有验证过的备份。
4. 决策异常时可用环境变量关闭 hierarchy，或把各层保持 shadow/off；不要删除决策账本来伪造恢复。
5. 外部行情或公告来源失败时停止使用过期推荐；历史行情抓取器当前还可能写入随机模拟数据，不能把这条路径称为安全降级。

## 事故优先级

- 凭证泄露：先轮换，再清理 Git 历史和部署配置。
- 未授权访问：先用防火墙/反向代理封端口，再查写接口与 scheduler 日志。
- stale data：停止当前推荐，修复更新链路与交易日历。
- 行情来源失败或日志出现“使用模拟数据”：立即停止更新、scheduler 和决策生成，隔离该次运行写入的行情目录；由于当前文件没有可靠来源标记，无法精确排除污染时应把整次更新视为受影响，并从可信快照恢复或从真实来源重建。
- 模型异常：取消 active、保留 baseline/账本与 evidence，重新 walk-forward。
- 模拟盘对账失败：停止新增委托，备份 `data/views.db`，核对最后一条现金事件、持仓批次、成交与净值；不得直接改净值掩盖差异。
- 数据库损坏：停止写入，复制原文件后再做 WAL/SQLite 恢复。
