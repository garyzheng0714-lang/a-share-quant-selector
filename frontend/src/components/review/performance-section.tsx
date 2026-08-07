import { useState } from "react";
import { useNavigate } from "@/lib/spa-router";
import { Button } from "@astryxdesign/core/Button";
import { Icon } from "@astryxdesign/core/Icon";
import { List, ListItem } from "@astryxdesign/core/List";
import { Skeleton, Gauge, LoadError } from "@/components/ui";
import { EmptyState } from "@/components/onboarding";
import { usePerformanceRecords, usePerformanceSummary } from "@/lib/hooks";
import { CATEGORY_LABELS } from "@/lib/tokens";
import type { BenchmarkAgg, PerfAgg, PerformanceRecord, WindowAgg } from "@/lib/api";

type RetKey = "ret_1" | "ret_5" | "ret_10" | "ret_20";

const WINDOWS: { key: RetKey; label: string }[] = [
  { key: "ret_1", label: "T+1" },
  { key: "ret_5", label: "T+5" },
  { key: "ret_10", label: "T+10" },
  { key: "ret_20", label: "T+20" },
];

const SIMILARITY_LABELS: Record<string, string> = {
  ">=80": "相似度 ≥80",
  "60-80": "相似度 60-80",
  "<60": "相似度 <60",
  无B1分: "无 B1 评分",
};

const CATEGORY_DOT_COLOR: Record<string, string> = {
  bowl_center: "bg-bull",
  near_duokong: "bg-accent",
  near_short_trend: "bg-bear",
};

function retColor(v: number | null): string {
  if (v === null || v === undefined) return "text-ink-muted";
  return v > 0 ? "text-bull" : v < 0 ? "text-bear" : "text-ink-muted";
}

function fmtRet(v: number | null): string {
  if (v === null || v === undefined) return "—";
  return `${v > 0 ? "+" : ""}${v.toFixed(1)}%`;
}

/**
 * 持有期真相（R1）：从真实回填数据回答"选出的票该拿几天"。
 * 数据支持不了盈利时就直说——这块的职责是诚实，不是打气。
 */
