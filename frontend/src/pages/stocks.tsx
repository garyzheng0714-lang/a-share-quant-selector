import { useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { AnimatePresence, LayoutGroup, motion } from "framer-motion";
import { duration } from "@/lib/tokens";
import { PageTransition } from "@/components/layout/page-transition";
import { Card, Skeleton, Button, Input } from "@/components/ui";
import { useStocks } from "@/lib/hooks";
import { useAppStore } from "@/lib/store";
import type { StockItem } from "@/lib/api";

function formatMarketCap(value: number): string {
  if (value >= 1e8) return `${(value / 1e8).toFixed(0)}亿`;
  if (value >= 1e4) return `${(value / 1e4).toFixed(0)}万`;
  return `${value.toFixed(0)}亿`;
}

function ListIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
      <rect x="2" y="3" width="14" height="2" rx="1" fill="currentColor" />
      <rect x="2" y="8" width="14" height="2" rx="1" fill="currentColor" />
      <rect x="2" y="13" width="14" height="2" rx="1" fill="currentColor" />
    </svg>
  );
}

function GridIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
      <rect x="2" y="2" width="6" height="6" rx="1.5" fill="currentColor" />
      <rect x="10" y="2" width="6" height="6" rx="1.5" fill="currentColor" />
      <rect x="2" y="10" width="6" height="6" rx="1.5" fill="currentColor" />
      <rect x="10" y="10" width="6" height="6" rx="1.5" fill="currentColor" />
    </svg>
  );
}

function StockRow({ stock, onClick }: { stock: StockItem; onClick: () => void }) {
  return (
    <motion.div
      layout
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      onClick={onClick}
      className="group grid grid-cols-[5rem_1fr_5rem] sm:grid-cols-[7rem_2fr_1fr_1fr_1fr] items-center h-11 sm:h-12 px-3 sm:px-4 border-l-2 border-transparent hover:bg-surface-hover hover:border-accent transition-colors duration-150 cursor-pointer rounded-lg"
    >
      <span className="font-mono text-xs sm:text-sm text-accent">
        {stock.code}
      </span>
      <span className="text-xs sm:text-sm text-ink font-medium truncate">
        {stock.name}
      </span>
      <span className="text-xs sm:text-sm text-ink tabular-nums text-right">
        {stock.latest_price.toFixed(2)}
      </span>
      <span className="hidden sm:block text-sm text-ink-secondary text-right">
        {formatMarketCap(stock.market_cap)}
      </span>
      <span className="hidden sm:block text-sm text-ink-muted text-right">
        {stock.data_count}
      </span>
    </motion.div>
  );
}

function StockCard({ stock, onClick }: { stock: StockItem; onClick: () => void }) {
  return (
    <Card hoverable onClick={onClick} className="p-4">
      <div className="flex items-center justify-between mb-3">
        <span className="font-mono text-sm text-accent">{stock.code}</span>
        <span className="text-xs text-ink-muted bg-inset px-2 py-0.5 rounded-md">
          {formatMarketCap(stock.market_cap)}
        </span>
      </div>
      <p className="text-sm font-medium text-ink truncate">{stock.name}</p>
      <p className="text-lg font-semibold text-ink mt-1 tabular-nums">
        {stock.latest_price.toFixed(2)}
      </p>
    </Card>
  );
}

function ListSkeleton() {
  return (
    <div className="space-y-2">
      {Array.from({ length: 10 }, (_, i) => (
        <Skeleton key={i} className="h-14 w-full" />
      ))}
    </div>
  );
}

function GridSkeleton() {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-[repeat(auto-fill,minmax(260px,1fr))] gap-4 sm:gap-5">
      {Array.from({ length: 8 }, (_, i) => (
        <Skeleton key={i} className="h-28 w-full" />
      ))}
    </div>
  );
}

