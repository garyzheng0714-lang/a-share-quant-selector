import { PageTransition } from "@/components/layout/page-transition";

export function Component() {
  return (
    <PageTransition>
      <div className="max-w-6xl mx-auto px-6 py-8">
        <h1 className="text-2xl font-semibold text-ink">智能选股</h1>
        <p className="text-ink-secondary mt-2">Selection placeholder</p>
      </div>
    </PageTransition>
  );
}
