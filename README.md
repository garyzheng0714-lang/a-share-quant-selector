# QSelect · A 股因子选股

一个纯匹配的选股工具：盘后抓全市场日线，用 29 个通达信口径的因子逐只匹配，网页上点因子就出股票，点股票看 K 线。没有回测、没有模型、没有 AI、没有数据库。1 核 1G 的机器绰绰有余（全市场扫描峰值内存约 100 MB）。

研究工具，不构成投资建议。

## 组成

| 文件 | 作用 |
|---|---|
| `updater.py` | 盘后更新：腾讯接口抓日线（前复权）、股票池与市值，新浪行业；然后全因子扫描写缓存 |
| `app.py` | 只读 Flask：因子清单、且/或组合结果、K 线、个股简介；托管前端 |
| `strategy/factors/` | 29 个因子（B1 系 / 知行系 / 动量系 / 三度系 / 生命线系）与常用组合 `PRESETS` |
| `strategy/factor_lib.py`, `strategy/tdx.py` | 单股指标缓存与通达信基础函数 |
| `utils/store.py` | CSV + JSON 存储；`utils/fetch.py` 抓取；`utils/scan.py` 扫描；`utils/kline.py` K 线 |
| `frontend/` | React + Astryx：`/select` 选股工作台，`/stock/:code` K 线 |

数据目录 `data/`（环境变量 `QUANT_DATA_DIR`）：`{前两位}/{code}.csv` 日线、`stock_names.json`、`stock_industry.json`、`stock_market_cap.json`、`factor_cache/{date}.json`。

## 本地运行

```bash
pip install -r requirements.txt
python updater.py --init --years 3   # 首次入库，约 6000 只，十几分钟
python updater.py                    # 之后每次：增量更新 + 扫描
python app.py                        # http://127.0.0.1:18321
cd frontend && npm ci && npm run dev # 开发前端，代理到 18321
```

## 部署

`docker compose up -d` 起两个容器：`web`（gunicorn，读缓存）和 `updater`（常驻，工作日 15:35 跑一轮；启动时若落后也补一轮）。数据在卷 `quant-data`。

GitHub Actions：推 `main` → CI（ruff + pytest + 前端 lint/build）→ Deploy（在 runner 构建镜像，`docker save | ssh docker load`，`docker compose up -d`，健康检查）。仓库 secrets：`SERVER_HOST`、`SERVER_USER`、`SERVER_SSH_KEY`。

## 验证

```bash
python -m pytest -q
cd frontend && npm run lint && npm run build
```
