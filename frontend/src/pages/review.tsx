import { useState } from "react";
import { Tab as AstryxTab, TabList } from "@astryxdesign/core/TabList";
import { PageTransition } from "@/components/layout/page-transition";
import { SelectionLists } from "@/components/review/selection-lists";
import { SectorRotationCard } from "@/components/dashboard/sector-rotation-card";
import { PicksHistory } from "@/components/review/picks-history";
import { PerformanceSection } from "@/components/review/performance-section";
import { HistorySection } from "@/components/review/history-section";
import { SuperB1PerformanceSection } from "@/components/review/super-b1-performance";

type ReviewTab = "lists" | "sectors" | "performance" | "superb1" | "history" | "picks";

const TABS: { key: ReviewTab; label: string }[] = [
  { key: "lists", label: "方法体检" },
  { key: "sectors", label: "板块复盘" },
  { key: "performance", label: "整体战绩" },
  { key: "superb1", label: "Super B1" },
  { key: "history", label: "每日记录" },
  { key: "picks", label: "AI 历史" },
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
  const [tab, setTab] = useState<ReviewTab>("lists");

  return (
    <PageTransition>
      <div className="mx-auto max-w-7xl px-4 py-6 sm:px-8 sm:py-9">
        <header className="mb-5">
          <p className="section-kicker">研究复盘</p>
          <h1 className="mt-2 text-2xl font-semibold tracking-[-0.04em] text-ink">验证方法，不追逐结果</h1>
          <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-ink-muted">用样本外战绩、每日记录和历史版本校准研究方法，不在这里制造新的推荐结论。</p>
        </header>

        <div className="mb-5 overflow-x-auto scrollbar-none">
          <TabList value={tab} onChange={(value) => setTab(value as ReviewTab)} size="sm" layout="hug" hasDivider>
            {TABS.map((item) => <AstryxTab key={item.key} value={item.key} label={item.label} />)}
          </TabList>
        </div>

        <div id={`review-${tab}-panel`} role="tabpanel" aria-labelledby={`review-${tab}-tab`}>
          {tab === "lists" && <SelectionLists />}
          {tab === "sectors" && <SectorRotationCard />}
          {tab === "performance" && <PerformanceSection />}
          {tab === "superb1" && <SuperB1PerformanceSection />}
          {tab === "history" && <HistorySection />}
          {tab === "picks" && <PicksHistory />}
        </div>
      </div>
    </PageTransition>
  );
}
