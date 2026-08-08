import { useState } from "react";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Heading } from "@astryxdesign/core/Heading";
import { List, ListItem } from "@astryxdesign/core/List";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { Text } from "@astryxdesign/core/Text";
import { KlineChart } from "@/components/charts/kline-chart";
import { HoldPathChart } from "@/components/review/review-charts";
import { Skeleton } from "@/components/ui";
import { useKline } from "@/lib/hooks";
import type { StrategyReviewPick } from "@/lib/api";
import type { StockReviewRow } from "@/lib/review-stock";

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
  awaiting_next_session: "等次日开盘",
  tracking: "次日跟踪中",
  open: "持有中",
  complete: "窗口已满",
  no_price: "无行情",
  signal_missing: "缺信号日",
  entry_unavailable: "无法入场",
};

function Metric({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <div className="rounded-lg border border-border/40 px-3 py-2">
      <div className="text-[11px] text-ink-muted">{label}</div>
      <div className={`mt-0.5 text-sm font-medium tabular-nums ${tone ?? "text-ink"}`}>{value}</div>
    </div>
  );
}

function PickDetailBody({
  pick,
  history,
}: {
  pick: StrategyReviewPick | StockReviewRow;
  history: StrategyReviewPick[];
}) {
  const [period, setPeriod] = useState<"daily" | "weekly">("daily");
  const [activeDate, setActiveDate] = useState(pick.pick_date);
  const historyRows = history.length ? history : [pick];
  const view = historyRows.find((row) => row.pick_date === activeDate) ?? historyRows[0] ?? pick;
  const { data: kline, isLoading: klineLoading } = useKline(pick.code, period);

  const signalMarks = historyRows.map((row, index) => ({
    date: row.pick_date,
    category: index === 0 ? "首次选出" : `第${index + 1}次`,
  }));

  return (
    <div className="flex max-h-[calc(90vh-72px)] flex-col gap-4 overflow-y-auto px-4 pb-4">
      {historyRows.length > 1 && (
        <div>
          <Heading level={3}>入选历史</Heading>
          <List density="compact" hasDividers className="mt-2" aria-label="入选历史">
            {historyRows.map((row) => (
              <ListItem
                key={`${row.pick_date}-${row.code}`}
                label={row.pick_date}
                description={`隔日 ${fmtPct(row.next_day_chg)} · 至今 ${fmtPct(row.ret_to_date)} · T+5 ${fmtPct(row.ret_5)}`}
                isSelected={view.pick_date === row.pick_date}
                onClick={() => setActiveDate(row.pick_date)}
              />
            ))}
          </List>
        </div>
      )}

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Metric label="选出日" value={view.pick_date} />
        <Metric label="隔日涨跌" value={fmtPct(view.next_day_chg)} tone={pctClass(view.next_day_chg)} />
        <Metric label="次日开盘缺口" value={fmtPct(view.entry_gap_pct)} tone={pctClass(view.entry_gap_pct)} />
        <Metric label="持有至今" value={fmtPct(view.ret_to_date)} tone={pctClass(view.ret_to_date)} />
        <Metric label="状态" value={STATUS_LABEL[view.status] ?? view.status} />
        <Metric label="入场日" value={view.entry_date ?? "—"} />
        <Metric label="入场价(开)" value={fmtNum(view.entry_price)} />
        <Metric label="信号收盘" value={fmtNum(view.signal_close as number | null)} />
        <Metric label="最新收盘" value={fmtNum(view.latest_close)} />
        <Metric label="持有交易日" value={view.holding_sessions_to_date?.toString() ?? "—"} />
        <Metric label="期间最大浮盈" value={fmtPct(view.mfe_to_date)} tone={pctClass(view.mfe_to_date)} />
        <Metric label="期间最大浮亏" value={fmtPct(view.mae_to_date)} tone={pctClass(view.mae_to_date)} />
        <Metric label="行业" value={view.industry || "—"} />
        <Metric label="截至" value={view.as_of ?? "—"} />
      </div>

      <div>
        <Heading level={3}>持有窗口</Heading>
        <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
          {([1, 5, 10, 20] as const).map((n) => (
            <div key={n} className="rounded-lg border border-border/40 px-3 py-2">
              <div className="text-[11px] text-ink-muted">T+{n} 净收益</div>
              <div className={`mt-0.5 text-sm font-medium tabular-nums ${pctClass(view[`ret_${n}`] as number | null)}`}>
                {fmtPct(view[`ret_${n}`] as number | null)}
              </div>
              <div className="mt-1 text-[11px] text-ink-muted">
                高 {fmtPct(view[`max_gain_${n}`] as number | null)} · 回撤{" "}
                {fmtPct(view[`max_dd_${n}`] as number | null)}
              </div>
              <div className="text-[11px] text-ink-muted">
                卖出 {(view[`exit_date_${n}`] as string | null) ?? "—"}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div>
        <Heading level={3}>入场后路径</Heading>
        <div className="mt-2">
          <HoldPathChart pick={view} />
        </div>
      </div>

      <div>
        <div className="mb-2 flex items-center justify-between gap-3">
          <Heading level={3}>K 线</Heading>
          <SegmentedControl
            value={period}
            onChange={(value) => setPeriod(value as "daily" | "weekly")}
            label="K线周期"
            size="sm"
          >
            <SegmentedControlItem value="daily" label="日线" />
            <SegmentedControlItem value="weekly" label="周线" />
          </SegmentedControl>
        </div>
        {klineLoading && <Skeleton className="h-72 w-full" />}
        {!klineLoading && kline?.data?.length ? (
          <div className="h-80 w-full">
            <KlineChart
              data={kline.data}
              period={period}
              signals={period === "daily" ? signalMarks : undefined}
              className="h-full w-full"
            />
          </div>
        ) : (
          !klineLoading && (
            <Text size="sm" className="text-ink-muted">
              暂无 K 线
            </Text>
          )
        )}
        {period === "daily" && (
          <Text size="sm" className="mt-1 text-ink-muted">
            金点为历次选出日；当前查看 {view.pick_date}
            {view.entry_date ? ` · 入场 ${view.entry_date}` : ""}
          </Text>
        )}
      </div>

      {view.signal && Object.keys(view.signal).length > 0 && (
        <div>
          <Heading level={3}>信号字段</Heading>
          <List density="compact" hasDividers className="mt-2" aria-label="信号字段">
            {Object.entries(view.signal).map(([key, value]) => (
              <ListItem
                key={key}
                label={key}
                description={typeof value === "object" ? JSON.stringify(value) : String(value)}
              />
            ))}
          </List>
        </div>
      )}
    </div>
  );
}

export function PickDetailDialog({
  pick,
  history = [],
  isOpen,
  onOpenChange,
}: {
  pick: StrategyReviewPick | StockReviewRow | null;
  history?: StrategyReviewPick[];
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  if (!pick) return null;

  const title = `${pick.name} · ${pick.code}`;
  const historyRows = history.length ? history : [pick];
  const subtitle = `${pick.strategy_name ?? pick.strategy ?? ""} · 首次 ${
    "first_pick_date" in pick ? pick.first_pick_date : pick.pick_date
  }${historyRows.length > 1 ? ` · 共${historyRows.length}次` : ""}`;

  return (
    <Dialog
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      purpose="info"
      width="min(960px, 96vw)"
      maxHeight="90vh"
    >
      <DialogHeader title={title} subtitle={subtitle} onOpenChange={onOpenChange} hasDivider />
      {isOpen ? <PickDetailBody key={pick.code} pick={pick} history={historyRows} /> : null}
    </Dialog>
  );
}