export function Component() {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const { data, isLoading } = useStocks(page);
  const viewMode = useAppStore((s) => s.stockListViewMode);
  const toggleViewMode = useAppStore((s) => s.toggleStockListViewMode);
  const navigate = useNavigate();

  const stocks = data?.data ?? [];
  const totalPages = data?.total_pages ?? 1;

  const filtered = useMemo(() => {
    if (!search) return stocks;
    const q = search.toLowerCase();
    return stocks.filter(
      (s) => s.code.includes(q) || s.name.toLowerCase().includes(q),
    );
  }, [stocks, search]);

  return (
    <PageTransition>
      <div className="max-w-6xl mx-auto px-5 sm:px-8 lg:px-16 py-6 sm:py-12">
        <div className="flex flex-col sm:flex-row sm:items-center gap-3 sm:justify-between mb-6 sm:mb-8">
          <h1 className="text-2xl sm:text-3xl font-bold tracking-[-0.03em] text-ink">股票列表</h1>
          <div className="flex items-center gap-2">
            <div className="flex-1 sm:w-56">
              <Input
                placeholder="搜索代码或名称..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <div className="flex items-center bg-inset rounded-[16px] p-1 shrink-0">
              <button
                onClick={() => viewMode !== "list" && toggleViewMode()}
                className={`p-2 rounded-lg transition-colors duration-150 ${
                  viewMode === "list"
                    ? "bg-surface text-accent shadow-card"
                    : "text-ink-muted hover:text-ink"
                }`}
                aria-label="列表视图"
              >
                <ListIcon />
              </button>
              <button
                onClick={() => viewMode !== "card" && toggleViewMode()}
                className={`p-2 rounded-lg transition-colors duration-150 ${
                  viewMode === "card"
                    ? "bg-surface text-accent shadow-card"
                    : "text-ink-muted hover:text-ink"
                }`}
                aria-label="卡片视图"
              >
                <GridIcon />
              </button>
            </div>
          </div>
        </div>

        {isLoading ? (
          viewMode === "list" ? <ListSkeleton /> : <GridSkeleton />
        ) : (
          <LayoutGroup>
            <AnimatePresence mode="wait">
              {viewMode === "list" ? (
                <motion.div
                  key="list"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: duration.fast }}
                >
                  <div className="grid grid-cols-[5rem_1fr_5rem] sm:grid-cols-[7rem_2fr_1fr_1fr_1fr] items-center h-10 px-3 sm:px-4 text-xs text-ink-muted font-medium border-b border-border mb-1">
                    <span>代码</span>
                    <span>名称</span>
                    <span className="text-right">最新价</span>
                    <span className="hidden sm:block text-right">市值</span>
                    <span className="hidden sm:block text-right">数据量</span>
                  </div>
                  <div className="space-y-0.5">
                    {filtered.map((stock) => (
                      <StockRow
                        key={stock.code}
                        stock={stock}
                        onClick={() => navigate(`/stock/${stock.code}`)}
                      />
                    ))}
                  </div>
                </motion.div>
              ) : (
                <motion.div
                  key="card"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: duration.fast }}
                  className="grid grid-cols-2 sm:grid-cols-[repeat(auto-fill,minmax(260px,1fr))] gap-4 sm:gap-5"
                >
                  {filtered.map((stock, i) => (
                    <motion.div
                      key={stock.code}
                      initial={{ opacity: 0, y: 12 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{
                        duration: 0.2,
                        delay: Math.min(i * 0.04, 0.5),
                        ease: [0.25, 0.1, 0.25, 1],
                      }}
                    >
                      <StockCard
                        stock={stock}
                        onClick={() => navigate(`/stock/${stock.code}`)}
                      />
                    </motion.div>
                  ))}
                </motion.div>
              )}
            </AnimatePresence>
          </LayoutGroup>
        )}

        {filtered.length === 0 && !isLoading && (
          <div className="text-center py-16 text-ink-muted">
            {search ? "未找到匹配的股票" : "暂无数据"}
          </div>
        )}

        {!search && totalPages > 1 && (
          <div className="flex items-center justify-center gap-3 mt-8">
            <Button
              variant="secondary"
              size="sm"
              disabled={page <= 1}
              onClick={() => setPage((p) => p - 1)}
            >
              上一页
            </Button>
            <span className="text-sm text-ink-secondary tabular-nums">
              {page} / {totalPages}
            </span>
            <Button
              variant="secondary"
              size="sm"
              disabled={page >= totalPages}
              onClick={() => setPage((p) => p + 1)}
            >
              下一页
            </Button>
          </div>
        )}
      </div>
    </PageTransition>
  );
}
