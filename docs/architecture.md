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

- 行情抓取只用腾讯/新浪公开接口。腾讯 K 线主域名对海外 IP 连发约 1500 次会被 WAF 拦成 501，所以按 `web.ifzq` → `proxy.finance` → `ifzq` 轮询、每次请求后节流 0.25 秒、2 个线程；全市场增量更新约 25 分钟。
- 扫描一次读一只股票的 CSV，29 个因子共用一个 `FactorContext`（同参指标只算一遍）。全市场 6000 只单线程约 2 分钟（M 系列 Mac），峰值内存约 100 MB。
- 没有数据库：一切都是 CSV 和 JSON，坏了就重跑 `updater.py`。
- 部署：`.github/workflows/deploy.yml` 在 CI 通过后构建镜像、`docker save | ssh docker load`、`docker compose up -d`。回滚就是重新部署上一个 commit。

## 神机信号的口径来源

「神机信号」（`strategy/factors/shenji_family.py`）不是原创指标，是 2026-09 从公众号「神机队长」14 篇文章、26 根被标记的 K 线（日线 / 60 分钟 / 30 分钟 / 15 分钟）加同图 435 根未标记 K 线逐根反推出来的：

- 生命线 = MA(CLOSE, 13)。像素级拟合四张截图，误差 0.004–0.037，明显优于 12 / 14 及各类 EMA。
- 触发 = 收盘带 0.5% 容差上穿生命线（昨日 BIAS ≤ 0.5%，今日 > 0.5%），且当日涨幅 > 2%。成交量过滤被 15 分钟样本证伪。
- 461 根样本里只剩 2 个分钟级例外，都在数据源分钟 K 的差异范围内。

它是滞后的趋势确认，不是预测。全市场每天触发 40–960 只（中位数约 230），大涨日等于市场广度指标；作者能每天只贴几只，靠的是题材和板块的人工挑选。作者自己标的票绝大多数不在 60 日区间低位，「底部」是文案，所以工具没有加底部过滤，只提供行业筛选和量比排序。生命线本身只画在 K 线上，不作为因子。
