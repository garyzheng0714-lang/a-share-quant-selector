import { useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { PageTransition } from "@/components/layout/page-transition";
import { Skeleton, Badge, CopyButton } from "@/components/ui";
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

function formatMarketCap(value: number): string {
  if (value >= 1e8) return `${(value / 1e8).toFixed(0)}亿`;
  if (value >= 1e4) return `${(value / 1e4).toFixed(0)}万`;
  return `${value.toFixed(0)}亿`;
}

function scoreBar(score: number) {
  const color =
    score >= 85 ? "bg-bear" : score >= 60 ? "bg-accent" : "bg-ink-muted";
  return (
    <div className="flex items-center gap-1.5 min-w-[80px]">
      <div className="flex-1 h-1.5 bg-elevated rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full ${color}`}
          style={{ width: `${Math.min(100, score)}%` }}
        />
      </div>
      <span className="text-xs tabular-nums text-ink-muted w-6 text-right">
        {score.toFixed(0)}
      </span>
    </div>
  );
}

function RankingRow({
  stock,
  rank,
  onClick,
}: {
  stock: RankingStock;
  rank: number;
  onClick: () => void;
}) {
  const score = stock.similarity_score ?? 0;

  return (
    <button
      onClick={onClick}
      className="w-full flex items-center gap-3 px-3 sm:px-4 py-2.5 sm:py-3 rounded-xl hover:bg-elevated active:bg-inset transition-colors duration-100 text-left group"
    >
      <span
        className={`text-sm font-bold tabular-nums w-5 text-center shrink-0 ${
          rank <= 3 ? "text-accent" : "text-ink-muted"
        }`}
      >
        {rank}
      </span>

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

      <div className="shrink-0 hidden sm:block">{scoreBar(score)}</div>

      <div className="shrink-0 sm:hidden">
        <span
          className={`text-xs font-medium tabular-nums ${
            score >= 85
              ? "text-bear"
              : score >= 60
                ? "text-accent"
                : "text-ink-muted"
          }`}
        >
          {score.toFixed(0)}
        </span>
      </div>

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

function RankingSkeleton() {
  return (
    <div className="space-y-1">
      {Array.from({ length: 10 }, (_, i) => (
        <Skeleton key={i} className="h-14 w-full rounded-xl" />
      ))}
    </div>
  );
}

type ViewMode = "ranking" | "industry";

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

function IndustryGroup({
  industry,
  stocks,
  expanded,
  onToggle,
  onStockClick,
}: {
  industry: string;
  stocks: RankingStock[];
  expanded: boolean;
  onToggle: () => void;
  onStockClick: (stock: RankingStock, index: number) => void;
}) {
  return (
    <div>
      <motion.button
        onClick={onToggle}
        className="w-full flex items-center gap-2 sm:gap-3 px-3 sm:px-4 py-3 rounded-xl hover:bg-elevated transition-colors duration-150 text-left"
      >
        <ChevronIcon expanded={expanded} />
        <span className="font-medium text-sm text-ink shrink-0">
          {industry}
        </span>
        <span className="text-xs text-ink-muted tabular-nums shrink-0">
          {stocks.length}只
        </span>
        <div className="hidden sm:flex items-center gap-1.5 ml-auto">
          {Object.entries(
            stocks.reduce<Record<string, number>>((acc, s) => {
              acc[s.category] = (acc[s.category] ?? 0) + 1;
              return acc;
            }, {}),
          ).map(([cat, count]) => (
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
              {stocks.map((stock, i) => (
                <RankingRow
                  key={stock.code}
                  stock={stock}
                  rank={i + 1}
                  onClick={() => onStockClick(stock, i)}
                />
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export function Component() {
  const { data: ranking, isLoading } = useRanking();
  const [filter, setFilter] = useState("all");
  const [viewMode, setViewMode] = useState<ViewMode>("ranking");
  const [expandedIndustry, setExpandedIndustry] = useState<string | null>(null);
  const navigate = useNavigate();
  const setStockNav = useAppStore((s) => s.setStockNav);

  const stocks = ranking?.data ?? [];
  const runDate = ranking?.run_date ?? "";
  const filtered =
    filter === "all"
      ? stocks
      : stocks.filter((s) => s.category === filter);

  const industryGroups = useMemo(() => {
    const groups: Record<string, RankingStock[]> = {};
    for (const s of filtered) {
      const key = s.industry || "未知";
      if (!groups[key]) groups[key] = [];
      groups[key].push(s);
    }
    return Object.entries(groups).sort((a, b) => b[1].length - a[1].length);
  }, [filtered]);

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
      <div className="max-w-3xl mx-auto px-4 sm:px-8 py-6 sm:py-10">
        <div className="flex items-center justify-between mb-5 sm:mb-6">
          <h1 className="text-xl sm:text-2xl font-bold tracking-[-0.03em] text-ink">
            综合排名
          </h1>
          <div className="flex items-center gap-2">
            {runDate && (
              <span className="text-xs text-ink-muted">{runDate}</span>
            )}
            {!isLoading && (
              <span className="text-xs text-ink-muted tabular-nums">
                {filtered.length}只
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-1.5 sm:gap-2 mb-4 sm:mb-5 overflow-x-auto scrollbar-none pb-1">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              className={`px-3 sm:px-4 py-1.5 text-xs sm:text-sm rounded-full whitespace-nowrap shrink-0 transition-colors duration-150 ${
                filter === f.key
                  ? "bg-accent text-ink-inverse font-medium"
                  : "bg-surface text-ink-muted hover:bg-elevated hover:text-ink-secondary"
              }`}
            >
              {f.label}
            </button>
          ))}

          <div className="w-px h-5 bg-border/50 shrink-0 mx-1" />

          {(["ranking", "industry"] as const).map((mode) => (
            <button
              key={mode}
              onClick={() => {
                setViewMode(mode);
                if (mode === "industry") setExpandedIndustry(null);
              }}
              className={`px-3 sm:px-4 py-1.5 text-xs sm:text-sm rounded-full whitespace-nowrap shrink-0 transition-colors duration-150 ${
                viewMode === mode
                  ? "bg-elevated text-ink font-medium ring-1 ring-border"
                  : "text-ink-muted hover:text-ink-secondary"
              }`}
            >
              {mode === "ranking" ? "排名" : "行业"}
            </button>
          ))}
        </div>

        {isLoading ? (
          <RankingSkeleton />
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
                <path
                  d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinejoin="round"
                />
              </svg>
            }
            title="暂无排名数据"
            description="运行策略后，综合排名将在这里展示"
          />
        ) : (
          <AnimatePresence mode="wait">
            {viewMode === "ranking" ? (
              <motion.div
                key={`ranking-${filter}`}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: duration.fast }}
                className="divide-y divide-border/50"
              >
                {filtered.map((stock, i) => (
                  <motion.div
                    key={stock.code}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{
                      duration: 0.15,
                      delay: Math.min(i * 0.02, 0.4),
                    }}
                  >
                    <RankingRow
                      stock={stock}
                      rank={i + 1}
                      onClick={() => handleClick(stock, i)}
                    />
                  </motion.div>
                ))}
              </motion.div>
            ) : (
              <motion.div
                key={`industry-${filter}`}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: duration.fast }}
                className="space-y-0.5"
              >
                {industryGroups.map(([industry, groupStocks]) => (
                  <IndustryGroup
                    key={industry}
                    industry={industry}
                    stocks={groupStocks}
                    expanded={expandedIndustry === industry}
                    onToggle={() =>
                      setExpandedIndustry((prev) =>
                        prev === industry ? null : industry,
                      )
                    }
                    onStockClick={(stock, index) => handleClick(stock, index)}
                  />
                ))}
              </motion.div>
            )}
          </AnimatePresence>
        )}
      </div>
    </PageTransition>
  );
}
