import { useState, useMemo } from "react";
import { useNavigate } from "@/lib/spa-router";
import { Button } from "@astryxdesign/core/Button";
import { Collapsible } from "@astryxdesign/core/Collapsible";
import { Icon } from "@astryxdesign/core/Icon";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { Skeleton, CopyButton, LoadError } from "@/components/ui";
import { EmptyState } from "@/components/onboarding";
import { useRanking } from "@/lib/hooks";
import { useAppStore } from "@/lib/store";
import { CATEGORY_LABELS } from "@/lib/tokens";
import type { RankingStock } from "@/lib/api";

/** B1 分数徽标：分数 + 一小段强度条，越高越红（越像历史强势样本） */
function B1Badge({ score }: { score: number }) {
  const color =
    score >= 85
      ? "var(--color-bull)"
      : score >= 60
        ? "var(--color-accent)"
        : "var(--color-ink-muted)";
  return (
    <span className="inline-flex flex-col items-end gap-1 shrink-0">
      <span className="flex items-baseline gap-1">
        <span className="text-[10px] text-ink-muted">B1</span>
        <span
          className="text-sm font-bold num"
          style={{ color }}
        >
          {score.toFixed(0)}
        </span>
      </span>
      <span
        className="h-1 w-9 rounded-full"
        style={{
          background: `linear-gradient(90deg, ${color} ${score}%, var(--color-inset) ${score}%)`,
        }}
      />
    </span>
  );
}

const FILTERS: { key: string; label: string }[] = [
  { key: "all", label: "全部" },
  { key: "bowl_center", label: "回落碗中" },
  { key: "near_duokong", label: "靠近多空线" },
  { key: "near_short_trend", label: "靠近趋势线" },
];

// 后端 /api/ranking 的 market_cap 单位是「亿」（策略层已除过 1e8），
// 此前把它当"元"处理，58 亿显示成 "0.0万"
function formatMarketCap(value: number | null): string {
  if (value == null || value <= 0) return "";
  if (value >= 1e4) return `${(value / 1e4).toFixed(1)}万亿`;
  return `${value >= 100 ? value.toFixed(0) : value.toFixed(1)}亿`;
}

/** 分类色点 + 文字（占位小、绝不换行、双端一致） */
const CATEGORY_DOT_COLOR: Record<string, string> = {
  bowl_center: "bg-bull",
  near_duokong: "bg-accent",
  near_short_trend: "bg-bear",
};

function CategoryTag({ category }: { category: string }) {
  return (
    <span className="inline-flex items-center gap-1 shrink-0 text-xs text-ink-muted whitespace-nowrap">
      <span
        className={`w-1.5 h-1.5 rounded-full ${CATEGORY_DOT_COLOR[category] ?? "bg-ink-muted"}`}
      />
      {CATEGORY_LABELS[category] ?? category}
    </span>
  );
}

/**
 * 候选行：两行式，一套布局双端通用。
 * 第一行：序号 + 名称 + 代码 + B1分 + 箭头
 * 第二行：价格 · J · 市值 · 行业（truncate） + 分类
 */
function CandidateRow({
  stock,
  rank,
  onClick,
}: {
  stock: RankingStock;
  rank: number;
  onClick: () => void;
}) {
  const score = stock.similarity_score;

  return (
    <Button
      label={`查看 ${stock.name || stock.code}`}
      variant="ghost"
      width="100%"
      onClick={onClick}
      className="w-full px-3 sm:px-4 py-3 rounded-xl hover:bg-elevated active:bg-inset transition-colors duration-100 text-left group"
    >
      <div className="flex items-center gap-2">
        <span
          className={`text-sm font-bold tabular-nums w-6 text-center shrink-0 ${
            rank <= 3 ? "text-accent" : "text-ink-muted"
          }`}
        >
          {rank}
        </span>
        <span className="text-[15px] font-medium text-ink truncate">
          {stock.name || stock.code}
        </span>
        <span className="font-mono text-xs text-ink-muted shrink-0">
          {stock.code}
        </span>
        <span className="hidden sm:inline-flex shrink-0">
          <CopyButton text={stock.code} />
        </span>
        <span className="ml-auto shrink-0 flex items-center gap-2">
          {score != null && <B1Badge score={score} />}
          <Icon icon="chevronRight" size="xsm" color="secondary" />
        </span>
      </div>
      <div className="flex items-center gap-3 mt-1 pl-8 text-xs whitespace-nowrap min-w-0">
        <span className="text-ink-secondary tabular-nums font-medium shrink-0">
          {stock.close != null ? stock.close.toFixed(2) : "—"}
        </span>
        <span className="text-ink-muted tabular-nums shrink-0">
          J {stock.J != null ? stock.J.toFixed(1) : "—"}
        </span>
        {formatMarketCap(stock.market_cap) && (
          <span className="text-ink-muted shrink-0">
            {formatMarketCap(stock.market_cap)}
          </span>
        )}
        {stock.industry && (
          <span className="text-ink-muted/70 truncate min-w-0">
            {stock.industry}
          </span>
        )}
        <span className="ml-auto shrink-0">
          <CategoryTag category={stock.category} />
        </span>
      </div>
    </Button>
  );
}

