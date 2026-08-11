import { useMemo, useState } from "react";
import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { Icon } from "@astryxdesign/core/Icon";
import { Item } from "@astryxdesign/core/Item";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { Link } from "react-router";
import { DecisionKline, type DecisionPeriod, type DecisionSubPanel } from "@/components/decision/decision-kline";
import { LoadError, Skeleton } from "@/components/ui";
import type { CloudMarketContext, RecommendStock } from "@/lib/api";
import { useCloudStairReview, useKline, useRecommend, useSectorDetail } from "@/lib/hooks";

type DetailPanel = "history" | "peers" | null;

const periodLabels: Record<DecisionPeriod, string> = {
  daily: "日K",
  weekly: "周K",
  monthly: "月K",
};

function signed(value?: number | null, digits = 1, suffix = "") {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}${suffix}`;
}

function sectorDescriptor(stock: RecommendStock) {
  const sector = stock.sector;
  if (!sector) return `${stock.industry || "行业待补全"} · 行业数据待补全`;
  return `${stock.industry} · 行业第 ${sector.rank}/${sector.total} · 热度 ${Math.round(sector.score)}`;
}

function signalDetail(detail: string) {
  return detail.replace(/(?:T|\s)00:00:00\b/g, "");
}

function decisionActionText(action: RecommendStock["action"]) {
  if (action === "buy") return "允许买入";
  if (action === "avoid") return "回避";
  if (action === "none") return "无正式动作";
  return "观察";
}

function actionText(stock: RecommendStock) {
  return stock.action_label || decisionActionText(stock.action);
}

function actionVariant(action: RecommendStock["action"]) {
  if (action === "buy") return "red" as const;
  if (action === "avoid") return "error" as const;
  if (action === "none") return "neutral" as const;
  return "warning" as const;
}

function CandidateDetail({
  stock,
  tradeDate,
  marketContext,
  formalDecisionAvailable,
}: {
  stock: RecommendStock;
  tradeDate?: string;
  marketContext?: CloudMarketContext;
  formalDecisionAvailable: boolean;
}) {
  const [period, setPeriod] = useState<DecisionPeriod>("daily");
  const [chartSettings, setChartSettings] = useState(false);
  const [panel, setPanel] = useState<DetailPanel>(null);
  const [ma, setMa] = useState({ ma5: true, ma10: true, ma20: true, ma60: false });
  const [overlays, setOverlays] = useState({ dk: true, trend: true, signals: true });
  const [subPanel, setSubPanel] = useState<DecisionSubPanel>("kdj");
  const kline = useKline(stock.code, period);
  const review = useCloudStairReview(500);
  const peers = useSectorDetail(panel === "peers" && stock.industry_available ? stock.industry : null);

  const history = useMemo(
    () => (review.data?.picks || []).filter((pick) => pick.code === stock.code).slice(0, 10),
    [review.data?.picks, stock.code],
  );
  const lastRow = kline.data?.data?.at(-1);
  const readoutDate = String(lastRow?.[0] || tradeDate || "—");
  const readoutClose = typeof lastRow?.[2] === "number" ? lastRow[2].toFixed(2) : stock.close.toFixed(2);
  const executionMode = marketContext?.execution_mode || "按计划";
  const candidateFormalAvailable = formalDecisionAvailable && stock.candidate_decision_available === true;
  const formalAction = candidateFormalAvailable
    ? actionText(stock)
    : formalDecisionAvailable
      ? "未纳入正式模型"
      : "待生成";

  const togglePanel = (next: Exclude<DetailPanel, null>) => setPanel((current) => current === next ? null : next);
  const toggleMa = (key: keyof typeof ma) => setMa((current) => ({ ...current, [key]: !current[key] }));
  const toggleOverlay = (key: keyof typeof overlays) => setOverlays((current) => ({ ...current, [key]: !current[key] }));

  return (
    <article className="q-candidate-detail" aria-labelledby={`candidate-${stock.code}`}>
      <header className="q-research-header">
        <div className="q-research-identity">
          <div className="q-research-title-line">
            <h2 id={`candidate-${stock.code}`}>{stock.name}</h2>
            <code>{stock.code}</code>
            <span className="q-confirmed-state">
              <Icon icon="check" size="xsm" color="secondary" label="云阶结构已确认" />
              {stock.signal_label || "云阶结构已确认"}
            </span>
            <Badge
              variant={candidateFormalAvailable ? actionVariant(stock.action) : "neutral"}
              label={`正式动作：${formalAction}`}
            />
          </div>
          <p>{sectorDescriptor(stock)}</p>
        </div>
        <div className="q-research-price">
          <strong>{stock.close.toFixed(2)}</strong>
          <span className={(stock.pct_change || 0) >= 0 ? "q-up" : "q-down"}>{signed(stock.pct_change, 2, "%")}</span>
        </div>
      </header>

      <div className="q-chart-toolbar">
        <SegmentedControl
          value={period}
          onChange={(value) => setPeriod(value as DecisionPeriod)}
          label="K线周期"
          size="sm"
        >
          {(Object.keys(periodLabels) as DecisionPeriod[]).map((key) => (
            <SegmentedControlItem key={key} value={key} label={periodLabels[key]} />
          ))}
        </SegmentedControl>
        <span className="q-chart-readout">{readoutDate} 收 {readoutClose}</span>
        <Button
          label={chartSettings ? "收起设置" : "图表设置"}
          variant="ghost"
          size="sm"
          onClick={() => setChartSettings((value) => !value)}
        />
      </div>

      {chartSettings && (
        <div className="q-chart-settings">
          <span className="q-settings-label">均线</span>
          {(["ma5", "ma10", "ma20", "ma60"] as const).map((key) => (
            <Button key={key} label={key.toUpperCase()} variant={ma[key] ? "secondary" : "ghost"} size="sm" onClick={() => toggleMa(key)} />
          ))}
          <span className="q-settings-divider" />
          <span className="q-settings-label">叠加</span>
          {(["dk", "trend", "signals"] as const).map((key) => (
            <Button
              key={key}
              label={{ dk: "多空线", trend: "趋势线", signals: "历史信号" }[key]}
              variant={overlays[key] ? "secondary" : "ghost"}
              size="sm"
              onClick={() => toggleOverlay(key)}
            />
          ))}
          <span className="q-settings-divider" />
          <span className="q-settings-label">副图</span>
          {(["kdj", "volume", "none"] as const).map((key) => (
            <Button
              key={key}
              label={{ kdj: "KDJ", volume: "成交量", none: "关闭" }[key]}
              variant={subPanel === key ? "secondary" : "ghost"}
              size="sm"
              onClick={() => setSubPanel(key)}
              isDisabled={key === "kdj" && period !== "daily"}
              tooltip={key === "kdj" && period !== "daily" ? "周/月线接口不返回 KDJ" : undefined}
            />
          ))}
        </div>
      )}

      {kline.isLoading ? (
        <Skeleton className="q-chart-skeleton" />
      ) : kline.error || !kline.data?.data?.length ? (
        <LoadError label="K 线加载失败" onRetry={() => kline.mutate()} />
      ) : (
        <DecisionKline
          data={kline.data.data}
          period={period}
          ma={ma}
          overlays={overlays}
          subPanel={period === "daily" ? subPanel : subPanel === "none" ? "none" : "volume"}
          signals={kline.data.signals}
        />
      )}

      <div className="q-detail-body">
        <section className="q-evidence-section" aria-labelledby={`why-${stock.code}`}>
          <h3 id={`why-${stock.code}`}>信号证据链</h3>
          <div className="q-evidence-chain">
            {(stock.signal_steps || []).map((step, index) => (
              <div className="q-evidence-step" key={step.key}>
                <span className="q-evidence-index">{index + 1}</span>
                <div>
                  <strong>{step.label}</strong>
                  <span>{signalDetail(step.detail)}</span>
                </div>
              </div>
            ))}
          </div>
        </section>

        <div className="q-next-step">
          <div>
            <span>正式动作</span>
            <strong>{formalAction}</strong>
          </div>
          <div>
            <span>结构证据</span>
            <strong>{stock.evidence_grade ? `${stock.evidence_grade}级` : "待评估"}</strong>
          </div>
          <p>
            {formalDecisionAvailable
              ? stock.action_detail || "正式动作以决策账本为准。"
              : "正式决策尚未生成，当前只展示结构信号。"}
            {` 市场执行背景：${executionMode}。`}
          </p>
        </div>

        <div className="q-detail-links">
          <Link to={`/stock/${stock.code}`}>查看个股详情</Link>
          <Button label={`历史被选中记录 (${history.length})`} variant="ghost" size="sm" onClick={() => togglePanel("history")} />
          <Button label="同板块横向对比" variant="ghost" size="sm" onClick={() => togglePanel("peers")} />
        </div>

        {panel === "history" && (
          <div className="q-inline-panel q-history-table" role="region" aria-label="历史被选中记录">
            <div className="q-history-head"><span>选中日</span><span>入场日</span><span>T+1</span><span>T+5</span><span>T+10</span><span>最大回撤</span></div>
            {review.isLoading ? <Skeleton className="h-24" /> : history.length ? history.map((row) => (
              <div className="q-history-row" key={`${row.pick_date}-${row.code}`}>
                <span>{row.pick_date}</span><span>{row.entry_date || "待入场"}</span>
                <span className={row.ret_1 != null && row.ret_1 >= 0 ? "q-up" : "q-down"}>{signed(row.ret_1, 2, "%")}</span>
                <span className={row.ret_5 != null && row.ret_5 >= 0 ? "q-up" : "q-down"}>{signed(row.ret_5, 2, "%")}</span>
                <span className={row.ret_10 != null && row.ret_10 >= 0 ? "q-up" : "q-down"}>{signed(row.ret_10, 2, "%")}</span>
                <span className="q-down">{signed(row.max_dd_5, 2, "%")}</span>
              </div>
            )) : <p>这只股票暂时没有可回读的云阶历史记录。</p>}
          </div>
        )}

        {panel === "peers" && (
          <div className="q-inline-panel q-peer-table" role="region" aria-label="同板块横向对比">
            <div className="q-peer-head"><span>#</span><span>股票</span><span>现价</span><span>5 日</span><span>确认项</span><span>动作</span></div>
            {peers.isLoading ? <Skeleton className="h-28" /> : peers.data?.stocks?.length ? peers.data.stocks.slice(0, 10).map((peer) => (
              <div className={peer.code === stock.code ? "q-peer-row is-current" : "q-peer-row"} key={peer.code}>
                <span>{peer.rank}</span><span><strong>{peer.name}</strong><small>{peer.code}</small></span>
                <span>{peer.close.toFixed(2)}</span>
                <span className={peer.ret5 != null && peer.ret5 >= 0 ? "q-up" : "q-down"}>{signed(peer.ret5, 1, "%")}</span>
                <span>{peer.confirmation_count}</span><span>{decisionActionText(peer.action)}</span>
              </div>
            )) : <p>当前板块没有可用的横向比较数据。</p>}
          </div>
        )}
      </div>
    </article>
  );
}

export function Component() {
  const recommend = useRecommend();
  const [selectedCode, setSelectedCode] = useState<string | undefined>(undefined);

  const allCandidates = useMemo(
    () => recommend.data?.candidates || [],
    [recommend.data?.candidates],
  );
  const selectedStock = allCandidates.find((stock) => stock.code === selectedCode) || allCandidates[0] || null;

  if (recommend.isLoading) {
    return <main className="q-decision-page"><h1 className="sr-only">云阶决策台</h1><Skeleton className="q-page-skeleton" /></main>;
  }
  if (recommend.error || !recommend.data?.available) {
    return (
      <main className="q-decision-page">
        <h1 className="sr-only">云阶决策台</h1>
        <LoadError label="云阶决策暂不可用" onRetry={() => recommend.mutate()} />
      </main>
    );
  }

  const decision = recommend.data;
  const marketContext = decision.market_context;
  const leader = decision.sector_leader;
  const dataReady = Boolean(decision.freshness?.fresh);
  const canonical = decision.canonical_decision;
  const formalDecisionAvailable = Boolean(canonical?.available);
  const formalDecisionLabel = !formalDecisionAvailable
    ? "决策待生成"
    : canonical?.status === "degraded"
      ? "决策降级"
      : "决策已落账";

  return (
    <main className="q-decision-page">
      <header className="q-decision-intro">
        <div className="q-decision-title-group">
          <h1>收盘决策</h1>
          <div className="q-decision-summary">
            <strong>{allCandidates.length} 个结构信号</strong>
            <span aria-hidden="true" />
            <b>
              {formalDecisionAvailable
                ? `${decision.today_buy?.length || 0} 只正式允许买入`
                : "正式动作待生成"}
            </b>
            <time dateTime={decision.trade_date}>{decision.trade_date}</time>
            <em className={dataReady ? "is-ready" : "is-review"}>{dataReady ? "行情就绪" : "行情需复核"}</em>
            <em className={formalDecisionAvailable && canonical?.status !== "degraded" ? "is-ready" : "is-review"}>
              {formalDecisionLabel}
            </em>
          </div>
        </div>
        <div className="q-market-context" aria-label="今日市场环境">
          <div><span>市场</span><strong>{marketContext?.score != null ? Math.round(marketContext.score) : "—"}</strong><em>{marketContext?.execution_mode || "待评估"}</em></div>
          <i aria-hidden="true" />
          <div><span>主线</span><strong>{leader?.name || "待补全"}</strong><em>{leader?.score != null ? Math.round(leader.score) : "—"}</em></div>
        </div>
      </header>

      <section className="q-decision-workspace" aria-label="云阶候选与当前研究结论">
        <aside className="q-signal-pane" aria-label="今日云阶候选">
          <div className="q-signal-list-header" aria-hidden="true">
            <span>优先级</span><span>名称 / 行业</span><span>信号分</span><span>最新价 / 涨跌</span>
          </div>
          {allCandidates.length ? (
            <ol className="q-signal-list">
              {allCandidates.map((stock, index) => (
                <Item
                  key={stock.code}
                  as="li"
                  align="start"
                  density="spacious"
                  marker={<span className="q-signal-rank">{index + 1}</span>}
                  label={<span className="q-signal-name"><strong>{stock.name}</strong><code>{stock.code}</code></span>}
                  description={(
                    <span className="q-signal-industry">
                      {stock.industry || "行业待补全"} · 正式动作：
                      {formalDecisionAvailable
                        ? stock.candidate_decision_available === true
                          ? actionText(stock)
                          : "未纳入正式模型"
                        : "待生成"}
                    </span>
                  )}
                  endContent={
                    <span className="q-signal-metrics">
                      <strong>{stock.priority_score?.toFixed(1) ?? "—"}</strong>
                      <span><b>{stock.close.toFixed(2)}</b><em className={(stock.pct_change || 0) >= 0 ? "q-up" : "q-down"}>{signed(stock.pct_change, 2, "%")}</em></span>
                    </span>
                  }
                  isSelected={selectedStock?.code === stock.code}
                  onClick={() => setSelectedCode(stock.code)}
                  data-testid={`candidate-${stock.code}`}
                />
              ))}
            </ol>
          ) : (
            <div className="q-empty-state">
              <strong>今天云阶没有选出股票</strong>
              <span>系统不会为了有票而降低突破确认门槛。</span>
            </div>
          )}
        </aside>

        <div className="q-research-pane">
          {selectedStock ? (
            <CandidateDetail
              stock={selectedStock}
              tradeDate={decision.trade_date}
              marketContext={marketContext}
              formalDecisionAvailable={formalDecisionAvailable}
            />
          ) : (
            <div className="q-research-empty">选择一只候选查看证据。</div>
          )}
        </div>
      </section>

      <p className="q-disclaimer">研究工具，不构成投资建议。云阶只生成结构信号；正式动作以决策账本为准，市场温度仅作执行背景。</p>
    </main>
  );
}
