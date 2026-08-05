import { useState } from "react";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { Collapsible } from "@astryxdesign/core/Collapsible";
import { Heading } from "@astryxdesign/core/Heading";
import { Icon } from "@astryxdesign/core/Icon";
import { Text } from "@astryxdesign/core/Text";
import { PageTransition } from "@/components/layout/page-transition";
import { QuantPickCard } from "@/components/dashboard/quant-pick-card";
import { FactorWorkbench } from "@/components/today/factor-workbench";
import { useCoverage } from "@/lib/hooks";

type View = "workspace" | "decision";

function CoverageDetails() {
  const { data: coverage } = useCoverage();

  if (!coverage) return <Text type="supporting" className="mt-2 block">正在读取覆盖率…</Text>;

  return (
    <Text type="body" className="mt-2 block leading-relaxed">
      已覆盖 {coverage.covered_count}/{coverage.universe_count}，可训练 {coverage.trainable_count}/{coverage.trainable_eligible_count}，次新股 {coverage.short_history_count} 只单列。
      {coverage.running ? `后台仍在补齐 ${coverage.remaining_count} 只。` : "当前回补任务已结束。"}
    </Text>
  );
}

export function Component() {
  const [view, setView] = useState<View>("workspace");
  const [coverageOpen, setCoverageOpen] = useState(false);

  return (
    <PageTransition>
      <div className="strategy-page">
        <div className="flex min-h-12 items-center justify-between gap-3 border-b border-border bg-surface px-3 py-2 sm:px-5">
          <div className="min-w-0">
            <Heading level={1} className="truncate">每日策略池</Heading>
            <Text type="supporting" className="hidden sm:block">真实数据驱动的条件组合与结果复核</Text>
          </div>
          <SegmentedControl
            value={view}
            onChange={(value) => setView(value as View)}
            label="研究模式"
            size="sm"
          >
            <SegmentedControlItem value="workspace" label="策略组合" />
            <SegmentedControlItem value="decision" label="B1 决策" />
          </SegmentedControl>
        </div>

        {view === "workspace" ? (
          <section aria-label="策略组合工作台" className="view-enter">
            <FactorWorkbench />
          </section>
        ) : (
          <div className="mx-auto max-w-[1440px] px-3 py-5 sm:px-5 sm:py-7">
            <header className="mb-4">
              <Heading level={2}>B1 分层决策</Heading>
              <Text type="supporting" className="mt-1 block">作为预设决策模型独立展示；不伪装成可与因子做交集的同类数据源。</Text>
            </header>
            <QuantPickCard />
            <Collapsible
              trigger={<span className="flex items-center gap-2"><Icon icon="viewColumns" size="xsm" />查看全市场数据覆盖</span>}
              isOpen={coverageOpen}
              onOpenChange={setCoverageOpen}
              className="mt-3"
            >
              <CoverageDetails />
            </Collapsible>
          </div>
        )}
      </div>
    </PageTransition>
  );
}
