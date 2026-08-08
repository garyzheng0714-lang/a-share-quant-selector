import { startTransition, useCallback, useEffect, useMemo, useState } from "react";
import { Badge } from "@astryxdesign/core/Badge";
import { Selector } from "@astryxdesign/core/Selector";
import {
  Table,
  pixel,
  proportional,
  useTableStickyColumns,
  type TableColumn,
} from "@astryxdesign/core/Table";
import { List, ListItem } from "@astryxdesign/core/List";
import { EmptyState } from "@/components/onboarding";
import { PickDetailDialog } from "@/components/review/pick-detail-dialog";
import { LoadError, Skeleton } from "@/components/ui";
import {
  api,
  type StrategyReviewCatalogItem,
  type StrategyReviewResponse,
} from "@/lib/api";
import {
  loadReviewCache,
  saveReviewCatalog,
  saveStrategyReview,
} from "@/lib/review-cache";
import { aggregateByStock, type StockReviewRow } from "@/lib/review-stock";

function pctClass(value: number | null | undefined) {
  if (value == null || value === 0) return "text-ink-muted";
  return value > 0 ? "text-bull" : "text-bear";
}

function fmtPct(value: number | null | undefined) {
  if (value == null || Number.isNaN(value)) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function fmtNum(value: number | null | undefined, digits = 2) {
  if (value == null || Number.isNaN(value)) return "—";
  return value.toFixed(digits);
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

function StatChip({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <div className="min-w-[7.5rem] flex-1 rounded-lg border border-border/40 px-3 py-2">
      <div className="text-[11px] text-ink-muted">{label}</div>
      <div className={`mt-0.5 text-sm font-semibold tabular-nums ${tone ?? "text-ink"}`}>{value}</div>
    </div>
  );
}

/**
 * 复盘主视图：股票唯一行 + 固定表头/股票列 + 密字段表。
 */
export function StrategyReviewWorkspace() {
  const [catalog, setCatalog] = useState<StrategyReviewCatalogItem[]>([]);
  const [strategy, setStrategy] = useState("cloud_stair");
  const [reviews, setReviews] = useState<Record<string, StrategyReviewResponse>>({});
  const [loading, setLoading] = useState(true);
  const [prefetching, setPrefetching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<StockReviewRow | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  const stickyColumns = useTableStickyColumns<StockReviewRow>({ startKeys: ["name"] });

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
                // ignore single strategy failure
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
  const stocks = useMemo(() => aggregateByStock(review?.picks ?? []), [review?.picks]);

  const openStock = useCallback((row: StockReviewRow) => {
    startTransition(() => {
      setSelected(row);
      setDialogOpen(true);
    });
  }, []);

  const columns: TableColumn<StockReviewRow>[] = useMemo(
    () => [
      {
        key: "name",
        header: "股票",
        width: proportional(1.5, { minWidth: 128 }),
        renderCell: (row) => (
          <button
            type="button"
            className="flex min-w-0 flex-col items-start text-left"
            onClick={() => openStock(row)}
          >
            <span className="truncate text-sm font-semibold text-ink">{row.name}</span>
            <span className="tabular-nums text-xs text-ink-muted">{row.code}</span>
          </button>
        ),
      },
      {
        key: "industry",
        header: "行业",
        width: pixel(96),
        renderCell: (row) => (
          <span className="truncate text-xs text-ink-secondary">{row.industry || "—"}</span>
        ),
      },
      {
        key: "first_pick_date",
        header: "首次选出",
        width: pixel(100),
        renderCell: (row) => <span className="tabular-nums text-sm">{row.first_pick_date}</span>,
      },
      {
        key: "last_pick_date",
        header: "最近选出",
        width: pixel(100),
        renderCell: (row) => <span className="tabular-nums text-sm">{row.last_pick_date}</span>,
      },
      {
        key: "pick_count",
        header: "次数",
        width: pixel(56),
        align: "end",
        renderCell: (row) => <span className="tabular-nums text-sm">{row.pick_count}</span>,
      },
      {
        key: "entry_date",
        header: "入场日",
        width: pixel(100),
        renderCell: (row) => <span className="tabular-nums text-sm">{row.entry_date ?? "—"}</span>,
      },
      {
        key: "entry_price",
        header: "入场价",
        width: pixel(76),
        align: "end",
        renderCell: (row) => <span className="tabular-nums text-sm">{fmtNum(row.entry_price)}</span>,
      },
      {
        key: "signal_close",
        header: "信号价",
        width: pixel(76),
        align: "end",
        renderCell: (row) => (
          <span className="tabular-nums text-sm">{fmtNum(row.signal_close as number | null)}</span>
        ),
      },
      {
        key: "entry_gap_pct",
        header: "开盘缺口",
        width: pixel(84),
        align: "end",
        renderCell: (row) => (
          <span className={`tabular-nums text-sm ${pctClass(row.entry_gap_pct)}`}>
            {fmtPct(row.entry_gap_pct)}
          </span>
        ),
      },
      {
        key: "next_day_chg",
        header: "隔日涨跌",
        width: pixel(84),
        align: "end",
        renderCell: (row) => (
          <span className={`tabular-nums text-sm font-medium ${pctClass(row.next_day_chg)}`}>
            {fmtPct(row.next_day_chg)}
          </span>
        ),
      },
      {
        key: "ret_to_date",
        header: "持有至今",
        width: pixel(84),
        align: "end",
        renderCell: (row) => (
          <span className={`tabular-nums text-sm font-medium ${pctClass(row.ret_to_date)}`}>
            {fmtPct(row.ret_to_date)}
          </span>
        ),
      },
      {
        key: "holding_sessions_to_date",
        header: "持有天",
        width: pixel(68),
        align: "end",
        renderCell: (row) => (
          <span className="tabular-nums text-sm">{row.holding_sessions_to_date ?? "—"}</span>
        ),
      },
      {
        key: "mfe_to_date",
        header: "最大浮盈",
        width: pixel(84),
        align: "end",
        renderCell: (row) => (
          <span className={`tabular-nums text-sm ${pctClass(row.mfe_to_date)}`}>{fmtPct(row.mfe_to_date)}</span>
        ),
      },
      {
        key: "mae_to_date",
        header: "最大浮亏",
        width: pixel(84),
        align: "end",
        renderCell: (row) => (
          <span className={`tabular-nums text-sm ${pctClass(row.mae_to_date)}`}>{fmtPct(row.mae_to_date)}</span>
        ),
      },
      {
        key: "latest_close",
        header: "最新价",
        width: pixel(76),
        align: "end",
        renderCell: (row) => <span className="tabular-nums text-sm">{fmtNum(row.latest_close)}</span>,
      },
      {
        key: "ret_1",
        header: "T+1",
        width: pixel(72),
        align: "end",
        renderCell: (row) => (
          <span className={`tabular-nums text-sm ${pctClass(row.ret_1)}`}>{fmtPct(row.ret_1)}</span>
        ),
      },
      {
        key: "ret_5",
        header: "T+5",
        width: pixel(72),
        align: "end",
        renderCell: (row) => (
          <span className={`tabular-nums text-sm ${pctClass(row.ret_5)}`}>{fmtPct(row.ret_5)}</span>
        ),
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
        key: "max_gain_5",
        header: "T+5高",
        width: pixel(72),
        align: "end",
        renderCell: (row) => (
          <span className={`tabular-nums text-sm ${pctClass(row.max_gain_5)}`}>{fmtPct(row.max_gain_5)}</span>
        ),
      },
      {
        key: "max_dd_5",
        header: "T+5回撤",
        width: pixel(80),
        align: "end",
        renderCell: (row) => (
          <span className={`tabular-nums text-sm ${pctClass(row.max_dd_5)}`}>{fmtPct(row.max_dd_5)}</span>
        ),
      },
      {
        key: "status",
        header: "状态",
        width: pixel(72),
        renderCell: (row) => (
          <span className="text-xs text-ink-secondary">{STATUS_LABEL[row.status] ?? row.status}</span>
        ),
      },
    ],
    [openStock],
  );

  const selectorOptions = useMemo(
    () =>
      catalog.map((item) => ({
        value: item.key,
        label: item.has_data ? `${item.name}（${item.pick_count}信号）` : `${item.name}（暂无）`,
      })),
    [catalog],
  );

  if (loading && !review) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-80 w-full" />
      </div>
    );
  }

  if (error && !review) {
    return <LoadError label={error} />;
  }

  const hold = summary?.recommended_hold;
  const signalCount = summary?.pick_count ?? 0;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0 flex-1 sm:max-w-xs">
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
          {prefetching ? <Badge variant="neutral" label="同步中" /> : null}
          <Badge variant="blue" label={`${stocks.length} 只股票`} />
        </div>
      </div>

      {!review?.available ? (
        <EmptyState title="该策略暂无历史命中" description="每日预热写入后会出现在这里。" />
      ) : (
        <>
          <div className="flex gap-2 overflow-x-auto pb-1">
            <StatChip
              label="股票 / 信号"
              value={`${stocks.length} / ${signalCount}`}
            />
            <StatChip
              label="隔日均"
              value={fmtPct(summary?.next_day.avg)}
              tone={pctClass(summary?.next_day.avg)}
            />
            <StatChip
              label="至今均"
              value={fmtPct(summary?.to_date.avg)}
              tone={pctClass(summary?.to_date.avg)}
            />
            <StatChip
              label="建议卖点"
              value={
                hold
                  ? `${hold.label} ${fmtPct(hold.avg)}`
                  : "—"
              }
              tone={pctClass(hold?.avg)}
            />
            <StatChip label="T+5均" value={fmtPct(summary?.windows?.ret_5?.avg)} tone={pctClass(summary?.windows?.ret_5?.avg)} />
            <StatChip label="T+10均" value={fmtPct(summary?.windows?.ret_10?.avg)} tone={pctClass(summary?.windows?.ret_10?.avg)} />
          </div>

          <div className="review-stock-table hidden md:block">
            <Table
              data={stocks}
              columns={columns}
              idKey="id"
              density="compact"
              dividers="rows"
              hasHover
              textOverflow="truncate"
              plugins={{ stickyColumns }}
            />
          </div>

          <div className="md:hidden">
            <List density="spacious" hasDividers aria-label="股票复盘">
              {stocks.map((row) => (
                <ListItem
                  key={row.id}
                  label={
                    <button
                      type="button"
                      className="flex w-full min-w-0 flex-col items-start text-left"
                      onClick={() => openStock(row)}
                    >
                      <span className="flex w-full items-baseline justify-between gap-2">
                        <span className="truncate text-sm font-semibold text-ink">{row.name}</span>
                        <span className={`shrink-0 tabular-nums text-sm font-medium ${pctClass(row.ret_to_date)}`}>
                          {fmtPct(row.ret_to_date)}
                        </span>
                      </span>
                      <span className="mt-0.5 text-xs text-ink-muted">
                        {row.first_pick_date}
                        {row.pick_count > 1 ? ` · ${row.pick_count}次` : ""}
                        {" · 隔日 "}
                        <span className={pctClass(row.next_day_chg)}>{fmtPct(row.next_day_chg)}</span>
                      </span>
                    </button>
                  }
                />
              ))}
            </List>
          </div>
        </>
      )}

      <PickDetailDialog
        pick={selected}
        history={selected?.history ?? []}
        isOpen={dialogOpen}
        onOpenChange={setDialogOpen}
      />
    </div>
  );
}
