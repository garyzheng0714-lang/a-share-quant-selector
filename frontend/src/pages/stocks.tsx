import { useMemo, useState } from "react";
import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { ClickableCard } from "@astryxdesign/core/ClickableCard";
import { Collapsible } from "@astryxdesign/core/Collapsible";
import { Icon } from "@astryxdesign/core/Icon";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { StatusDot } from "@astryxdesign/core/StatusDot";
import { DecisionKline, type DecisionPeriod, type DecisionSubPanel } from "@/components/decision/decision-kline";
import { LoadError, Skeleton } from "@/components/ui";
import type { CloudEventEvidence, CloudMarketContext, RecommendStock, SectorHot } from "@/lib/api";
import { useCloudStairReview, useKline, useRecommend, useSectorDetail, useSectors } from "@/lib/hooks";

type DetailPanel = "news" | "history" | "peers" | null;
type CandidateFilter = "sector" | "ai" | "wave" | "heat" | "industry";
type SectorDrawerRow = {
  name: string;
  score: number;
  delta3?: number;
  stage?: string;
  trend?: SectorHot["trend"];
  breadth_ma10?: number;
  heat_series?: number[];
  rank?: number;
  total?: number;
  reasons?: string[];
};

const periodLabels: Record<DecisionPeriod, string> = {
  daily: "日 K",
  weekly: "周 K",
  monthly: "月 K",
};

const aiReasonLabels: Record<string, string> = {
  llm_unconfigured: "AI 尚未配置",
  no_cloud_stair_signals: "今日没有云阶信号",
  decision_not_ready: "收盘决策尚未完成",
  comment_not_ready: "AI 解释尚未生成",
  ai_run_not_current: "AI 解释尚未绑定当前快照",
};