function ChevronToggle({ expanded }: { expanded: boolean }) {
  return (
    <span className={`inline-flex transition-transform ${expanded ? "rotate-90" : ""}`}>
      <Icon icon="chevronRight" size="sm" />
    </span>
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
      <Collapsible
        trigger={<span className="flex items-center gap-2 sm:gap-3"><ChevronToggle expanded={expanded} /><span className="font-medium text-sm text-ink shrink-0">{industry}</span><span className="text-xs text-ink-muted tabular-nums shrink-0">{stocks.length}只</span><span className="hidden sm:flex items-center gap-1.5 ml-auto">{Object.entries(stocks.reduce<Record<string, number>>((acc, s) => { acc[s.category] = (acc[s.category] ?? 0) + 1; return acc; }, {})).map(([cat, count]) => <span key={cat} className="text-xs bg-inset text-ink-muted px-2 py-0.5 rounded-md whitespace-nowrap">{CATEGORY_LABELS[cat] ?? cat} {count}</span>)}</span></span>}
        isOpen={expanded}
        onOpenChange={onToggle}
      >
            <div className="divide-y divide-border/30 ml-6 mr-2 mb-3 border-l border-border/40 pl-1">
              {stocks.map((stock, i) => (
                <CandidateRow
                  key={stock.code}
                  stock={stock}
                  rank={i + 1}
                  onClick={() => onStockClick(stock, i)}
                />
              ))}
            </div>
      </Collapsible>
    </div>
  );
}

type ViewMode = "ranking" | "industry";

/** 今日候选：策略选出的全部票（AI 从这里挑出今日一票），按 B1 排名或按行业分组 */
export function CandidateList() {
  const { data: ranking, isLoading, error, mutate } = useRanking();
  const [filter, setFilter] = useState("all");
  const [viewMode, setViewMode] = useState<ViewMode>("ranking");
  const [expandedIndustry, setExpandedIndustry] = useState<string | null>(null);
  const navigate = useNavigate();
  const setStockNav = useAppStore((s) => s.setStockNav);

  const stocks = ranking?.data ?? [];
  const runDate = ranking?.run_date ?? "";
  const filtered =
    filter === "all" ? stocks : stocks.filter((s) => s.category === filter);

  const industryGroups = useMemo(() => {
    const groups: Record<string, RankingStock[]> = {};
    for (const s of filtered) {
      const key = s.industry || "未知";
      if (!groups[key]) groups[key] = [];
      groups[key].push(s);
    }
    return Object.entries(groups).sort((a, b) => b[1].length - a[1].length);
  }, [filtered]);

  // list = 点击时所处的列表上下文（排名视图=全列表，行业视图=该行业组），
  // 详情页的 上一只/下一只 与 N/总数 都跟随这个上下文——此前行业视图把
  // 组内索引当全列表索引传，导致翻页从无关位置开始跳
  const handleClick = (list: RankingStock[], stock: RankingStock, index: number) => {
    const signalStocks = list.map((s) => ({
      code: s.code,
      name: s.name,
      strategy: "",
      category: s.category,
      close: s.close ?? 0,
      J: s.J ?? 0,
      volume_ratio: s.volume_ratio ?? 0,
      market_cap: s.market_cap ?? 0,
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
    <section className="pb-[env(safe-area-inset-bottom)]">
      <div className="flex items-start justify-between mb-3">
        <div>
          <h2 className="text-base sm:text-lg font-bold tracking-[-0.02em] text-ink">
            今日候选
          </h2>
          <p className="text-xs text-ink-muted mt-0.5 tabular-nums">
            {runDate}
            {!isLoading && ` · ${filtered.length}只`}
          </p>
        </div>
        <div className="flex items-center bg-surface rounded-full p-0.5 shrink-0 mt-0.5">
          <SegmentedControl value={viewMode} onChange={(value) => { const mode = value as ViewMode; setViewMode(mode); if (mode === "industry") setExpandedIndustry(null); }} label="候选视图" size="sm">
            <SegmentedControlItem value="ranking" label="排名" />
            <SegmentedControlItem value="industry" label="行业" />
          </SegmentedControl>
        </div>
      </div>

      <div className="flex items-center gap-1.5 sm:gap-2 mb-4 overflow-x-auto scrollbar-none">
        {FILTERS.map((f) => (
          <Button
            key={f.key}
            label={f.label}
            variant={filter === f.key ? "primary" : "secondary"}
            size="sm"
            onClick={() => setFilter(f.key)}
            className={`px-2.5 sm:px-4 py-1.5 text-xs sm:text-sm rounded-full whitespace-nowrap shrink-0 transition-colors duration-150 ${
              filter === f.key
                ? "bg-accent text-ink-inverse font-medium"
                : "bg-surface text-ink-muted hover:bg-elevated hover:text-ink-secondary"
            }`}
          >{f.label}</Button>
        ))}
      </div>

      {isLoading ? (
        <div className="space-y-1">
          {Array.from({ length: 10 }, (_, i) => (
            <Skeleton key={i} className="h-14 w-full rounded-xl" />
          ))}
        </div>
      ) : error ? (
        <LoadError label="候选数据加载失败" onRetry={() => mutate()} />
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={<Icon icon="success" size="md" />}
          title="暂无候选"
          description="每个交易日选股后，候选票会在这里展示"
        />
      ) : (
        <div className="card-modern px-1 py-1">
        {viewMode === "ranking" ? (
            <div key={`ranking-${filter}`} className="view-enter divide-y divide-border/40">
              {filtered.map((stock, i) => (
                <div key={stock.code}>
                  <CandidateRow
                    stock={stock}
                    rank={i + 1}
                    onClick={() => handleClick(filtered, stock, i)}
                  />
                </div>
              ))}
            </div>
          ) : (
            <div key={`industry-${filter}`} className="view-enter space-y-0.5">
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
                  onStockClick={(stock, index) =>
                    handleClick(groupStocks, stock, index)
                  }
                />
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
