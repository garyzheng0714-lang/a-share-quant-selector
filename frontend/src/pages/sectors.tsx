import { useState } from "react";
import { ChevronDown, ChevronRight, Database } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { PageTransition } from "@/components/layout/page-transition";
import { LoadError, Skeleton } from "@/components/ui";
import { useCoverage, useSectors, useSuperB1, useThermometer } from "@/lib/hooks";
import type { SectorsData } from "@/lib/api";

type RankingItem = NonNullable<SectorsData["ranking"]>[number];
type FocusItem = { name: string; score: number; label: "主线" | "接力" };

function FocusRow({ item, index, b1, onOpen }: { item: FocusItem; index: number; b1: number; onOpen: () => void }) {
  return (
    <button onClick={onOpen} className="grid min-h-16 w-full grid-cols-[28px_1fr_auto_18px] items-center gap-3 px-4 text-left transition-colors hover:bg-surface-hover active:bg-inset">
      <span className={`num text-sm font-semibold ${index < 3 ? "text-accent" : "text-ink-muted"}`}>{index + 1}</span>
      <span className="min-w-0">
        <span className="block truncate text-[15px] font-semibold text-ink">{item.name}</span>
        <span className="mt-1 block text-[11px] text-ink-muted">{item.label}{b1 > 0 ? `，B1 ${b1} 只` : ""}</span>
      </span>
      <span className="num text-lg font-semibold text-ink">{Math.round(item.score)}</span>
      <ChevronRight size={15} className="text-ink-muted" />
    </button>
  );
}

function RankingRow({ item, b1, onOpen }: { item: RankingItem; b1: number; onOpen: () => void }) {
  return (
    <button onClick={onOpen} className="grid min-h-14 w-full grid-cols-[28px_1fr_auto_18px] items-center gap-3 px-4 text-left transition-colors hover:bg-surface-hover active:bg-inset">
      <span className="num text-xs text-ink-muted">{item.rank}</span>
      <span className="min-w-0">
        <span className="block truncate text-sm font-medium text-ink">{item.name}</span>
        {b1 > 0 && <span className="mt-0.5 block text-[10px] text-bull">B1 {b1} 只</span>}
      </span>
      <span className="num text-sm text-ink-secondary">{Math.round(item.score)}</span>
      <ChevronRight size={14} className="text-ink-muted" />
    </button>
  );
}

export function Component() {
  const [showAll, setShowAll] = useState(false);
  const navigate = useNavigate();
  const sectors = useSectors();
  const thermometer = useThermometer();
  const { data: b1 } = useSuperB1();
  const { data: coverage } = useCoverage();

  if (sectors.isLoading) return <div className="mx-auto max-w-4xl px-4 py-6"><Skeleton className="h-48 w-full rounded-[14px]" /></div>;
  if (sectors.error) return <LoadError label="板块加载失败" onRetry={() => sectors.mutate()} />;

  const data = sectors.data;
  const ranking = data?.ranking ?? [];
  const leaders: FocusItem[] = (data?.hot ?? []).slice(0, 3).map((item) => ({ name: item.name, score: item.score, label: "主线" }));
  const leaderNames = new Set(leaders.map((item) => item.name));
  const relays: FocusItem[] = (data?.relay ?? []).filter((item) => !leaderNames.has(item.name)).slice(0, 2).map((item) => ({ name: item.name, score: item.score, label: "接力" }));
  const focus = [...leaders, ...relays];
  const b1Counts = (b1?.hits ?? []).reduce<Record<string, number>>((out, row) => {
    if (row.industry) out[row.industry] = (out[row.industry] ?? 0) + 1;
    return out;
  }, {});
  const openSector = (name: string) => navigate(`/sectors/${encodeURIComponent(name)}`);
  const signal = thermometer.data?.signal;
  const marketTitle = signal === "caution" ? "今天少动" : signal === "opportunity" ? "今天可做" : "只做强板块";
  const marketNote = signal === "caution"
    ? "市场胜率偏低，只看不追。"
    : signal === "opportunity"
      ? "环境允许出手，优先下面的强板块。"
      : "环境一般，只做强板块里的 B1。";

  return (
    <PageTransition>
      <div className="mx-auto max-w-4xl px-4 py-5 sm:px-6 sm:py-8">
        <header className="mb-5 flex items-end justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-[-0.04em] text-ink">板块</h1>
            <p className="mt-1 text-sm text-ink-muted">先选板块，再选股票</p>
          </div>
          <p className="num text-xs text-ink-muted">{data?.trade_date ?? "待更新"}</p>
        </header>

        <section className={`mb-4 rounded-[14px] border-l-2 bg-surface px-4 py-4 ${signal === "opportunity" ? "border-bull" : "border-accent"}`}>
          <h2 className="text-xl font-semibold tracking-[-0.03em] text-ink">{marketTitle}</h2>
          <p className="mt-1 text-sm text-ink-secondary">{marketNote}</p>
          <details className="mt-2 text-[11px] text-ink-muted">
            <summary className="cursor-pointer list-none hover:text-ink-secondary">查看市场依据</summary>
            <p className="mt-2 leading-relaxed">{thermometer.data?.conclusion ?? "市场数据正在计算"}</p>
          </details>
        </section>

        <section className="overflow-hidden card-modern">
          <div className="flex items-center justify-between px-4 py-3">
            <h2 className="text-sm font-semibold text-ink">今天先看</h2>
            <span className="text-[10px] text-ink-muted">强度</span>
          </div>
          {data?.available && focus.length ? (
            <div className="divide-y divide-border/60">{focus.map((item, index) => <FocusRow key={`${item.label}-${item.name}`} item={item} index={index} b1={b1Counts[item.name] ?? 0} onOpen={() => openSector(item.name)} />)}</div>
          ) : <p className="border-t border-border px-4 py-5 text-sm text-ink-muted">{data?.reason ?? "今天没有重点板块"}</p>}
        </section>

        {ranking.length > 0 && (
          <section className="mt-4 overflow-hidden card-modern">
            <button onClick={() => setShowAll((value) => !value)} className="flex w-full items-center justify-between px-4 py-3 text-left transition-colors hover:bg-surface-hover active:bg-inset">
              <span className="text-sm font-medium text-ink-secondary">全部板块</span>
              <span className="flex items-center gap-2 text-xs text-ink-muted">{ranking.length} 个<ChevronDown size={14} className={`transition-transform ${showAll ? "rotate-180" : ""}`} /></span>
            </button>
            {showAll && <div className="reveal-list divide-y divide-border/60 border-t border-border">{ranking.map((item) => <RankingRow key={item.name} item={item} b1={b1Counts[item.name] ?? 0} onOpen={() => openSector(item.name)} />)}</div>}
          </section>
        )}

        {coverage && (
          <details className="mt-4 px-1 py-2 text-[11px] text-ink-muted">
            <summary className="flex cursor-pointer list-none items-center gap-2 hover:text-ink-secondary"><Database size={13} />数据 {coverage.covered_count}/{coverage.universe_count}</summary>
            <p className="mt-2 pl-5">可训练 {coverage.trainable_count}/{coverage.trainable_eligible_count}，次新股 {coverage.short_history_count} 只单列。</p>
          </details>
        )}
      </div>
    </PageTransition>
  );
}
