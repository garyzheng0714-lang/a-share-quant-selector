import { PageTransition } from "@/components/layout/page-transition";
import { Card, Skeleton, Badge, AnimatedNumber } from "@/components/ui";
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
      <div className="max-w-6xl mx-auto px-6 py-8">
        <div className="flex items-baseline justify-between mb-8">
          <h1 className="text-2xl font-semibold text-ink">
            今日选股概览
          </h1>
          <span className="text-sm text-ink-muted">
            {stats?.latest_date ?? ""}
          </span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-10">
          {statsLoading ? (
            Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-24 rounded-2xl" />
            ))
          ) : (
            <>
              <StatCard
                label="总股票数"
                value={stats?.total_stocks ?? 0}
              />
              <StatCard
                label="选股视图"
                value={stats?.total_views ?? 0}
              />
              <StatCard
                label="活跃视图"
                value={stats?.active_views ?? 0}
              />
            </>
          )}
        </div>

        <h2 className="text-lg font-medium text-ink mb-4">
          最新排名信号
        </h2>
        <div className="space-y-2">
          {rankingLoading ? (
            Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-14 rounded-xl" />
            ))
          ) : topStocks.length === 0 ? (
            <Card className="p-8 text-center">
              <p className="text-ink-muted">暂无排名数据</p>
            </Card>
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
                  className="flex items-center px-5 py-3 gap-4"
                  onClick={() => handleStockClick(stock.code, i)}
                >
                  <span
                    className={`text-sm font-mono w-6 text-center ${
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
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-mono font-medium text-ink">
                        {stock.code}
                      </span>
                      <span className="text-sm text-ink-secondary truncate">
                        {stock.name}
                      </span>
                      <Badge variant={badgeVariant}>
                        {CATEGORY_LABELS[stock.category] ??
                          stock.category}
                      </Badge>
                    </div>
                  </div>
                  <span className={`text-sm font-mono ${changeColor}`}>
                    {stock.close?.toFixed(2)}
                  </span>
                  {stock.similarity_score != null && (
                    <span className="text-sm font-mono text-accent font-medium">
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
}: {
  label: string;
  value: number;
}) {
  return (
    <Card className="p-6">
      <AnimatedNumber
        value={value}
        className="text-3xl font-mono font-semibold text-ink block"
      />
      <span className="text-sm text-ink-secondary mt-1 block">
        {label}
      </span>
    </Card>
  );
}
