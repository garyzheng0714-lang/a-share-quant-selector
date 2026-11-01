# QSelect · A 股因子选股

一个纯匹配的选股工具：盘后抓全市场日线，用 29 个通达信口径的因子逐只匹配，网页上点因子就出股票，点股票看 K 线。没有回测、没有模型、没有 AI、没有数据库。1 核 1G 的机器绰绰有余（全市场扫描峰值内存约 100 MB）。

研究工具，不构成投资建议。

线上：https://garyzheng0714-lang.github.io/a-share-quant-selector/ （GitHub Pages，没有服务器）。

## 组成

| 文件 | 作用 |
|---|---|
| `updater.py` | 盘后更新：腾讯接口抓日线（前复权）、股票池与市值，新浪的申万一级行业；然后全因子扫描写缓存 |
| `export_static.py` | 把 `data/` 导出成网页直接读的静态 JSON（因子清单、每日命中、个股 K 线） |
| `strategy/factors/` | 29 个因子（B1 系 / 知行系 / 动量系 / 三度系 / 生命线系）与常用组合 `PRESETS` |
| `strategy/factor_lib.py`, `strategy/tdx.py` | 单股指标缓存与通达信基础函数 |
| `utils/store.py` | CSV + JSON 存储；`utils/fetch.py` 抓取；`utils/scan.py` 扫描；`utils/kline.py` K 线 |
| `frontend/` | React + Astryx：`/select` 选股工作台，`/stock/:code` K 线 |

数据目录 `data/`（环境变量 `QUANT_DATA_DIR`）：`{前两位}/{code}.csv` 日线、`stock_names.json`、`stock_industry.json`、`stock_market_cap.json`、`factor_cache/{date}.json`。

因子口径见各 `strategy/factors/*_family.py` 的 docstring；「神机信号」是从公众号截图反推的，来源与参数见 `docs/architecture.md`。

## 本地运行

```bash
pip install -r requirements.txt
python updater.py --init --years 3   # 首次入库，约 6000 只，十几分钟
python updater.py                    # 之后每次：增量更新 + 扫描
python export_static.py --out frontend/public/d
cd frontend && npm ci && npm run dev # http://localhost:3000
```

## 部署

`.github/workflows/site.yml`，全在 GitHub 上跑，公开仓库免费、不用任何密钥：

- 每个工作日北京时间 15:40：抓行情 → 扫描 → 导出 → 连同网页发布到 GitHub Pages（约 20 分钟）。
- 推 `main`：CI（ruff + pytest + 前端 lint/build）通过后只重新扫描、发布，不抓行情。
- 行情数据存在 Actions 缓存（`quant-data-*`，只留最新一份）；缓存丢了会自动从头抓 3 年，约 40 分钟。
- 「且 / 或」组合和连命中天数在浏览器里算（`frontend/src/lib/compose.ts`），口径与扫描缓存一致。

## 验证

```bash
python -m pytest -q
cd frontend && npm run lint && npm run build
```
