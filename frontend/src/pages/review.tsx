import { useState } from "react";
import { Tab as AstryxTab, TabList } from "@astryxdesign/core/TabList";
import { PageHeader, PageShell } from "@/components/layout/page-shell";
import { PageTransition } from "@/components/layout/page-transition";
import { ListSourceControl, ListSourceBody, type ListSource } from "@/components/review/selection-lists";
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
 *
 * 策略因子（FactorWorkbench）是三栏全宽工作台，不能塞进本页的定宽 PageShell——
 * 命中「选股名单」Tab 且来源为「策略因子」时，工作台在 PageShell 外全宽渲染，
 * 与个股页研究视图（stocks.tsx）保持同一处理方式；其余 Tab 与名单来源仍在
 * PageShell 内定宽展示。
 */
export function Component() {
  const [tab, setTab] = useState<Tab>("lists");
  const [listSource, setListSource] = useState<ListSource>("factors");
  const isFactorWorkbench = tab === "lists" && listSource === "factors";

  return (
    <PageTransition>
      <PageShell className={isFactorWorkbench ? "pb-0" : undefined}>
        <PageHeader
          title="验证方法，不追逐结果"
          description="用样本外战绩与当前研究快照校准方法，不在这里制造新的推荐结论。"
        />

        <div className="mb-5 overflow-x-auto scrollbar-none">
          <TabList value={tab} onChange={(value) => setTab(value as Tab)} size="sm" layout="hug" hasDivider>
            {TABS.map((item) => (
              <AstryxTab key={item.key} value={item.key} label={item.label} />
            ))}
          </TabList>
        </div>

        <div id={`review-${tab}-panel`} role="tabpanel" aria-labelledby={`review-${tab}-tab`}>
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
