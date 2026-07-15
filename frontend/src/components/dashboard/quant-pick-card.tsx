import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import {
  Check, ChevronDown, CircleMinus, ExternalLink, RefreshCw, ShieldAlert, ShieldCheck,
} from "lucide-react";
import { Skeleton, LoadError } from "@/components/ui";
import { useEvolutionStatus, useLatestDecision } from "@/lib/hooks";
import { useAppStore } from "@/lib/store";
import { duration } from "@/lib/tokens";
import type {
  DecisionAction, DecisionCandidate, DecisionModel, EvolutionStatus, SignalStock,
} from "@/lib/api";

const REASONS: Record<string, string> = {
  hierarchy_models_unvalidated: "市场/板块模型未通过样本外走查",
  no_rule_hits: "基础形态没有命中",
  market_gate: "大环境闸门未通过",
  sector_gate: "所属板块闸门未通过",
  stock_risk_veto: "个股风险模型否决",
  overnight_event_veto: "隔夜重大公告否决",
  overnight_event_review: "隔夜公告需要人工复核",
  overnight_source_missing: "盘前公告源不可用",
  unresolved_tie_over_3: "无法可靠区分多只并列标的",
  outside_top3: "未进入经验证的前三名",
  all_candidates_downgraded: "全部候选均被上层闸门降级",
};

const ACTION: Record<DecisionAction, { label: string; className: string }> = {
  buy: { label: "可执行", className: "bg-bull-dim text-bull" },
  observe: { label: "只观察", className: "bg-accent-dim text-accent" },
  avoid: { label: "回避", className: "bg-bear-dim text-bear" },
  none: { label: "空仓", className: "bg-inset text-ink-muted" },
};

const EVOLUTION_REASONS: Record<string, string> = {
  universe_coverage_insufficient: "股票覆盖仍不足",
  market_walk_forward_failed: "大环境层样本外未通过",
  sector_walk_forward_failed: "板块层样本外未通过",
  market_average_return_nonpositive: "大环境层收益仍为负",
  sector_average_return_nonpositive: "板块层收益仍为负",
  evolution_exception: "本轮训练失败，已保留原模型",
};

function EvolutionStrip({ evolution }: { evolution: EvolutionStatus }) {
  const promoted = evolution.promotion_status === "promoted";
  const coverage = Math.max(0, Math.min(100, evolution.coverage_ratio * 100));
  const reason = evolution.reason_codes
    .map((code) => EVOLUTION_REASONS[code])
    .filter(Boolean)
    .slice(0, 2)
    .join("；");
  return (
    <div className="mt-3 rounded-[10px] bg-inset px-3 py-2.5">
      <div className="flex items-center gap-2">
        <motion.span
          animate={{ rotate: promoted ? 360 : 0 }}
          transition={{ duration: duration.slow }}
          className={promoted ? "text-bull" : "text-ink-muted"}
        >
          <RefreshCw size={13} />
        </motion.span>
        <span className="text-[11px] font-semibold text-ink">每日进化</span>
        <span className={`ml-auto text-[10px] font-medium ${promoted ? "text-bull" : "text-ink-muted"}`}>
          {promoted ? "挑战模型已晋级" : "冠军模型保持不变"}
        </span>
      </div>
      <p className="mt-1.5 text-[10px] leading-relaxed text-ink-muted">
        覆盖 {evolution.covered_count}/{evolution.universe_count}（{coverage.toFixed(1)}%）
        {evolution.dataset_rows ? ` / 训练样本 ${evolution.dataset_rows}` : ""}
        {reason ? ` / ${reason}` : ""}
      </p>
    </div>
  );
}

function modelFor(models: DecisionModel[], key: string) {
  return models.find((model) => model.model_key === key);
}

