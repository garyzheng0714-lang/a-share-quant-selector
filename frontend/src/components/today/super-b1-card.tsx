import { useNavigate } from "react-router-dom";
import { Skeleton, LoadError } from "@/components/ui";
import { useSuperB1 } from "@/lib/hooks";
import { useAppStore } from "@/lib/store";
import type { SignalStock, SuperB1Hit } from "@/lib/api";

/**
 * 超级B1（知行公式）独立信号列表。
 * 通过今日页顶部的源切换进入（与策略候选并列，同一个入口承载两套体系）。
 * 与碗口候选池 / AI 荐票完全独立：缩量回调派买点，另一套体系的第二只眼。
 * 无信号是常态（公式条件苛刻），空态如实说明而不是留白。
 */
export function SuperB1Card() {
  const { data, isLoading, error, mutate } = useSuperB1();
  const navigate = useNavigate();
  const setStockNav = useAppStore((s) => s.setStockNav);

  /** 点进个股时把整份命中列表接入 stockNavList（个股页左侧联动 + 上下切换） */
  const openStock = (list: SuperB1Hit[], code: string) => {
    const nav: SignalStock[] = list.map((h) => ({
      code: h.code, name: h.name, strategy: "super_b1",
      category: h.industry || "", close: h.close, J: h.J,
      volume_ratio: 0, market_cap: (h.market_cap_yi || 0) * 1e8,
      short_term_trend: 0, bull_bear_line: 0, reasons: h.signal_labels,
      similarity_score: null, matched_case: null, match_breakdown: null,
      industry: h.industry,
    }));
    setStockNav(nav, list.findIndex((x) => x.code === code));
    navigate(`/stock/${code}`);
  };

  if (isLoading) {
    return (
      <div className="space-y-1">
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="h-14 w-full rounded-xl" />
        ))}
      </div>
    );
  }

  const hits: SuperB1Hit[] = data?.hits ?? [];

  return (
    <section data-testid="super-b1">
      <p className="text-[11px] text-ink-muted leading-relaxed mb-3">
        知行超级B1公式（缩量回调派）独立扫描
        {data?.trade_date && ` · ${data.trade_date}`}
        {!isLoading && data?.available && ` · ${hits.length}只`}
        ，与策略候选、AI 荐票互不影响
        {(data?.cap_missing ?? 0) > 0 && ` · ${data!.cap_missing} 只因缺市值数据未纳入`}
      </p>

      {error ? (
        <LoadError label="超级B1数据加载失败" onRetry={() => mutate()} />
      ) : !data?.available ? (
        <p className="text-xs text-ink-muted leading-relaxed py-2">
          {data?.reason ?? "数据准备中，每个交易日收盘后自动扫描"}
        </p>
      ) : hits.length === 0 ? (
        <p className="text-xs text-ink-muted leading-relaxed py-2">
          今日全市场无超级B1信号——该公式条件苛刻，多数交易日为空是正常现象。
        </p>
      ) : (
        <div className="card-modern px-1 py-1">
          <div className="divide-y divide-border/40">
            {hits.map((h) => (
              <button
                key={h.code}
                onClick={() => openStock(hits, h.code)}
                className="w-full px-3 sm:px-4 py-2.5 hover:bg-elevated active:bg-inset rounded-xl transition-colors duration-100 text-left"
              >
                <div className="flex items-center gap-2 min-w-0">
                  <span className="text-sm font-medium text-ink truncate">
                    {h.name || h.code}
                  </span>
                  <span className="font-mono text-xs text-ink-muted shrink-0">
                    {h.code}
                  </span>
                  <span className="ml-auto flex items-center gap-1 shrink-0">
                    {h.signal_labels.map((label) => (
                      <span
                        key={label}
                        className="px-1.5 py-0.5 text-[10px] rounded bg-accent/10 text-accent whitespace-nowrap"
                      >
                        {label}
                      </span>
                    ))}
                  </span>
                </div>
                <div className="flex items-center gap-3 mt-1 text-xs text-ink-muted tabular-nums whitespace-nowrap min-w-0">
                  <span className="text-ink-secondary font-medium shrink-0">
                    {h.close.toFixed(2)}
                  </span>
                  <span className="shrink-0">J {h.J.toFixed(1)}</span>
                  <span className="shrink-0">RSI {h.RSI.toFixed(1)}</span>
                  {h.market_cap_yi > 0 && (
                    <span className="shrink-0">{h.market_cap_yi.toFixed(0)}亿</span>
                  )}
                  {h.industry && (
                    <span className="text-ink-muted/70 truncate min-w-0">
                      {h.industry}
                    </span>
                  )}
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
