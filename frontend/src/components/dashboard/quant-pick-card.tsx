import { useState, type ReactNode } from "react";
import { useNavigate } from "@/lib/spa-router";
import { Button } from "@astryxdesign/core/Button";
import { Collapsible } from "@astryxdesign/core/Collapsible";
import { Icon } from "@astryxdesign/core/Icon";
import { LoadError, Skeleton } from "@/components/ui";
import { useEvolutionStatus, useLatestDecision } from "@/lib/hooks";
import { useAppStore } from "@/lib/store";
import type {
  DecisionAction,
  DecisionCandidate,
  DecisionModel,
  EvolutionStatus,
  SignalStock,
} from "@/lib/api";

const ACTION: Record<DecisionAction, { label: string; className: string; dotClassName: string }> = {
  buy: { label: "通过复核", className: "text-bull", dotClassName: "bg-bull" },
  observe: { label: "研究候选", className: "text-accent", dotClassName: "bg-accent" },
  avoid: { label: "未通过", className: "text-bear", dotClassName: "bg-bear" },
  none: { label: "无信号", className: "text-ink-muted", dotClassName: "bg-ink-muted" },
};

function modelFor(models: DecisionModel[], key: string) {
  return models.find((model) => model.model_key === key);
}

function layerState(mode?: "off" | "shadow" | "active") {
  if (mode === "active") return "已启用";
  if (mode === "shadow") return "影子验证";
  return "未启用";
}

function layerTone(mode?: "off" | "shadow" | "active") {
  if (mode === "active") return "text-bear";
  if (mode === "shadow") return "text-accent";
  return "text-ink-muted";
}

function modelState(model: DecisionModel | undefined, mode?: "off" | "shadow" | "active") {
  if (mode) return layerState(mode);
  if (model?.mode === "active" || model?.status === "active") return "已启用";
  if (model?.mode === "shadow" || model?.status === "shadow") return "影子验证";
  return "未验证，当前不启用";
}

function toNav(list: DecisionCandidate[]): SignalStock[] {
  return list.map((item) => ({
    code: item.code,
    name: item.name,
    strategy: "hierarchical_decision",
    category: item.industry || "",
    close: item.baseline.close ?? 0,
    J: item.baseline.J ?? 0,
    volume_ratio: 0,
    market_cap: (item.baseline.cap_yi ?? 0) * 1e8,
    short_term_trend: 0,
    bull_bear_line: 0,
    reasons: item.baseline.signal_labels ?? [],
    similarity_score: null,
    matched_case: null,
    match_breakdown: null,
    industry: item.industry,
  }));
}

