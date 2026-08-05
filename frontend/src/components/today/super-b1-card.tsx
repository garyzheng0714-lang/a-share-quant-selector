import { useState } from "react";
import { Button } from "@astryxdesign/core/Button";
import { Icon } from "@astryxdesign/core/Icon";
import { useNavigate } from "@/lib/spa-router";
import { Skeleton, LoadError } from "@/components/ui";
import { useSuperB1 } from "@/lib/hooks";
import { useAppStore } from "@/lib/store";
import type { SignalStock, SuperB1Hit } from "@/lib/api";

/**
 * 超级B1（知行公式）原始信号列表，也是分层决策的主候选入口。
 * 无信号是常态（公式条件苛刻），空态如实说明而不是留白。
 */
export function SuperB1Card({ initialLimit }: { initialLimit?: number } = {}) {
  const [showAll, setShowAll] = useState(false);
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
  const visibleHits = initialLimit && !showAll ? hits.slice(0, initialLimit) : hits;

  return (
    <section data-testid="super-b1">
      <p className="mb-3 text-[11px] leading-relaxed text-ink-muted">
        知行超级B1独立扫描
        {data?.trade_date && ` / ${data.trade_date}`}
        {!isLoading && data?.available && ` / ${hits.length}只`}
        。上层闸门只决定通过复核、研究候选或未通过
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
          今日全市场无超级B1信号。该公式条件苛刻，多数交易日为空是正常现象。
        </p>
      ) : (
        <div className="card-modern px-1 py-1">
          <div className="reveal-list divide-y divide-border/40">
            {visibleHits.map((h) => (
              <Button
                key={h.code}
                label={`查看 ${h.name || h.code}`}
                variant="ghost"
                width="100%"
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
              </Button>
            ))}
          </div>
          {initialLimit && hits.length > initialLimit && (
            <Button label={showAll ? "收起" : `查看全部 ${hits.length} 只`} variant="ghost" width="100%" onClick={() => setShowAll((value) => !value)} className="border-t border-border">
              {showAll ? "收起" : `查看全部 ${hits.length} 只`}
              <Icon icon="chevronDown" size="xsm" />
            </Button>
          )}
        </div>
      )}
    </section>
  );
}
