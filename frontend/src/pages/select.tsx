import { PageTransition } from "@/components/layout/page-transition";
import { FactorWorkbench } from "@/components/today/factor-workbench";

/** /select：因子选股工作台（常用组合直出、且/或组合、只读 worker 快照） */
export function Component() {
  return (
    <PageTransition>
      <div className="strategy-page">
        <FactorWorkbench />
      </div>
    </PageTransition>
  );
}