function CandidateStatus({ action }: { action: DecisionAction }) {
  const meta = ACTION[action];
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap text-xs font-medium ${meta.className}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${meta.dotClassName}`} aria-hidden="true" />
      {meta.label}
    </span>
  );
}

function CandidateRow({ item, list }: { item: DecisionCandidate; list: DecisionCandidate[] }) {
  const navigate = useNavigate();
  const setStockNav = useAppStore((state) => state.setStockNav);
  const signal = item.baseline.signal_labels?.[0] ?? "B1";
  const weekly = item.baseline.weekly;
  const weeklyLines = (["MA5", "MA10", "MA20", "MA60"] as const).map((line) => ({
    line,
    rising: weekly?.directions?.[line],
  }));
  const hasWeeklyDirections = weeklyLines.every(({ rising }) => rising != null);
  const weeklyLabel = hasWeeklyDirections
    ? `${weekly?.rising_count ?? 0}/4 向上 · ${weekly?.aligned ? "多头排列" : "未多头"}`
    : "历史数据不足";
  const close = item.baseline.close?.toFixed(2) ?? "--";
  const j = item.baseline.J?.toFixed(2) ?? "--";
  const sector = item.sector?.score != null ? Math.round(item.sector.score).toString() : "--";
  const action = ACTION[item.action];

  const openStock = () => {
    setStockNav(toNav(list), list.findIndex((stock) => stock.code === item.code));
    navigate(`/stock/${item.code}`);
  };

  return (
    <Button
      label={`${item.name} ${item.code}，查看 K 线`}
      variant="ghost"
      width="100%"
      onClick={openStock}
      aria-label={`${item.name} ${item.code}，收盘 ${close}，J ${j}，板块 ${sector}，${weeklyLabel}，${action.label}，查看 K 线`}
      className="group w-full border-b border-border/70 px-4 py-4 text-left transition-colors last:border-b-0 hover:bg-surface-hover focus-visible:relative focus-visible:z-10 sm:px-5 md:py-0"
    >
      <span className="block md:hidden">
        <span className="flex items-start justify-between gap-3">
          <span className="min-w-0">
            <span className="block truncate text-sm font-semibold text-ink">{item.name}</span>
            <span className="mt-0.5 block font-mono text-[10px] text-ink-muted">{item.code}</span>
          </span>
          <CandidateStatus action={item.action} />
        </span>
        <span className="mt-3 grid grid-cols-3 gap-x-3 gap-y-2 text-xs">
          <span><span className="block text-[10px] text-ink-muted">收盘</span><span className="num mt-0.5 block text-ink">{close}</span></span>
          <span><span className="block text-[10px] text-ink-muted">J</span><span className="num mt-0.5 block text-ink">{j}</span></span>
          <span><span className="block text-[10px] text-ink-muted">板块</span><span className="num mt-0.5 block text-ink">{sector}</span></span>
          <span className="col-span-3 flex min-w-0 items-center gap-2 text-ink-muted">
            <span className="truncate">{item.industry || "未分类"}</span>
            <span className="shrink-0 text-ink-secondary">{signal}</span>
            <span className="ml-auto shrink-0 text-ink-secondary">{weeklyLabel}</span>
          </span>
        </span>
      </span>

      <span className="hidden min-h-[82px] grid-cols-[minmax(160px,1.4fr)_72px_68px_80px_minmax(180px,1.25fr)_96px_20px] items-center gap-3 md:grid">
        <span className="min-w-0">
          <span className="flex items-baseline gap-2">
            <span className="truncate text-sm font-semibold text-ink">{item.name}</span>
            <span className="shrink-0 font-mono text-[10px] text-ink-muted">{item.code}</span>
          </span>
          <span className="mt-1 flex min-w-0 items-center gap-2 text-[11px] text-ink-muted">
            <span className="truncate">{item.industry || "未分类"}</span>
            <span className="shrink-0 text-ink-secondary">{signal}</span>
          </span>
        </span>
        <span className="num text-sm font-medium text-ink">{close}</span>
        <span className="num text-sm text-ink-secondary">{j}</span>
        <span className="num text-sm text-ink-secondary">{sector}</span>
        <span className="min-w-0">
          <span className="block text-xs text-ink-secondary">{weeklyLabel}</span>
          <span className="mt-1 block truncate text-[10px] text-ink-muted">
            {weekly?.gate_mode === "shadow" ? "影子门槛，不影响当前结果" : "四周线均线证据"}
          </span>
        </span>
        <CandidateStatus action={item.action} />
        <Icon icon="externalLink" size="xsm" color="secondary" />
      </span>
    </Button>
  );
}

function EvolutionSummary({ evolution }: { evolution: EvolutionStatus }) {
  const coveragePercent = Math.max(0, Math.min(100, Math.round(evolution.coverage_ratio * 100)));
  const promoted = evolution.promotion_status === "promoted";
  const status = promoted
    ? "挑战模型已通过发布门槛"
    : evolution.coverage_ratio < 0.6
      ? "数据覆盖不足，保持既有策略"
      : evolution.reason_codes.includes("reference_history_insufficient")
        ? "时点快照仍在积累"
        : "挑战模型尚未通过验证";

  return (
    <div className="py-4">
      <div className="flex items-center justify-between gap-3 text-xs">
        <span className="font-medium text-ink-secondary">验证进度</span>
        <span className="num text-ink">{coveragePercent}%</span>
      </div>
      <div
        className="mt-2 h-1.5 overflow-hidden rounded-full bg-inset"
        role="progressbar"
        aria-label="行情数据覆盖率"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={coveragePercent}
      >
        <span className="block h-full rounded-full bg-accent" style={{ width: `${coveragePercent}%` }} />
      </div>
      <p className="mt-2 text-xs leading-relaxed text-ink-muted">{status}</p>
      <p className="mt-1 text-[10px] leading-relaxed text-ink-muted">
        覆盖 {evolution.covered_count}/{evolution.universe_count} 只，可训练样本 {evolution.dataset_rows} 条。
      </p>
    </div>
  );
}

function EvidenceRow({
  icon,
  label,
  value,
  hint,
  valueClassName = "text-ink-secondary",
}: {
  icon: ReactNode;
  label: string;
  value: string;
  hint: string;
  valueClassName?: string;
}) {
  return (
    <div className="border-b border-border/70 py-4 last:border-b-0">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 text-ink-muted" aria-hidden="true">{icon}</span>
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
            <span className="text-xs font-medium text-ink-secondary">{label}</span>
            <span className={`text-xs font-medium ${valueClassName}`}>{value}</span>
          </span>
          <span className="mt-1.5 block text-[11px] leading-relaxed text-ink-muted">{hint}</span>
        </span>
      </div>
    </div>
  );
}

export function QuantPickCard() {
  const [showAll, setShowAll] = useState(false);
  const { data, isLoading, error, mutate } = useLatestDecision();
  const { data: evolutionResponse } = useEvolutionStatus();

  if (isLoading) {
    return (
      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_320px]">
        <Skeleton className="h-[520px] w-full rounded-[10px]" />
        <Skeleton className="h-[420px] w-full rounded-[10px]" />
      </div>
    );
  }

  if (error) {
    return (
      <section className="workspace-panel" aria-label="B1 决策加载失败">
        <LoadError label="B1 决策加载失败" onRetry={() => mutate()} />
      </section>
    );
  }

  if (!data?.available) {
    const stale = data?.reason === "stale_market_data";
    return (
      <section className="workspace-panel p-5" aria-labelledby="decision-unavailable-title">
        <div className="flex items-start gap-3">
          <Icon icon="warning" size="sm" color="accent" />
          <div>
            <h2 id="decision-unavailable-title" className="text-sm font-semibold text-ink">
              {stale ? "行情未更新，暂无可回放决策" : "当前没有可用决策"}
            </h2>
            <p className="mt-1 text-xs leading-relaxed text-ink-muted">
              {stale ? `当前数据截至 ${data?.freshness?.local_date ?? "未知"}，请在行情更新后重试。` : data?.reason ?? "数据准备中"}
            </p>
          </div>
        </div>
      </section>
    );
  }

  const candidates = data.candidates ?? [];
  const buys = candidates.filter((item) => item.action === "buy");
  const visible = showAll ? candidates : candidates.slice(0, 8);
  const models = data.models ?? [];
  const hasApproved = buys.length > 0;
  const decisionTitle = hasApproved
    ? `通过复核 ${buys.length} 只`
    : candidates.length
      ? `研究候选 ${candidates.length} 只`
      : "当前无 B1 信号";
  const decisionNote = hasApproved
    ? "候选已通过当前启用的策略门槛，仍需结合自身风险承受能力判断。"
    : candidates.length
      ? "B1 信号已记录，未验证模型和周线影子门槛不会被包装成买入结论。"
      : "当前规则没有产生候选，系统不会用模型补造股票。";
  const weeklyMode = data.market?.layer_modes?.weekly_four_ma;
  const marketMode = data.market?.layer_modes?.market;
  const sectorMode = data.market?.layer_modes?.sector;
  const localDate = data.freshness?.local_date ?? data.trade_date ?? "未知";
  const expectedDate = data.freshness?.expected_date;

  return (
    <section className="grid items-start gap-3 lg:grid-cols-[minmax(0,1fr)_320px] xl:grid-cols-[minmax(0,1fr)_360px]" data-testid="hierarchical-decision">
      <div className="workspace-panel overflow-hidden">
        {data.is_stale && (
          <div className="border-b border-accent/25 bg-accent-dim px-4 py-3 text-xs leading-relaxed text-ink-secondary sm:px-5" role="status">
            正在回放最近一次有效决策。行情截至 <span className="num text-ink">{localDate}</span>
            {expectedDate ? <>，当前应更新到 <span className="num text-ink">{expectedDate}</span></> : null}。
          </div>
        )}

        <div className="px-4 py-5 sm:px-5 sm:py-6">
          <div className="flex items-start gap-3">
            <div className={`mt-0.5 grid h-10 w-10 shrink-0 place-items-center rounded-lg ${hasApproved ? "bg-bull-dim text-bull" : "bg-accent-dim text-accent"}`}>
              {hasApproved ? <Icon icon="success" size="sm" /> : <Icon icon="stop" size="sm" />}
            </div>
            <div className="min-w-0">
              <p className="section-kicker">策略决策</p>
              <h2 className="mt-1.5 text-2xl font-semibold tracking-[-0.04em] text-ink">{decisionTitle}</h2>
              <p className="mt-2 max-w-3xl text-sm leading-relaxed text-ink-secondary">{decisionNote}</p>
              <p className="mt-3 text-xs text-ink-muted">
                面向 <span className="num text-ink-secondary">{data.market?.decision_for_date ?? "下一交易日"}</span>，
                基于 <span className="num text-ink-secondary">{data.trade_date}</span> 收盘数据
              </p>
            </div>
          </div>
        </div>

        <div className="flex items-end justify-between border-y border-border bg-inset px-4 py-3 sm:px-5">
          <div>
            <h3 className="text-sm font-semibold text-ink">候选比较</h3>
            <p className="mt-1 text-[10px] text-ink-muted">点击任意一行打开个股 K 线并保留候选顺序</p>
          </div>
          <span className="num text-xs text-ink-muted">{candidates.length} 只</span>
        </div>

        {candidates.length ? (
          <>
            <div className="hidden min-h-9 grid-cols-[minmax(160px,1.4fr)_72px_68px_80px_minmax(180px,1.25fr)_96px_20px] items-center gap-3 border-b border-border bg-canvas/35 px-5 text-[10px] text-ink-muted md:grid" aria-hidden="true">
              <span>代码 / 名称</span><span>收盘</span><span>J</span><span>板块</span><span>周线证据</span><span>状态</span><span />
            </div>
            <div>{visible.map((item) => <CandidateRow key={item.code} item={item} list={candidates} />)}</div>
            {candidates.length > 8 && (
              <Button
                label={showAll ? "收起多余候选" : `查看全部 ${candidates.length} 只`}
                variant="ghost"
                width="100%"
                onClick={() => setShowAll((value) => !value)}
                aria-expanded={showAll}
                className="flex min-h-11 w-full items-center justify-center gap-2 border-t border-border px-4 text-xs font-medium text-accent transition-colors hover:bg-surface-hover"
              >
                {showAll ? "收起多余候选" : `查看全部 ${candidates.length} 只`}
                <Icon icon="chevronDown" size="xsm" />
              </Button>
            )}
          </>
        ) : (
          <p className="px-5 py-8 text-sm text-ink-muted">当前规则没有产生 B1 候选。</p>
        )}
      </div>

      <aside className="workspace-panel self-start px-4 sm:px-5 lg:sticky lg:top-20" aria-labelledby="decision-evidence-title">
        <div className="border-b border-border py-4">
          <h2 id="decision-evidence-title" className="text-base font-semibold text-ink">决策依据</h2>
          <p className="mt-1 text-[11px] leading-relaxed text-ink-muted">只展示真实的启用状态与可追溯证据。</p>
        </div>

        <EvidenceRow
          icon={<Icon icon="clock" size="sm" />}
          label="数据时点"
          value={data.is_stale ? "数据过期" : "数据就绪"}
          valueClassName={data.is_stale ? "text-bull" : "text-bear"}
          hint={data.is_stale && expectedDate ? `${localDate} 收盘；当前应更新到 ${expectedDate}。` : `${localDate} 收盘数据。`}
        />
        <EvidenceRow
          icon={<Icon icon="viewColumns" size="sm" />}
          label="周线四均线"
          value={layerState(weeklyMode)}
          valueClassName={layerTone(weeklyMode)}
          hint={weeklyMode === "shadow" ? "只记录影子结果，不影响当前决策。" : "按当前完整策略记录。"}
        />
        <EvidenceRow
          icon={<Icon icon="viewColumns" size="sm" />}
          label="市场模型"
          value={modelState(modelFor(models, "market"), marketMode)}
          valueClassName={layerTone(marketMode)}
          hint="未通过样本外验证时，不参与生产策略。"
        />
        <EvidenceRow
          icon={<Icon icon="viewColumns" size="sm" />}
          label="板块模型"
          value={modelState(modelFor(models, "sector"), sectorMode)}
          valueClassName={layerTone(sectorMode)}
          hint="板块热度是研究特征，不单独构成买入理由。"
        />

        {evolutionResponse?.available && evolutionResponse.data ? (
          <EvolutionSummary evolution={evolutionResponse.data} />
        ) : (
          <p className="border-b border-border/70 py-4 text-xs text-ink-muted">当前没有可用的模型验证记录。</p>
        )}

        <Collapsible className="border-t border-border py-3 text-xs text-ink-muted" trigger="版本与可追溯记录">
          <dl className="mt-2 grid gap-2 rounded-md bg-inset p-3 text-[11px]">
            <div className="grid grid-cols-[72px_minmax(0,1fr)] gap-2"><dt>策略版本</dt><dd className="break-all text-ink-secondary">{data.strategy_version ?? "未记录"}</dd></div>
            <div className="grid grid-cols-[72px_minmax(0,1fr)] gap-2"><dt>模型版本</dt><dd className="break-all text-ink-secondary">{data.model_version ?? "未记录"}</dd></div>
            <div className="grid grid-cols-[72px_minmax(0,1fr)] gap-2"><dt>决策 run</dt><dd className="break-all text-ink-secondary">{data.run_id ?? "未记录"}</dd></div>
            <div className="grid grid-cols-[72px_minmax(0,1fr)] gap-2"><dt>来源记录</dt><dd className="text-ink-secondary">{data.source_refs?.length ?? 0} 条</dd></div>
          </dl>
        </Collapsible>

        <p className="border-t border-border py-4 text-[11px] leading-relaxed text-ink-muted">
          研究工具，不构成投资建议。任何决策都需要结合自身风险承受能力独立判断。
        </p>
      </aside>
    </section>
  );
}
