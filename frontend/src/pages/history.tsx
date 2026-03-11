import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { PageTransition } from "@/components/layout/page-transition";
import { Skeleton, Badge, CopyButton } from "@/components/ui";
import { EmptyState } from "@/components/onboarding";
import { useViews, useViewResults } from "@/lib/hooks";
import { CATEGORY_LABELS, CATEGORY_BADGE_VARIANT, duration, ease } from "@/lib/tokens";
import type { SelectionResult, SignalStock } from "@/lib/api";

function formatMarketCap(value: number): string {
  if (value >= 1e8) return `${(value / 1e8).toFixed(0)}亿`;
  if (value >= 1e4) return `${(value / 1e4).toFixed(0)}万`;
  return `${value.toFixed(0)}亿`;
}

function ChevronIcon({ expanded }: { expanded: boolean }) {
  return (
    <motion.svg
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      animate={{ rotate: expanded ? 90 : 0 }}
      transition={{ duration: duration.fast }}
    >
      <path
        d="M6 4l4 4-4 4"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </motion.svg>
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
    <button
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
              ? "text-bear"
              : score >= 60
                ? "text-accent"
                : "text-ink-muted"
          }`}
        >
          {score.toFixed(0)}
        </span>
      )}

      <svg
        width="14"
        height="14"
        viewBox="0 0 14 14"
        fill="none"
        className="text-ink-muted/50 shrink-0 group-hover:text-ink-muted transition-colors"
      >
        <path
          d="M5.25 3.5L8.75 7l-3.5 3.5"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </button>
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
      <motion.button
        onClick={onToggle}
        className="w-full flex items-center gap-2 sm:gap-3 px-3 sm:px-4 py-3 rounded-xl hover:bg-elevated transition-colors duration-150 text-left"
      >
        <ChevronIcon expanded={expanded} />
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
      </motion.button>

      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: duration.normal, ease: [...ease.default] }}
            className="overflow-hidden"
          >
            <div className="divide-y divide-border/30 ml-6 mr-2 mb-3 border-l border-border/40 pl-1">
              {result.stocks.map((stock) => (
                <StockRow
                  key={stock.code}
                  stock={stock}
                  onClick={() => onStockClick(stock)}
                />
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function HistorySkeleton() {
  return (
    <div className="space-y-2">
      {Array.from({ length: 5 }, (_, i) => (
        <Skeleton key={i} className="h-12 w-full rounded-xl" />
      ))}
    </div>
  );
}

export function Component() {
  const { data: views } = useViews();
  const [selectedViewId, setSelectedViewId] = useState<number | null>(null);
  const { data: results, isLoading } = useViewResults(selectedViewId, 20);
  const [expandedDate, setExpandedDate] = useState<string | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    if (views?.length && selectedViewId === null) {
      setSelectedViewId(views[0].id);
    }
  }, [views, selectedViewId]);

  const handleStockClick = (stock: SignalStock) => {
    navigate(`/stock/${stock.code}`);
  };

  return (
    <PageTransition>
      <div className="max-w-3xl mx-auto px-4 sm:px-8 py-6 sm:py-10">
        <div className="flex items-center justify-between mb-5 sm:mb-6">
          <h1 className="text-xl sm:text-2xl font-bold tracking-[-0.03em] text-ink">
            历史记录
          </h1>
          <div className="relative">
            <select
              value={selectedViewId ?? ""}
              onChange={(e) => {
                const val = e.target.value;
                setSelectedViewId(val ? Number(val) : null);
                setExpandedDate(null);
              }}
              className="h-9 pl-3 pr-7 bg-elevated rounded-full text-xs sm:text-sm text-ink border border-border appearance-none cursor-pointer transition-all duration-150 focus:border-border-focus focus:ring-2 focus:ring-accent/10"
            >
              {!views?.length && <option value="">加载中...</option>}
              {views?.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.name}
                </option>
              ))}
            </select>
            <svg
              className="absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none text-ink-muted"
              width="12"
              height="12"
              viewBox="0 0 14 14"
              fill="none"
            >
              <path
                d="M3.5 5.25L7 8.75l3.5-3.5"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </div>
        </div>

        {isLoading ? (
          <HistorySkeleton />
        ) : !results?.length ? (
          selectedViewId === null ? (
            <EmptyState
              icon={
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
                  <rect
                    x="3"
                    y="3"
                    width="18"
                    height="18"
                    rx="3"
                    stroke="currentColor"
                    strokeWidth="1.5"
                  />
                  <path
                    d="M9 12l2 2 4-4"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              }
              title="请选择一个视图"
              description="从右上角下拉菜单选择视图，查看对应的历史选股记录"
            />
          ) : (
            <EmptyState
              icon={
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
                  <circle
                    cx="12"
                    cy="12"
                    r="9"
                    stroke="currentColor"
                    strokeWidth="1.5"
                  />
                  <path
                    d="M12 7v5l3 3"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              }
              title="暂无历史记录"
              description="运行选股策略后，每次结果会自动保存在这里"
            />
          )
        ) : (
          <AnimatePresence mode="wait">
            <motion.div
              key={selectedViewId}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: duration.fast }}
              className="space-y-0.5"
            >
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
            </motion.div>
          </AnimatePresence>
        )}
      </div>
    </PageTransition>
  );
}
