# 已知限制

更新时间：2026-08-14。

## 发布状态

- Git 分支、工作区或历史 WORKLOG 都不能证明线上版本；必须核对部署 workflow、线上 Git SHA、健康检查与页面状态。

## 安全

- `config/config.yaml` 虽被 `.gitignore` 排除，但仍是 tracked 文件。2026-07-17 的只报布尔结果扫描确认：当前文件与 HEAD 中都存在非占位的 secret-like 值。必须轮换相关凭证、停止跟踪并清理/评估 Git 历史；在轮换完成前按已泄露处理。本文件不记录任何值。
- Flask 默认监听 `0.0.0.0`，Compose 映射 18321；应用没有登录、权限、CSRF 或请求签名。
- 数据更新、决策、调度器和视图写接口都可能被网络调用，必须依赖防火墙、私网或认证反向代理。
- `GET /api/decision/latest`、`GET /api/quant-pick` 以及强制扫描/板块 read-through 接口可能生成账本或缓存；不能仅凭 HTTP GET 就假定无副作用。
- `GET /api/super-b1` 在缓存缺失或过期时会全量扫描并写 JSON 缓存，也不是纯查询。
- `deploy.sh` 有远端 SSH 与 `rsync --delete`，不能作为无审核的一键操作。
- Dockerfile 使用 `COPY . .`，仓库却没有 `.dockerignore`；本地配置、行情、虚拟环境、依赖目录和 Git 元数据可能进入构建上下文或镜像。补齐严格白名单并处置已跟踪凭证前，不得分发当前方式构建的镜像。

## 模型与数据

- Super B1 是规则 baseline，不是收益保证。
- 周线闸门默认 shadow；市场/板块/风险/质量模型只有满足严格 source refs 才能 active。
- 历史证券宇宙、行业成分、公告正文/精确发布时间、交易费用和可成交性数据仍不完整。
- 旧回测中的胜率/超额受样本、幸存者偏差、多重检验和交易成本影响。
- 板块当日强弱的分段研究使用当前行业映射和简化成交口径；运行时综合热度分又不是同一特征。`/api/quant-pick` 的排序只能视为展示顺序，不能当作已验证 top-1 或账本 `buy`。
- tomorrow watch 已被样本外证伪，只能作为观察提示。
- 外部行情、东财公告、交易日历与 LLM 都可能不可用；系统必须降级而不是猜测。
- 这一目标目前被历史行情抓取器破坏：两个真实来源都失败时，它会生成随机 OHLCV，初始化/回补还可能把结果写入正式 CSV。现有文件没有可靠来源标记，freshness 也不能识别这种污染；代码修复、数据隔离并从可信来源重建前，相关研究与决策不可发布。
- `python3 main.py web` 会无条件启动 scheduler 和六年股票池回补，且没有禁用 bootstrap 的 CLI 开关；因此当前也不能把 `web` 当作可信数据目录的只读启动方式。
- `/api/quant-pick` 当前把全部云阶命中写进旧字段 `today_buy`，陈旧行情下仍可能 `available=true`；旧客户端会把它展示为“今日推荐”。恢复旧语义和 stale fail-closed、或迁移到新字段前不可发布。
- 完整 policy 仍需要至少 21 个真实有信号月份、统计功效和前向观察；当前数据不足时只能登记 shadow，不能宣称已自我提升。
- 模拟账户从新账本启用后才开始积累成交与净值；早期样本很少，不能用短期盈亏评估算法有效性。
- 当前模拟成交依赖日线可执行性近似，无法还原开盘集合竞价队列、盘中临停或逐笔冲击成本。

## 工程

- `requirements.txt` 没有声明 pytest；按运行时依赖安装的干净环境不能直接执行文档中的 Python 测试。
- 前端没有独立自动化测试脚本；当前质量门禁是 ESLint 与 TypeScript/Vite build。
- 2026-08-05 的构建记录显示 ECharts 生产 chunk 约 574 kB，超过 Vite 500 kB 警告阈值；当前值必须以重新构建结果为准。
- `views/views.db` 不应存在；主库实际在 `data/views.db`，前者已由 `.gitignore` 排除。
- `strategy/pattern_library.py`、`utils/kline_chart_fast.py` 与旧图表测试仍含 `/root/quant-csv` 历史绝对路径；当前主部署目录是 `/opt/a-share-quant`。
- `strategy/pattern_config.py` 当前重复定义 `case_011`；相同 ID 会在案例字典中覆盖，虽未增加有效案例数，但破坏配置的唯一性与可复现性。
- Docker 镜像安装了 gunicorn，但实际 CMD 使用 Flask 内置服务器；当前不是经过核准的生产 WSGI 运行方式。
- `/today` 已重定向到 `/stocks`，但旧 `today.tsx` 与 `TodayRecommendCard` 仍不可达；`main.py` 的 `run_schedule()` 也没有对应 CLI 命令。
- `config/strategy_params.yaml` 由进程内单例首次加载；修改文件后必须启动新进程才会稳定生效。
