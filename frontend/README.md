# 前端

React 19 + TypeScript + Vite 的量化研究界面。项目总入口与运行方式见 [根 README](../README.md)，视觉规范见 [DESIGN](../DESIGN.md)。

## 路由

- `/sectors`：板块；
- `/stocks`：候选与决策；
- `/review`：战绩、因子、模型和历史；
- `/stock/:code`：个股与日/周 K。

## 开发与验证

```bash
npm ci
npm run dev
npm run lint
npm run build
```

通过 `VITE_API_BASE` 指向受控 Flask API。不要把生产配置或 token 写入前端环境。

手机验收工具：

```bash
node scripts/mobile-shot.mjs http://127.0.0.1:5000 /tmp/quant-mobile \
  /sectors,/stocks,/review
```

输出放在仓库外。当前没有前端单元测试脚本，lint、TypeScript/build 和真实浏览器检查共同构成基线。
