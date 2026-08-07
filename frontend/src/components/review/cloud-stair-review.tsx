import { useMemo } from "react";
import { useNavigate } from "@/lib/spa-router";
import { Banner } from "@astryxdesign/core/Banner";
import { Heading } from "@astryxdesign/core/Heading";
import { List, ListItem } from "@astryxdesign/core/List";
import { Table, pixel, proportional, type TableColumn } from "@astryxdesign/core/Table";
import { Text } from "@astryxdesign/core/Text";
import { EmptyState } from "@/components/onboarding";
import { LoadError, Skeleton } from "@/components/ui";
import { useCloudStairReview } from "@/lib/hooks";
import { useAppStore } from "@/lib/store";
import type { CloudStairPick, CloudStairWindowAgg, SignalStock } from "@/lib/api";

type RetKey = "ret_1" | "ret_5" | "ret_10" | "ret_20";

const WINDOWS: { key: RetKey; label: string }[] = [
  { key: "ret_1", label: "T+1" },
  { key: "ret_5", label: "T+5" },
  { key: "ret_10", label: "T+10" },
  { key: "ret_20", label: "T+20" },
];

const STATUS_LABEL: Record<string, string> = {
  awaiting_next_session: "等次日开盘",
  tracking: "次日跟踪中",
  open: "持有中",
  complete: "窗口已满",
  no_price: "无行情",
  signal_missing: "缺信号日",
  entry_unavailable: "无法入场",
};

function pctClass(value: number | null | undefined) {
  if (value == null || value === 0) return "text-ink-muted";
  return value > 0 ? "text-bull" : "text-bear";
}

