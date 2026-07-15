import { useState } from "react";
import { ArrowLeft, CheckCircle2, ChevronDown, Info } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { PageTransition } from "@/components/layout/page-transition";
import { LoadError, Skeleton } from "@/components/ui";
import { useSectorDetail } from "@/lib/hooks";
import type { SectorDetailStock } from "@/lib/api";

const actionLabel = { buy: "可执行", observe: "观察", avoid: "回避", none: "无B1" } as const;

function StockRow({ stock, onOpen, emphasized = false }: { stock: SectorDetailStock; onOpen: () => void; emphasized?: boolean }) {
  return (
    <button onClick={onOpen} className={`grid min-h-15 w-full grid-cols-[28px_1fr_58px] items-center gap-2 px-3 text-left transition-colors hover:bg-surface-hover active:bg-inset sm:grid-cols-[36px_1.3fr_84px_76px_72px] ${emphasized ? "bg-accent-dim/40" : ""}`}>
      <span className={`num text-xs ${stock.b1 ? "font-semibold text-accent" : "text-ink-muted"}`}>{stock.rank}</span>
      <div className="min-w-0">
        <div className="flex items-center gap-2"><span className="truncate text-sm font-medium text-ink">{stock.name}</span><span className="font-mono text-[10px] text-ink-muted">{stock.code}</span></div>
        <div className="mt-1 flex min-w-0 items-center gap-2 text-[10px] text-ink-muted">
          {stock.b1_signals[0] && <span className="truncate text-accent-light">{stock.b1_signals[0]}</span>}
          {stock.confirmation_count > 0 && <span className="shrink-0">辅助 {stock.confirmation_count}</span>}
        </div>
      </div>
      <span className={`justify-self-end text-[10px] font-medium ${stock.action === "buy" ? "text-bull" : stock.action === "avoid" ? "text-bear" : "text-ink-muted"}`}>{actionLabel[stock.action]}</span>
      <span className="hidden num text-right text-xs text-ink-secondary sm:block">{stock.close.toFixed(2)}</span>
      <span className={`hidden num text-right text-xs sm:block ${(stock.ret5 ?? 0) >= 0 ? "text-bull" : "text-bear"}`}>{stock.ret5 == null ? "-" : `${stock.ret5 > 0 ? "+" : ""}${stock.ret5.toFixed(2)}%`}</span>
    </button>
  );
}

