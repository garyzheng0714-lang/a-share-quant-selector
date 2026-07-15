import { useState } from "react";
import { ChevronDown, ChevronRight, CircleGauge, Database, TrendingDown, TrendingUp } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { PageTransition } from "@/components/layout/page-transition";
import { LoadError, Skeleton } from "@/components/ui";
import { useCoverage, useSectors, useSuperB1, useThermometer } from "@/lib/hooks";
import type { SectorHot, SectorRelay, SectorsData } from "@/lib/api";

type RankingItem = NonNullable<SectorsData["ranking"]>[number];

function Trend({ trend, delta }: { trend: "up" | "down" | "flat"; delta: number }) {
  const Icon = trend === "down" ? TrendingDown : TrendingUp;
  if (trend === "flat") return <span className="num text-xs text-ink-muted">持平</span>;
  return (
    <span className={`inline-flex items-center gap-1 num text-xs ${trend === "up" ? "text-bull" : "text-bear"}`}>
      <Icon size={13} />{delta > 0 ? "+" : ""}{Math.round(delta)}
    </span>
  );
}

function PrimarySector({ item, b1, onOpen }: { item: SectorHot; b1: number; onOpen: () => void }) {
  return (
    <button onClick={onOpen} className="card-hero group min-h-44 w-full p-5 text-left transition-transform active:scale-[0.99]">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-medium text-accent">当前主线</p>
          <h2 className="mt-2 text-2xl font-semibold tracking-[-0.04em] text-ink group-hover:text-accent-light">{item.name}</h2>
        </div>
        <div className="text-right">
          <p className="num text-4xl font-semibold tracking-[-0.05em] text-ink">{Math.round(item.score)}</p>
          <p className="mt-1 text-[10px] text-ink-muted">热度</p>
        </div>
      </div>
      <div className="mt-6 grid grid-cols-3 gap-3 border-t border-border pt-4 text-xs">
        <div><p className="text-ink-muted">3日变化</p><div className="mt-1"><Trend trend={item.trend} delta={item.delta3} /></div></div>
        <div><p className="text-ink-muted">MA10广度</p><p className="mt-1 num text-ink">{item.breadth_ma10 ?? "-"}%</p></div>
        <div><p className="text-ink-muted">B1候选</p><p className={`mt-1 num ${b1 > 0 ? "text-bull" : "text-ink"}`}>{b1} 只</p></div>
      </div>
    </button>
  );
}

function SecondarySector({ item, b1, onOpen }: { item: SectorHot; b1: number; onOpen: () => void }) {
  return (
    <button onClick={onOpen} className="flex w-full items-center gap-4 rounded-[10px] px-3 py-3 text-left transition-colors hover:bg-surface-hover active:scale-[0.99]">
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-ink">{item.name}</p>
        <p className="mt-1 text-[11px] text-ink-muted">{item.stage} / B1 {b1} 只</p>
      </div>
      <Trend trend={item.trend} delta={item.delta3} />
      <span className="num w-8 text-right text-lg font-semibold text-ink">{Math.round(item.score)}</span>
      <ChevronRight size={15} className="text-ink-muted" />
    </button>
  );
}

function RelaySector({ item, onOpen }: { item: SectorRelay; onOpen: () => void }) {
  return (
    <button onClick={onOpen} className="group flex w-full items-start gap-3 rounded-[10px] bg-inset px-3 py-3 text-left transition-colors hover:bg-surface-hover active:scale-[0.99]">
      <span className="num min-w-8 text-xl font-semibold text-accent-light">{Math.round(item.score)}</span>
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-medium text-ink">{item.name}</span>
        <span className="mt-1 block truncate text-[11px] text-ink-muted">{item.reasons.slice(0, 2).join(" / ")}</span>
      </span>
      <ChevronRight size={15} className="mt-1 text-ink-muted group-hover:text-ink" />
    </button>
  );
}

