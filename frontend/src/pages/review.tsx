import { useState } from "react";
import { Tab as AstryxTab, TabList } from "@astryxdesign/core/TabList";
import { PageHeader, PageShell } from "@/components/layout/page-shell";
import { PageTransition } from "@/components/layout/page-transition";
import { ListSourceControl, ListSourceBody, type ListSource } from "@/components/review/selection-lists";
import { SectorRotationCard } from "@/components/dashboard/sector-rotation-card";
import { CloudStairReviewSection } from "@/components/review/cloud-stair-review";
import { PerformanceSection } from "@/components/review/performance-section";

type Tab = "cloud" | "lists" | "sectors" | "performance";

const TABS: { key: Tab; label: string }[] = [
  { key: "cloud", label: "云阶复盘" },
  { key: "lists", label: "选股名单" },
  { key: "sectors", label: "板块风向" },
  { key: "performance", label: "决策账本" },
];

/**
 * 复盘页：默认以云阶票级历史衡量「选出当日买入 → 隔日 / 持有至今」。
 * 选股名单与板块风向仍作研究辅助；决策账本保留 canonical decision outcomes。
 */
export function Component() {
  const [tab, setTab] = useState<Tab>("cloud");
  const [listSource, setListSource] = useState<ListSource>("factors");
  const isFactorWorkbench = tab === "lists" && listSource === "factors";

  return (
    <PageTransition>
      <PageShell className={isFactorWorkbench ? "pb-0" : undefined}>
        <PageHeader
          title="用历史命中校准方法"
          description="先看云阶每日选出的票：隔日涨跌、持有至今、以及更合适的卖点窗口。"
        />

        <div className="mb-5 overflow-x-auto scrollbar-none">
          <TabList value={tab} onChange={(value) => setTab(value as Tab)} size="sm" layout="hug" hasDivider>
            {TABS.map((item) => (
              <AstryxTab key={item.key} value={item.key} label={item.label} />
            ))}
          </TabList>
        </div>

        <div id={`review-${tab}-panel`} role="tabpanel" aria-labelledby={`review-${tab}-tab`}>
          {tab === "cloud" && <CloudStairReviewSection />}
          {tab === "lists" && (
            <>
              <ListSourceControl value={listSource} onChange={setListSource} />
              {listSource !== "factors" && (
                <div className="mt-4">
                  <ListSourceBody source={listSource} />
                </div>
              )}
            </>
          )}
          {tab === "sectors" && <SectorRotationCard />}
          {tab === "performance" && <PerformanceSection />}
        </div>
      </PageShell>

      {isFactorWorkbench && (
        <div className="mt-4">
          <ListSourceBody source="factors" />
        </div>
      )}
    </PageTransition>
  );
}
