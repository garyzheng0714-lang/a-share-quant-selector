# A-Share Quant Selector

基于 Python + AkShare 的 A 股量化选股系统，包含命令行选股流程、K 线图生成、钉钉通知、B1 图形相似度匹配，以及一个 React Web 管理界面。

## Overview

系统从 AkShare 获取 A 股历史数据，按策略计算技术指标并筛选候选股票。命令行流程可以完成数据初始化、增量更新、选股和通知；Web 服务提供排行榜、历史结果、股票详情和多视图参数管理。前端构建后由 Flask 服务统一托管，也支持 Docker Compose 部署。

本项目仅用于研究和自动化分析，不构成投资建议。

## Features

- 首次全量抓取和每日增量更新股票数据
- 碗口反弹策略：趋势线、多空线、放量阳线和 KDJ 低位筛选
- B1 完美图形匹配：与历史案例做趋势结构、量能、价格形态和 KDJ 相似度排序
- 选股结果分类：回落碗中、靠近多空线、靠近短期趋势线
- K 线图和技术指标图生成
- 钉钉群机器人通知，包含限流和重试保护
- Flask API + APScheduler 定时任务
- SQLite 多视图结果管理
- React 19 + ECharts Web 管理界面
- Dockerfile 和 `docker-compose.yml` 一键部署配置

## Tech Stack

Backend:

- Python 3.11+
- AkShare, pandas, NumPy
- matplotlib, Pillow
- Flask, gunicorn, APScheduler
- SQLite, orjson
- SciPy, fastdtw
- DingTalk robot webhook

Frontend:

- React 19, TypeScript, Vite
- Tailwind CSS
- ECharts
- SWR, Zustand
- React Router

Deployment:

- Docker multi-stage build
- Docker Compose
- GitHub Actions workflow

## Project Structure

```text
.
├── main.py                   # CLI entry point
├── web_server.py             # Flask API and frontend static server
├── strategy/                 # Strategy registry and implementations
├── utils/                    # Data fetcher, CSV manager, charts and DingTalk notifier
├── views/                    # SQLite-backed view/result management
├── frontend/                 # React Web UI
├── config/
│   ├── config.yaml.template  # Runtime config template
│   ├── strategy_params.yaml  # Strategy parameters
│   └── crontab.txt           # Cron reference
├── B1_PATTERN_MATCH.md       # Detailed B1 matching notes
├── Dockerfile
└── docker-compose.yml
```

## Getting Started

Install Python dependencies:

```bash
pip3 install -r requirements.txt
```

Create runtime configuration:

```bash
cp config/config.yaml.template config/config.yaml
```

Edit `config/config.yaml` to set DingTalk webhook settings if notifications are needed.

Initialize local stock data:

```bash
python3 main.py init
```

Run the full update, select and notify flow:

```bash
python3 main.py run
```

Start the Web interface:

```bash
python3 main.py web
```

The Flask service defaults to port `5000`.

## Commands

| Command | Description |
| --- | --- |
| `python3 main.py init` | Fetch initial historical stock data |
| `python3 main.py update` | Run daily incremental update |
| `python3 main.py select` | Execute stock selection only |
| `python3 main.py run` | Update data, select stocks and send notification |
| `python3 main.py run --max-stocks 500` | Process only the first 500 stocks for a quick test |
| `python3 main.py run --category bowl_center` | Filter by category |
| `python3 main.py run --b1-match` | Enable B1 pattern matching |
| `python3 main.py web` | Start the Web API/UI |
| `python3 main.py --version` | Print version information |

## Frontend Development

```bash
cd frontend
npm install
npm run dev
npm run build
```

The Docker build runs the frontend build first and copies `frontend/dist` into the Python app image.

## Configuration

Main runtime config:

```text
config/config.yaml
```

Use `config/config.yaml.template` as the starting point. Key sections:

| Key | Purpose |
| --- | --- |
| `data_dir` | Local stock data directory |
| `dingtalk.webhook_url` | DingTalk robot webhook |
| `dingtalk.secret` | DingTalk signing secret |
| `schedule.time` | Daily scheduled run time |
| `update.lookback_days` | Incremental update lookback window |

Strategy parameters:

```text
config/strategy_params.yaml
```

Important strategy sections:

- `BowlReboundStrategy`: volume multiplier, lookback days, market cap threshold, KDJ threshold and trend-line proximity settings
- `B1PatternMatch`: minimum similarity, lookback days, dimension weights, matching tolerances and top result count

## Docker

Build and run with Docker Compose:

```bash
docker compose up -d --build
```

The checked-in compose file maps host port `18321` to container port `5000` and stores generated data in the `quant-data` Docker volume.

## Notes

- Market data is stored locally under `data/` at runtime.
- DingTalk credentials should be kept in local config or deployment secrets.
- `B1_PATTERN_MATCH.md` documents the historical cases and similarity calculation details.
