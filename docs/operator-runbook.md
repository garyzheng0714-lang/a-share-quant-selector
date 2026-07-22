# 运维手册

更新时间：2026-07-23。

## 运行前提

- Python 3.11.15、Node.js 22.17.1，或使用仓库中已按 digest 固定的 Docker 镜像。
- `data/` 所在磁盘有足够空间，且只有一个生产 worker 写入。
- viewer、publisher、admin 三个 token 长度至少 32 字符且彼此不同。生产使用 root 只读 secret file，文件权限建议 `0600`；不要在文档、日志、工单或命令行中写真值。
- 数据已从可信源重建。

## 本地安装和启动

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements.lock

python main.py migrate
python main.py web --host 127.0.0.1 --port 5000
```

另开一个终端：

```bash
source .venv/bin/activate
python main.py worker
```

数据库未迁移、schema 版本过旧、表/列缺失、完整性失败或默认模拟账户不完整时，Web 和 worker 都会拒绝启动。不要绕过这个检查。

## 本地验证

```bash
ruff check main.py worker.py web_server.py utils views strategy tools tests
ruff format --check main.py worker.py web_server.py utils views strategy tools tests
mypy --follow-imports=skip utils/api_security.py utils/artifact_integrity.py \
  utils/data_contracts.py \
  utils/decision_ledger.py utils/market_snapshot.py utils/operations_store.py \
  utils/runtime_schema.py utils/task_submission.py utils/probability_model.py \
  tools/hierarchical_walk_forward.py tools/migration_dry_run.py
pytest -q --cov=utils.api_security --cov=utils.artifact_integrity \
  --cov=utils.csv_manager \
  --cov=utils.data_contracts --cov=utils.data_freshness \
  --cov=utils.decision_ledger --cov=utils.execution_model \
  --cov=utils.market_snapshot --cov=utils.operations_store \
  --cov=utils.paper_trading --cov=utils.probability_model \
  --cov=utils.reference_snapshots --cov=utils.runtime_schema \
  --cov-report=term-missing --cov-fail-under=75
bandit -q -r main.py web_server.py worker.py utils views tools -lll
pip-audit --disable-pip --require-hashes -r requirements.lock
pip-audit --disable-pip --require-hashes -r requirements-dev.lock

cd frontend
npm ci
npm run lint
npm run test
npm run build
npm audit --audit-level=high
```

CI 使用带 hash 的 Python 锁文件，生产与开发/CI 两份 lock 都执行 pip-audit，并额外执行 Hadolint 和 Trivy。

## 运行状态

- `GET /healthz`：只表示 Web 进程能回应，不读全市场文件，不访问外部网络。
- `GET /readyz`：同时要求市场快照 freshness 和 scheduler leader 正常。
- `GET /api/version`：核对完整 Git SHA、strategy version 和 snapshot ID。
- `GET /api/stats`：常数级返回快照、决策和 scheduler 摘要。
- `GET /api/decision/system-status`：查看 freshness、当前 policy、模拟盘、AI 和演进状态。
- `GET /api/scheduler/status` 和 `GET /api/tasks/<task_id>`：需要 viewer token。
- `GET /api/alerts`：需要 viewer token，返回最近的不可变运行告警事件和 24 小时 warning/critical 汇总；可用 `limit=1..200`、`severity=warning|critical` 过滤。

`healthz` 成功不代表数据可用；对外展示决策前必须要求 `readyz.ready=true`。
`readyz` 同时带出最近 24 小时告警计数，但历史告警本身不自动改变 readiness；生产监控必须按 `alert_id` 去重消费 `/api/alerts`，critical 立即通知值班人员，并保留通知送达与处置工单。认证 GET 不写限流、nonce 或审计表，因此监控轮询不会改变运行状态。

## 任务操作

本地 CLI 只会入队，不会在当前进程扫描全市场：

```bash
python main.py enqueue-ingestion --trade-date YYYY-MM-DD
python main.py enqueue-close --trade-date YYYY-MM-DD
python main.py enqueue-rebuild --years 6
```

通过 API 提交时，必须使用适当角色的 Bearer Token、唯一 `Idempotency-Key`、可追溯 `X-Change-Reason` 和 5 分钟内有效的 HMAC 请求签名。不得通过重复换 key 的方式绕过任务幂等。请使用仓库内客户端，避免把 token 真值写进 shell 历史：

```bash
python tools/signed_request.py \
  --url http://127.0.0.1:18321/api/data/update \
  --token-file /secure/path/admin-token \
  --idempotency-key daily-update-YYYY-MM-DD \
  --reason "operator approved daily ingestion"