function GateRail({ models }: { models: DecisionModel[] }) {
  const gates = [
    ["market", "1", "大环境"], ["sector", "2", "板块"],
    ["b1", "3", "B1主判"], ["execution", "4", "执行"],
  ] as const;
  const hierarchyActive = ["market", "sector", "risk"].every(
    (key) => modelFor(models, key)?.status === "active",
  );
  return (
    <div className="grid grid-cols-4 gap-1.5" aria-label="决策顺序">
      {gates.map(([key, no, label], index) => {
        const model = modelFor(models, key);
        const execution = key === "execution";
        const b1 = key === "b1";
        const passed = b1 ? true : execution ? hierarchyActive : model?.status === "active";
        return (
          <div key={key} className="relative min-w-0">
            {index < gates.length - 1 && (
              <div className={`absolute left-[56%] top-3 h-px w-[94%] ${passed ? "bg-bull/45" : "bg-border"}`} />
            )}
            <div className="relative flex flex-col items-center text-center">
              <span className={`grid h-6 w-6 place-items-center rounded-full border text-[10px] num ${
                passed ? "border-bull/50 bg-bull-dim text-bull" : "border-border bg-surface text-ink-muted"
              }`}>
                {passed ? <Check size={12} /> : no}
              </span>
              <span className="mt-1 text-[11px] font-medium text-ink-secondary">{label}</span>
              <span className={`text-[9px] ${passed ? "text-bull" : "text-ink-muted"}`}>
                {execution
                  ? hierarchyActive ? "成本已计入" : "未到执行层"
                  : b1 ? "候选入口"
                  : model?.status === "active" ? "已验证" : model?.status === "shadow" ? "影子观察" : "尚未验证"}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function toNav(list: DecisionCandidate[]): SignalStock[] {
  return list.map((item) => ({
    code: item.code, name: item.name, strategy: "hierarchical_decision",
    category: item.industry || "", close: item.baseline.close ?? 0, J: item.baseline.J ?? 0,
    volume_ratio: 0, market_cap: (item.baseline.cap_yi ?? 0) * 1e8,
    short_term_trend: 0, bull_bear_line: 0, reasons: item.reason_codes,
    similarity_score: null, matched_case: null, match_breakdown: null,
    industry: item.industry,
  }));
}

function Probability({ value, threshold }: { value?: number | null; threshold?: number | null }) {
  if (value == null) return <span className="text-ink-muted">未启用</span>;
  return (
    <span className={threshold != null && value >= threshold ? "text-bull" : "text-ink-muted"}>
      {(value * 100).toFixed(0)}%{threshold != null ? ` / 门槛 ${(threshold * 100).toFixed(0)}%` : ""}
    </span>
  );
}

function CandidateRow({ item, list }: { item: DecisionCandidate; list: DecisionCandidate[] }) {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const setStockNav = useAppStore((state) => state.setStockNav);
  const action = ACTION[item.action];
  return (
    <div className="border-t border-border/50 first:border-t-0">
      <div className="flex items-center gap-3 py-3">
        <button
          className="min-w-0 flex-1 text-left group"
          onClick={() => {
            setStockNav(toNav(list), list.findIndex((stock) => stock.code === item.code));
            navigate(`/stock/${item.code}`);
          }}
        >
          <div className="flex items-baseline gap-2">
            <span className="truncate text-sm font-semibold text-ink group-hover:text-accent transition-colors">
              {item.name}
            </span>
            <span className="font-mono text-[11px] text-ink-muted">{item.code}</span>
            <span className="ml-auto num text-sm text-ink">{item.baseline.close?.toFixed(2) ?? "-"}</span>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-2 text-[11px] text-ink-muted">
            <span>{item.industry || "未知板块"}</span>
            {item.sector?.score != null && <span className="num">板块热度 {Math.round(item.sector.score)}</span>}
            <span className="text-accent">B1主判</span>
            {(item.baseline.confirmation_count ?? 0) > 0 && <span>辅助确认 {item.baseline.confirmation_count}</span>}
            {item.reason_codes[0] && <span className="text-ink-secondary">{REASONS[item.reason_codes[0]] || item.reason_codes[0]}</span>}
          </div>
        </button>
        <span className={`shrink-0 rounded-full px-2 py-1 text-[10px] font-semibold ${action.className}`}>
          {action.label}
        </span>
        <button
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          aria-label={`查看${item.name}决策证据`}
          className="grid h-8 w-8 shrink-0 place-items-center rounded-lg text-ink-muted hover:bg-inset hover:text-ink transition-colors"
        >
          <motion.span animate={{ rotate: open ? 180 : 0 }} transition={{ duration: duration.fast }}>
            <ChevronDown size={15} />
          </motion.span>
        </button>
      </div>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }} transition={{ duration: duration.fast }}
            className="overflow-hidden"
          >
            <div className="mb-3 grid grid-cols-3 gap-2 rounded-xl bg-inset px-3 py-2.5 text-[10px] text-ink-muted">
              <div><p>大环境概率</p><p className="mt-0.5 num"><Probability value={item.market?.probability} threshold={item.market?.threshold} /></p></div>
              <div><p>板块概率</p><p className="mt-0.5 num"><Probability value={item.sector?.probability} threshold={item.sector?.threshold} /></p></div>
              <div><p>个股风险</p><p className="mt-0.5 num"><Probability value={item.stock?.risk_probability} threshold={item.stock?.risk_threshold} /></p></div>
              {item.events?.length > 0 && (
                <div className="col-span-3 border-t border-border/50 pt-2">
                  {item.events.map((event) => event.source_url ? (
                    <a key={event.event_id} href={event.source_url} target="_blank" rel="noreferrer" className="flex items-start gap-1 text-accent hover:underline">
                      <ExternalLink size={10} className="mt-0.5 shrink-0" />{event.title}
                    </a>
                  ) : <p key={event.event_id}>{event.title}</p>)}
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export function QuantPickCard() {
  const [showAllCandidates, setShowAllCandidates] = useState(false);
  const { data, isLoading, error, mutate } = useLatestDecision();
  const { data: evolutionResponse } = useEvolutionStatus();
  if (isLoading) return <Skeleton className="h-32 w-full rounded-[14px]" />;
  if (error) return <LoadError label="分层决策加载失败" onRetry={() => mutate()} />;
  if (!data?.available) {
    const stale = data?.reason === "stale_market_data";
    return (
      <div className="card-modern p-4">
        <div className="flex items-start gap-2">
          <ShieldAlert size={16} className="mt-0.5 shrink-0 text-accent" />
          <div>
            <p className="text-sm font-semibold text-ink">{stale ? "行情过期，已停止推荐" : "决策尚未生成"}</p>
            <p className="mt-1 text-xs leading-relaxed text-ink-muted">
              {stale
                ? `本地数据只到 ${data.freshness?.local_date ?? "未知"}，应至少更新到 ${data.freshness?.expected_date ?? "最近交易日"}。为避免拿旧行情冒充今天，系统不会展示任何股票。`
                : data?.reason ?? "数据准备中"}
            </p>
          </div>
        </div>
      </div>
    );
  }

  const action = ACTION[data.final_action ?? "none"];
  const candidates = data.candidates ?? [];
  const visibleCandidates = showAllCandidates ? candidates : candidates.slice(0, 5);
  const buys = candidates.filter((item) => item.action === "buy");
  const models = data.models ?? [];
  const degraded = data.status === "degraded" || models.some((model) => ["market", "sector"].includes(model.model_key) && model.status !== "active");
  const reasonText = data.reason_codes?.length
    ? data.reason_codes.map((code) => REASONS[code] || code).join("；")
    : "上层环境没有给出足够胜率";

  return (
    <motion.section
      initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
      transition={{ duration: duration.normal }} className="card-modern overflow-hidden"
      data-testid="hierarchical-decision"
    >
      <div className={`border-l-2 px-4 py-4 sm:px-5 ${buys.length ? "border-bull" : "border-accent"}`}>
        <div className="flex items-start gap-3">
          <div className={`mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-[10px] ${buys.length ? "bg-bull-dim text-bull" : "bg-accent-dim text-accent"}`}>
            {buys.length ? <ShieldCheck size={18} /> : <CircleMinus size={18} />}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-lg font-semibold tracking-[-0.03em] text-ink">{buys.length ? `今天可执行 ${buys.length} 只` : "今天不出手"}</h2>
              <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${action.className}`}>{action.label}</span>
            </div>
            <p className="mt-1 text-xs leading-relaxed text-ink-secondary">{buys.length ? "候选已通过大环境、板块与 B1 主判。" : `${reasonText}，候选仅保留观察。`}</p>
            <p className="mt-2 text-[10px] text-ink-muted">{data.market?.decision_for_date ? `${data.market.decision_for_date} 计划` : "下一交易日计划"} / {data.trade_date} 收盘数据</p>
          </div>
        </div>
      </div>

      <div className="border-t border-border px-4 py-3 sm:px-5">
        <div className="mb-1 flex items-center justify-between gap-3">
          <h3 className="text-xs font-semibold text-ink">{buys.length ? "可执行名单" : "观察名单"}</h3>
          <span className="num text-[10px] text-ink-muted">{candidates.length} 只</span>
        </div>
        {candidates.length ? (
          <>
            <div className="reveal-list">
              {visibleCandidates.map((item) => <CandidateRow key={item.code} item={item} list={candidates} />)}
            </div>
            {candidates.length > 5 && (
              <button onClick={() => setShowAllCandidates((value) => !value)} className="flex w-full items-center justify-center gap-2 border-t border-border py-3 text-xs font-medium text-accent hover:text-accent-hover">
                {showAllCandidates ? "收起观察名单" : `还有 ${candidates.length - 5} 只，查看全部`}
                <ChevronDown size={14} className={`transition-transform ${showAllCandidates ? "rotate-180" : ""}`} />
              </button>
            )}
          </>
        ) : <p className="py-4 text-xs text-ink-muted">没有 B1 候选，保持空仓。</p>}
      </div>

      <details className="border-t border-border px-4 py-3 text-[10px] text-ink-muted sm:px-5">
        <summary className="cursor-pointer select-none font-medium text-ink-secondary hover:text-ink">查看判定依据</summary>
        <div className="mt-4"><GateRail models={models} /></div>
        <div className="mt-4 rounded-[10px] bg-inset px-3 py-2.5 leading-relaxed">
          <p>大环境看收益、上涨家数、成交额、跌停占比与均线位置。</p>
          <p className="mt-1">板块看相对强弱、广度、成交占比、波动分散度和有效成分股数。</p>
          {degraded && <p className="mt-1 text-accent">当前市场或板块模型尚未通过样本外验证，因此自动降级。</p>}
        </div>
        {evolutionResponse?.available && evolutionResponse.data && <EvolutionStrip evolution={evolutionResponse.data} />}
        <details className="mt-3">
          <summary className="cursor-pointer hover:text-ink-secondary">版本与审计信息</summary>
          <div className="mt-2 space-y-1 break-all font-mono"><p>run {data.run_id}</p><p>strategy {data.strategy_version}</p><p>feature {data.feature_version}</p><p>model {data.model_version}</p><p>data {data.data_version}</p></div>
        </details>
      </details>
    </motion.section>
  );
}
