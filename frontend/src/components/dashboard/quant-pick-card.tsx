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
  buy: { label: "买入", className: "text-bull" },
  observe: { label: "观察", className: "text-accent" },
  avoid: { label: "回避", className: "text-bear" },
  none: { label: "空仓", className: "text-ink-muted" },
};

function modelFor(models: DecisionModel[], key: string) {
  return models.find((model) => model.model_key === key);
}

function modelState(model?: DecisionModel) {
  if (model?.status === "active") return "通过";
  if (model?.status === "shadow") return "观察中";
  return "未通过";
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

  return (
    <button
      onClick={() => {
        setStockNav(toNav(list), list.findIndex((stock) => stock.code === item.code));
        navigate(`/stock/${item.code}`);
      }}
      className="grid min-h-16 w-full grid-cols-[1fr_auto] items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-surface-hover active:bg-inset"
    >
      <span className="min-w-0">
        <span className="flex items-baseline gap-2">
          <span className="truncate text-[15px] font-semibold text-ink">{item.name}</span>
          <span className="font-mono text-[10px] text-ink-muted">{item.code}</span>
        </span>
        <span className="mt-1 flex min-w-0 items-center gap-2 text-[11px] text-ink-muted">
          <span className="truncate">{item.industry || "未知板块"}</span>
          {item.sector?.score != null && <span className="num shrink-0">{Math.round(item.sector.score)} 分</span>}
          <span className="shrink-0 text-ink-secondary">{signal}</span>
        </span>
      </span>
      <span className="text-right">
        <span className="num block text-sm text-ink">{item.baseline.close?.toFixed(2) ?? "-"}</span>
        <span className={`mt-1 block text-[11px] font-medium ${action.className}`}>{action.label}</span>
      </span>
    </button>
  );
}

function EvolutionStrip({ evolution }: { evolution: EvolutionStatus }) {
  const promoted = evolution.promotion_status === "promoted";
  return (
    <div className="mt-3 rounded-[10px] bg-inset px-3 py-2.5 text-[11px] text-ink-muted">
      <div className="flex items-center gap-2">
        <RefreshCw size={13} />
        <span className="font-medium text-ink-secondary">每日学习</span>
        <span className="ml-auto">{promoted ? "新模型已启用" : "继续使用原模型"}</span>
      </div>
      <p className="mt-1.5">已覆盖 {evolution.covered_count}/{evolution.universe_count}，训练样本 {evolution.dataset_rows} 条。</p>
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
            <p className="text-sm font-semibold text-ink">{stale ? "行情未更新，暂停选股" : "今天还没有结果"}</p>
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
  const canBuy = buys.length > 0;
  const decisionTitle = canBuy ? `今天可以买 ${buys.length} 只` : "今天不买";
  const decisionNote = canBuy
    ? "下面标红的股票通过了大环境、板块和 B1。"
    : "大环境或板块没有通过，B1 信号只观察。";

  return (
    <motion.section
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: duration.normal }}
      className="overflow-hidden card-modern"
      data-testid="hierarchical-decision"
    >
      <div className={`border-l-2 px-4 py-4 ${canBuy ? "border-bull" : "border-accent"}`}>
        <div className="flex items-start gap-3">
          <div className={`mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-[10px] ${canBuy ? "bg-bull-dim text-bull" : "bg-accent-dim text-accent"}`}>
            {canBuy ? <ShieldCheck size={18} /> : <CircleMinus size={18} />}
          </div>
          <div>
            <h2 className="text-xl font-semibold tracking-[-0.03em] text-ink">{decisionTitle}</h2>
            <p className="mt-1 text-xs leading-relaxed text-ink-secondary">{decisionNote}</p>
            <p className="mt-2 text-[10px] text-ink-muted">{data.market?.decision_for_date ?? "下一交易日"}计划，使用 {data.trade_date} 收盘数据</p>
          </div>
        </div>
      </div>

      <div className="flex items-center justify-between border-t border-border px-4 py-3">
        <h3 className="text-sm font-semibold text-ink">B1 股票</h3>
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

      <details className="border-t border-border px-4 py-3 text-[11px] text-ink-muted">
        <summary className="cursor-pointer select-none font-medium text-ink-secondary hover:text-ink">为什么</summary>
        <div className="mt-3 space-y-2 rounded-[10px] bg-inset px-3 py-3">
          <div className="flex justify-between"><span>大环境</span><span>{modelState(modelFor(models, "market"))}</span></div>
          <div className="flex justify-between"><span>板块</span><span>{modelState(modelFor(models, "sector"))}</span></div>
          <div className="flex justify-between"><span>B1 信号</span><span>{candidates.length} 只</span></div>
        </div>
        {evolutionResponse?.available && evolutionResponse.data && <EvolutionStrip evolution={evolutionResponse.data} />}
      </details>
    </motion.section>
  );
}