function RankingRow({ item, b1, onOpen }: { item: RankingItem; b1: number; onOpen: () => void }) {
  return (
    <button onClick={onOpen} className="grid min-h-13 w-full grid-cols-[32px_1fr_48px_24px] items-center gap-2 px-3 text-left transition-colors hover:bg-surface-hover active:bg-inset sm:grid-cols-[40px_1fr_90px_64px_56px_24px]">
      <span className={`num text-xs ${item.rank <= 3 ? "font-semibold text-accent" : "text-ink-muted"}`}>{item.rank}</span>
      <div className="min-w-0">
        <p className="truncate text-sm font-medium text-ink">{item.name}</p>
        <p className="mt-0.5 text-[10px] text-ink-muted sm:hidden">{item.stage} / B1 {b1}</p>
      </div>
      <span className="hidden text-xs text-ink-secondary sm:block">{item.stage}</span>
      <span className="hidden sm:block"><Trend trend={item.trend} delta={item.delta3} /></span>
      <span className="num text-right text-sm font-semibold text-ink">{Math.round(item.score)}</span>
      <span className={`hidden num text-right text-xs sm:block ${b1 > 0 ? "text-bull" : "text-ink-muted"}`}>{b1}</span>
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

  if (sectors.isLoading) {
    return <div className="mx-auto max-w-6xl px-4 py-6"><Skeleton className="h-32 w-full rounded-[14px]" /></div>;
  }
  if (sectors.error) return <LoadError label="板块排名加载失败" onRetry={() => sectors.mutate()} />;

  const data = sectors.data;
  const ranking = data?.ranking ?? [];
  const leaders = (data?.hot ?? []).slice(0, 3);
  const relays = (data?.relay ?? []).slice(0, 3);
  const b1Counts = (b1?.hits ?? []).reduce<Record<string, number>>((out, row) => {
    if (row.industry) out[row.industry] = (out[row.industry] ?? 0) + 1;
    return out;
  }, {});
  const visibleRanking = showAll ? ranking : ranking.slice(0, 12);
  const openSector = (name: string) => navigate(`/sectors/${encodeURIComponent(name)}`);

  return (
    <PageTransition>
      <div className="mx-auto max-w-6xl px-4 py-5 sm:px-6 sm:py-8">
        <header className="mb-5 flex items-end justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-[-0.04em] text-ink">板块</h1>
            <p className="mt-1 text-sm text-ink-muted">先定方向，再找 B1</p>
          </div>
          <p className="num text-xs text-ink-muted">{data?.trade_date ?? "待更新"} 收盘</p>
        </header>

        <section className="mb-4 flex items-start gap-3 rounded-[14px] border border-border bg-surface px-4 py-3" aria-label="大环境结论">
          <CircleGauge size={18} className="mt-0.5 shrink-0 text-accent" />
          <div className="min-w-0">
            <p className="text-xs font-semibold text-ink">今天先看环境</p>
            <p className="mt-1 text-xs leading-relaxed text-ink-secondary">{thermometer.data?.conclusion ?? "正在读取市场广度、趋势和成交热度"}</p>
          </div>
        </section>

        {!data?.available || leaders.length === 0 ? (
          <div className="card-modern p-5 text-sm text-ink-muted">{data?.reason ?? "板块数据尚未生成"}</div>
        ) : (
          <>
            <section className="grid gap-3 lg:grid-cols-[1.2fr_0.8fr]" aria-label="主线板块">
              <PrimarySector item={leaders[0]} b1={b1Counts[leaders[0].name] ?? 0} onOpen={() => openSector(leaders[0].name)} />
              <div className="card-modern p-2">
                <p className="px-3 pb-1 pt-2 text-xs font-semibold text-ink-secondary">次强板块</p>
                {leaders.slice(1).map((item) => <SecondarySector key={item.name} item={item} b1={b1Counts[item.name] ?? 0} onOpen={() => openSector(item.name)} />)}
              </div>
            </section>

            <section className="mt-4 card-modern p-4" aria-label="接力观察">
              <div className="mb-3 flex items-baseline justify-between gap-3">
                <div><h2 className="text-sm font-semibold text-ink">接力观察</h2><p className="mt-1 text-[11px] text-ink-muted">尚未过热，但强度和资金正在改善</p></div>
                <span className="text-[10px] text-ink-muted">潜力分</span>
              </div>
              {relays.length ? <div className="grid gap-2 md:grid-cols-3">{relays.map((item) => <RelaySector key={item.name} item={item} onOpen={() => openSector(item.name)} />)}</div> : <p className="py-2 text-xs text-ink-muted">今天没有满足条件的接力板块</p>}
            </section>
          </>
        )}

        {ranking.length > 0 && (
          <section className="mt-5 overflow-hidden card-modern" aria-label="全部板块排名">
            <div className="flex items-center justify-between border-b border-border px-4 py-3">
              <div><h2 className="text-sm font-semibold text-ink">全部板块</h2><p className="mt-0.5 text-[10px] text-ink-muted">按当前热度排序，点击查看板块内个股</p></div>
              <span className="num text-xs text-ink-muted">{ranking.length} 个</span>
            </div>
            <div className="grid grid-cols-[32px_1fr_48px_24px] gap-2 border-b border-border px-3 py-2 text-[10px] text-ink-muted sm:grid-cols-[40px_1fr_90px_64px_56px_24px]"><span>#</span><span>板块</span><span className="hidden sm:block">阶段</span><span className="hidden sm:block">3日</span><span className="text-right">热度</span><span className="hidden text-right sm:block">B1</span></div>
            <div className="reveal-list divide-y divide-border/60">{visibleRanking.map((item) => <RankingRow key={item.name} item={item} b1={b1Counts[item.name] ?? 0} onOpen={() => openSector(item.name)} />)}</div>
            {ranking.length > 12 && <button onClick={() => setShowAll((value) => !value)} className="flex w-full items-center justify-center gap-2 border-t border-border px-4 py-3 text-xs font-medium text-accent transition-colors hover:bg-surface-hover active:bg-inset">{showAll ? "收起" : `查看全部 ${ranking.length} 个`}<ChevronDown size={14} className={`transition-transform ${showAll ? "rotate-180" : ""}`} /></button>}
          </section>
        )}

        {coverage && (
          <details className="mt-4 text-[11px] text-ink-muted">
            <summary className="flex cursor-pointer list-none items-center gap-2 py-2 hover:text-ink-secondary"><Database size={13} />数据覆盖 {coverage.covered_count}/{coverage.universe_count}</summary>
            <p className="pb-2 pl-5">可训练 {coverage.trainable_count}/{coverage.trainable_eligible_count}，次新股 {coverage.short_history_count} 只单列。</p>
          </details>
        )}
      </div>
    </PageTransition>
  );
}
