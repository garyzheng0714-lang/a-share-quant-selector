# a-share-quant-selector

![类型](https://img.shields.io/badge/%E7%B1%BB%E5%9E%8B-%E9%87%8F%E5%8C%96%E5%B7%A5%E5%85%B7-dc2626)
![技术栈](https://img.shields.io/badge/%E6%8A%80%E6%9C%AF%E6%A0%88-Python%20%2B%20Flask%20%2B%20React-2563eb)
![状态](https://img.shields.io/badge/%E7%8A%B6%E6%80%81-%E7%A0%94%E7%A9%B6%E5%B7%A5%E5%85%B7-16a34a)
![README](https://img.shields.io/badge/README-%E4%B8%AD%E6%96%87-111827)

基于 Python、AkShare 和 React 的 A 股量化选股系统，支持本地数据更新、策略筛选、图形匹配、通知和 Web 管理界面。

## 仓库定位

- 分类：量化工具 / A 股研究 / 策略筛选与可视化。
- 服务对象：需要自动更新 A 股数据、运行选股策略、查看历史结果和管理策略参数的个人研究工作流。
- 风险说明：本项目仅用于研究和自动化分析，不构成任何投资建议。

## 功能概览

- 从 AkShare 获取 A 股历史数据，并保存到本地 `data/`。
- 支持首次全量抓取和每日增量更新。
- 内置碗口反弹策略，结合趋势线、多空线、放量阳线和 KDJ 低位筛选。
- 支持 B1 图形相似度匹配，按趋势结构、量能、价格形态和 KDJ 相似度排序。
- 支持回落碗中、靠近多空线、靠近短期趋势线等结果分类。
- 可生成 K 线图和技术指标图。
- 支持钉钉群机器人通知。
- Flask API 提供排行榜、历史结果、股票详情、多视图参数管理和异步任务。
- React 19 + ECharts 前端用于 Web 管理。
- 提供 Dockerfile、Docker Compose 和 GitHub Actions workflow。

## 技术栈

- 后端：Python 3.11+、Flask、gunicorn、APScheduler。
- 数据与计算：AkShare、pandas、NumPy、SciPy、fastdtw、orjson。
- 图表与图片：matplotlib、Pillow。
- 前端：React 19、TypeScript、Vite、Tailwind CSS、ECharts、SWR、Zustand、React Router。
- 部署：Docker multi-stage build、Docker Compose。

## 快速开始

安装 Python 依赖：

```bash
pip3 install -r requirements.txt
```

创建运行配置：

```bash
cp config/config.yaml.template config/config.yaml
```

根据需要编辑 `config/config.yaml`，例如钉钉 webhook、数据目录和调度时间。

初始化本地股票数据：

```bash
python3 main.py init
```

执行更新、选股和通知完整流程：

```bash
python3 main.py run
```

启动 Web 服务：

```bash
python3 main.py web
```

Flask 服务默认监听 `5000`。

## 常用命令

| 命令 | 说明 |
| --- | --- |
| `python3 main.py init` | 首次全量抓取历史数据 |
| `python3 main.py update` | 每日增量更新 |
| `python3 main.py select` | 仅执行选股 |
| `python3 main.py run` | 更新数据、选股并发送通知 |
| `python3 main.py run --max-stocks 500` | 快速测试前 500 只股票 |
| `python3 main.py run --category bowl_center` | 按分类筛选 |
| `python3 main.py run --b1-match` | 启用 B1 图形匹配 |
| `python3 main.py schedule` | 启动定时调度 |
| `python3 main.py web` | 启动 Web API/UI |
| `python3 main.py --version` | 输出版本信息 |

## 前端开发

```bash
cd frontend
npm install
npm run dev
npm run build
```

Docker 构建会先构建前端，并把 `frontend/dist` 复制进 Python 应用镜像。

## 配置

主配置文件：

```text
config/config.yaml
```

可从 `config/config.yaml.template` 创建。常见配置项：

| 配置 | 说明 |
| --- | --- |
| `data_dir` | 本地股票数据目录 |
| `dingtalk.webhook_url` | 钉钉机器人 webhook |
| `dingtalk.secret` | 钉钉签名密钥 |
| `schedule.time` | 每日定时运行时间 |
| `update.lookback_days` | 增量更新回看天数 |

策略参数文件：

```text
config/strategy_params.yaml
```

重点参数包括：

- `BowlReboundStrategy`：成交量倍数、回看天数、市值门槛、KDJ 阈值和趋势线距离。
- `B1PatternMatch`：最小相似度、回看天数、维度权重、匹配容忍度和返回数量。

## 项目结构

```text
.
├── main.py                   # CLI 入口
├── web_server.py             # Flask API 与前端静态服务
├── strategy/                 # 策略注册、碗口反弹和 B1 图形匹配
├── utils/                    # AkShare 拉取、CSV、图表和钉钉通知
├── views/                    # SQLite 视图和结果管理
├── frontend/                 # React Web UI
├── config/                   # 运行配置和策略参数
├── B1_PATTERN_MATCH.md       # B1 匹配说明
├── Dockerfile
└── docker-compose.yml
```

## Docker

使用 Docker Compose 构建并运行：

```bash
docker compose up -d --build
```

当前 `docker-compose.yml` 将宿主机 `18321` 映射到容器 `5000`，并用 `quant-data` volume 保存生成数据。

## 注意事项

- 市场数据保存在运行时 `data/` 目录。
- 钉钉 webhook 和签名密钥应保存在本地配置或部署环境中。
- `B1_PATTERN_MATCH.md` 记录了 B1 历史案例、特征维度和相似度计算说明。
- 输出结果用于研究参考，不应直接作为交易依据。
