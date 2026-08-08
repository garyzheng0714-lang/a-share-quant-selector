import { PageShell } from "@/components/layout/page-shell";
import { PageTransition } from "@/components/layout/page-transition";
import { TodayRecommendCard } from "@/components/dashboard/today-recommend-card";

export function Component() {
  return (
    <PageTransition>
      <div className="strategy-page">
        <PageShell className="cloud-decision-page">
          <TodayRecommendCard />
        </PageShell>
      </div>
    </PageTransition>
  );
}
