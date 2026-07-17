import { useState } from "react";
import { Database, SlidersHorizontal, Target } from "lucide-react";
import { PageTransition } from "@/components/layout/page-transition";
import { QuantPickCard } from "@/components/dashboard/quant-pick-card";
import { FactorWorkbench } from "@/components/today/factor-workbench";
import { useCoverage } from "@/lib/hooks";

type View = "decision" | "research";

function CoverageDetails() {
  const { data: coverage } = useCoverage();

  if (!coverage) return <p className="mt-2 pl-5 text-ink-muted">正在读取覆盖率…</p>;

  return (
    <p className="mt-2 pl-5 leading-relaxed">
      已覆盖 {coverage.covered_count}/{coverage.universe_count}，可训练 {coverage.trainable_count}/{coverage.trainable_eligible_count}，次新股 {coverage.short_history_count} 只单列。
      {coverage.running ? `后台仍在补齐 ${coverage.remaining_count} 只。` : "当前回补任务已结束。"}
    </p>
  );
}

export function Component() {
  const [view, setView] = useState<View>("decision");
  const [coverageOpen, setCoverageOpen] = useState(false);

  return (
    <PageTransition>
      <div className="mx-auto max-w-4xl px-4 py-7 sm:px-6 sm:py-10">
        <header className="mb-6">
          <h1 className="text-[28px] font-semibold tracking-[-0.045em] text-ink">个股</h1>
          <p className="mt-1.5 text-sm text-ink-muted">B1 信号与分层证据，先复核再研究</p>
        </header>

        <div className="mb-6 flex border-b border-border" role="tablist" aria-label="个股视图">
          <button type="button" role="tab" aria-selected={view === "decision"} onClick={() => setView("decision")} className={`relative flex min-h-11 flex-1 items-center justify-center gap-2 text-sm font-medium transition-colors active:scale-[0.99] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent ${view === "decision" ? "text-accent" : "text-ink-muted hover:text-ink-secondary"}`}><Target size={16} strokeWidth={1.7} />B1{view === "decision" && <span className="absolute inset-x-6 bottom-0 h-px bg-accent" />}</button>
          <button type="button" role="tab" aria-selected={view === "research"} onClick={() => setView("research")} className={`relative flex min-h-11 flex-1 items-center justify-center gap-2 text-sm font-medium transition-colors active:scale-[0.99] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent ${view === "research" ? "text-accent" : "text-ink-muted hover:text-ink-secondary"}`}><SlidersHorizontal size={16} strokeWidth={1.7} />其他策略{view === "research" && <span className="absolute inset-x-6 bottom-0 h-px bg-accent" />}</button>
        </div>

        {view === "decision" ? (
          <div className="view-enter">
            <QuantPickCard />
            <details
              className="mt-5 px-1 py-2 text-xs text-ink-muted"
              onToggle={(event) => setCoverageOpen(event.currentTarget.open)}
            >
              <summary className="flex cursor-pointer list-none items-center gap-2 hover:text-ink-secondary"><Database size={13} />数据底座</summary>
              {coverageOpen && <CoverageDetails />}
            </details>
          </div>
        ) : (
          <section className="view-enter">
            <div className="mb-4">
              <h2 className="text-base font-semibold text-ink">其他策略</h2>
              <p className="mt-1 text-xs text-ink-muted">这些只做参考，B1 仍是主策略。</p>
            </div>
            <FactorWorkbench />
          </section>
        )}
      </div>
    </PageTransition>
  );
}
