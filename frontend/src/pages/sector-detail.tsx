import { ArrowLeft, CheckCircle2, ShieldX } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { PageTransition } from "@/components/layout/page-transition";
import { LoadError, Skeleton } from "@/components/ui";
import { useSectorDetail } from "@/lib/hooks";
import type { SectorDetailStock } from "@/lib/api";

const actionLabel = { buy: "可执行", observe: "观察", avoid: "回避", none: "无B1" } as const;

function StockRow({ stock, onOpen }: { stock: SectorDetailStock; onOpen: () => void }) {
  return (
    <button onClick={onOpen} className="grid min-h-16 w-full grid-cols-[32px_1fr_64px] items-center gap-2 px-3 text-left transition-colors duration-200 hover:bg-surface-hover active:bg-inset sm:grid-cols-[40px_1.3fr_100px_90px_80px]">
      <span className={`num text-sm ${stock.b1 ? "font-semibold text-accent" : "text-ink-muted"}`}>{stock.rank}</span>
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-medium text-ink">{stock.name}</span>
          <span className="font-mono text-[10px] text-ink-muted">{stock.code}</span>
        </div>
        <div className="mt-1 flex flex-wrap gap-1">
          {stock.b1_signals.slice(0, 2).map((signal) => <span key={signal} className="rounded bg-accent-dim px-1.5 py-0.5 text-[9px] text-accent">{signal}</span>)}
          {stock.confirmation_count > 0 && <span className="text-[10px] text-ink-muted">辅助确认 {stock.confirmation_count}</span>}
        </div>
      </div>
      <span className={`justify-self-end rounded-full px-2 py-1 text-[10px] font-medium ${stock.action === "buy" ? "bg-bull-dim text-bull" : stock.action === "avoid" ? "bg-bear-dim text-bear" : "bg-inset text-ink-muted"}`}>{actionLabel[stock.action]}</span>
      <span className="hidden num text-right text-xs text-ink-secondary sm:block">{stock.close.toFixed(2)}</span>
      <span className={`hidden num text-right text-xs sm:block ${(stock.ret5 ?? 0) >= 0 ? "text-bull" : "text-bear"}`}>{stock.ret5 == null ? "—" : `${stock.ret5 > 0 ? "+" : ""}${stock.ret5.toFixed(2)}%`}</span>
    </button>
  );
}

export function Component() {
  const { name = "" } = useParams();
  const sectorName = decodeURIComponent(name);
  const navigate = useNavigate();
  const query = useSectorDetail(sectorName || null);
  if (query.isLoading) return <div className="mx-auto max-w-5xl px-4 py-6"><Skeleton className="h-[520px] w-full rounded-2xl" /></div>;
  if (query.error) return <LoadError label="板块个股加载失败" onRetry={() => query.mutate()} />;
  const data = query.data;
  const state = data?.sector;
  const stocks = data?.stocks ?? [];
  const recommended = data?.recommended ?? [];

  return (
    <PageTransition>
      <div className="mx-auto max-w-5xl px-4 py-6 lg:px-8 lg:py-10">
        <Link to="/sectors" className="mb-4 inline-flex min-h-11 items-center gap-2 text-sm text-ink-muted transition-colors hover:text-ink"><ArrowLeft size={16} />返回板块排名</Link>
        <header className="mb-5 flex flex-wrap items-end gap-3">
          <div><p className="text-xs text-accent">第 {state?.rank ?? "—"} / {state?.total ?? "—"}</p><h1 className="mt-1 text-2xl font-semibold text-ink">{sectorName}</h1></div>
          <div className="ml-auto text-right"><p className="num text-3xl font-semibold text-ink">{state?.score != null ? Math.round(state.score) : "—"}</p><p className="text-[11px] text-ink-muted">板块热度 · {state?.stage ?? "未评级"}</p></div>
        </header>

        <section className="mb-4 rounded-2xl border border-border bg-surface p-4">
          <div className="flex items-center gap-2">
            {recommended.length ? <CheckCircle2 size={16} className="text-bull" /> : <ShieldX size={16} className="text-ink-muted" />}
            <h2 className="text-sm font-semibold text-ink">B1 主判命中</h2>
            <span className="ml-auto num text-xs text-ink-muted">{recommended.length} 只</span>
          </div>
          <p className="mt-2 text-xs leading-relaxed text-ink-muted">只有B1先命中，才进入推荐候选；板块状态决定顺风或逆风，其他因子只增加确认或触发风险否决。</p>
        </section>

        <section className="overflow-hidden rounded-2xl border border-border bg-surface">
          <div className="grid grid-cols-[32px_1fr_64px] gap-2 border-b border-border px-3 py-2 text-[10px] text-ink-muted sm:grid-cols-[40px_1.3fr_100px_90px_80px]"><span>排名</span><span>个股</span><span className="text-right">判定</span><span className="hidden text-right sm:block">收盘</span><span className="hidden text-right sm:block">5日</span></div>
          {stocks.length ? <div className="divide-y divide-border/60">{stocks.map((stock) => <StockRow key={stock.code} stock={stock} onOpen={() => navigate(`/stock/${stock.code}`)} />)}</div> : <p className="p-5 text-sm text-ink-muted">{data?.reason ?? "该板块暂无可用个股行情"}</p>}
        </section>
      </div>
    </PageTransition>
  );
}
