import { PageTransition } from "@/components/layout/page-transition";
import {
  Card,
  Skeleton,
  Badge,
  AnimatedNumber,
  CopyButton,
} from "@/components/ui";
import { WorkflowGuideBanner, EmptyState } from "@/components/onboarding";
import { useStats, useRanking } from "@/lib/hooks";
import { CATEGORY_LABELS, CATEGORY_BADGE_VARIANT } from "@/lib/tokens";
import { useAppStore } from "@/lib/store";
import { useNavigate } from "react-router-dom";

export function Component() {
  const { data: stats, isLoading: statsLoading } = useStats();
  const { data: ranking, isLoading: rankingLoading } = useRanking();
  const navigate = useNavigate();
  const setStockNav = useAppStore((s) => s.setStockNav);

  const topStocks = ranking?.data?.slice(0, 10) ?? [];

  const handleStockClick = (code: string, index: number) => {
    if (ranking?.data) {
      setStockNav(
        ranking.data.map((s) => ({
          code: s.code,
          name: s.name,
          category: s.category,
          close: s.close,
          J: s.J,
          volume_ratio: s.volume_ratio,
          market_cap: s.market_cap,
          strategy: "",
          short_term_trend: 0,
          bull_bear_line: 0,
          reasons: [],
          similarity_score: s.similarity_score,
          matched_case: s.matched_case,
          match_breakdown: s.match_breakdown,
        })),
        index,
      );
    }
    navigate(`/stock/${code}`);
  };

  return (
    <PageTransition>
      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-4 sm:py-8">
        <div className="flex items-baseline justify-between mb-4 sm:mb-8">
          <h1 className="text-xl sm:text-2xl font-semibold text-ink">
            今日选股概览
          </h1>
          <span className="text-xs sm:text-sm text-ink-muted">
            {stats?.latest_date ?? ""}
          </span>
        </div>

        <WorkflowGuideBanner />

        <div className="grid grid-cols-3 gap-2 sm:gap-4 mb-6 sm:mb-10">
          {statsLoading ? (
            Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-24 rounded-2xl" />
            ))
          ) : (
            <>
              <StatCard label="总股票数" value={stats?.total_stocks ?? 0} />
              <StatCard label="选股视图" value={stats?.total_views ?? 0} />
              <StatCard
                label="活跃视图"
                value={stats?.active_views ?? 0}
                accent
              />
            </>
          )}
        </div>

        <h2 className="text-lg font-medium text-ink mb-4">最新排名信号</h2>
        <div className="space-y-2">
          {rankingLoading ? (
            Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-14 rounded-xl" />
            ))
          ) : topStocks.length === 0 ? (
            <EmptyState
              icon={
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
                  <path d="M3 3v18h18" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                  <path d="M7 14l4-4 3 3 6-6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              }
              title="暂无排名信号"
              description="创建选股视图并运行策略后，排名结果将显示在这里"
              ctaLabel="去选股"
              onCta={() => navigate("/selection")}
            />
          ) : (
            topStocks.map((stock, i) => {
              const badgeVariant =
                CATEGORY_BADGE_VARIANT[stock.category] ?? "bowl";
              const changeColor =
                stock.close > 0 ? "text-bull" : "text-bear";
              return (
                <Card
                  key={stock.code}
                  hoverable
                  className="flex items-center px-3 sm:px-5 py-2.5 sm:py-3 gap-2 sm:gap-4"
                  onClick={() => handleStockClick(stock.code, i)}
                >
                  <span
                    className={`text-xs sm:text-sm font-mono w-5 sm:w-6 text-center shrink-0 ${
                      i === 0
                        ? "text-accent font-bold"
                        : i < 3
                          ? "text-ink-secondary font-medium"
                          : "text-ink-muted"
                    }`}
                  >
                    {i + 1}
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5 sm:gap-2 flex-wrap">
                      <span className="text-xs sm:text-sm font-mono font-medium text-ink">
                        {stock.code}
                      </span>
                      <CopyButton text={stock.code} />
                      <span className="text-xs sm:text-sm text-ink-secondary truncate">
                        {stock.name}
                      </span>
                      <Badge variant={badgeVariant}>
                        {CATEGORY_LABELS[stock.category] ?? stock.category}
                      </Badge>
                    </div>
                  </div>
                  <span
                    className={`text-xs sm:text-sm font-mono shrink-0 ${changeColor}`}
                  >
                    {stock.close?.toFixed(2)}
                  </span>
                  {stock.similarity_score != null && (
                    <span className="text-xs sm:text-sm font-mono text-accent font-medium shrink-0">
                      {Math.round(stock.similarity_score)}%
                    </span>
                  )}
                </Card>
              );
            })
          )}
        </div>
      </div>
    </PageTransition>
  );
}

function StatCard({
  label,
  value,
  accent,
}: {
  label: string;
  value: number;
  accent?: boolean;
}) {
  return (
    <Card className="p-3 sm:p-6 relative overflow-hidden">
      {accent && (
        <div
          className="absolute top-0 left-0 right-0 h-px"
          style={{
            background:
              "linear-gradient(90deg, transparent, rgba(228,168,83,0.5), transparent)",
          }}
        />
      )}
      <AnimatedNumber
        value={value}
        className={`text-xl sm:text-3xl font-mono font-semibold block ${accent ? "text-accent" : "text-ink"}`}
      />
      <span className="text-xs sm:text-sm text-ink-secondary mt-0.5 sm:mt-1 block">
        {label}
      </span>
    </Card>
  );
}
