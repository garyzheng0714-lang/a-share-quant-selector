import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { PageTransition } from "@/components/layout/page-transition";
import { Card, Skeleton, Badge, ProgressBar, CopyButton } from "@/components/ui";
import { EmptyState } from "@/components/onboarding";
import { useRanking } from "@/lib/hooks";
import { useAppStore } from "@/lib/store";
import { CATEGORY_LABELS, CATEGORY_BADGE_VARIANT, duration, ease } from "@/lib/tokens";
import type { RankingStock } from "@/lib/api";

const FILTERS: { key: string; label: string }[] = [
  { key: "all", label: "全部" },
  { key: "bowl_center", label: "回落碗中" },
  { key: "near_duokong", label: "靠近多空线" },
  { key: "near_short_trend", label: "靠近趋势线" },
];

const BREAKDOWN_LABELS: Record<string, string> = {
  kdj_state: "KDJ",
  price_shape: "形态",
  trend_structure: "趋势",
  volume_pattern: "量能",
};

function formatMarketCap(value: number): string {
  if (value >= 1e8) return `${(value / 1e8).toFixed(1)}亿`;
  if (value >= 1e4) return `${(value / 1e4).toFixed(1)}万`;
  return value.toFixed(0);
}

function rankColor(rank: number): string {
  if (rank === 1) return "text-accent";
  if (rank === 2) return "text-ink-secondary";
  if (rank === 3) return "text-ink-muted";
  return "text-ink-muted";
}

function scoreColor(score: number): string {
  if (score >= 85) return "bg-bear";
  if (score >= 60) return "bg-accent";
  return "bg-ink-muted";
}

function RankingCard({
  stock,
  rank,
  onClick,
}: {
  stock: RankingStock;
  rank: number;
  onClick: () => void;
}) {
  const score = stock.similarity_score ?? 0;
  const breakdown = stock.match_breakdown;

  return (
    <Card hoverable onClick={onClick} className="p-5">
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-3">
          <span
            className={`text-2xl font-bold tabular-nums ${rankColor(rank)}`}
          >
            {rank}
          </span>
          <div>
            <span className="flex items-center gap-1">
              <span className="font-mono text-sm text-accent">{stock.code}</span>
              <CopyButton text={stock.code} />
            </span>
            <p className="text-sm font-medium text-ink">{stock.name}</p>
          </div>
        </div>
        <Badge variant={CATEGORY_BADGE_VARIANT[stock.category] ?? "inactive"}>
          {CATEGORY_LABELS[stock.category] ?? stock.category}
        </Badge>
      </div>

      <div className="grid grid-cols-3 gap-3 text-sm mb-4">
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

      <div className="mb-3">
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-xs text-ink-muted">相似度</span>
          <span className="text-xs font-medium tabular-nums text-ink">
            {score.toFixed(0)}
          </span>
        </div>
        <div className="h-1.5 bg-elevated rounded-full overflow-hidden">
          <motion.div
            className={`h-full rounded-full ${scoreColor(score)}`}
            initial={{ width: 0 }}
            animate={{ width: `${Math.min(100, score)}%` }}
            transition={{ duration: duration.slow, ease: [...ease.default] }}
          />
        </div>
      </div>

      {breakdown && Object.keys(breakdown).length > 0 && (
        <div className="space-y-1.5 mb-3">
          {Object.entries(breakdown).map(([key, value]) => (
            <div key={key} className="flex items-center gap-2">
              <span className="text-xs text-ink-muted w-8 shrink-0 text-right">
                {BREAKDOWN_LABELS[key] ?? key}
              </span>
              <div className="flex-1 min-w-0">
                <ProgressBar value={value} />
              </div>
              <span className="text-xs text-ink-muted tabular-nums w-7 shrink-0 text-right">
                {value.toFixed(0)}
              </span>
            </div>
          ))}
        </div>
      )}

      {stock.views.length > 0 && (
        <div className="flex flex-wrap gap-1 pt-2 border-t border-border">
          {stock.views.map((v) => (
            <span
              key={v}
              className="text-xs bg-inset text-ink-muted px-2 py-0.5 rounded-md"
            >
              {v}
            </span>
          ))}
        </div>
      )}
    </Card>
  );
}

function RankingSkeleton() {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-[repeat(auto-fill,minmax(300px,1fr))] gap-3 sm:gap-4">
      {Array.from({ length: 6 }, (_, i) => (
        <Skeleton key={i} className="h-56 w-full" />
      ))}
    </div>
  );
}

export function Component() {
  const { data: ranking, isLoading } = useRanking();
  const [filter, setFilter] = useState("all");
  const navigate = useNavigate();
  const setStockNav = useAppStore((s) => s.setStockNav);

  const stocks = ranking?.data ?? [];
  const runDate = ranking?.run_date ?? "";
  const filtered =
    filter === "all"
      ? stocks
      : stocks.filter((s) => s.category === filter);

  const handleClick = (stock: RankingStock, index: number) => {
    const signalStocks = filtered.map((s) => ({
      code: s.code,
      name: s.name,
      strategy: "",
      category: s.category,
      close: s.close,
      J: s.J,
      volume_ratio: s.volume_ratio,
      market_cap: s.market_cap,
      short_term_trend: 0,
      bull_bear_line: 0,
      reasons: [],
      similarity_score: s.similarity_score,
      matched_case: s.matched_case,
      match_breakdown: s.match_breakdown,
    }));
    setStockNav(signalStocks, index);
    navigate(`/stock/${stock.code}`);
  };

  return (
    <PageTransition>
      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-4 sm:py-8">
        <div className="flex items-center justify-between mb-4 sm:mb-6">
          <h1 className="text-xl sm:text-2xl font-semibold text-ink">综合排名</h1>
          <div className="flex items-center gap-2">
            {runDate && (
              <span className="text-xs sm:text-sm text-ink-muted">{runDate}</span>
            )}
            {!isLoading && (
              <span className="text-xs sm:text-sm text-ink-muted tabular-nums">
                {filtered.length}只
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-1.5 sm:gap-2 mb-4 sm:mb-6 overflow-x-auto scrollbar-none pb-1">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              className={`px-3 sm:px-4 py-1.5 sm:py-2 text-xs sm:text-sm rounded-xl whitespace-nowrap shrink-0 transition-colors duration-150 ${
                filter === f.key
                  ? "bg-accent text-ink-inverse"
                  : "bg-surface text-ink-secondary hover:bg-elevated"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>

        {isLoading ? (
          <RankingSkeleton />
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
                <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
              </svg>
            }
            title="暂无排名数据"
            description="创建选股视图并运行策略后，综合排名将在这里展示"
            ctaLabel="去选股"
            onCta={() => navigate("/selection")}
          />
        ) : (
          <AnimatePresence mode="wait">
            <motion.div
              key={filter}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: duration.fast }}
              className="grid grid-cols-1 sm:grid-cols-[repeat(auto-fill,minmax(300px,1fr))] gap-3 sm:gap-4"
            >
              {filtered.map((stock, i) => (
                <RankingCard
                  key={stock.code}
                  stock={stock}
                  rank={i + 1}
                  onClick={() => handleClick(stock, i)}
                />
              ))}
            </motion.div>
          </AnimatePresence>
        )}
      </div>
    </PageTransition>
  );
}
