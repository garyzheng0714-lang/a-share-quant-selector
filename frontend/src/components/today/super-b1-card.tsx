import { useState } from "react";
import { Button } from "@astryxdesign/core/Button";
import { Icon } from "@astryxdesign/core/Icon";
import { List, ListItem } from "@astryxdesign/core/List";
import { Token } from "@astryxdesign/core/Token";
import { useNavigate } from "@/lib/spa-router";
import { Skeleton, LoadError } from "@/components/ui";
import { useSuperB1 } from "@/lib/hooks";
import { useAppStore } from "@/lib/store";
import type { SignalStock, SuperB1Hit } from "@/lib/api";

/** 命中行：名称+代码 / 价格·J·RSI·市值·行业，信号标签落在行尾 */
function SuperB1Row({ hit, onClick }: { hit: SuperB1Hit; onClick: () => void }) {
  return (
    <ListItem
      label={
        <span className="flex min-w-0 items-baseline gap-2">
          <span className="truncate text-sm font-medium text-ink">
            {hit.name || hit.code}
          </span>
          <span className="shrink-0 font-mono text-xs text-ink-muted">
            {hit.code}
          </span>
        </span>
      }
      description={
        <span className="mt-0.5 flex min-w-0 items-center gap-3 whitespace-nowrap text-xs tabular-nums text-ink-muted">
          <span className="shrink-0 font-medium text-ink-secondary">
            {hit.close.toFixed(2)}
          </span>
          <span className="shrink-0">J {hit.J.toFixed(1)}</span>
          <span className="shrink-0">RSI {hit.RSI.toFixed(1)}</span>
          {hit.market_cap_yi > 0 && (
            <span className="shrink-0">{hit.market_cap_yi.toFixed(0)}亿</span>
          )}
          {hit.industry && (
            <span className="min-w-0 truncate text-ink-muted/70">{hit.industry}</span>
          )}
        </span>
      }
      endContent={
        hit.signal_labels.length ? (
          <span className="flex items-center gap-1">
            {hit.signal_labels.map((label) => (
              <Token key={label} label={label} size="sm" />
            ))}
          </span>
        ) : undefined
      }
      onClick={onClick}
    />
  );
}

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
          <List density="compact" hasDividers aria-label="超级B1命中列表">
            {visibleHits.map((h) => (
              <SuperB1Row key={h.code} hit={h} onClick={() => openStock(hits, h.code)} />
            ))}
          </List>
          {initialLimit && hits.length > initialLimit && (
            <Button
              label={showAll ? "收起" : `查看全部 ${hits.length} 只`}
              variant="ghost"
              width="100%"
              onClick={() => setShowAll((value) => !value)}
              className="border-t border-border"
              endContent={!showAll ? <Icon icon="chevronDown" size="xsm" /> : undefined}
            />
          )}
        </div>
      )}
    </section>
  );
}