export function Component() {
  const [showAll, setShowAll] = useState(false);
  const { name = "" } = useParams();
  const sectorName = decodeURIComponent(name);
  const navigate = useNavigate();
  const query = useSectorDetail(sectorName || null);

  if (query.isLoading) return <div className="mx-auto max-w-5xl px-4 py-6"><Skeleton className="h-32 w-full rounded-[14px]" /></div>;
  if (query.error) return <LoadError label="板块个股加载失败" onRetry={() => query.mutate()} />;

  const data = query.data;
  const state = data?.sector;
  const stocks = data?.stocks ?? [];
  const recommended = data?.recommended ?? [];
  const visibleStocks = showAll ? stocks : stocks.slice(0, 15);
  const metrics = [
    { label: "相对强度", value: state?.relative_strength, hint: "5/10/20日相对全市场" },
    { label: "资金升温", value: state?.turn_ratio, hint: "近3日成交占比 / 20日" },
    { label: "上涨广度", value: state?.breadth, hint: "上涨、站上MA10与新高合成" },
    { label: "MA10广度", value: state?.breadth_ma10, hint: "板块内站上10日线比例" },
  ];

  return (
    <PageTransition>
      <div className="mx-auto max-w-5xl px-4 py-5 sm:px-6 sm:py-8">
        <Link to="/sectors" className="mb-4 inline-flex min-h-9 items-center gap-2 text-xs text-ink-muted transition-colors hover:text-ink"><ArrowLeft size={14} />返回板块</Link>

        <section className="card-hero p-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-xs text-accent">第 {state?.rank ?? "-"} / {state?.total ?? "-"}</p>
              <h1 className="mt-2 text-2xl font-semibold tracking-[-0.04em] text-ink">{sectorName}</h1>
              <p className="mt-1 text-xs text-ink-muted">{state?.stage ?? "未评级"}</p>
            </div>
            <div className="text-right"><p className="num text-4xl font-semibold tracking-[-0.05em] text-ink">{state?.score != null ? Math.round(state.score) : "-"}</p><p className="mt-1 text-[10px] text-ink-muted">板块热度</p></div>
          </div>
          <div className="mt-5 flex items-center justify-between border-t border-border pt-4 text-xs">
            <span className="text-ink-muted">3日热度变化</span>
            <span className={`num font-semibold ${state && state.delta3 >= 0 ? "text-bull" : "text-bear"}`}>{state?.delta3 == null ? "-" : `${state.delta3 > 0 ? "+" : ""}${state.delta3.toFixed(1)}`}</span>
          </div>
        </section>

        <details className="mt-3 rounded-[12px] border border-border bg-surface px-4 py-3">
          <summary className="flex cursor-pointer list-none items-center gap-2 text-xs font-medium text-ink-secondary"><Info size={14} className="text-accent" />为什么这个板块排在这里<ChevronDown size={14} className="ml-auto text-ink-muted" /></summary>
          <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            {metrics.map((metric) => (
              <div key={metric.label} className="rounded-[10px] bg-inset p-3">
                <p className="text-[10px] text-ink-muted">{metric.label}</p>
                <p className="mt-1 num text-lg font-semibold text-ink">{metric.value == null ? "-" : metric.value.toFixed(metric.label === "资金升温" ? 2 : 1)}</p>
                <p className="mt-1 text-[9px] leading-relaxed text-ink-muted">{metric.hint}</p>
              </div>
            ))}
          </div>
          <p className="mt-3 text-[10px] leading-relaxed text-ink-muted">热度由相对强度、资金占比、上涨广度与持续性共同计算，并扣除龙头过度集中惩罚。</p>
        </details>

        {recommended.length > 0 && (
          <section className="mt-5 overflow-hidden card-modern">
            <div className="flex items-center gap-2 border-b border-border px-4 py-3"><CheckCircle2 size={15} className="text-bull" /><h2 className="text-sm font-semibold text-ink">B1 命中</h2><span className="ml-auto num text-xs text-bull">{recommended.length} 只</span></div>
            <div className="divide-y divide-border/60">{recommended.map((stock) => <StockRow key={stock.code} stock={stock} emphasized onOpen={() => navigate(`/stock/${stock.code}`)} />)}</div>
          </section>
        )}

        <section className="mt-5 overflow-hidden card-modern">
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <div><h2 className="text-sm font-semibold text-ink">板块个股</h2><p className="mt-0.5 text-[10px] text-ink-muted">B1 优先，其次看辅助确认</p></div>
            <span className="num text-xs text-ink-muted">{stocks.length} 只</span>
          </div>
          <div className="grid grid-cols-[28px_1fr_58px] gap-2 border-b border-border px-3 py-2 text-[10px] text-ink-muted sm:grid-cols-[36px_1.3fr_84px_76px_72px]"><span>#</span><span>个股</span><span className="text-right">判定</span><span className="hidden text-right sm:block">收盘</span><span className="hidden text-right sm:block">5日</span></div>
          {visibleStocks.length ? <div className="divide-y divide-border/60">{visibleStocks.map((stock) => <StockRow key={stock.code} stock={stock} onOpen={() => navigate(`/stock/${stock.code}`)} />)}</div> : <p className="p-5 text-sm text-ink-muted">{data?.reason ?? "该板块暂无可用个股行情"}</p>}
          {stocks.length > 15 && <button onClick={() => setShowAll((value) => !value)} className="flex w-full items-center justify-center gap-2 border-t border-border px-4 py-3 text-xs font-medium text-accent hover:bg-surface-hover active:bg-inset">{showAll ? "收起" : `查看全部 ${stocks.length} 只`}<ChevronDown size={14} className={`transition-transform ${showAll ? "rotate-180" : ""}`} /></button>}
        </section>
      </div>
    </PageTransition>
  );
}