function signed(value?: number | null, digits = 1, suffix = "") {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}${suffix}`;
}

const riskTagLabels: Record<string, string> = {
  accident: "事故或停产",
  deal_failed: "重组终止",
  debt_or_fraud: "债务或诉讼",
  delisting: "退市风险",
  earnings_shock: "业绩恶化",
  inquiry: "监管问询",
  investigation: "立案调查",
  penalty: "处罚处分",
  pledge: "质押或冻结",
  reduction: "股东减持",
  risk_notice: "风险提示",
};

function riskTagLabel(tag: string) {
  return riskTagLabels[tag] || tag.replaceAll("_", " ");
}

function actionTone(stock: RecommendStock) {
  return stock.action === "buy" ? "buy" : "observe";
}

function stageLabel(stage?: string) {
  return stage || "状态待补全";
}

function sectorLine(stock: RecommendStock) {
  const sector = stock.sector;
  if (!sector) return `${stock.industry || "行业待补全"} · 行业热度待补全`;
  return `${stock.industry} · 热度 ${Math.round(sector.score)} · ${sector.rank}/${sector.total} · ${stageLabel(sector.stage)}`;
}

function eventVariant(event: CloudEventEvidence): "success" | "error" | "warning" | "neutral" {
  if (event.sentiment === "positive") return "success";
  if (event.sentiment === "negative") return "error";
  if (event.sentiment === "mixed") return "warning";
  return "neutral";
}

function eventLabel(event: CloudEventEvidence) {
  return event.sentiment_label || (event.source_category === "announcement" ? "公告" : "中性信息");
}

function eventTime(value?: string) {
  if (!value) return "时间未记录";
  return value.slice(5, 16).replace("T", " ");
}

function intelligenceLine(stock: RecommendStock) {
  const counts = stock.event_counts;
  const eventText = counts
    ? `消息 +${counts.positive} / -${counts.negative}`
    : "消息待收录";
  return `云阶结构 ${stock.structure_score?.toFixed(0) ?? "—"} · ${sectorLine(stock)} · ${eventText}`;
}

function visibleByFilters(stock: RecommendStock, filters: Set<CandidateFilter>) {
  const sectorStage = stock.sector?.stage || "";
  if (filters.has("sector") && !sectorStage.includes("主线") && !["升温", "接力"].includes(sectorStage)) return false;
  if (filters.has("ai") && !stock.ai_analysis) return false;
  if (filters.has("wave") && (stock.wave_gain_pct ?? 0) < 30) return false;
  if (filters.has("heat") && (stock.sector?.score ?? 0) < 60) return false;
  if (filters.has("industry") && !stock.industry_available) return false;
  return true;
}

function MiniSectorSparkline({ values, trend }: { values?: number[]; trend?: SectorHot["trend"] }) {
  const points = values?.slice(-9) ?? [];
  if (points.length < 2) return <span className="q-sector-spark-empty">—</span>;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const span = max - min || 1;
  return (
    <span className={`q-sector-spark q-sector-spark--${trend || "flat"}`} aria-label={`近 ${points.length} 日热度`}>
      {points.map((value, index) => (
        <span
          key={`${index}-${value}`}
          className="q-sector-spark-bar"
          style={{ height: `${4 + ((value - min) / span) * 14}px` }}
        />
      ))}
    </span>
  );
}

function CandidateDetail({
  stock,
  tradeDate,
  marketContext,
  intelligenceCutoff,
}: {
  stock: RecommendStock;
  tradeDate?: string;
  marketContext?: CloudMarketContext;
  intelligenceCutoff?: string | null;
}) {
  const [period, setPeriod] = useState<DecisionPeriod>("daily");
  const [chartSettings, setChartSettings] = useState(false);
  const [panel, setPanel] = useState<DetailPanel>(null);
  const [ma, setMa] = useState({ ma5: true, ma10: true, ma20: true, ma60: false });
  const [overlays, setOverlays] = useState({ dk: true, trend: true, signals: true });
  const [subPanel, setSubPanel] = useState<DecisionSubPanel>("kdj");
  const kline = useKline(stock.code, period);
  const review = useCloudStairReview(500);
  const peers = useSectorDetail(stock.industry_available ? stock.industry : null);

  const history = useMemo(
    () => (review.data?.picks || []).filter((pick) => pick.code === stock.code).slice(0, 10),
    [review.data?.picks, stock.code],
  );
  const events = stock.decision_evidence?.events || [];
  const hardRiskTags = events.flatMap((event) => event.hard_tags || []);
  const reviewRiskTags = events.flatMap((event) => event.review_tags || []);
  const riskLine = hardRiskTags.length
    ? `重要风险 · ${Array.from(new Set(hardRiskTags)).map(riskTagLabel).join(" / ")}`
    : reviewRiskTags.length
      ? `需复核 · ${Array.from(new Set(reviewRiskTags)).map(riskTagLabel).join(" / ")}`
      : stock.ai_analysis?.risk || "通过 · 暂无已记录硬红线";
  const sector = stock.sector;
  const lastRow = kline.data?.data?.at(-1);
  const readoutDate = String(lastRow?.[0] || tradeDate || "—");
  const readoutClose = typeof lastRow?.[2] === "number" ? lastRow[2].toFixed(2) : stock.close.toFixed(2);

  const togglePanel = (next: Exclude<DetailPanel, null>) => setPanel((current) => current === next ? null : next);
  const toggleMa = (key: keyof typeof ma) => setMa((current) => ({ ...current, [key]: !current[key] }));
  const toggleOverlay = (key: keyof typeof overlays) => setOverlays((current) => ({ ...current, [key]: !current[key] }));

  return (
    <div className="q-candidate-detail">
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
        <section className="q-detail-section" aria-labelledby={`why-${stock.code}`}>
          <h3 id={`why-${stock.code}`}>为什么被选中</h3>
          <div className="q-reason-list">
            {stock.priority_score != null && (
              <div className="q-reason-row">
                <Icon icon="viewColumns" size="xsm" color="accent" label="优先级证据" />
                <strong>{stock.rank_label || "云阶候选"}</strong>
                <Badge variant="neutral" label={`证据 ${stock.evidence_grade || "—"}级`} />
                <span>综合优先级 {stock.priority_score.toFixed(1)}；云阶结构 {stock.structure_score?.toFixed(1) ?? "—"}，板块 {stock.sector_score?.toFixed(1) ?? "—"}，事件修正 {signed(stock.event_adjustment, 1)}。</span>
              </div>
            )}
            {(stock.signal_steps || []).map((step) => (
              <div className="q-reason-row" key={step.key}>
                <Icon icon="check" size="xsm" color="success" label={`${step.label}已通过`} />
                <strong>{step.label}</strong>
                <Badge variant="success" label="云阶条件" />
                <span>{step.detail}</span>
              </div>
            ))}
            {stock.ai_analysis && (
              <div className="q-reason-row">
                <Icon icon="checkDouble" size="xsm" color="accent" label="AI 已解释" />
                <strong>AI 解释</strong>
                <Badge variant="neutral" label="不改规则" />
                <span>{stock.ai_analysis.comment}</span>
              </div>
            )}
          </div>
        </section>

        <section className="q-detail-section" aria-labelledby={`resonance-${stock.code}`}>
          <h3 id={`resonance-${stock.code}`}>共振与主线</h3>
          <div className="q-resonance-row">
            <div><strong>行业热度</strong><b>{sector?.score != null ? Math.round(sector.score) : "—"}</b><span>{stageLabel(sector?.stage)}</span></div>
            <p>{sector ? `${stock.industry} 当前全市场第 ${sector.rank}/${sector.total}；3 日热度 ${signed(sector.delta3, 1, " 分")}。` : "行业热度产物尚未与当前快照绑定。"}</p>
            <span className="q-score-track"><span style={{ width: `${Math.min(Math.max(sector?.score || 0, 0), 100)}%` }} /></span>
          </div>
          <div className="q-resonance-row">
            <div><strong>板块广度</strong><b>{sector?.breadth_ma10 != null ? Math.round(sector.breadth_ma10) : "—"}</b><span>站上 MA10</span></div>
            <p>{sector?.breadth_ma10 != null ? `板块内站上 MA10 的成分股占比 ${sector.breadth_ma10.toFixed(1)}%。` : "当前板块广度数据待补全。"}</p>
            <span className="q-score-track"><span style={{ width: `${Math.min(Math.max(sector?.breadth_ma10 || 0, 0), 100)}%` }} /></span>
          </div>
        </section>

        <section className="q-detail-section" aria-labelledby={`news-${stock.code}`}>
          <div className="q-section-heading-row">
            <h3 id={`news-${stock.code}`}>消息面</h3>
            <span>{events.length ? `近 30 日 ${events.length} 条 · 利好 ${stock.event_counts?.positive || 0} · 利空 ${stock.event_counts?.negative || 0}` : stock.news_available === false ? "情报抓取部分失败" : "当前情报快照未收录事件"}</span>
          </div>
          {events.length ? (
            <div className="q-top-news">
              {events.slice(0, 3).map((event, index) => (
                <div key={event.event_id || `${event.title}-${index}`}>
                  <Badge variant={eventVariant(event)} label={eventLabel(event)} />
                  <span className="q-news-copy">
                    {event.source_url ? <a href={event.source_url} target="_blank" rel="noreferrer">{event.title}</a> : <strong>{event.title}</strong>}
                    <small>{event.source_name || event.source || "来源未记录"}{event.summary ? ` · ${event.summary}` : ""}</small>
                  </span>
                  <time>{eventTime(event.published_at)}</time>
                </div>
              ))}
            </div>
          ) : (
            <p className="q-muted-line">没有记录不代表没有利好或利空，只代表截至当前情报截止时间尚未收录。</p>
          )}
          {intelligenceCutoff && <p className="q-intelligence-cutoff">情报截止 {intelligenceCutoff.slice(0, 16).replace("T", " ")} · 推荐后出现的消息只进入后续复盘</p>}
        </section>

        <div className={`q-next-step q-next-step--${actionTone(stock)}`}>
          <div>
            <span>下一步</span>
            <strong>{stock.action_label} · {marketContext?.execution_mode || stock.action_detail}</strong>
            <p>云阶规则已完成突破确认；市场温度只调整执行强度，AI 只解释已落账证据。</p>
          </div>
          <div><span>证据与风险</span><strong>{stock.evidence_grade ? `${stock.evidence_grade}级 · ` : ""}{riskLine}</strong></div>
        </div>

        <div className="q-detail-links">
          <Button label={`全部新闻与公告 (${events.length})`} variant="ghost" size="sm" onClick={() => togglePanel("news")} />
          <Button label={`历史被选中记录 (${history.length})`} variant="ghost" size="sm" onClick={() => togglePanel("history")} />
          <Button label="同板块横向对比" variant="ghost" size="sm" onClick={() => togglePanel("peers")} />
        </div>

        {panel === "news" && (
          <div className="q-inline-panel">
            {events.length ? events.map((event, index) => (
              <article key={event.event_id || `${event.title}-${index}`}>
                <div><Badge variant={eventVariant(event)} label={eventLabel(event)} /><span>{event.source_name || event.source || "来源未记录"}</span><time>{event.published_at || "时间未记录"}</time></div>
                <strong>{event.title}</strong>
                {event.summary && <p>{event.summary}</p>}
                {event.source_url && <a href={event.source_url} target="_blank" rel="noreferrer">查看来源</a>}
              </article>
            )) : <p>当前没有已落账的新闻或公告。</p>}
          </div>
        )}

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
                <span>{peer.confirmation_count}</span><span>{peer.action === "buy" ? "买点" : peer.action === "avoid" ? "回避" : "观察"}</span>
              </div>
            )) : <p>当前板块没有可用的横向比较数据。</p>}
          </div>
        )}
      </div>
    </div>
  );
}

export function Component() {
  const recommend = useRecommend();
  const sectors = useSectors();
  const [openCode, setOpenCode] = useState<string | null | undefined>(undefined);
  const [showAll, setShowAll] = useState(false);
  const [filters, setFilters] = useState<Set<CandidateFilter>>(new Set());
  const [factorDrawerOpen, setFactorDrawerOpen] = useState(false);
  const [sectorStage, setSectorStage] = useState("全部");
  const [selectedSector, setSelectedSector] = useState<string | null>(null);

  const allCandidates = useMemo(
    () => recommend.data?.candidates || [],
    [recommend.data?.candidates],
  );
  const candidates = useMemo(
    () => allCandidates.filter((stock) => visibleByFilters(stock, filters)),
    [allCandidates, filters],
  );
  const sectorRows = useMemo<SectorDrawerRow[]>(() => {
    if (sectorStage === "接力") {
      const relay = sectors.data?.relay || [];
      return relay.map((sector, index) => ({
        ...sector,
        stage: "接力",
        trend: "flat",
        rank: index + 1,
        total: relay.length,
      }));
    }
    const rows: SectorDrawerRow[] = sectors.data?.ranking || sectors.data?.hot || [];
    if (sectorStage === "主线") {
      return rows.filter((sector) => sector.stage?.includes("主线") || sector.score >= 80);
    }
    return rows.filter((sector) => sectorStage === "全部" || sector.stage === sectorStage);
  }, [sectorStage, sectors.data?.hot, sectors.data?.ranking, sectors.data?.relay]);
  const leader = recommend.data?.sector_leader || sectorRows[0] || null;
  const activeSectorName = selectedSector || leader?.name || null;
  const activeSector = sectorRows.find((sector) => sector.name === activeSectorName) || leader;
  const sectorEvents = allCandidates
    .filter((stock) => stock.industry === activeSectorName)
    .flatMap((stock) => stock.decision_evidence?.events || []);

  const resolvedOpenCode = openCode === undefined
    ? candidates[0]?.code || null
    : openCode && !candidates.some((candidate) => candidate.code === openCode)
      ? candidates[0]?.code || null
      : openCode;

  const toggleFilter = (filter: CandidateFilter) => {
    setFilters((current) => {
      const next = new Set(current);
      if (next.has(filter)) next.delete(filter);
      else next.add(filter);
      return next;
    });
  };

  if (recommend.isLoading) {
    return <main className="q-decision-page"><Skeleton className="q-page-skeleton" /></main>;
  }
  if (recommend.error || !recommend.data?.available) {
    return (
      <main className="q-decision-page">
        <LoadError label="云阶决策暂不可用" onRetry={() => recommend.mutate()} />
      </main>
    );
  }

  const decision = recommend.data;
  const visibleCandidates = showAll ? candidates : candidates.slice(0, 6);
  const marketContext = decision.market_context;
  const intelligence = decision.intelligence;
  const eventTotals = allCandidates.reduce(
    (total, stock) => ({
      positive: total.positive + (stock.event_counts?.positive || 0),
      negative: total.negative + (stock.event_counts?.negative || 0),
    }),
    { positive: 0, negative: 0 },
  );
  const combinationStocks = (intelligence?.combination_codes || [])
    .map((code) => allCandidates.find((stock) => stock.code === code))
    .filter((stock): stock is RecommendStock => Boolean(stock));
  const aiStatus = decision.ai;
  const aiStatusText = aiStatus?.available
    ? `AI 已解释 · ${aiStatus.model || "模型已记录"}`
    : (aiStatus?.reason_codes || []).map((code) => aiReasonLabels[code] || code).join("、") || "AI 尚未生成解释";

  return (
    <main className="q-decision-page">
      <section className="q-decision-hero" aria-labelledby="today-count">
        <div className="q-count-line">
          <span>今日</span>
          <strong id="today-count">{candidates.length}</strong>
          <b>只符合</b>
          <time>{decision.trade_date} 收盘 · {decision.freshness?.fresh ? "数据就绪" : "数据需复核"}</time>
        </div>
        <p>{decision.core_factor?.plain || "第一波大涨 → 缩量横盘不破位 → 再次突破前高"}</p>
        <div className="q-temperature-strip" aria-label="云阶环境仪表盘">
          <div>
            <span>市场温度</span>
            <strong>{marketContext?.score != null ? Math.round(marketContext.score) : "—"}<small>/100</small></strong>
            <p>{marketContext?.state_label || "待补全"} · {marketContext?.execution_mode || "不影响云阶入选"}</p>
          </div>
          <div>
            <span>主线板块</span>
            <strong>{leader?.name || "待补全"}<small>{leader?.score != null ? Math.round(leader.score) : "—"}</small></strong>
            <p>{leader ? `第 ${leader.rank || 1}/${leader.total || sectors.data?.industries || "—"} · 3 日 ${signed(leader.delta3, 1, " 分")}` : "行业热度尚未就绪"}</p>
          </div>
          <div>
            <span>情报覆盖</span>
            <strong>{intelligence?.coverage ? `${intelligence.coverage.covered}/${intelligence.coverage.total}` : "—"}<small>只</small></strong>
            <p>利好 {eventTotals.positive} · 利空 {eventTotals.negative} · {intelligence?.available ? "已锁定截止时间" : "等待收盘情报任务"}</p>
          </div>
        </div>
        <div className="q-ai-status"><StatusDot variant={aiStatus?.available ? "success" : "warning"} label={aiStatusText} /><span>{aiStatusText}</span></div>
      </section>

      {combinationStocks.length > 1 && (
        <p className="q-combination-note">
          <strong>优先组合</strong>
          {combinationStocks.map((stock) => `${stock.name}（${stock.industry}）`).join(" + ")}
          <span>优先跨板块，避免把三只同板块股票误当成分散。</span>
        </p>
      )}

      <section className="q-candidate-list" aria-label="今日云阶候选">
        {visibleCandidates.length ? visibleCandidates.map((stock, index) => {
          const isOpen = resolvedOpenCode === stock.code;
          return (
            <div className={isOpen ? "q-candidate-card is-open" : "q-candidate-card"} key={stock.code}>
              <ClickableCard
                label={`${stock.name} ${stock.code}，${stock.action_label}`}
                padding={0}
                variant="default"
                onClick={() => setOpenCode(isOpen ? null : stock.code)}
                className="q-candidate-trigger"
              >
                <span className="q-candidate-rank">{index + 1}</span>
                <span className="q-candidate-copy">
                  <span><strong>{stock.name}</strong><code>{stock.code}</code>{stock.rank_label && <em>{stock.rank_label}</em>}</span>
                  <small>{intelligenceLine(stock)}</small>
                </span>
                <span className="q-candidate-price"><strong>{stock.close.toFixed(2)}</strong><em className={(stock.pct_change || 0) >= 0 ? "q-up" : "q-down"}>{signed(stock.pct_change, 2, "%")}</em></span>
                <Badge variant="error" label={stock.action_label} />
              </ClickableCard>
              {isOpen && <CandidateDetail stock={stock} tradeDate={decision.trade_date} marketContext={marketContext} intelligenceCutoff={intelligence?.cutoff_at} />}
            </div>
          );
        }) : (
          <div className="q-empty-state">
            <strong>{allCandidates.length ? "当前显示条件下没有候选" : "今天云阶没有选出股票"}</strong>
            <span>{allCandidates.length ? "清空下方筛选即可恢复全部云阶候选。" : "系统不会为了有票而降低云阶突破确认门槛。"}</span>
          </div>
        )}
        {candidates.length > 6 && (
          <Button width="100%" label={showAll ? "收起" : `还有 ${candidates.length - 6} 只 · 展开全部`} variant="secondary" onClick={() => setShowAll((value) => !value)} />
        )}
      </section>

      <section className="q-decision-drawers">
        <Collapsible
          isOpen={factorDrawerOpen}
          trigger={
            <span className="q-drawer-trigger-copy">
              <strong>调整因子</strong>
              <span>{filters.size} 个展示条件 · 云阶规则固定</span>
              <small>只过滤已命中的云阶，不重新选股</small>
            </span>
          }
          onOpenChange={setFactorDrawerOpen}
          className="q-drawer-shell q-filter-drawer"
        >
          <div className="q-filter-note">云阶三段条件是固定入选规则。以下选项只帮助收窄显示范围，不会改变买点结论。</div>
          <div className="q-filter-grid">
            <Badge variant="success" label="云阶三段结构固定" />
            {([
              ["sector", "行业主线 / 升温"],
              ["ai", "已有 AI 解释"],
              ["wave", "第一波涨幅 ≥ 30%"],
              ["heat", "行业热度 ≥ 60"],
              ["industry", "行业信息完整"],
            ] as Array<[CandidateFilter, string]>).map(([key, label]) => (
              <Button key={key} label={label} variant={filters.has(key) ? "primary" : "secondary"} size="sm" onClick={() => toggleFilter(key)} />
            ))}
            {filters.size > 0 && <Button label="清空" variant="ghost" size="sm" onClick={() => setFilters(new Set())} />}
          </div>
        </Collapsible>

        <Collapsible
          defaultIsOpen={false}
          trigger={
            <span className="q-drawer-trigger-copy">
              <strong>板块全景</strong>
              <span>{sectors.data?.industries || sectorRows.length} 个行业 · 当前主线 {leader?.name || "待补全"}</span>
              <small>点开看排名与已落账事件</small>
            </span>
          }
          className="q-drawer-shell"
        >
          <div className="q-sector-toolbar">
            {(["全部", "主线", "升温", "接力"] as const).map((stage) => (
              <Button key={stage} label={stage} size="sm" variant={sectorStage === stage ? "primary" : "ghost"} onClick={() => setSectorStage(stage)} />
            ))}
            <span>{sectorRows.length} / {sectors.data?.industries || sectorRows.length}</span>
          </div>
          <div className="q-sector-drawer-grid">
            <div className="q-sector-list">
              {sectorRows.map((sector, index) => (
                <ClickableCard
                  key={sector.name}
                  label={`${sector.name}，热度 ${sector.score}`}
                  padding={0}
                  variant={activeSectorName === sector.name ? "blue" : "default"}
                  onClick={() => setSelectedSector(sector.name)}
                  className="q-sector-row"
                >
                  <span>{typeof sector.rank === "number" ? sector.rank : index + 1}</span>
                  <span><strong>{sector.name}</strong><small>{stageLabel(sector.stage)}</small></span>
                  <MiniSectorSparkline values={sector.heat_series} trend={sector.trend} />
                  <span><b>{Math.round(sector.score)}</b><em className={(sector.delta3 ?? 0) >= 0 ? "q-up" : "q-down"}>{signed(sector.delta3, 1)}</em></span>
                </ClickableCard>
              ))}
            </div>
            <aside className="q-sector-evidence">
              <h3>{activeSector?.name || "板块"} · 已落账信息</h3>
              {activeSector && <p>热度 {Math.round(activeSector.score || 0)} · {stageLabel(activeSector.stage)} · 3 日 {signed(activeSector.delta3, 1, " 分")}</p>}
              {sectorEvents.length ? sectorEvents.slice(0, 5).map((event, index) => (
                <article key={event.event_id || `${event.title}-${index}`}><Badge variant="neutral" label="事件" /><span>{event.title}</span></article>
              )) : <p>当前决策账本没有收录该行业的事件。</p>}
            </aside>
          </div>
        </Collapsible>
      </section>

      <p className="q-disclaimer">研究工具，不构成投资建议。云阶规则决定入选；结构、板块和事件证据生成可追溯优先级，市场温度只调整执行强度；AI 只解释已落账事实，不增删候选。</p>
    </main>
  );
}