```

收盘 DAG 的任何上游阶段失败都会阻断下游决策。不允许手工修改任务状态、决策账本或 NAV 来伪造恢复。

调度 leader 每 30 秒对账任务，不依赖某个 cron 瞬间：收盘任务在 16:00 后或翌日可按原交易日补齐；盘前复核只能在当日 08:45–09:25 执行。请求的交易日与当前/快照日期不同时会失败关闭。

任务详情中的 `attempts` 是不可用新任务覆盖的尝试历史。可重试失败指数退避（上限 15 分钟）；非可重试错误或达到 `max_attempts` 后终止。租约过期会把未完成 attempt 记为 `lease_expired` 后才由新 worker 接管。
每次可重试失败或租约接管会在 `alert_events` 追加 warning；不可重试失败、重试耗尽或最终租约耗尽会追加 critical。任务状态与告警在同一事务提交，告警表由 trigger 禁止更新和删除。

queued/running 任务总量默认上限为 1000，可用 `QUANT_MAX_PENDING_TASKS` 在 1–100000 内调整。重复提交同一业务幂等键仍返回原任务，不占新名额；新任务超过上限会返回 `task_queue_capacity_exceeded`、追加 critical 告警，但不会让 worker 退出。

只取消尚未开始的任务：

```bash
python tools/signed_request.py \
  --url http://127.0.0.1:18321/api/tasks/TASK_ID/cancel \
  --token-file /secure/path/admin-token \
  --idempotency-key cancel-TASK_ID \
  --reason "operator cancelled obsolete task"
