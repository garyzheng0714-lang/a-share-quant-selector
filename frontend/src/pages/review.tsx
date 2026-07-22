import { useState } from "react";
import { PageTransition } from "@/components/layout/page-transition";
import { SelectionLists } from "@/components/review/selection-lists";
import { SectorRotationCard } from "@/components/dashboard/sector-rotation-card";
import { PerformanceSection } from "@/components/review/performance-section";

type Tab = "lists" | "sectors" | "performance";

const TABS: { key: Tab; label: string }[] = [
  { key: "lists", label: "选股名单" },
  { key: "sectors", label: "板块风向" },
  { key: "performance", label: "整体战绩" },
];

/**
 * 复盘页 = 研究区 + 信任审计。主页只管"今天买哪个"，一切要动脑子的东西住在这里。
 *
 * 生产复盘只展示当前快照研究产物和 canonical decision outcomes。
 * 旧 views/results、旧 Super B1 tracker 与 AI 自主荐票已经从产品入口移除。
 */
export function Component() {
  const [tab, setTab] = useState<Tab>("lists");

  return (
    <PageTransition>
      <div className="max-w-4xl mx-auto px-4 sm:px-8 py-6 sm:py-10">
        <h1 className="text-xl sm:text-2xl font-bold tracking-[-0.03em] text-ink mb-4">
          复盘
        </h1>

        <div className="relative mb-5 w-full sm:w-fit">
          <div className="flex items-center gap-1 bg-surface rounded-full p-1 overflow-x-auto scrollbar-none">
            {TABS.map((t) => (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className={`shrink-0 px-3 sm:px-4 py-1.5 text-xs sm:text-sm rounded-full whitespace-nowrap transition-colors duration-150 ${
                  tab === t.key
                    ? "bg-elevated text-ink font-medium ring-1 ring-border"
                    : "text-ink-muted hover:text-ink-secondary"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
          <div className="sm:hidden pointer-events-none absolute inset-y-0 right-0 w-10 rounded-r-full bg-gradient-to-l from-surface to-transparent" />
        </div>

        {tab === "lists" && <SelectionLists />}
        {tab === "sectors" && <SectorRotationCard />}
        {tab === "performance" && <PerformanceSection />}
      </div>
    </PageTransition>
  );
}
