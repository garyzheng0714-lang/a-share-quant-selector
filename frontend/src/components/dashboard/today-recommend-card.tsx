import { useNavigate } from "@/lib/spa-router";
import { Card } from "@astryxdesign/core/Card";
import { Heading } from "@astryxdesign/core/Heading";
import { Icon } from "@astryxdesign/core/Icon";
import { List, ListItem } from "@astryxdesign/core/List";
import { StatusDot } from "@astryxdesign/core/StatusDot";
import { Text } from "@astryxdesign/core/Text";
import { Token } from "@astryxdesign/core/Token";
import { LoadError, Skeleton } from "@/components/ui";
import { useRecommend } from "@/lib/hooks";
import { useAppStore } from "@/lib/store";
import type { RecommendStock, SignalStock } from "@/lib/api";

/**
 * 今日推荐：云阶命中票，按板块热度排序。
 * 列表行必须用 List/ListItem，不能用定高 Button 包多行内容。
 */
function deltaTone(v: number | undefined | null): "bull" | "bear" | "muted" {
  if (v === undefined || v === null || v === 0) return "muted";
  return v > 0 ? "bull" : "bear";
}

function formatDelta(v: number | undefined | null): string {
  if (v === undefined || v === null || v === 0) return "";
  return `${v > 0 ? "+" : ""}${v.toFixed(0)}`;
}

function RankMark({ rank }: { rank: number }) {
  return (
    <span
      className={`grid h-7 w-7 shrink-0 place-items-center rounded-full text-xs font-semibold tabular-nums ${
        rank === 1 ? "bg-accent-dim text-accent" : "bg-inset text-ink-muted"
      }`}
      aria-hidden="true"
    >
      {rank}
    </span>
  );
}

function RecommendMeta({ item }: { item: RecommendStock }) {
  const sector = item.sector;
  const delta = sector ? formatDelta(sector.delta3) : "";
  const tone = sector ? deltaTone(sector.delta3) : "muted";

  return (
    <div className="mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-[11px] leading-5 text-ink-muted tabular-nums">
      {sector && (
        <Token
          label={`板块 ${sector.score?.toFixed(0) ?? "—"} · ${sector.rank}/${sector.total}${delta ? ` ${delta}` : ""}`}
          color={tone === "bull" ? "red" : tone === "bear" ? "green" : "gray"}
          size="sm"
        />
      )}
      {item.industry ? <span className="inline-flex h-5 items-center truncate">{item.industry}</span> : null}
      {item.cap_yi != null ? <span className="inline-flex h-5 shrink-0 items-center">{item.cap_yi.toFixed(0)}亿</span> : null}
      {item.pct_change != null ? (
        <span
          className={`inline-flex h-5 items-center ${
            item.pct_change > 0 ? "text-bull" : item.pct_change < 0 ? "text-bear" : ""
          }`}
        >
          {item.pct_change > 0 ? "+" : ""}
          {item.pct_change.toFixed(2)}%
        </span>
      ) : null}
    </div>
  );
}

function RecommendRow({ item, list }: { item: RecommendStock; list: RecommendStock[] }) {
  const navigate = useNavigate();
  const setStockNav = useAppStore((state) => state.setStockNav);

  return (
    <ListItem
      label={
        <span className="flex w-full min-w-0 items-start justify-between gap-3">
          <span className="min-w-0">
            <span className="flex min-w-0 items-baseline gap-2">
              <span className="truncate text-sm font-medium text-ink">{item.name || item.code}</span>
              <span className="shrink-0 font-mono text-xs text-ink-muted">{item.code}</span>
            </span>
          </span>
          <span className="shrink-0 pt-0.5 text-sm font-medium tabular-nums leading-5 text-ink">
            {item.close?.toFixed(2) ?? "—"}
          </span>
        </span>
      }
      description={
        <div className="min-w-0">
          <RecommendMeta item={item} />
          {item.reason ? (
            <p className="mt-1 text-[11px] leading-5 text-ink-muted">{item.reason}</p>
          ) : null}
        </div>
      }
      startContent={<RankMark rank={item.rank ?? 0} />}
      onClick={() => {
        const navList: SignalStock[] = list.map((s) => ({
          code: s.code,
          name: s.name,
          strategy: "云阶",
          category: "云阶",
          close: s.close ?? 0,
          J: 0,
          volume_ratio: 0,
          market_cap: 0,
          short_term_trend: 0,
          bull_bear_line: 0,
          reasons: [],
          similarity_score: null,
          matched_case: null,
          match_breakdown: null,
          industry: s.industry,
        }));
        setStockNav(navList, navList.findIndex((x) => x.code === item.code));
        navigate(`/stock/${item.code}`);
      }}
    />
  );
}

export function TodayRecommendCard() {
  const { data, error, isLoading, mutate } = useRecommend();
  const picks: RecommendStock[] = data?.today_buy ?? [];

  return (
    <Card className="mb-6 overflow-hidden" data-testid="today-recommend">
      <div className="flex items-center gap-2 border-b border-border px-4 py-3 sm:px-5">
        <StatusDot variant="success" label="今日推荐" />
        <Heading level={2} className="text-sm">今日推荐</Heading>
        {data?.trade_date ? (
          <Text type="supporting">截至 {data.trade_date} 收盘</Text>
        ) : null}
        {data?.core_factor ? (
          <span className="ml-auto inline-flex items-center gap-1">
            <Icon icon="checkDouble" size="xsm" color="success" />
            <Text type="supporting">云阶 · 双周期验证主策略</Text>
          </span>
        ) : null}
      </div>

      {isLoading ? (
        <div className="space-y-3 px-4 py-4 sm:px-5">
          <Skeleton className="h-16 w-full rounded-lg" />
          <Skeleton className="h-16 w-full rounded-lg" />
        </div>
      ) : error ? (
        <div className="px-4 py-4 sm:px-5">
          <LoadError label="今日推荐加载失败" onRetry={() => mutate()} />
        </div>
      ) : !data?.available ? (
        <div className="flex items-start gap-2 px-4 py-4 sm:px-5">
          <Icon icon="warning" size="xsm" color="warning" />
          <Text type="supporting">{data?.reason ?? "数据准备中"}</Text>
        </div>
      ) : picks.length === 0 ? (
        <div className="px-4 py-4 sm:px-5">
          <Text type="supporting">今日无云阶信号。好机会稀缺，空仓是常态——这是事实，不是建议。</Text>
        </div>
      ) : (
        <>
          <List density="spacious" hasDividers aria-label="今日推荐列表">
            {picks.map((item) => (
              <RecommendRow key={item.code} item={item} list={picks} />
            ))}
          </List>
          {data.honest_note ? (
            <div className="border-t border-border px-4 py-3 sm:px-5">
              <Text type="supporting">{data.honest_note}</Text>
            </div>
          ) : null}
        </>
      )}
    </Card>
  );
}