function HoldingTruth({ agg, benchmark }: { agg: PerfAgg; benchmark?: BenchmarkAgg | null }) {
  const withData = WINDOWS.filter((w) => agg[w.key].count > 0);
  if (withData.length === 0) return null;

  const best = withData.reduce((a, b) =>
    (agg[b.key].avg ?? -Infinity) > (agg[a.key].avg ?? -Infinity) ? b : a,
  );
  const bestAgg = agg[best.key];
  const noEdge = withData.every((w) => (agg[w.key].win_rate ?? 0) < 50);
  const dd = agg.drawdown;

  return (
    <div className="card-modern px-4 py-3.5 mb-6">
      <h3 className="text-sm font-semibold text-ink mb-2">
        持有期真相（该拿几天，数据说话）
      </h3>

      {noEdge ? (
        <p className="text-[13px] text-ink-secondary leading-relaxed">
          历史上<span className="text-amber-500/90 font-medium">没有任何持有窗口胜率过半</span>
          ——表现最好的 {best.label} 也只有胜率{" "}
          <span className="num">{bestAgg.win_rate}%</span>、平均{" "}
          <span className={`num ${(bestAgg.avg ?? 0) > 0 ? "text-bull" : "text-bear"}`}>
            {(bestAgg.avg ?? 0) > 0 ? "+" : ""}
            {bestAgg.avg}%
          </span>
          。这套信号当前整体不占优，宜观望或轻仓试错，等胜率回暖再加码。
        </p>
      ) : (
        <p className="text-[13px] text-ink-secondary leading-relaxed">
          历史最优持有窗口是 <span className="text-ink font-medium">{best.label}</span>
          ：胜率 <span className="text-bull num font-medium">{bestAgg.win_rate}%</span>、平均{" "}
          <span className="text-bull num font-medium">+{bestAgg.avg}%</span>
          （{bestAgg.count} 笔）。
        </p>
      )}

      {dd && dd.avg !== null && (
        <p className="text-xs text-ink-muted leading-relaxed mt-1.5">
          持有 20 日内平均最大浮亏{" "}
          <span className="text-bear num font-medium">{dd.avg}%</span>（中位{" "}
          <span className="num">{dd.median}%</span>）——止损设得比这紧几乎必然被打掉，
          仓位要按扛得住这个回撤来定。
        </p>
      )}

      {benchmark && (
        <div className="mt-3 pt-2.5 border-t border-border/40">
          <div className="text-[10px] text-ink-muted mb-1.5">
            对比同期上证指数（超额 = 策略均值 − 指数均值，指数以收盘价近似）
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-1.5">
            {WINDOWS.map((w) => {
              const s = agg[w.key].avg;
              const b = benchmark[w.key];
              if (s === null || b === null || b === undefined) return null;
              const excess = Math.round((s - b) * 100) / 100;
              return (
                <div key={w.key} className="flex items-baseline gap-1.5 tabular-nums min-w-0">
                  <span className="text-[10px] text-ink-muted w-8 shrink-0">{w.label}</span>
                  <span
                    className={`text-xs font-medium ${excess > 0 ? "text-bull" : excess < 0 ? "text-bear" : "text-ink-muted"}`}
                  >
                    超额 {excess > 0 ? "+" : ""}
                    {excess}%
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

/** 顶部统计卡：环形胜率 + 均收益，手机 2×2、桌面 4 列 */
function StatCard({ label, agg }: { label: string; agg: WindowAgg }) {
  const hasData = agg.count > 0;
  const win = agg.win_rate ?? 0;
  return (
    <div className="card-modern px-3.5 py-3 min-w-0">
      <div className="text-xs text-ink-muted mb-2">持有{label}</div>
      {hasData ? (
        <div className="flex items-center gap-2.5">
          <Gauge
            value={win}
            size={44}
            stroke={4}
            color={win >= 50 ? "var(--color-bull)" : "var(--color-ink-muted)"}
          >
            <span className="text-[13px] font-bold num text-ink">{win}</span>
          </Gauge>
          <div className="min-w-0">
            <div className="text-[10px] text-ink-muted">胜率</div>
            <div
              className={`text-[15px] font-semibold num ${retColor(agg.avg)}`}
            >
              {fmtRet(agg.avg)}
            </div>
            <div className="text-[10px] text-ink-muted num">{agg.count}笔</div>
          </div>
        </div>
      ) : (
        <div className="text-sm text-ink-muted mt-1">暂无数据</div>
      )}
    </div>
  );
}

function GroupCard({
  name,
  dotColor,
  agg,
}: {
  name: string;
  dotColor?: string;
  agg: PerfAgg;
}) {
  return (
    <div className="card-modern px-4 py-3">
      <div className="flex items-center gap-1.5 mb-2">
        {dotColor && <span className={`w-1.5 h-1.5 rounded-full ${dotColor}`} />}
        <span className="text-sm font-medium text-ink">{name}</span>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-1.5">
        {WINDOWS.map((w) => {
          const a = agg[w.key];
          return (
            <div
              key={w.key}
              className="flex items-baseline gap-1.5 tabular-nums min-w-0"
            >
              <span className="text-[10px] text-ink-muted w-8 shrink-0">
                {w.label}
              </span>
              {a.count > 0 ? (
                <>
                  <span className="text-xs text-ink font-medium">
                    {a.win_rate}%
                  </span>
                  <span className={`text-xs ${retColor(a.avg)}`}>
                    {fmtRet(a.avg)}
                  </span>
                </>
              ) : (
                <span className="text-xs text-ink-muted">—</span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function GroupSection({
  title,
  groups,
  labelMap,
  dotColors,
}: {
  title: string;
  groups: Record<string, PerfAgg>;
  labelMap: Record<string, string>;
  dotColors?: Record<string, string>;
}) {
  const entries = Object.entries(groups).filter(([, agg]) =>
    WINDOWS.some((w) => agg[w.key].count > 0),
  );
  if (entries.length === 0) return null;

  return (
    <div className="mb-6">
      <h3 className="text-sm font-semibold text-ink mb-2">{title}</h3>
      <div className="grid sm:grid-cols-2 gap-2">
        {entries.map(([key, agg]) => (
          <GroupCard
            key={key}
            name={labelMap[key] ?? key}
            dotColor={dotColors?.[key]}
            agg={agg}
          />
        ))}
      </div>
    </div>
  );
}

/** 明细行：ListItem 两行式（名称+代码，分类点落在行尾 / 日期+四窗口收益） */
function RecordRow({
  record,
  onClick,
}: {
  record: PerformanceRecord;
  onClick: () => void;
}) {
  return (
    <ListItem
      label={
        <span className="flex min-w-0 items-baseline gap-2">
          <span className="truncate text-sm font-medium text-ink">
            {record.name || record.code}
          </span>
          {record.name && (
            <span className="shrink-0 font-mono text-xs text-ink-muted">
              {record.code}
            </span>
          )}
        </span>
      }
      description={
        <div className="mt-1 flex items-center gap-2 tabular-nums">
          <span className="text-[11px] text-ink-muted w-[74px] shrink-0">
            {record.run_date}
          </span>
          <div className="grid grid-cols-4 flex-1 gap-x-2">
            {WINDOWS.map((w) => {
              const v = record[w.key as keyof PerformanceRecord] as number | null;
              return (
                <div
                  key={w.key}
                  className="flex items-baseline gap-0.5 justify-end min-w-0"
                >
                  <span className="text-[10px] text-ink-muted shrink-0">
                    {w.label}
                  </span>
                  <span className={`text-[11px] font-medium ${retColor(v)}`}>
                    {fmtRet(v)}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      }
      endContent={
        <span className="inline-flex shrink-0 items-center gap-1 whitespace-nowrap text-[11px] text-ink-muted">
          <span
            className={`h-1.5 w-1.5 rounded-full ${CATEGORY_DOT_COLOR[record.category] ?? "bg-ink-muted"}`}
          />
          {CATEGORY_LABELS[record.category] ?? record.category}
        </span>
      }
      onClick={onClick}
    />
  );
}

/** 整体战绩：所有选股记录的后续真实涨跌统计 + 明细 */
export function PerformanceSection() {
  const {
    data: summary,
    isLoading: summaryLoading,
    error: summaryError,
    mutate: retrySummary,
  } = usePerformanceSummary();
  const { data: recordsData, isLoading: recordsLoading } =
    usePerformanceRecords();
  const [showAll, setShowAll] = useState(false);
  const navigate = useNavigate();

  const records = recordsData?.records ?? [];
  const visible = showAll ? records : records.slice(0, 30);
  const isLoading = summaryLoading || recordsLoading;
  const hasData = (summary?.total_records ?? 0) > 0;

  if (isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-24 w-full rounded-2xl" />
        <Skeleton className="h-40 w-full rounded-2xl" />
      </div>
    );
  }

  if (summaryError) {
    return <LoadError label="战绩数据加载失败" onRetry={() => retrySummary()} />;
  }

  if (!hasData) {
    return (
      <EmptyState
        icon={<Icon icon="viewColumns" size="md" />}
        title="战绩还在积累中"
        description="每天选股后，这里会自动记录每只票的后续涨跌。跑几天就有数据了"
      />
    );
  }

  return (
    <div className="view-enter">
      <p className="text-xs text-ink-muted mb-4 leading-relaxed">
        每天选出的票自动追踪后续真实涨跌（按选出次日开盘价买入计算）· 共{" "}
        {summary!.total_records} 条
      </p>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 sm:gap-2.5 mb-4">
        {WINDOWS.map((w) => (
          <StatCard key={w.key} label={w.label} agg={summary!.overall[w.key]} />
        ))}
      </div>

      <HoldingTruth agg={summary!.overall} benchmark={summary!.benchmark} />

      <GroupSection
        title="按分类（哪类信号更靠谱）"
        groups={summary!.by_category}
        labelMap={CATEGORY_LABELS}
        dotColors={CATEGORY_DOT_COLOR}
      />
      <GroupSection
        title="按 B1 相似度（高分是否真的涨得多）"
        groups={summary!.by_similarity}
        labelMap={SIMILARITY_LABELS}
      />

      <h3 className="text-sm font-semibold text-ink mb-2">明细</h3>
      <List density="compact" hasDividers aria-label="选股记录明细">
        {visible.map((r) => (
          <RecordRow
            key={r.id}
            record={r}
            onClick={() => navigate(`/stock/${r.code}`)}
          />
        ))}
      </List>
      {!showAll && records.length > 30 && (
        <Button
          label={`展开全部 ${records.length} 条`}
          variant="ghost"
          width="100%"
          onClick={() => setShowAll(true)}
          className="mt-3"
        />
      )}
    </div>
  );
}
