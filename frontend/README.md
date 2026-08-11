# 前端

React 19 + TypeScript + Vite 的量化研究界面。项目总入口与运行方式见 [根 README](../README.md)，视觉规范见 [DESIGN](../DESIGN.md)。

## 路由

- `/stocks`：云阶候选与决策；
- `/review`：云阶真实历史复盘；
- `/admin`：只读的数据、任务、策略和快照状态；
- `/data-pipeline`：数据管线、来源与保留证据；
- `/stock/:code`：个股与日/周 K。

历史的 `/sectors`、`/today`、`/performance` 和 `/history` 只作兼容跳转，不再维护独立页面树。

## 开发与验证

```bash
npm ci
npm run dev
npm run lint
npm run test
npm run build
```

通过 `VITE_API_BASE` 指向受控 Flask API。不要把生产配置或 token 写入前端环境。

手机验收工具：

```bash
node scripts/mobile-shot.mjs http://127.0.0.1:5000 /tmp/quant-mobile \
  /stocks,/review,/admin,/data-pipeline,/stock/000676
```

输出放在仓库外。lint、现有单元测试、TypeScript/build 和真实浏览器检查共同构成基线。
