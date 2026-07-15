import { motion } from "framer-motion";
import { ChevronRight, CircleGauge, Database, TrendingDown, TrendingUp } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { PageTransition } from "@/components/layout/page-transition";
import { SectorRotationCard } from "@/components/dashboard/sector-rotation-card";
import { LoadError, Skeleton } from "@/components/ui";
import { useCoverage, useSectors, useSuperB1, useThermometer } from "@/lib/hooks";

function direction(trend: "up" | "down" | "flat") {
  if (trend === "up") return <TrendingUp size={13} className="text-bull" />;
  if (trend === "down") return <TrendingDown size={13} className="text-bear" />;
  return <span className="h-px w-3 bg-ink-muted" />;
}

export function Component() {
  const navigate = useNavigate();
  const sectors = useSectors();
  const thermometer = useThermometer();
  const { data: b1 } = useSuperB1();
  const { data: coverage } = useCoverage();

  if (sectors.isLoading) {
    return <div className="mx-auto max-w-5xl px-4 py-6"><Skeleton className="h-[520px] w-full rounded-2xl" /></div>;
  }
  if (sectors.error) {
    return <LoadError label="板块排名加载失败" onRetry={() => sectors.mutate()} />;
  }

  const data = sectors.data;
  const ranking = data?.ranking ?? [];
  const b1Counts = (b1?.hits ?? []).reduce<Record<string, number>>((out, row) => {
    if (row.industry) out[row.industry] = (out[row.industry] ?? 0) + 1;
    return out;
  }, {});

  return (
    <PageTransition>
      <div className="mx-auto max-w-5xl px-4 py-6 lg:px-8 lg:py-10">
        <header className="mb-5 grid gap-3 lg:grid-cols-[1fr_320px]">
          <div>
            <p className="text-xs font-medium text-accent">先看环境，再看板块</p>
            <h1 className="mt-1 text-2xl font-semibold tracking-tight text-ink">板块强弱排名</h1>
            <p className="mt-2 max-w-2xl text-sm leading-relaxed text-ink-muted">
              大盘决定仓位，板块决定方向。高分但退潮的板块不会因为绝对热度高就排成买点。
            </p>
          </div>
          <div className="rounded-2xl border border-border bg-surface px-4 py-3">
            <div className="flex items-center gap-2 text-xs font-semibold text-ink">
              <CircleGauge size={15} className="text-accent" />大环境
              <span className="ml-auto num text-ink-muted">{data?.trade_date ?? "待更新"}</span>
            </div>
            <p className="mt-2 text-xs leading-relaxed text-ink-secondary">
              {thermometer.data?.conclusion ?? "正在读取市场广度、趋势和成交热度。"}
            </p>
          </div>
        </header>

        {coverage && (
          <div className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-1 rounded-xl border border-border/70 bg-inset px-3 py-2 text-[11px] text-ink-muted">
            <Database size={13} className={coverage.running ? "text-accent" : "text-ink-muted"} />
            <span>行情覆盖 <b className="num text-ink-secondary">{coverage.covered_count}/{coverage.universe_count}</b></span>
            <span>可训练 <b className="num text-ink-secondary">{coverage.trainable_count}/{coverage.trainable_eligible_count}</b></span>
            <span>{coverage.running ? `后台补齐中，剩余 ${coverage.remaining_count} 只` : "全量回补待命"}</span>
          </div>
        )}

        {data?.available && (
          <section className="mb-5" aria-label="板块风向明细">
            <SectorRotationCard />
          </section>
        )}

        {!data?.available || ranking.length === 0 ? (
          <div className="card-modern p-5 text-sm text-ink-muted">{data?.reason ?? "板块数据尚未生成"}</div>
        ) : (
          <section className="overflow-hidden rounded-2xl border border-border bg-surface" aria-label="板块排名">
            <div className="grid grid-cols-[38px_1fr_64px_64px_28px] items-center gap-2 border-b border-border px-3 py-2 text-[10px] text-ink-muted sm:grid-cols-[44px_1fr_100px_80px_80px_32px]">
              <span>排名</span><span>板块</span><span className="hidden sm:block">阶段</span>
              <span className="text-right">热度</span><span className="hidden text-right sm:block">B1</span><span />
            </div>
            <div className="divide-y divide-border/60">
              {ranking.map((item, index) => (
                <motion.button
                  key={item.name}
                  initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: Math.min(index, 10) * 0.025 }}
                  onClick={() => navigate(`/sectors/${encodeURIComponent(item.name)}`)}
                  className="grid min-h-14 w-full grid-cols-[38px_1fr_64px_28px] items-center gap-2 px-3 text-left transition-colors duration-200 hover:bg-surface-hover active:bg-inset sm:grid-cols-[44px_1fr_100px_80px_80px_32px]"
                >
                  <span className={`num text-sm ${item.rank <= 3 ? "font-semibold text-accent" : "text-ink-muted"}`}>{item.rank}</span>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2"><span className="truncate text-sm font-medium text-ink">{item.name}</span>{direction(item.trend)}</div>
                    <span className="text-[10px] text-ink-muted sm:hidden">{item.stage} · B1 {b1Counts[item.name] ?? 0}</span>
                  </div>
                  <span className="hidden text-xs text-ink-secondary sm:block">{item.stage}</span>
                  <span className="num text-right text-sm font-semibold text-ink">{Math.round(item.score)}</span>
                  <span className={`hidden num text-right text-xs sm:block ${(b1Counts[item.name] ?? 0) > 0 ? "text-bull" : "text-ink-muted"}`}>{b1Counts[item.name] ?? 0}</span>
                  <ChevronRight size={16} className="text-ink-muted" />
                </motion.button>
              ))}
            </div>
          </section>
        )}
      </div>
    </PageTransition>
  );
}
