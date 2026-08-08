import { startTransition, useCallback, useEffect, useMemo, useState } from "react";
import { Badge } from "@astryxdesign/core/Badge";
import { Heading } from "@astryxdesign/core/Heading";
import { List, ListItem } from "@astryxdesign/core/List";
import { Selector } from "@astryxdesign/core/Selector";
import { Table, pixel, proportional, type TableColumn } from "@astryxdesign/core/Table";
import { Text } from "@astryxdesign/core/Text";
import { EmptyState } from "@/components/onboarding";
import { PickDetailDialog } from "@/components/review/pick-detail-dialog";
import { ByDateChart, WindowStatsChart } from "@/components/review/review-charts";
import { LoadError, Skeleton } from "@/components/ui";
import { api, type StrategyReviewCatalogItem, type StrategyReviewPick, type StrategyReviewResponse } from "@/lib/api";
import {
  loadReviewCache,
  saveReviewCatalog,
  saveStrategyReview,
} from "@/lib/review-cache";

function pctClass(value: number | null | undefined) {
  if (value == null || value === 0) return "text-ink-muted";
  return value > 0 ? "text-bull" : "text-bear";
}

function fmtPct(value: number | null | undefined) {
  if (value == null || Number.isNaN(value)) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function fmtAgg(avg: number | null | undefined, win: number | null | undefined, count?: number) {
  if (avg == null) return "—";
  const base = `${avg > 0 ? "+" : ""}${avg.toFixed(2)}%`;
  if (win == null) return base;
  return count != null ? `${base} · ${win}% · ${count}笔` : `${base} · ${win}%`;
}

const STATUS_LABEL: Record<string, string> = {
  awaiting_next_session: "等开盘",
  tracking: "跟踪中",
  open: "持有中",
  complete: "已满窗",
  no_price: "无行情",
  signal_missing: "缺信号",
  entry_unavailable: "未入场",
};

function StatCard({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: string;
}) {
  return (
    <div className="rounded-lg border border-border/40 px-3 py-2.5">
      <div className="text-[11px] text-ink-muted">{label}</div>
      <div className={`mt-1 text-sm font-semibold tabular-nums ${tone ?? "text-ink"}`}>{value}</div>
      {hint ? <div className="mt-0.5 text-[11px] text-ink-muted">{hint}</div> : null}
    </div>
  );
}

/**
 * 复盘工作台：策略秒切（IndexedDB + 内存）+ 卡片/图表 + 票级明细弹窗。
 */
export function StrategyReviewWorkspace() {
  const [catalog, setCatalog] = useState<StrategyReviewCatalogItem[]>([]);
  const [strategy, setStrategy] = useState("cloud_stair");
  const [reviews, setReviews] = useState<Record<string, StrategyReviewResponse>>({});
  const [loading, setLoading] = useState(true);
  const [prefetching, setPrefetching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<StrategyReviewPick | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  const upsertReview = useCallback((key: string, review: StrategyReviewResponse) => {
    setReviews((prev) => ({ ...prev, [key]: review }));
    void saveStrategyReview(key, review);
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function bootstrap() {
      setLoading(true);
      setError(null);

      const cached = await loadReviewCache();
      if (!cancelled && cached) {
        setCatalog(cached.catalog);
        setReviews(cached.reviews);
        if (cached.defaultStrategy) setStrategy(cached.defaultStrategy);
        setLoading(false);
      }

      try {
        const catalogRes = await api.getReviewCatalog();
        if (cancelled) return;
        const nextCatalog = catalogRes.catalog ?? [];
        const defaultStrategy = catalogRes.default_strategy || "cloud_stair";
        setCatalog(nextCatalog);
        setStrategy((prev) =>
          nextCatalog.some((item) => item.key === prev && item.has_data)
            ? prev
            : defaultStrategy,
        );
        await saveReviewCatalog(nextCatalog, defaultStrategy);

        const withData = nextCatalog.filter((item) => item.has_data);
        setPrefetching(true);

        // 当前策略优先，其余后台灌进本地缓存 → 秒切
        const preferred =
          withData.find((item) => item.key === defaultStrategy)?.key ?? withData[0]?.key;
        if (preferred) {
          const first = await api.getStrategyReview(preferred, 300);
          if (!cancelled) upsertReview(preferred, first);
        }

        if (!cancelled) setLoading(false);

        await Promise.all(
          withData
            .filter((item) => item.key !== preferred)
            .map(async (item) => {
              try {
                const review = await api.getStrategyReview(item.key, 300);
                if (!cancelled) upsertReview(item.key, review);
              } catch {
                // 单策略失败不阻断其余
              }
            }),
        );
      } catch (err) {
        if (!cancelled && !cached) {
          setError(err instanceof Error ? err.message : "复盘加载失败");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
          setPrefetching(false);
        }
      }
    }

    void bootstrap();
    return () => {
      cancelled = true;
    };
  }, [upsertReview]);

  // 切到尚未缓存的策略时再拉一次
  useEffect(() => {
    if (!strategy || reviews[strategy]) return;
    let cancelled = false;
    (async () => {
      try {
        const review = await api.getStrategyReview(strategy, 300);
        if (!cancelled) upsertReview(strategy, review);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "策略复盘加载失败");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [strategy, reviews, upsertReview]);

  const review = reviews[strategy];
  const summary = review?.summary;
  const picks = useMemo(
    () =>
      (review?.picks ?? []).map((row) => ({
        ...row,
        id: `${row.pick_date}-${row.code}`,
      })),
    [review?.picks],
  );

  const openPick = useCallback((row: StrategyReviewPick) => {
    startTransition(() => {
      setSelected(row);
      setDialogOpen(true);
    });
  }, []);

  const columns: TableColumn<StrategyReviewPick>[] = useMemo(
    () => [
      {
        key: "name",
        header: "股票",
        width: proportional(1.4, { minWidth: 130 }),
        renderCell: (row) => (
          <button type="button" className="flex min-w-0 flex-col items-start text-left" onClick={() => openPick(row)}>
            <span className="truncate text-sm font-semibold text-ink">{row.name}</span>
            <span className="tabular-nums text-xs text-ink-muted">{row.code}</span>
          </button>
        ),
      },
      {
        key: "pick_date",
        header: "选出日",
        width: pixel(100),
        renderCell: (row) => <span className="tabular-nums text-sm">{row.pick_date}</span>,
      },
      {
        key: "next_day_chg",
        header: "隔日",
        width: pixel(84),
        align: "end",
        renderCell: (row) => (
          <span className={`tabular-nums text-sm font-medium ${pctClass(row.next_day_chg)}`}>
            {fmtPct(row.next_day_chg)}
          </span>
        ),
      },
      {
        key: "entry_gap_pct",
        header: "开盘缺口",
        width: pixel(88),
        align: "end",
        renderCell: (row) => (
          <span className={`tabular-nums text-sm ${pctClass(row.entry_gap_pct)}`}>
            {fmtPct(row.entry_gap_pct)}
          </span>
        ),
      },
      {
        key: "ret_to_date",
        header: "至今",
        width: pixel(84),
        align: "end",
        renderCell: (row) => (
          <span className={`tabular-nums text-sm font-medium ${pctClass(row.ret_to_date)}`}>
            {fmtPct(row.ret_to_date)}
          </span>
        ),
      },
      {
        key: "mfe_to_date",
        header: "最大浮盈",
        width: pixel(88),
        align: "end",
        renderCell: (row) => (
          <span className={`tabular-nums text-sm ${pctClass(row.mfe_to_date)}`}>{fmtPct(row.mfe_to_date)}</span>
        ),
      },
      {
        key: "mae_to_date",
        header: "最大浮亏",
        width: pixel(88),
        align: "end",
        renderCell: (row) => (
          <span className={`tabular-nums text-sm ${pctClass(row.mae_to_date)}`}>{fmtPct(row.mae_to_date)}</span>
        ),
      },
      {
        key: "ret_1",
        header: "T+1",
        width: pixel(72),
        align: "end",
        renderCell: (row) => <span className={`tabular-nums text-sm ${pctClass(row.ret_1)}`}>{fmtPct(row.ret_1)}</span>,
      },
      {
        key: "ret_5",
        header: "T+5",
        width: pixel(72),
        align: "end",
        renderCell: (row) => <span className={`tabular-nums text-sm ${pctClass(row.ret_5)}`}>{fmtPct(row.ret_5)}</span>,
      },
      {
        key: "ret_10",
        header: "T+10",
        width: pixel(72),
        align: "end",
        renderCell: (row) => (
          <span className={`tabular-nums text-sm ${pctClass(row.ret_10)}`}>{fmtPct(row.ret_10)}</span>
        ),
      },
      {
        key: "ret_20",
        header: "T+20",
        width: pixel(72),
        align: "end",
        renderCell: (row) => (
          <span className={`tabular-nums text-sm ${pctClass(row.ret_20)}`}>{fmtPct(row.ret_20)}</span>
        ),
      },
      {
        key: "status",
        header: "状态",
        width: pixel(80),
        renderCell: (row) => (
          <span className="text-xs text-ink-secondary">{STATUS_LABEL[row.status] ?? row.status}</span>
        ),
      },
    ],
    [openPick],
  );

  const selectorOptions = useMemo(
    () =>
      catalog.map((item) => ({
        value: item.key,
        label: item.has_data
          ? `${item.name}（${item.pick_count}）`
          : `${item.name}（暂无）`,
      })),
    [catalog],
  );

  if (loading && !review) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (error && !review) {
    return <LoadError label={error} />;
  }

  const hold = summary?.recommended_hold;
  const cachedCount = Object.keys(reviews).length;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0 flex-1 sm:max-w-sm">
          <Selector
            label="策略"
            hasSearch
            searchPlaceholder="搜索策略"
            value={strategy}
            onChange={(value) => setStrategy(String(value))}
            options={selectorOptions}
            width="100%"
          />
        </div>
        <div className="flex items-center gap-2">
          {prefetching ? <Badge variant="neutral" label="同步缓存中" /> : null}
          {cachedCount > 0 ? <Badge variant="blue" label={`${cachedCount} 策略已缓存`} /> : null}
        </div>
      </div>

      {!review?.available ? (
        <EmptyState
          title="该策略暂无历史命中"
          description="等每日预热写入命中后，会出现在本地复盘缓存里，可秒切查看。"
        />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-6">
            <StatCard
              label="样本"
              value={`${summary?.pick_count ?? 0}`}
              hint={
                review.date_span
                  ? `${review.date_span.from.slice(5)} → ${review.date_span.to.slice(5)}`
                  : undefined
              }
            />
            <StatCard
              label="隔日"
              value={fmtPct(summary?.next_day.avg)}
              hint={summary?.next_day.win_rate != null ? `胜率 ${summary.next_day.win_rate}%` : undefined}
              tone={pctClass(summary?.next_day.avg)}
            />
            <StatCard
              label="持有至今"
              value={fmtPct(summary?.to_date.avg)}
              hint={summary?.to_date.win_rate != null ? `胜率 ${summary.to_date.win_rate}%` : undefined}
              tone={pctClass(summary?.to_date.avg)}
            />
            <StatCard
              label="建议卖点"
              value={hold ? hold.label : "—"}
              hint={hold ? fmtAgg(hold.avg, hold.win_rate, hold.count) : "样本不足"}
              tone={pctClass(hold?.avg)}
            />
            <StatCard
              label="平均最大浮盈"
              value={fmtPct(summary?.mfe?.avg)}
              hint={summary?.mfe?.best != null ? `单票最好 ${fmtPct(summary.mfe.best)}` : undefined}
              tone={pctClass(summary?.mfe?.avg)}
            />
            <StatCard
              label="平均最大浮亏"
              value={fmtPct(summary?.mae?.avg)}
              hint={summary?.mae?.worst != null ? `单票最差 ${fmtPct(summary.mae.worst)}` : undefined}
              tone={pctClass(summary?.mae?.avg)}
            />
          </div>

          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {(["ret_1", "ret_5", "ret_10", "ret_20"] as const).map((key) => {
              const agg = summary?.windows?.[key];
              const label = key.replace("ret_", "T+");
              return (
                <StatCard
                  key={key}
                  label={`${label} 净收益`}
                  value={fmtPct(agg?.avg)}
                  hint={
                    agg
                      ? `胜率 ${agg.win_rate ?? "—"}% · 中位 ${fmtPct(agg.median)} · ${agg.count}笔`
                      : undefined
                  }
                  tone={pctClass(agg?.avg)}
                />
              );
            })}
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <div className="rounded-lg border border-border/40 p-3">
              <Heading level={3}>持有窗口</Heading>
              <div className="mt-2">
                {summary ? <WindowStatsChart summary={summary} /> : null}
              </div>
            </div>
            <div className="rounded-lg border border-border/40 p-3">
              <Heading level={3}>按选出日</Heading>
              <div className="mt-2">
                {summary ? <ByDateChart summary={summary} /> : null}
              </div>
            </div>
          </div>

          {(summary?.top_picks?.length || summary?.bottom_picks?.length) && (
            <div className="grid gap-4 md:grid-cols-2">
              <List density="compact" hasDividers aria-label="贡献最大">
                <ListItem label="贡献最大" description="持有至今收益最高" />
                {(summary?.top_picks ?? []).map((row) => (
                  <ListItem
                    key={`top-${row.pick_date}-${row.code}`}
                    label={`${row.name} ${row.code}`}
                    description={`${row.pick_date} · 至今 ${fmtPct(row.ret_to_date)} · 隔日 ${fmtPct(row.next_day_chg)}`}
                    onClick={() => {
                      const full = picks.find((p) => p.code === row.code && p.pick_date === row.pick_date);
                      if (full) openPick(full);
                    }}
                  />
                ))}
              </List>
              <List density="compact" hasDividers aria-label="拖累最大">
                <ListItem label="拖累最大" description="持有至今收益最低" />
                {(summary?.bottom_picks ?? []).map((row) => (
                  <ListItem
                    key={`bottom-${row.pick_date}-${row.code}`}
                    label={`${row.name} ${row.code}`}
                    description={`${row.pick_date} · 至今 ${fmtPct(row.ret_to_date)} · 隔日 ${fmtPct(row.next_day_chg)}`}
                    onClick={() => {
                      const full = picks.find((p) => p.code === row.code && p.pick_date === row.pick_date);
                      if (full) openPick(full);
                    }}
                  />
                ))}
              </List>
            </div>
          )}

          <div>
            <Heading level={3}>票级明细</Heading>
            <Text size="sm" className="mt-1 text-ink-muted">
              点击股票查看完整路径、窗口极值与 K 线
            </Text>
            <div className="mt-3 hidden overflow-x-auto md:block">
              <Table
                data={picks}
                columns={columns}
                idKey="id"
                density="compact"
                dividers="rows"
                hasHover
                textOverflow="truncate"
              />
            </div>
            <div className="mt-3 md:hidden">
              <List density="spacious" hasDividers aria-label="票级明细">
                {picks.map((row) => (
                  <ListItem
                    key={row.id}
                    label={
                      <button
                        type="button"
                        className="flex w-full min-w-0 flex-col items-start text-left"
                        onClick={() => openPick(row)}
                      >
                        <span className="flex w-full items-baseline justify-between gap-2">
                          <span className="truncate text-sm font-semibold text-ink">{row.name}</span>
                          <span className={`shrink-0 tabular-nums text-sm font-medium ${pctClass(row.ret_to_date)}`}>
                            {fmtPct(row.ret_to_date)}
                          </span>
                        </span>
                        <span className="mt-0.5 text-xs text-ink-muted">
                          {row.pick_date} · 隔日{" "}
                          <span className={pctClass(row.next_day_chg)}>{fmtPct(row.next_day_chg)}</span>
                          {" · "}
                          {STATUS_LABEL[row.status] ?? row.status}
                        </span>
                      </button>
                    }
                  />
                ))}
              </List>
            </div>
          </div>
        </>
      )}

      <PickDetailDialog pick={selected} isOpen={dialogOpen} onOpenChange={setDialogOpen} />
    </div>
  );
}
