import { PageTransition } from "@/components/layout/page-transition";
import { useParams } from "react-router-dom";

export function Component() {
  const { code } = useParams<{ code: string }>();
  return (
    <PageTransition>
      <div className="max-w-6xl mx-auto px-6 py-8">
        <h1 className="text-2xl font-semibold text-ink">股票详情 - {code}</h1>
        <p className="text-ink-secondary mt-2">Stock detail placeholder</p>
      </div>
    </PageTransition>
  );
}
