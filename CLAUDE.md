# QSelect · Agent 入口

这是个人 A 股因子选股工具：盘后抓日线 → 全因子匹配 → 网页点因子出股票。**纯匹配，不做分析**。任何页面和文案都保留「研究工具，不构成投资建议」的边界。

## 铁律

- 不加回测、模型、AI、账本、数据库、任务队列这类东西；有需求先问用户。目标是 1 核 1G 跑得动。
- 行情源失败就保留旧数据并如实记录，绝不生成假行情。
- ST / *ST / 退市股不进选股池。
- `app.py` 只读，不写文件；只有 `updater.py` 写 `data/`。
- 不读取或提交 `data/`、`config/`、`.env`。

## 结构

见 [README](README.md)。因子实现在 `strategy/factors/*_family.py`，注册表和常用组合在 `strategy/factors/__init__.py`；加因子只改这两处。

## 验证

```bash
python -m pytest -q
cd frontend && npm run lint && npm run build
```

只跑受影响的检查；不新增 CI 门禁、覆盖率、UI 单测。设计规范见 `DESIGN.md`。
