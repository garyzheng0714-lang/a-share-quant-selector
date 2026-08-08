import { PageHeader, PageShell } from "@/components/layout/page-shell";
import { PageTransition } from "@/components/layout/page-transition";
import { StrategyReviewWorkspace } from "@/components/review/strategy-review-workspace";

/**
 * 复盘：只做策略历史命中的票级复盘。
 * 市场环境 / 策略工作台 / 决策账本不再塞进本页。
 */
export function Component() {
  return (
    <PageTransition>
      <PageShell>
        <PageHeader title="复盘" />
        <StrategyReviewWorkspace />
      </PageShell>
    </PageTransition>
  );
}
