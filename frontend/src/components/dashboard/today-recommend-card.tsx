import { useNavigate } from "react-router";
import { BadgeCheck, CircleAlert, Sparkles } from "lucide-react";
import { LoadError, Skeleton } from "@/components/ui";
import { useRecommend } from "@/lib/hooks";
import { useAppStore } from "@/lib/store";
import type { RecommendStock, SignalStock } from "@/lib/api";

/**
 * 今日推荐：云阶命中票，按板块热度排序，直接回答「推荐几只、哪只、排名、为什么」。
 * 只呈现事实（信号 + 板块热度 + 排名），不做买卖建议。
 */
function deltaColor(v: number | undefined): string {
  if (v === undefined || v === null) return "text-ink-muted";
  if (v > 0) return "text-bull";
  if (v < 0) return "text-bear";
  return "text-ink-muted";
}

function RecommendRow({ item, list }: { item: RecommendStock; list: RecommendStock[] }) {
  const navigate = useNavigate();
  const setStockNav = useAppStore((state) => state.setStockNav);
  const sector = item.sector;

  return (
    <button
      type="button"
      onClick={() => {
        const navList: SignalStock[] = list.map((s) => ({
          code: s.code, name: s.name, strategy: "云阶", category: "云阶",
          close: s.close ?? 0, J: 0, volume_ratio: 0, market_cap: 0,
          short_term_trend: 0, bull_bear_line: 0, reasons: [],
          similarity_score: null, matched_case: null, match_breakdown: null,
          industry: s.industry,
        }));
        setStockNav(navList, navList.findIndex((x) => x.code === item.code));
        navigate(`/stock/${item.code}`);
      }}
      className="w-full text-left px-3.5 py-3 hover:bg-elevated active:bg-inset rounded-xl transition-colors duration-100"
    >
      <div className="flex items-center gap-2.5 min-w-0">
        <span
          className={`shrink-0 inline-flex items-center justify-center w-6 h-6 rounded-full text-xs font-semibold tabular-nums ${
            item.rank === 1 ? "bg-accent/15 text-accent" : "bg-surface text-ink-muted"
          }`}
          aria-label={`第 ${item.rank} 名`}
        >
          {item.rank}
        </span>
        <span className="text-sm font-medium text-ink truncate">{item.name || item.code}</span>
        <span className="font-mono text-xs text-ink-muted shrink-0">{item.code}</span>
        <span className="ml-auto shrink-0 text-sm font-medium tabular-nums text-ink">
          {item.close?.toFixed(2) ?? "-"}
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 mt-1.5 pl-9 text-[11px] text-ink-muted tabular-nums">
        {sector && (
          <span className="shrink-0 rounded-full bg-surface px-1.5 py-0.5 text-ink-secondary">
            板块 {sector.score?.toFixed(0)} · {sector.rank}/{sector.total}
            <span className={deltaColor(sector.delta3)}>
              {sector.delta3 !== undefined && sector.delta3 !== null && sector.delta3 !== 0
                ? `${sector.delta3 > 0 ? " +" : " "}${sector.delta3.toFixed(0)}`
                : ""}
            </span>
          </span>
        )}
        {item.industry && <span className="shrink-0">{item.industry}</span>}
        {item.cap_yi !== null && item.cap_yi !== undefined && (
          <span className="shrink-0">{item.cap_yi.toFixed(0)}亿</span>
        )}
        {item.pct_change !== null && item.pct_change !== undefined && (
          <span className={deltaColor(item.pct_change)}>
            {item.pct_change > 0 ? "+" : ""}
            {item.pct_change.toFixed(2)}%
          </span>
        )}
      </div>
      {item.reason && (
        <p className="mt-1.5 pl-9 text-[11px] leading-relaxed text-ink-muted">{item.reason}</p>
      )}
    </button>
  );
}

export function TodayRecommendCard() {
  const { data, error, isLoading, mutate } = useRecommend();
  const picks: RecommendStock[] = data?.today_buy ?? [];

  return (
    <section className="card-modern mb-5" data-testid="today-recommend">
      <header className="flex items-center gap-2 px-4 pt-3.5 pb-2">
        <Sparkles size={15} className="text-accent" strokeWidth={1.7} />
        <h2 className="text-sm font-semibold text-ink">今日推荐</h2>
        <span className="text-[11px] text-ink-muted">
          {data?.trade_date ? `截至 ${data.trade_date} 收盘` : ""}
        </span>
        {data?.core_factor && (
          <span className="ml-auto inline-flex items-center gap-1 rounded-full bg-surface px-1.5 py-0.5 text-[10px] text-ink-secondary">
            <BadgeCheck size={11} className="text-bull" />
            云阶 · 双周期验证主策略
          </span>
        )}
      </header>

      {isLoading ? (
        <div className="px-4 pb-4 space-y-2">
          <Skeleton className="h-12 w-full rounded-xl" />
          <Skeleton className="h-12 w-full rounded-xl" />
        </div>
      ) : error ? (
        <div className="px-4 pb-4">
          <LoadError label="今日推荐加载失败" onRetry={() => mutate()} />
        </div>
      ) : !data?.available ? (
        <p className="px-4 pb-4 flex items-start gap-1.5 text-xs text-ink-muted leading-relaxed">
          <CircleAlert size={13} className="mt-0.5 shrink-0" />
          {data?.reason ?? "数据准备中"}
        </p>
      ) : picks.length === 0 ? (
        <p className="px-4 pb-4 text-xs text-ink-muted leading-relaxed">
          今日无云阶信号。好机会稀缺，空仓是常态——这是事实，不是建议。
        </p>
      ) : (
        <>
          <div className="divide-y divide-border/40">
            {picks.map((item) => (
              <RecommendRow key={item.code} item={item} list={picks} />
            ))}
          </div>
          {data.honest_note && (
            <p className="px-4 py-2.5 border-t border-border/40 text-[10px] text-ink-muted leading-relaxed">
              {data.honest_note}
            </p>
          )}
        </>
      )}
    </section>
  );
}