function fmtPct(value: number | null | undefined) {
  if (value == null || Number.isNaN(value)) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function fmtAgg(agg: CloudStairWindowAgg | undefined) {
  if (!agg || agg.count <= 0 || agg.avg == null) return "—";
  return `${agg.avg > 0 ? "+" : ""}${agg.avg.toFixed(2)}% · 胜率 ${agg.win_rate ?? "—"}%`;
}

function toNav(list: CloudStairPick[]): SignalStock[] {
  return list.map((item) => ({
    code: item.code,
    name: item.name,
    strategy: "cloud_stair",
    category: item.industry || "",
    close: Number(item.entry_price ?? item.signal_close ?? 0) || 0,
    J: 0,
    volume_ratio: 0,
    market_cap: 0,
    short_term_trend: 0,
    bull_bear_line: 0,
    reasons: [],
    similarity_score: null,
    matched_case: null,
    match_breakdown: null,
    industry: item.industry || "",
  }));
}

/**
 * 云阶票级复盘：以「票」为核心，回答选出日买入后隔日怎么走、拿到现在赚多少、拿几天更合适。
 */
export function CloudStairReviewSection() {
  const { data, error, isLoading } = useCloudStairReview(200);
  const navigate = useNavigate();
  const setStockNav = useAppStore((state) => state.setStockNav);

  const picks = data?.picks ?? [];
  const summary = data?.summary;
  const navList = useMemo(() => toNav(picks), [picks]);

  const columns: TableColumn<CloudStairPick>[] = useMemo(
    () => [
      {
        key: "name",
        header: "股票",
        width: proportional(1.5, { minWidth: 140 }),
        renderCell: (row) => (
          <button
            type="button"
            className="flex min-w-0 flex-col items-start text-left"
            onClick={() => {
              setStockNav(navList, navList.findIndex((item) => item.code === row.code));
              navigate(`/stocks/${row.code}`);
            }}
          >
            <span className="truncate text-sm font-semibold text-ink">{row.name}</span>
            <span className="tabular-nums text-xs text-ink-muted">{row.code}</span>
          </button>
        ),
      },
      {
        key: "pick_date",
        header: "选出日",
        width: pixel(108),
        renderCell: (row) => <span className="tabular-nums text-sm">{row.pick_date}</span>,
      },
      {
        key: "next_day_chg",
        header: "隔日涨跌",
        width: pixel(96),
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
        width: pixel(96),
        align: "end",
        renderCell: (row) => (
          <span className={`tabular-nums text-sm font-medium ${pctClass(row.ret_to_date)}`}>
            {fmtPct(row.ret_to_date)}
          </span>
        ),
      },
      {
        key: "ret_1",
        header: "T+1",
        width: pixel(80),
        align: "end",
        renderCell: (row) => (
          <span className={`tabular-nums text-sm ${pctClass(row.ret_1)}`}>{fmtPct(row.ret_1)}</span>
        ),
      },
      {
        key: "ret_5",
        header: "T+5",
        width: pixel(80),
        align: "end",
        renderCell: (row) => (
          <span className={`tabular-nums text-sm ${pctClass(row.ret_5)}`}>{fmtPct(row.ret_5)}</span>
        ),
      },
      {
        key: "ret_10",
        header: "T+10",
        width: pixel(80),
        align: "end",
        renderCell: (row) => (
          <span className={`tabular-nums text-sm ${pctClass(row.ret_10)}`}>{fmtPct(row.ret_10)}</span>
        ),
      },
      {
        key: "ret_20",
        header: "T+20",
        width: pixel(80),
        align: "end",
        renderCell: (row) => (
          <span className={`tabular-nums text-sm ${pctClass(row.ret_20)}`}>{fmtPct(row.ret_20)}</span>
        ),
      },
      {
        key: "status",
        header: "状态",
        width: pixel(100),
        renderCell: (row) => (
          <span className="text-xs text-ink-secondary">{STATUS_LABEL[row.status] ?? row.status}</span>
        ),
      },
    ],
    [navigate, navList, setStockNav],
  );

  if (isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (error) {
    return <LoadError label="云阶复盘加载失败" />;
  }

  if (!data?.available) {
    return (
      <EmptyState
        title="暂无云阶历史命中"
        description="等每日预热把 cloud_stair 命中写入 factor_cache 后，这里会按票列出选出日、隔日涨跌与持有收益。"
      />
    );
  }

  const hold = summary?.recommended_hold;
  const nextDay = summary?.next_day;
  const toDate = summary?.to_date;

  return (
    <div className="space-y-5">
      <div>
        <Heading level={2}>云阶 · 票级复盘</Heading>
        <Text size="sm" className="mt-1 text-ink-secondary">
          假设选出日收盘后决定、次日开盘买入。隔日涨跌看第二天收盘；持有至今看拿到最新收盘；T+n
          为含成本近似净收益。
        </Text>
        {data.date_span && (
          <Text size="sm" className="mt-1 text-ink-muted">
            样本 {summary?.pick_count ?? 0} 票 · 选出日 {data.date_span.from} → {data.date_span.to}
            {data.truncated ? `（已截断，缓存共 ${data.total_cached_picks} 票）` : ""}
          </Text>
        )}
      </div>

      <List density="compact" hasDividers aria-label="云阶复盘统计">
        <ListItem
          label="隔日表现"
          description={
            nextDay && nextDay.count > 0
              ? `${nextDay.count} 笔可计 · 均 ${fmtPct(nextDay.avg)} · 胜率 ${nextDay.win_rate ?? "—"}%`
              : "尚无次日收盘数据"
          }
        />
        <ListItem
          label="持有至今"
          description={
            toDate && toDate.count > 0
              ? `${toDate.count} 笔可计 · 均 ${fmtPct(toDate.avg)} · 胜率 ${toDate.win_rate ?? "—"}%`
              : "尚无入场后行情"
          }
        />
        <ListItem
          label="建议卖点"
          description={
            hold
              ? `历史均值最好的是 ${hold.label}：均 ${fmtPct(hold.avg)}，胜率 ${hold.win_rate ?? "—"}%（${hold.count} 笔）`
              : "持有窗口样本不足，暂不建议固定卖点"
          }
        />
        <ListItem
          label="观察到的持有天数"
          description={
            summary?.avg_holding_sessions_observed != null
              ? `当前样本平均已持有约 ${summary.avg_holding_sessions_observed} 个交易日（到最新收盘）`
              : "—"
          }
        />
      </List>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {WINDOWS.map((window) => {
          const agg = summary?.windows?.[window.key];
          return (
            <div key={window.key} className="rounded-lg border border-border/40 px-3 py-2.5">
              <div className="text-[11px] text-ink-muted">{window.label} 净收益</div>
              <div className={`mt-1 text-sm font-medium tabular-nums ${pctClass(agg?.avg)}`}>
                {fmtAgg(agg)}
              </div>
            </div>
          );
        })}
      </div>

      {summary?.execution_note && (
        <Banner status="info" title="成交口径" description={summary.execution_note} />
      )}

      {/* 桌面：票级表；移动：列表，避免定高多行塞进 Button */}
      <div className="hidden md:block overflow-x-auto">
        <Table
          data={picks.map((row) => ({ ...row, id: `${row.pick_date}-${row.code}` }))}
          columns={columns}
          idKey="id"
          density="compact"
          dividers="rows"
          hasHover
          textOverflow="truncate"
        />
      </div>

      <div className="md:hidden">
        <List density="spacious" hasDividers aria-label="云阶复盘明细">
          {picks.map((row) => (
            <ListItem
              key={`${row.pick_date}-${row.code}`}
              label={
                <button
                  type="button"
                  className="flex w-full min-w-0 flex-col items-start text-left"
                  onClick={() => {
                    setStockNav(navList, navList.findIndex((item) => item.code === row.code));
                    navigate(`/stocks/${row.code}`);
                  }}
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
  );
}
