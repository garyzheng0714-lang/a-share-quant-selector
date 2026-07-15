import { useState } from "react";
import { Database, SlidersHorizontal, Target } from "lucide-react";
import { PageTransition } from "@/components/layout/page-transition";
import { QuantPickCard } from "@/components/dashboard/quant-pick-card";
import { FactorWorkbench } from "@/components/today/factor-workbench";
import { useCoverage } from "@/lib/hooks";

type View = "decision" | "research";

export function Component() {
  const [view, setView] = useState<View>("decision");
  const { data: coverage } = useCoverage();

  return (
    <PageTransition>
      <div className="mx-auto max-w-4xl px-4 py-5 sm:px-6 sm:py-8">
        <header className="mb-5">
          <h1 className="text-2xl font-semibold tracking-[-0.04em] text-ink">个股</h1>
          <p className="mt-1 text-sm text-ink-muted">只看 B1，先判断能不能买</p>
        </header>

        <div className="mb-5 grid grid-cols-2 rounded-[12px] bg-inset p-1" aria-label="个股视图">
          <button onClick={() => setView("decision")} className={`flex min-h-10 items-center justify-center gap-2 rounded-[9px] text-sm font-medium transition-colors active:scale-[0.99] ${view === "decision" ? "bg-elevated text-ink shadow-card" : "text-ink-muted hover:text-ink-secondary"}`}><Target size={15} />B1</button>
          <button onClick={() => setView("research")} className={`flex min-h-10 items-center justify-center gap-2 rounded-[9px] text-sm font-medium transition-colors active:scale-[0.99] ${view === "research" ? "bg-elevated text-ink shadow-card" : "text-ink-muted hover:text-ink-secondary"}`}><SlidersHorizontal size={15} />其他策略</button>
        </div>

        {view === "decision" ? (
          <div className="view-enter">
            <QuantPickCard />
            {coverage && (
              <details className="mt-4 px-1 py-2 text-[11px] text-ink-muted">
                <summary className="flex cursor-pointer list-none items-center gap-2 hover:text-ink-secondary"><Database size={13} />数据底座 {coverage.covered_count}/{coverage.universe_count}</summary>
                <p className="mt-2 pl-5 leading-relaxed">可训练 {coverage.trainable_count}/{coverage.trainable_eligible_count}，次新股 {coverage.short_history_count} 只单列。{coverage.running ? `后台仍在补齐 ${coverage.remaining_count} 只。` : "当前回补任务已结束。"}</p>
              </details>
            )}
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