```

running/succeeded/failed/cancelled 任务会返回 409，不会假装已中止。确需停止正在运行的长任务时，应先隔离写入口并停止专用 worker，保留 staging、任务、租约和日志证据；确认副作用边界后，再按事故流程处置，不能直接改任务状态。

`enqueue-ingestion` 只允许从已验证的可信快照继续；如果没有可信基础，必须使用 `enqueue-rebuild`。全量重建从空 staging 开始，不会复制旧 CSV。两种流程都要求同日完整证券状态，快照 payload 出现任何 manifest 外文件都不会发布。

## 备份、迁移和恢复

发布前检查：

```bash
python tools/backup_databases.py
GIT_COMMIT_SHA="$(git rev-parse HEAD)" python tools/migration_dry_run.py
python tools/migrate_databases.py
python tools/predeploy_check.py
```

`backup_databases.py` 使用 SQLite online backup API，对每个备份执行完整性检查，并在本地 `data/backups/<UTC timestamp>/manifest.json` 或生产 `/app/state/backups/<UTC timestamp>/manifest.json` 记录文件大小和 SHA-256。`migration_dry_run.py` 再用 online backup 把当前两个账本复制到一次性目录，在副本上完整执行 migration 和 predeploy；它不会修改线上源库，首次部署没有旧 DB 时也会演练从空状态建库。只有副本演练通过后才可迁移正式库，最后再做只读检查。生产发布会先停止旧 web/worker，确保最终备份、演练和正式迁移期间没有旧进程写入；切换前失败会恢复旧发布文件并重启旧服务。备份目录不得和主数据库使用同一个无冗余磁盘作为唯一副本。

迁移会保留旧模拟盘事件，但不会为它们伪造 `snapshot_id` 或执行版本。只读预检发现这类旧 fill/NAV 时会以 `runtime_unverified_legacy_paper_evidence` 阻止启动；应将旧账本完整归档，经批准后从新账户开始可验证运行，不得手工补写快照来绕过门禁。

数据库恢复不自动执行，因为覆盖数据可能丢失备份后的新事件。需要恢复时：

1. 停止 worker 和所有写请求，记录当前 SHA、源镜像 digest、运行镜像 ID、snapshot ID 和数据库文件哈希。
2. 复制当前 DB/WAL/SHM 到独立取证目录，不在原文件上尝试修复。
3. 在临时目录恢复备份，验证 manifest hash、`PRAGMA integrity_check`、外键、schema 和关键账本余额。
4. 明确评估会丢失的新写入，经变更批准后再替换生产 DB。
5. 重新执行 `python tools/migrate_databases.py` 和全部 ready/对账检查。

## Docker Compose

生产 `.release.env` 由发布 workflow 生成，必须同时记录唯一本地镜像标识、内容寻址镜像 ID、经签名扫描的源 digest、40 位 SHA 和三个 secret file 绝对路径。Compose 禁止自行拉取镜像；镜像必须先由 workflow 传入并验证 ID，然后执行：

```bash
docker image inspect "$(sed -n 's/^QUANT_IMAGE=//p' .release.env)"
docker compose --env-file .release.env up -d --remove-orphans
docker compose --env-file .release.env ps
```

Compose 会先运行一次性 `migrate`，只有成功后才启动 web/worker。Web 只读挂载市场数据 volume，对独立 state volume 保留审计、限流和任务写权，并只绑定 `127.0.0.1:18321`；若需远程访问，必须通过受控反向代理/VPN，不得改为公网 `0.0.0.0`。`canary` profile 不常驻、不发布端口，对 data/state 两个 volume 都只读，只供发布流程在正式切换前验证候选镜像 ID、SHA 和数据状态。

## 发布和回滚

`.github/workflows/release.yml` 只接受人工输入的完整 SHA，由仓库所有者手动触发。流程会：

1. 再次验证后端/前端门禁；
2. 只构建一次，推送 SHA tag，生成 provenance/SBOM，按 digest 签名和扫描；
3. GitHub runner 按源 digest 拉取镜像并复验构建 SHA，以压缩流通过 SSH 传入目标主机，只有服务器镜像 ID 与 runner 完全相同才继续；
4. 停止旧 web/worker，在线备份静止账本，在临时数据库副本上完成迁移演练，再使用新镜像显式迁移正式库并执行只读预检；
5. 启动不发布端口、只读挂载 data/state 的候选 canary，核对镜像 ID、`/healthz`、`/api/version`、snapshot 和 `/api/stats` 后删除 canary；
6. 切换 web/worker，并验证线上镜像 ID、预期 SHA、snapshot、readiness、关键只读查询和 scheduler leader；
7. 所有一次性备份/迁移/预检容器都禁用交互式标准输入；只有完成正式容器镜像 ID、SHA、snapshot、readiness 和 scheduler leader 复验后才写入发布回执，GitHub 端会再次读取回执，缺失即判定发布失败；
8. canary 或切换前检查失败时清理候选容器、恢复旧发布文件并重启旧服务；切换或线上健康检查失败时回退上一个 Compose/镜像。

当前 migration 只允许向前兼容变更。回滚应用默认保留数据 volume；只有数据库已损坏或经评审确认 schema 不兼容时，才进入人工恢复流程。

policy 回退不是“改一个 active 字段”：只能回到当前 policy 激活时已预批的上一 policy，必须提供不同的 operator/reviewer、工单、变更原因和 `expected_current_policy`。回退会新增不可变发布/审计事件，不删除或改写旧记录。

## 故障处置

- stale/future/mixed snapshot：停止展示当前决策，修复数据源和快照链，不手工改 manifest。
- scheduler 无 leader 或多 leader：停止多余 worker，保留 `scheduler_leases`、任务和日志证据，核对幂等键后再恢复。
- 模型异常：拒绝/回退 active policy，保留注册、验证和发布事件，不删账本。
- 模拟盘对账失败：停止新委托，备份 DB，独立重建现金、持仓和净值；不直接改 NAV 或差额。
- 数据库损坏/锁死/磁盘满：停止 writer，保全 DB/WAL/SHM 和磁盘证据，在副本上分析。
- `/api/alerts` 出现 critical：先按 `subject_id` 查看对应任务和 attempts，确认是否仍在重试；不得删除或修改告警来制造恢复，恢复后在外部工单记录处置结果。
