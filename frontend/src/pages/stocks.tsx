import { Database, RefreshCw } from "lucide-react";
import { PageTransition } from "@/components/layout/page-transition";
import { QuantPickCard } from "@/components/dashboard/quant-pick-card";
import { SuperB1Card } from "@/components/today/super-b1-card";
import { useCoverage } from "@/lib/hooks";

export function Component() {
  const { data: coverage } = useCoverage();
  return (
    <PageTransition>
      <div className="mx-auto max-w-3xl px-4 py-6 lg:px-8 lg:py-10">
        <header className="mb-5">
          <p className="text-xs font-medium text-accent">B1 主判</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-ink">个股决策排名</h1>
          <p className="mt-2 text-sm leading-relaxed text-ink-muted">排序固定遵守：大环境 → 板块 → B1形态 → 辅助确认 → 风险否决。</p>
        </header>
        {coverage && (
          <div className="mb-4 rounded-2xl border border-border bg-surface px-4 py-3">
            <div className="flex items-center gap-2 text-xs text-ink-secondary">
              {coverage.running ? <RefreshCw size={14} className="animate-spin text-accent" /> : <Database size={14} className="text-ink-muted" />}
              <span>全量数据底座</span><span className="ml-auto num">{(coverage.coverage_ratio * 100).toFixed(1)}%</span>
            </div>
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-inset"><div className="h-full rounded-full bg-accent transition-[width] duration-300" style={{ width: `${coverage.coverage_ratio * 100}%` }} /></div>
            <p className="mt-2 text-[10px] leading-relaxed text-ink-muted">行情 {coverage.covered_count}/{coverage.universe_count} · 可训练 {coverage.trainable_count}/{coverage.trainable_eligible_count} · 次新股 {coverage.short_history_count} 只单列，不冒充缺数</p>
          </div>
        )}
        <QuantPickCard />
        <section className="mt-5">
          <h2 className="mb-3 text-sm font-semibold text-ink">B1 原始命中池</h2>
          <SuperB1Card />
        </section>
      </div>
    </PageTransition>
  );
}
