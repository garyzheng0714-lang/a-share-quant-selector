# 架构

```
updater.py（常驻，工作日 15:35）
  腾讯 qt.gtimg.cn  ──股票池/名称/市值──▶ stock_names.json / stock_market_cap.json
  腾讯 fqkline      ──前复权日线────────▶ data/{前两位}/{code}.csv（最新在前）
  新浪行业          ──行业（每周）──────▶ stock_industry.json
  strategy/factors  ──全因子扫描───────▶ data/factor_cache/{date}.json（保留 40 天）

app.py（gunicorn，只读）
  GET /api/factors                     因子清单 + 常用组合 + 当日命中数 + 可选日期
  GET /api/factor-compose?keys&join    且/或组合；任一因子缺当日缓存则整体不可用；连命中天数用历史缓存回溯
  GET /api/factor-scan?strategy&date   单因子结果
  GET /api/stock/<code>/kline          日 K / 周 K + 该票历史因子命中日
  GET /api/stock/<code>/profile        名称 / 行业 / 流通市值
  GET /api/stats, /healthz
  其余路径                              frontend/dist
```

- 扫描一次读一只股票的 CSV，29 个因子共用一个 `FactorContext`（同参指标只算一遍）。全市场 6000 只单线程约 2 分钟（M 系列 Mac），峰值内存约 100 MB。
- 没有数据库：一切都是 CSV 和 JSON，坏了就重跑 `updater.py`。
- 部署：`.github/workflows/deploy.yml` 在 CI 通过后构建镜像、`docker save | ssh docker load`、`docker compose up -d`。回滚就是重新部署上一个 commit。
