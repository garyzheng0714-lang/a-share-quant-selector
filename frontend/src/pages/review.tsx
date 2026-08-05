import { useState } from "react";
import { Tab as AstryxTab, TabList } from "@astryxdesign/core/TabList";
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
      <div className="mx-auto max-w-7xl px-4 py-6 sm:px-8 sm:py-9">
        <header className="mb-5">
          <p className="section-kicker">研究复盘</p>
          <h1 className="mt-2 text-2xl font-semibold tracking-[-0.04em] text-ink">验证方法，不追逐结果</h1>
          <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-ink-muted">
            用样本外战绩与当前研究快照校准方法，不在这里制造新的推荐结论。
          </p>
        </header>

        <div className="mb-5 overflow-x-auto scrollbar-none">
          <TabList value={tab} onChange={(value) => setTab(value as Tab)} size="sm" layout="hug" hasDivider>
            {TABS.map((item) => (
              <AstryxTab key={item.key} value={item.key} label={item.label} />
            ))}
          </TabList>
        </div>

        <div id={`review-${tab}-panel`} role="tabpanel" aria-labelledby={`review-${tab}-tab`}>
          {tab === "lists" && <SelectionLists />}
          {tab === "sectors" && <SectorRotationCard />}
          {tab === "performance" && <PerformanceSection />}
        </div>
      </div>
    </PageTransition>
  );
}
