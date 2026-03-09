import { PageTransition } from "@/components/layout/page-transition";

export function Component() {
  return (
    <PageTransition>
      <div className="max-w-6xl mx-auto px-6 py-8">
        <h1 className="text-2xl font-semibold text-ink">综合排名</h1>
        <p className="text-ink-secondary mt-2">Ranking placeholder</p>
      </div>
    </PageTransition>
  );
}
