import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { ChevronDown, CircleMinus, RefreshCw, ShieldAlert, ShieldCheck } from "lucide-react";
import { LoadError, Skeleton } from "@/components/ui";
import { useEvolutionStatus, useLatestDecision } from "@/lib/hooks";
import { useAppStore } from "@/lib/store";
import { duration } from "@/lib/tokens";
import type { DecisionAction, DecisionCandidate, DecisionModel, EvolutionStatus, SignalStock } from "@/lib/api";

const ACTION: Record<DecisionAction, { label: string; className: string }> = {
  buy: { label: "通过复核", className: "text-bull" },
  observe: { label: "研究候选", className: "text-accent" },
  avoid: { label: "未通过", className: "text-bear" },
  none: { label: "无信号", className: "text-ink-muted" },
};

function modelFor(models: DecisionModel[], key: string) {
  return models.find((model) => model.model_key === key);
}

function modelState(model: DecisionModel | undefined, mode?: "off" | "shadow" | "active") {
  if (mode) return layerState(mode);
  if (model?.mode === "active" || model?.status === "active") return "已启用";
  if (model?.mode === "shadow" || model?.status === "shadow") return "影子验证";
  return "未启用";
}

function layerState(mode?: "off" | "shadow" | "active") {
  if (mode === "active") return "已启用";
  if (mode === "shadow") return "影子验证";
  return "未启用";
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

function CandidateRow({ item, list }: { item: DecisionCandidate; list: DecisionCandidate[] }) {
  const navigate = useNavigate();
  const setStockNav = useAppStore((state) => state.setStockNav);
  const action = ACTION[item.action];
  const signal = item.baseline.signal_labels?.[0] ?? "B1";
  const weekly = item.baseline.weekly;
  const weeklyLines = (["MA5", "MA10", "MA20", "MA60"] as const).map((line) => ({
    line,
    rising: weekly?.directions?.[line],
  }));
  const hasWeeklyDirections = weeklyLines.every(({ rising }) => rising != null);

  return (
    <button
      onClick={() => {
        setStockNav(toNav(list), list.findIndex((stock) => stock.code === item.code));
        navigate(`/stock/${item.code}`);
      }}
      className="grid min-h-[112px] w-full grid-cols-[1fr_auto] items-start gap-3 px-5 py-4 text-left transition-colors duration-200 hover:bg-surface-hover active:bg-inset focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent"
    >
      <span className="min-w-0">
        <span className="flex items-baseline gap-2">
          <span className="truncate text-base font-semibold tracking-[-0.01em] text-ink">{item.name}</span>
          <span className="font-mono text-[11px] text-ink-muted">{item.code}</span>
        </span>
        <span className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
          <span><span className="text-ink-muted">收盘 </span><span className="num font-medium text-ink">{item.baseline.close?.toFixed(2) ?? "--"}</span></span>
          <span><span className="text-ink-muted">J </span><span className="num font-medium text-ink">{item.baseline.J?.toFixed(2) ?? "--"}</span></span>
          <span><span className="text-ink-muted">板块 </span><span className="num text-ink-secondary">{item.sector?.score != null ? `${Math.round(item.sector.score)} 分` : "--"}</span></span>
        </span>
        <span className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
          <span className="text-ink-muted">周线至今</span>
          {hasWeeklyDirections ? weeklyLines.map(({ line, rising }) => (
            <span key={line} className={rising ? "text-bull" : "text-bear"}>{line}{rising ? "↑" : "↓"}</span>
          )) : <span className="text-ink-secondary">历史数据不足</span>}
          {hasWeeklyDirections && <span className="text-ink-secondary">{weekly?.rising_count ?? 0}/4 向上</span>}
          {hasWeeklyDirections && <span className={weekly?.aligned ? "text-bull" : "text-ink-muted"}>{weekly?.aligned ? "多头排列" : "未多头"}</span>}
          {weekly?.gate_mode === "shadow" && (
            <span className="text-ink-muted">影子门槛，不影响当前结果</span>
          )}
        </span>
        <span className="mt-2 flex min-w-0 items-center gap-2 text-xs text-ink-muted">
          <span className="truncate">{item.industry || "未知板块"}</span>
          <span className="shrink-0 text-ink-secondary">{signal}</span>
        </span>
      </span>
      <span className={`mt-0.5 rounded-full border border-current/25 px-2 py-1 text-xs font-medium ${action.className}`}>
        {action.label}
      </span>
    </button>
  );
}

function EvolutionStrip({ evolution }: { evolution: EvolutionStatus }) {
  const promoted = evolution.promotion_status === "promoted";
  const completed = ["buy", "observe", "avoid"].reduce((total, key) => {
    const item = evolution.outcomes?.[key as "buy" | "observe" | "avoid"];
    return total + (item?.count ?? 0);
  }, 0);
  const coveragePercent = Math.round(evolution.coverage_ratio * 100);
  const validationState = promoted
    ? "新模型已启用"
    : evolution.coverage_ratio < 0.6
      ? "数据覆盖不足，已暂停训练"
      : evolution.reason_codes.includes("reference_history_insufficient")
        ? "时点快照积累中，训练未启动"
        : "挑战模型尚未通过验证";
  return (
    <div className="mt-3 rounded-[10px] bg-inset px-3 py-2.5 text-[11px] text-ink-muted">
      <div className="flex items-center gap-2">
        <RefreshCw size={13} />
        <span className="font-medium text-ink-secondary">验证进度</span>
        <span className="ml-auto">{validationState}</span>
      </div>
      <p className="mt-1.5">
        行情覆盖 {evolution.covered_count}/{evolution.universe_count}（{coveragePercent}%），
        可训练样本 {evolution.dataset_rows} 条，已完成结果 {completed} 条。
      </p>
    </div>
  );
}

export function QuantPickCard() {
  const [showAll, setShowAll] = useState(false);
  const { data, isLoading, error, mutate } = useLatestDecision();
  const { data: evolutionResponse } = useEvolutionStatus();

  if (isLoading) return <Skeleton className="h-48 w-full rounded-[14px]" />;
  if (error) return <LoadError label="今日B1加载失败" onRetry={() => mutate()} />;
  if (!data?.available) {
    const stale = data?.reason === "stale_market_data";
    return (
      <div className="card-modern p-4">
        <div className="flex items-start gap-2">
          <ShieldAlert size={16} className="mt-0.5 shrink-0 text-accent" />
          <div>
            <p className="text-sm font-semibold text-ink">{stale ? "行情未更新，暂无可回放决策" : "今天还没有结果"}</p>
            <p className="mt-1 text-xs leading-relaxed text-ink-muted">
              {stale ? `当前数据到 ${data?.freshness?.local_date ?? "未知"}，更新后再显示。` : data?.reason ?? "数据准备中"}
            </p>
          </div>
        </div>
      </div>
    );
  }

  const candidates = data.candidates ?? [];
  const buys = candidates.filter((item) => item.action === "buy");
  const visible = showAll ? candidates : candidates.slice(0, 5);
  const models = data.models ?? [];
  const hasApproved = buys.length > 0;
  const decisionTitle = hasApproved
    ? `通过复核 ${buys.length} 只`
    : candidates.length
      ? `研究候选 ${candidates.length} 只`
      : "今日无 B1 信号";
  const decisionNote = hasApproved
    ? "候选已通过当前启用的策略门禁，仍需结合自身风险承受能力判断。"
    : candidates.length
      ? "B1 信号已记录，未验证模型和周线影子门槛不会被包装成买入结论。"
      : "当前规则没有产生候选，系统不会用模型补造股票。";

  return (
    <motion.section
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: duration.normal }}
      className="decision-panel"
      data-testid="hierarchical-decision"
    >
      {data.is_stale && (
        <div className="border-b border-accent/25 bg-accent-dim px-5 py-3 text-xs text-ink-secondary" role="status">
          正在回放最近一次有效决策。行情截至 {data.freshness?.local_date ?? data.trade_date ?? "未知"}，
          当前应更新到 {data.freshness?.expected_date ?? "最新交易日"}。
        </div>
      )}
      <div className="px-5 py-5">
        <div className="flex items-start gap-3">
          <div className={`mt-0.5 grid h-10 w-10 shrink-0 place-items-center rounded-[10px] ${hasApproved ? "bg-bull-dim text-bull" : "bg-accent-dim text-accent"}`}>
            {hasApproved ? <ShieldCheck size={18} /> : <CircleMinus size={18} />}
          </div>
          <div>
            <p className="section-kicker">策略决策</p>
            <h2 className="mt-1.5 text-[26px] font-semibold tracking-[-0.04em] text-ink">{decisionTitle}</h2>
            <p className="mt-2 text-sm leading-relaxed text-ink-secondary">{decisionNote}</p>
            <p className="mt-3 text-xs text-ink-muted">
              面向 {data.market?.decision_for_date ?? "下一交易日"}，基于 {data.trade_date} 收盘数据
            </p>
          </div>
        </div>
      </div>

      <div className="flex items-center justify-between border-t border-border bg-inset px-5 py-3.5">
        <h3 className="text-sm font-semibold text-ink">候选证据</h3>
        <span className="num text-xs text-ink-muted">{candidates.length} 只</span>
      </div>
      {candidates.length ? (
        <>
          <div className="reveal-list divide-y divide-border/60">{visible.map((item) => <CandidateRow key={item.code} item={item} list={candidates} />)}</div>
          {candidates.length > 5 && (
            <button onClick={() => setShowAll((value) => !value)} className="flex w-full items-center justify-center gap-2 border-t border-border px-4 py-3 text-xs font-medium text-accent hover:bg-surface-hover active:bg-inset">
              {showAll ? "收起" : `查看全部 ${candidates.length} 只`}
              <ChevronDown size={14} className={`transition-transform ${showAll ? "rotate-180" : ""}`} />
            </button>
          )}
        </>
      ) : <p className="border-t border-border px-4 py-5 text-sm text-ink-muted">今天没有 B1 信号。</p>}

      <details className="border-t border-border px-5 py-3.5 text-xs text-ink-muted">
        <summary className="cursor-pointer select-none font-medium text-ink-secondary hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">决策依据</summary>
        <div className="mt-3 space-y-2 rounded-[10px] bg-inset px-3 py-3">
          <div className="flex justify-between"><span>周线四均线</span><span>{layerState(data.market?.layer_modes?.weekly_four_ma)}</span></div>
          <div className="flex justify-between"><span>大环境</span><span>{modelState(modelFor(models, "market"), data.market?.layer_modes?.market)}</span></div>
          <div className="flex justify-between"><span>板块</span><span>{modelState(modelFor(models, "sector"), data.market?.layer_modes?.sector)}</span></div>
          <div className="flex justify-between"><span>B1 信号</span><span>{candidates.length} 只</span></div>
        </div>
        {evolutionResponse?.available && evolutionResponse.data && <EvolutionStrip evolution={evolutionResponse.data} />}
      </details>
    </motion.section>
  );
}
