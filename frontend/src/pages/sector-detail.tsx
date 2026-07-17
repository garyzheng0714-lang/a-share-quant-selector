import { useState } from "react";
import { ArrowLeft, ChevronDown, ChevronRight } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { PageTransition } from "@/components/layout/page-transition";
import { LoadError, Skeleton } from "@/components/ui";
import { useSectorDetail } from "@/lib/hooks";
import type { SectorDetailStock } from "@/lib/api";

const actionLabel = { buy: "通过复核", observe: "研究候选", avoid: "未通过", none: "-" } as const;

function StockRow({ stock, onOpen }: { stock: SectorDetailStock; onOpen: () => void }) {
  return (
    <button onClick={onOpen} className="grid min-h-[72px] w-full grid-cols-[1fr_auto_16px] items-center gap-3 px-5 py-3.5 text-left transition-colors duration-200 hover:bg-surface-hover active:bg-inset">
      <span className="min-w-0">
        <span className="flex items-baseline gap-2">
          <span className="truncate text-base font-semibold tracking-[-0.01em] text-ink">{stock.name}</span>
          <span className="font-mono text-[11px] text-ink-muted">{stock.code}</span>
        </span>
        <span className={`mt-1.5 block truncate text-xs ${stock.b1 ? "text-accent-light" : "text-ink-muted"}`}>
          {stock.b1_signals[0] ?? (stock.confirmation_count > 0 ? `辅助信号 ${stock.confirmation_count} 个` : "暂无 B1")}
        </span>
      </span>
      <span className={`text-xs font-medium ${stock.action === "buy" ? "text-bull" : stock.action === "avoid" ? "text-bear" : stock.action === "observe" ? "text-accent" : "text-ink-muted"}`}>{actionLabel[stock.action]}</span>
      <ChevronRight size={14} className="text-ink-muted" />
    </button>
  );
}

export function Component() {
  const [showAll, setShowAll] = useState(false);
  const { name = "" } = useParams();
  const sectorName = decodeURIComponent(name);
  const navigate = useNavigate();
  const query = useSectorDetail(sectorName || null);

  if (query.isLoading) return <div className="mx-auto max-w-4xl px-4 py-6"><Skeleton className="h-48 w-full rounded-[14px]" /></div>;
  if (query.error) return <LoadError label="板块个股加载失败" onRetry={() => query.mutate()} />;

  const data = query.data;
  const state = data?.sector;
  const stocks = data?.stocks ?? [];
  const recommended = data?.recommended ?? [];
  const visible = showAll ? stocks : stocks.slice(0, 10);
  const metrics = [
    { label: "相对强度", value: state?.relative_strength },
    { label: "资金", value: state?.turn_ratio },
    { label: "上涨广度", value: state?.breadth },
    { label: "站上10日线", value: state?.breadth_ma10 },
  ];

  return (
    <PageTransition>
      <div className="mx-auto max-w-4xl px-4 py-7 sm:px-6 sm:py-10">
        <Link to="/sectors" className="mb-7 inline-flex min-h-9 items-center gap-2 text-xs text-ink-muted transition-colors hover:text-accent"><ArrowLeft size={14} />返回板块</Link>

        <header className="mb-6">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h1 className="text-[30px] font-semibold tracking-[-0.045em] text-ink">{sectorName}</h1>
              <p className="mt-1.5 text-sm text-ink-muted">排名 {state?.rank ?? "-"}，{state?.stage ?? "未评级"}</p>
            </div>
            <div className="text-right">
              <p className="num text-[36px] font-semibold tracking-[-0.04em] text-accent">{state?.score == null ? "-" : Math.round(state.score)}</p>
              <p className="mt-0.5 text-xs text-ink-muted">强度</p>
            </div>
          </div>
        </header>

        <section className="decision-panel mb-4 px-5 py-4">
          <p className="section-kicker">板块机会</p>
          <p className="mt-1.5 text-xl font-semibold text-ink">B1 {recommended.length} 只</p>
          <p className="mt-1.5 text-sm text-ink-muted">B1 股票已排在列表前面。</p>
        </section>

        <details className="mb-6 rounded-[12px] border border-border bg-surface/60 px-5 py-3.5 text-xs text-ink-muted">
          <summary className="flex cursor-pointer list-none items-center justify-between text-ink-secondary">为什么排在这里<ChevronDown size={14} /></summary>
          <div className="mt-3 grid grid-cols-2 gap-2">
            {metrics.map((metric) => (
              <div key={metric.label} className="rounded-[10px] bg-inset px-3 py-2">
                <p className="text-[10px]">{metric.label}</p>
                <p className="num mt-1 text-base font-semibold text-ink">{metric.value == null ? "-" : metric.value.toFixed(metric.label === "资金" ? 2 : 1)}</p>
              </div>
            ))}
          </div>
        </details>

        <section className="overflow-hidden card-modern">
          <div className="flex items-center justify-between bg-inset px-5 py-3.5">
            <h2 className="text-sm font-semibold text-ink">板块股票</h2>
            <span className="num text-xs text-ink-muted">{stocks.length} 只</span>
          </div>
          {visible.length ? <div className="reveal-list divide-y divide-border/60 border-t border-border">{visible.map((stock) => <StockRow key={stock.code} stock={stock} onOpen={() => navigate(`/stock/${stock.code}`)} />)}</div> : <p className="border-t border-border px-4 py-5 text-sm text-ink-muted">{data?.reason ?? "没有可用股票"}</p>}
          {stocks.length > 10 && (
            <button onClick={() => setShowAll((value) => !value)} className="flex w-full items-center justify-center gap-2 border-t border-border px-4 py-3 text-xs font-medium text-accent hover:bg-surface-hover active:bg-inset">
              {showAll ? "收起" : `查看全部 ${stocks.length} 只`}
              <ChevronDown size={14} className={`transition-transform ${showAll ? "rotate-180" : ""}`} />
            </button>
          )}
        </section>
      </div>
    </PageTransition>
  );
}
