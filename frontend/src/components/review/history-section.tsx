import { useState } from "react";
import { useNavigate } from "@/lib/spa-router";
import { Button } from "@astryxdesign/core/Button";
import { Icon } from "@astryxdesign/core/Icon";
import { Selector } from "@astryxdesign/core/Selector";
import { Skeleton, Badge, CopyButton } from "@/components/ui";
import { EmptyState } from "@/components/onboarding";
import { useViews, useViewResults } from "@/lib/hooks";
import { CATEGORY_LABELS, CATEGORY_BADGE_VARIANT } from "@/lib/tokens";
import type { SelectionResult, SignalStock } from "@/lib/api";

// 选股结果里的 market_cap 单位是「亿」（策略层已除过 1e8），与 candidate-list 同口径
function formatMarketCap(value: number): string {
  if (!value || value <= 0) return "";
  if (value >= 1e4) return `${(value / 1e4).toFixed(1)}万亿`;
  return `${value >= 100 ? value.toFixed(0) : value.toFixed(1)}亿`;
}

function ChevronToggle({ expanded }: { expanded: boolean }) {
  return (
    <span className={`inline-flex transition-transform ${expanded ? "rotate-90" : ""}`}>
      <Icon icon="chevronRight" size="sm" />
    </span>
  );
}

function StockRow({
  stock,
  onClick,
}: {
  stock: SignalStock;
  onClick: () => void;
}) {
  const score = stock.similarity_score;

  return (
    <Button
      label={`查看 ${stock.name || stock.code}`}
      variant="ghost"
      width="100%"
      onClick={onClick}
      className="w-full flex items-center gap-3 px-3 sm:px-4 py-2 sm:py-2.5 hover:bg-elevated active:bg-inset transition-colors duration-100 text-left group"
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className="text-sm font-medium text-ink truncate">
            {stock.name}
          </span>
          <span className="font-mono text-xs text-ink-muted">{stock.code}</span>
          <CopyButton text={stock.code} />
        </div>
        <div className="flex items-center gap-3 mt-0.5">
          <span className="text-xs text-ink-muted tabular-nums">
            {stock.close.toFixed(2)}
          </span>
          <span className="text-xs text-ink-muted tabular-nums">
            J {stock.J.toFixed(1)}
          </span>
          <span className="text-xs text-ink-muted">
            {formatMarketCap(stock.market_cap)}
          </span>
          {stock.industry && (
            <span className="text-xs text-ink-muted/70">{stock.industry}</span>
          )}
        </div>
      </div>

      <Badge
        variant={CATEGORY_BADGE_VARIANT[stock.category] ?? "inactive"}
        className="hidden sm:inline-flex shrink-0"
      >
        {CATEGORY_LABELS[stock.category] ?? stock.category}
      </Badge>

      {score !== null && (
        <span
          className={`text-xs font-medium tabular-nums shrink-0 ${
            score >= 85
              ? "text-bull"
              : score >= 60
                ? "text-accent-light"
                : "text-ink-muted"
          }`}
        >
          {score.toFixed(0)}
        </span>
      )}

      <Icon icon="chevronRight" size="xsm" color="secondary" />
    </Button>
  );
}

function DateRow({
  result,
  expanded,
  onToggle,
  onStockClick,
}: {
  result: SelectionResult;
  expanded: boolean;
  onToggle: () => void;
  onStockClick: (stock: SignalStock) => void;
}) {
  const categoryEntries = Object.entries(result.category_count ?? {});

  return (
    <div>
      <Button
        label={`展开 ${result.run_date}`}
        variant="ghost"
        width="100%"
        onClick={onToggle}
        className="w-full flex items-center gap-2 sm:gap-3 px-3 sm:px-4 py-3 rounded-xl hover:bg-elevated transition-colors duration-150 text-left"
      >
        <ChevronToggle expanded={expanded} />
        <span className="font-medium text-sm text-ink shrink-0">
          {result.run_date}
        </span>
        <span className="text-xs text-ink-muted tabular-nums shrink-0">
          {result.total || result.stocks.length}只
        </span>
        <div className="hidden sm:flex items-center gap-1.5 ml-auto">
          {categoryEntries.map(([cat, count]) => (
            <span
              key={cat}
              className="text-xs bg-inset text-ink-muted px-2 py-0.5 rounded-md whitespace-nowrap"
            >
              {CATEGORY_LABELS[cat] ?? cat} {count}
            </span>
          ))}
        </div>
      </Button>

      {expanded && (
          <div className="view-enter overflow-hidden">
            <div className="divide-y divide-border/30 ml-6 mr-2 mb-3 border-l border-border/40 pl-1">
              {result.stocks.map((stock) => (
                <StockRow
                  key={stock.code}
                  stock={stock}
                  onClick={() => onStockClick(stock)}
                />
              ))}
            </div>
          </div>
      )}
    </div>
  );
}

/** 每日名单：历史每个交易日选出的完整名单（可展开） */
export function HistorySection() {
  const { data: views } = useViews();
  const [selectedViewId, setSelectedViewId] = useState<number | null>(null);
  const effectiveViewId = selectedViewId ?? views?.[0]?.id ?? null;
  const { data: results, isLoading } = useViewResults(effectiveViewId, 20);
  const [expandedDate, setExpandedDate] = useState<string | null>(null);
  const navigate = useNavigate();

  const handleStockClick = (stock: SignalStock) => {
    navigate(`/stock/${stock.code}`);
  };

  return (
    <div>
      {views && views.length > 1 && (
        <div className="flex justify-end mb-3">
          <div className="relative">
            <Selector
              label="历史视图"
              isLabelHidden
              options={(views ?? []).map((view) => ({ value: String(view.id), label: view.name }))}
              value={effectiveViewId == null ? "" : String(effectiveViewId)}
              onChange={(val) => {
                setSelectedViewId(val ? Number(val) : null);
                setExpandedDate(null);
              }}
              size="sm"
            >
            </Selector>
          </div>
        </div>
      )}

      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 5 }, (_, i) => (
            <Skeleton key={i} className="h-12 w-full rounded-xl" />
          ))}
        </div>
      ) : !results?.length ? (
        <EmptyState
          icon={<Icon icon="calendar" size="md" />}
          title="暂无历史记录"
          description="每个交易日选股后，当天的名单会自动保存在这里"
        />
      ) : (
        <div key={effectiveViewId} className="view-enter space-y-0.5">
            {results.map((result) => (
              <DateRow
                key={result.run_date}
                result={result}
                expanded={expandedDate === result.run_date}
                onToggle={() =>
                  setExpandedDate((prev) =>
                    prev === result.run_date ? null : result.run_date,
                  )
                }
                onStockClick={handleStockClick}
              />
            ))}
        </div>
      )}
    </div>
  );
}
