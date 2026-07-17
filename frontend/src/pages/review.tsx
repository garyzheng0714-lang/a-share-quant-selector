import { useState } from "react";
import { PageTransition } from "@/components/layout/page-transition";
import { SelectionLists } from "@/components/review/selection-lists";
import { SectorRotationCard } from "@/components/dashboard/sector-rotation-card";
import { PicksHistory } from "@/components/review/picks-history";
import { PerformanceSection } from "@/components/review/performance-section";
import { HistorySection } from "@/components/review/history-section";
import { SuperB1PerformanceSection } from "@/components/review/super-b1-performance";

type Tab = "lists" | "sectors" | "performance" | "superb1" | "history" | "picks";

const TABS: { key: Tab; label: string }[] = [
  { key: "lists", label: "选股名单" },
  { key: "sectors", label: "板块风向" },
  { key: "performance", label: "整体战绩" },
  { key: "superb1", label: "超级B1" },
  { key: "history", label: "每日名单" },
  { key: "picks", label: "旧版 AI" },
];

/**
 * 复盘页 = 研究区 + 信任审计。主页只管"今天买哪个"，一切要动脑子的东西住在这里。
 *
 * 选股名单（28公式体检 + 碗口B1 + 超级B1 今日候选，2026-07-14 从主页搬来）/
 * 板块风向（完整热度榜 + 接力榜，同日从主页搬来）/ 整体战绩 / 超级B1 /
 * 每日名单 / AI 荐票（已于 2026-07-14 停用自主荐票，此处仅存历史档案——
 * AI 现在只在主页为量化选出的票写点评，不再自己挑票）
 */
export function Component() {
  const [tab, setTab] = useState<Tab>("lists");

  return (
    <PageTransition>
      <div className="max-w-4xl mx-auto px-4 sm:px-8 py-6 sm:py-10">
        <h1 className="text-xl sm:text-2xl font-bold tracking-[-0.03em] text-ink mb-4">
          复盘
        </h1>

        {/* 手机上 6 个 tab 一行放不下（是我从 4 个加到 6 个撑破的），需要横滑。
            右侧渐隐是唯一的"右边还有"提示——没有它，用户根本不知道能滑 */}
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
        {tab === "superb1" && <SuperB1PerformanceSection />}
        {tab === "history" && <HistorySection />}
        {tab === "picks" && <PicksHistory />}
      </div>
    </PageTransition>
  );
}
