# 模型治理与研究口径

更新时间：2026-07-23。

## 目标

系统首先要做到可回放、可归因、可空仓、可否决，再讨论收益改善。任何市场、板块、风险或质量模型都必须单独证明样本外增量，不能依靠直觉、样本内曲线或模型自报指标进入生产。

## 时点和数据边界

1. T 日收盘决策只使用与 T 日不可变 snapshot 一致、在决策 as-of 前可见的数据。
2. T+1 08:45 盘前复核可以加入 T 收盘后至该时点公开的公告，但不得回填到 T 日模型。
3. 决策的 `trade_date`、snapshot trade date、data version、snapshot ID 和预期已完成交易日必须一致；任一不一致都拒绝生成或展示。
4. 历史回放只能按顺序加载当时已发布的市场/参考快照，并复验 manifest 和文件哈希。不允许把当前股票池、行业、市值、证券状态倒填到历史日期。
5. 每个训练样本必须同时记录 `feature_snapshot_id` 和 `reference_snapshot_id`，二者必须是同一个信号日快照。当前快照中的前复权历史不能倒充历史 PIT 特征；缺少逐日可信快照时，日常进化记录 `pit_feature_history_unavailable` 并保留冠军。

## 候选、组件和唯一 policy

- Super B1 是唯一生产规则 baseline，旧 BowlRebound 不由生产包导出或自动注册；旧 CLI 已隔离到 `research/legacy/`。
- 完整 policy 由 market、sector、entry_risk、exit_risk 和 quality 五个冻结组件组成。生产不允许把新旧组件临时拼接。
- market 模型的语义是 `b1_signal_day_candidate_quality_gate`：它只评估“已经出现 B1 候选的信号日”，不是全市场涨跌预测模型。
- entry unbuyable 和 exit unsellable 是两类独立标签，必须保留在数据集中，不能删掉最差的可执行性样本。
- 周线 MA5/10/20/60 运行口径和 OOS 评估必须使用同一函数。在历史 PIT 证据不足时保持 shadow。
- 无已验证 market 模型时，严格门禁只输出 `observe`。无已验证 quality 模型时，不伪造精确 top-1。

## 训练和统计门禁

- 评估使用按时间顺序的 purged walk-forward，不做随机切分，不让标签窗口穿越折叠边界。
- 每个折叠的阈值仅来自当时可见的验证数据。最终模型另外保留最后 3 个月作为 purge 后的独立校准窗，不使用最后一个折叠的阈值。
- 优化不收敛、数值异常或单一类别数据不得静默退化成零系数模型；该产物必须标记为不可发布。
- 独立校准窗必须报告 Brier score、ECE 和分箱校准曲线；样本不足、Brier > 0.30、ECE > 0.20 或校准曲线无法形成时不可发布。
- 训练到校准窗的特征漂移使用包含缺失桶的 PSI，系数稳定性使用按时间扩展的重训窗口检查符号一致性和离散度。这些是发布门禁，不只是展示指标。
- bootstrap 固定 10,000 次，同时报告日期簇、股票簇和日期×股票 pigeonhole 双向簇。报告必须给出 Monte Carlo 标准误、分位数分辨率和预注册比较计划，不允许事后只选最好对照。
- 每个产物必须记录训练/测试/校准范围、特征、阈值、收敛诊断、数据集哈希、源码 SHA、产物哈希和 source refs。

## 注册、验证和发布

研究代码只能注册 `shadow` 候选，不能自称 validated/active。服务器会重新计算功效分析和完整 policy 评估 artifact 的规范化哈希，并校验其中的 policy、dataset、源码、独立月份和 runtime manifest，然后再校验：

- policy 五个组件全部存在，模型诊断可发布；
- 数据集、代码和模型产物哈希符合格式并与证据一致；
- source refs 至少包含 `super-b1-original`、`immutable-market-snapshots-v2`、`point-in-time-reference-snapshots-v4`、`point-in-time-feature-snapshots-v1`、`pit-security-state-and-listing-regime-v2`、`a-share-eod-open-open-v3`、`purged-walk-forward-v2` 和 `independent-final-calibration-v1`；
- 至少 6 个月独立前向观察，观察窗已真实结束；
- 统计功效和完整 policy 原子评估证据已验证；
- reviewer 和变更工单存在。

激活时要求 operator 与 reviewer 不同，且必须引用服务器已落账的 validation evidence hash。激活是完整 policy 的原子事件，不支持单层提升。模型/policy 登记、验证证据和发布事件均不可删改；唯一允许的状态迁移是经验证的 `shadow → validated`。

每次激活必须预先登记当时的上一 policy 为回退目标。回退时仍需不同的 operator/reviewer、工单、变更理由和 expected-current 乐观锁；不能临时指向任意历史模型。

## 交易口径

回放、T+1/T+5 标签、performance 和模拟盘共用 `a-share-eod-open-open-v3`：

- T 日收盘后产生信号，最早 T+1 开盘买入；持有 5 个完成会话后的可执行开盘卖出；
- 100 股整数手、T+1、停牌/零成交量、方向性涨跌停和上市初期无涨跌幅制度；
- ST 5%、创业板/科创板 20%、北交所 30%，主板和历史制度按日期/板块处理；
- 双边滑点、最低佣金、卖出印花税和过户费；
- 无法证明证券状态、上市会话或成交价时，保留 unbuyable/unsellable 结果并延期，不伪造成交。
- 标签从 pending/partial 发展到 complete 时只能追加新观测，不能覆盖历史。每条观测必须绑定 64 位不可变快照 ID；内容相同的重试幂等，performance 只消费每个决策候选的最新且哈希/快照校验通过的观测。

模拟账户的现金从 cash events 重建，持仓从 fills/lots/closures 重建，NAV 用当日价格独立重算并对账。每次 fill 和 NAV 都必须记录实际定价快照与 `execution_policy_version`；存在无快照来源的旧模拟事件时，生产只读预检会阻止启动。同一快照上重复日结和两个 worker 竞争不得创建重复 NAV。

## LLM 权限

LLM 只能对已经落账的候选和动作生成结构化解释，并记录 input hash、prompt version、模型和结果状态。它不能：

- 选择候选外的股票；
- 改变排名或 buy/observe/avoid；
- 在没有候选时强行生成荐股；
- 把无引用的新闻、业绩或事件当作事实。

未配置 LLM 时记录 `not_called`；输出不合规或调用失败时记录失败原因，不影响规则决策。

## 最低报告内容

每次完整 policy 评估必须同时报告 baseline 与五层消融、月份稳定性、左尾/CVaR、最大回撤、覆盖率、空仓收益/机会成本、不可买/不可卖率、费用和对账状态。不得只报告平均收益、胜率或事后最优参数。
