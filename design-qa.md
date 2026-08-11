# 决策台设计 QA

## 对照目标

- source visual truth path: `/Users/simba/Agentic-Engineering/归档/share/a-share-quant-selector-astryx-rebase/frontend/design-references/decision-console-master-detail.png`
- implementation screenshot path: `/Users/simba/Agentic-Engineering/归档/share/a-share-quant-selector-astryx-rebase/.runtime/qa/stocks-implementation.png`
- route: `http://127.0.0.1:5124/stocks`
- viewport: `1487 × 1058` CSS px
- source pixels: `1487 × 1058`
- implementation pixels: `1487 × 1058`
- deviceScaleFactor: `1`
- density normalization: 无需缩放；源图与实现截图像素尺寸相同。
- state: 亮色主题，`2026-08-11` 收盘，3 个云阶信号，默认选中“威派格”和日 K。

## 对照证据

- full-view comparison evidence: `/Users/simba/Agentic-Engineering/归档/share/a-share-quant-selector-astryx-rebase/.runtime/qa/stocks-design-comparison.png`
- focused list comparison evidence: `/Users/simba/Agentic-Engineering/归档/share/a-share-quant-selector-astryx-rebase/.runtime/qa/stocks-design-focus-list.png`
- focused detail comparison evidence: `/Users/simba/Agentic-Engineering/归档/share/a-share-quant-selector-astryx-rebase/.runtime/qa/stocks-design-focus-detail.png`
- mobile implementation evidence: `/Users/simba/Agentic-Engineering/归档/share/a-share-quant-selector-astryx-rebase/.runtime/qa/stocks-mobile-final.png`
- mobile viewport: `390 × 844` CSS px，全页截图 `390 × 1533` px，页面水平溢出为 `0` px。

## Findings

- 无剩余 P0 / P1 / P2 问题。
- 字体与排版：继续使用项目锁定的系统中文无衬线和等宽数字；标题、信号数、候选名称、价格与辅助信息层级清楚，没有截断或错位。实现比概念稿略紧凑，是为容纳真实 K 线、图例与三条证据，不改变阅读层级。
- 间距与布局：已实现 420px 候选清单 + 自适应研究区的主从工作面；候选、图表、证据链和执行结论的分区与概念稿一致。页面容器放宽到 1440px 后，大屏留白、左右比例和原图更接近。
- 颜色与 token：使用项目 Neutral 主题的画布、面板、边框和强调色；互动色统一为蓝色，A 股涨跌继续使用红涨绿跌，无渐变、重阴影或额外卡片噪声。
- 图像与资产：目标界面不包含摄影、插画或装饰资产；实现使用真实 ECharts K 线和 Astryx 图标，没有占位图、CSS 伪资产或手写 SVG。
- 文案与内容：删除重复的“值得买入”胶囊、优先组合、AI 未配置和板块全景等非当前决策内容；保留真实优先级、买点确认、市场执行强度、证据链和详情入口。零点时间已从证据日期中移除。
- 图标与状态：买点确认使用 Astryx `Icon`；候选选中、图表设置展开、周 K 选中、错误重试、空状态与加载骨架都有真实反馈。
- 响应式与可访问性：候选按钮可用键盘 Space 切换，选中状态通过 `aria-current` 暴露；`prefers-reduced-motion: reduce` 下详情动画时长为 `0s`；390px 宽度下无页面级横向滚动。

## 互动与运行证据

- 候选切换：威派格 → 美盈森的下一可绘制帧反馈为 31.2ms，低于 100ms 门槛；工作面顶部与宽度保持稳定。
- 提交范围：该次切换观察到 9 条 DOM 变更记录、1 个新增节点、3 个移除节点，无 long task，没有出现大范围重复提交。
- 稳定与动效：加载与候选切换累计 CLS 为 `0.000416`；自定义详情进场为 `qs-fade 0.15s cubic-bezier(0.16, 1, 0.3, 1)`，关键帧只改变 `opacity` 和 `transform`，时长与缓动来自项目 token。
- 键盘：聚焦第三个候选后按 Space，当前研究对象切换为“地铁设计”。
- 图表：周 K `aria-checked=true`；图表设置面板可展开；详情链接随当前候选切换为 `/stock/003013`。
- 状态：延迟接口时出现 752 × 640 骨架；503 时显示“云阶决策暂不可用”与重试按钮；空候选时说明不会为有票而降低门槛。
- 浏览器控制台错误：0。
- 网络请求失败：0（正常真实数据状态）。
- `npm run lint`：通过。
- `npm run build`：通过（TypeScript + Vite）。
- 按项目约定，本轮没有新增或运行自动化测试；使用真实浏览器状态、交互、错误恢复和视觉对照作为本轮功能证据。

## TRACE

- T — 真实目标：帮助收盘后复盘的 A 股研究用户，在十几秒内判断有无云阶信号、优先看哪只、理由是什么，不虚构买点、行业或 AI 结论。
- R — 任务路径：信号数与市场环境 → 候选优先级比较 → 选中一只 → K 线与三段证据 → 执行强度或个股详情；历史与同板块对比按需展开。
- A — 行为与状态：默认、候选切换、周 K、图表设置、详情链接、加载、空、可恢复错误和手机端都有真实运行证据。
- C — 工艺与代码：复用项目 Astryx `Item` / `Button` / `SegmentedControl` / `Icon`、Neutral 主题、现有 ECharts 与真实 API；未新增依赖，未增加假入口或不可操作控件。
- E — 验收证据：同尺寸双图对照、桌面/手机浏览器截图、主路径交互、错误恢复、键盘、减少动效、布局稳定、控制台/网络、Lint 与构建均已记录。

## Comparison History

1. 第一次对照发现 [P1] 执行文案“试仓观察”会弱化已确认买点，证据日期显示无意义的 `00:00:00`。已改为真实执行强度“试仓”，并对证据日期做只读格式化。
2. 第一次对照发现 [P2] 1320px 桌面容器在 1487px 参考尺寸下两侧留白过大，右侧研究区偏窄。已放宽为 1440px，使候选分栏、K 线与证据链的比例接近概念稿。
3. 修复后重新以 `1487 × 1058` 截图，并生成全景、候选清单和研究区聚焦对照。未再发现可执行的 P0 / P1 / P2 问题。

## Open Questions

- 无阻塞项。顶部导航保留项目真实的“决策台 / 复盘 / 后台”三个入口，没有照搬 ImageGen 概念稿中未存在的页面。
- 真实 K 线保留 MA5/10/20/60、多空线、趋势线和 KDJ，比概念稿的简化图表更密，这是真实功能约束。

## Implementation Checklist

- [x] 主从工作面与真实候选数据
- [x] 候选切换、日/周/月 K、图表设置与详情入口
- [x] 三段信号证据与执行强度
- [x] 加载、空、错误与重试状态
- [x] 1487px 桌面与 390px 手机浏览器验收
- [x] 键盘、降级动效、溢出与控制台检查

## Follow-up Polish

- [P3] 如后续希望更贴近概念稿的视觉尺度，可在不减少真实图表信息的前提下，再轻微放大候选列表文字。

final result: passed
