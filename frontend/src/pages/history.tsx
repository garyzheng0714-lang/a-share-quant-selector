import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { PageTransition } from "@/components/layout/page-transition";
import { Card, Skeleton, Badge, CopyButton } from "@/components/ui";
import { useViews, useViewResults } from "@/lib/hooks";
import { CATEGORY_LABELS, CATEGORY_BADGE_VARIANT } from "@/lib/tokens";
import type { SelectionResult, SignalStock } from "@/lib/api";

function formatMarketCap(value: number): string {
  if (value >= 1e8) return `${(value / 1e8).toFixed(1)}亿`;
  if (value >= 1e4) return `${(value / 1e4).toFixed(1)}万`;
  return value.toFixed(0);
}

function ChevronIcon({ expanded }: { expanded: boolean }) {
  return (
    <motion.svg
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      animate={{ rotate: expanded ? 90 : 0 }}
      transition={{ duration: 0.15 }}
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

function SignalCard({
  stock,
  onClick,
}: {
  stock: SignalStock;
  onClick: () => void;
}) {
  return (
    <Card hoverable onClick={onClick} className="p-4">
      <div className="flex items-center justify-between mb-2">
        <div>
          <span className="font-mono text-sm text-accent">{stock.code}</span>
          <CopyButton text={stock.code} />
          <span className="text-sm font-medium text-ink ml-2">
            {stock.name}
          </span>
        </div>
        <Badge variant={CATEGORY_BADGE_VARIANT[stock.category] ?? "inactive"}>
          {CATEGORY_LABELS[stock.category] ?? stock.category}
        </Badge>
      </div>
      <div className="grid grid-cols-3 gap-2 text-sm">
        <div>
          <span className="text-ink-muted text-xs">价格</span>
          <p className="font-medium text-ink tabular-nums">
            {stock.close.toFixed(2)}
          </p>
        </div>
        <div>
          <span className="text-ink-muted text-xs">J值</span>
          <p className="font-medium text-ink tabular-nums">
            {stock.J.toFixed(1)}
          </p>
        </div>
        <div>
          <span className="text-ink-muted text-xs">市值</span>
          <p className="font-medium text-ink-secondary">
            {formatMarketCap(stock.market_cap)}
          </p>
        </div>
      </div>
      {stock.similarity_score !== null && (
        <div className="mt-2 flex items-center gap-2">
          <span className="text-xs text-ink-muted">相似度</span>
          <div className="flex-1 h-1 bg-inset rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full ${
                stock.similarity_score >= 85
                  ? "bg-bear"
                  : stock.similarity_score >= 60
                    ? "bg-accent"
                    : "bg-ink-muted"
              }`}
              style={{
                width: `${Math.min(100, stock.similarity_score)}%`,
              }}
            />
          </div>
          <span className="text-xs text-ink-muted tabular-nums w-7 text-right">
            {stock.similarity_score.toFixed(0)}
          </span>
        </div>
      )}
    </Card>
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
        className="w-full flex items-center gap-2 sm:gap-3 px-3 sm:px-4 py-3 sm:py-3.5 rounded-xl hover:bg-elevated transition-colors duration-150 text-left"
      >
        <ChevronIcon expanded={expanded} />
        <span className="font-medium text-sm sm:text-base text-ink shrink-0">{result.run_date}</span>
        <span className="text-xs sm:text-sm text-ink-muted tabular-nums shrink-0">
          {result.total}只
        </span>
        <div className="flex items-center gap-1 sm:gap-1.5 ml-auto overflow-hidden">
          {categoryEntries.map(([cat, count]) => (
            <span
              key={cat}
              className="text-[10px] sm:text-xs bg-inset text-ink-muted px-1.5 sm:px-2 py-0.5 rounded-md whitespace-nowrap"
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
            transition={{ duration: 0.25, ease: [0.25, 0.1, 0.25, 1] }}
            className="overflow-hidden"
          >
            <div className="grid grid-cols-1 sm:grid-cols-[repeat(auto-fill,minmax(280px,1fr))] gap-3 px-3 sm:px-4 pb-4 pt-1">
              {result.stocks.map((stock) => (
                <SignalCard
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
        <Skeleton key={i} className="h-14 w-full" />
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
      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-4 sm:py-8">
        <div className="flex items-center justify-between mb-4 sm:mb-6">
          <h1 className="text-xl sm:text-2xl font-semibold text-ink">历史记录</h1>
          <div className="relative">
            <select
              value={selectedViewId ?? ""}
              onChange={(e) => {
                const val = e.target.value;
                setSelectedViewId(val ? Number(val) : null);
                setExpandedDate(null);
              }}
              className="h-10 pl-3 pr-8 bg-inset rounded-xl text-sm text-ink border border-border appearance-none cursor-pointer transition-all duration-150 focus:border-border-focus focus:ring-2 focus:ring-accent/10"
            >
              {!views?.length && (
                <option value="">加载中...</option>
              )}
              {views?.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.name}
                </option>
              ))}
            </select>
            <svg
              className="absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none text-ink-muted"
              width="14"
              height="14"
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
          <div className="text-center py-16 text-ink-muted">
            {selectedViewId === null ? "请选择一个视图" : "暂无历史记录"}
          </div>
        ) : (
          <AnimatePresence mode="wait">
            <motion.div
              key={selectedViewId}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="space-y-1"
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
