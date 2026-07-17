# 运维手册

更新时间：2026-07-17。

## 本地运行

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config/config.yaml.template config/config.yaml

python3 main.py init
python3 main.py web
```

另开终端：

```bash
cd frontend
npm ci
npm run dev
```

真实配置不得提交、打印或复制进报告。若只验证 UI，可设置 `VITE_API_BASE` 指向受控测试 API。

## 验证

```bash
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
  http://127.0.0.1:5000 /tmp/quant-mobile \
  /sectors,/stocks,/review
```

该脚本依赖本机 Google Chrome 与 `puppeteer-core`，输出目录必须在仓库外。

## 运行检查

- `GET /api/stats`：进程、股票数、视图和 scheduler。
- `GET /api/data/coverage`：行情 universe 覆盖。
- `GET /api/decision/latest`：最新版本化决策。
- `GET /api/decision/system-status`：行情时效、决策候选数、active policy、模拟盘、AI 和每日演进的统一状态。
- 决策不可用时先检查 `freshness`、数据日期、baseline、active model 与 reason codes。
- LLM 未配置只影响解释；不应阻断规则账本。
- `daily_auto_promotion` 必须始终为 `false`；如果出现自动晋级迹象，立即停止 scheduler 并保全账本。

手动写接口会改变数据或调度状态，调用前需要备份 `data/views.db` 并确认网络边界。

## Docker

```bash
docker compose up -d --build
docker compose logs --tail 100
curl -fsS http://127.0.0.1:18321/api/stats
```

`quant-data` volume 保存行情、快照和 SQLite。重建容器前确认 volume 存在；不要用空本地目录覆盖它。

## 自动部署

`.github/workflows/deploy.yml` 只响应 `main`。它会：

1. 在远端 `/opt/a-share-quant` fetch/reset `origin/main`；
2. 构建并重启 Compose；
3. 等待 `/api/stats`；
4. 更新行情并要求 freshness 通过；
5. 生成收盘决策与参考数据；
6. API 或数据刷新失败时退出并打印有限日志。

候选分支必须先合并到 `main` 才可能进入这条部署链路。不能用本地 HEAD 推断线上版本。

常驻服务的交易日任务顺序是：

1. 16:00 更新行情与 point-in-time 快照；
2. 处理前一盘前登记的模拟委托，写入成交/拒绝/延期，计算净值并对账；
3. 刷新规则候选、战绩、板块与因子；
4. 回填演进数据并只登记 shadow 完整 policy；
5. 生成收盘决策并记录 AI 是否调用及原因；
6. 下一交易日 08:45 复核公告风险，并登记下一开盘模拟委托。

部署后首次启动只会建立模拟账户；首个净值日和首笔成交要等日任务按交易日运行。不得手工补造历史成交。

`deploy.sh` 是独立的手工部署入口，包含 `rsync --delete` 与远端 Docker 操作。执行前必须明确核对目标主机、目录、config 备份、volume 与回滚点；本轮文档整理不会执行它。

## 回滚

1. 记录当前 Git SHA、容器镜像、行情日期与 `data/views.db` 备份。
2. 将 `main` 恢复到已知良好提交并重新走 workflow，或在远端明确 checkout 该提交后重建。
3. 不回滚/覆盖数据 volume，除非数据库格式不兼容且已有验证过的备份。
4. 决策异常时可用环境变量关闭 hierarchy，或把各层保持 shadow/off；不要删除决策账本来伪造恢复。
5. 外部行情或公告来源失败时降级观察，不发布过期推荐。

## 事故优先级

- 凭证泄露：先轮换，再清理 Git 历史和部署配置。
- 未授权访问：先用防火墙/反向代理封端口，再查写接口与 scheduler 日志。
- stale data：停止当前推荐，修复更新链路与交易日历。
- 模型异常：取消 active、保留 baseline/账本与 evidence，重新 walk-forward。
- 模拟盘对账失败：停止新增委托，备份 `data/views.db`，核对最后一条现金事件、持仓批次、成交与净值；不得直接改净值掩盖差异。
- 数据库损坏：停止写入，复制原文件后再做 WAL/SQLite 恢复。
