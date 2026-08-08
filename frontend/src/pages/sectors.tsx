import { useMemo, useState, type KeyboardEvent } from "react";
import { useNavigate, useSearchParams } from "@/lib/spa-router";
import { Heading } from "@astryxdesign/core/Heading";
import { Icon } from "@astryxdesign/core/Icon";
import { List, ListItem } from "@astryxdesign/core/List";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { Text } from "@astryxdesign/core/Text";
import { SectorHeatChart } from "@/components/charts/sector-heat-chart";
import { DataBrief } from "@/components/dashboard/data-brief";
import { PageHeader, PageShell } from "@/components/layout/page-shell";
import { PageTransition } from "@/components/layout/page-transition";
import { Button, Input, LoadError, Skeleton } from "@/components/ui";
import { usePipelineStatus, useSectorDetail, useSectors, useSuperB1 } from "@/lib/hooks";
import type { SectorDetailStock, SectorsData } from "@/lib/api";

type RankingItem = NonNullable<SectorsData["ranking"]>[number];
type Filter = "all" | "leader" | "warming";

const reasonText: Record<string, string> = {
  market_model_unvalidated: "市场层尚未通过前向验证",
  weekly_four_ma_shadow_fail: "周线四均线影子条件未通过",
  weekly_four_ma_gate: "周线四均线条件未通过",
  stock_risk_veto: "个股风险门禁否决",
  sector_gate: "板块门禁未通过",
  market_gate: "市场门禁未通过",
  unresolved_tie_over_3: "候选过多且没有可靠精排模型",
};

function signed(value: number | null | undefined, digits = 1, suffix = "") {
  if (value == null) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}${suffix}`;
}

function trendClass(value: number | null | undefined) {
  if (value == null || value === 0) return "text-ink-muted";
  return value > 0 ? "text-bull" : "text-bear";
}

function stageKind(item: RankingItem, relayNames: Set<string>) {
  if (item.score >= 80) return "主线";
  if (relayNames.has(item.name)) return "接力";
  if (item.delta3 >= 8) return "升温";
  return "观察";
}

function RankingRow({
  item, selected, b1Count, kind, onSelect, onMove,
}: {
  item: RankingItem;
  selected: boolean;
  b1Count: number;
  kind: string;
  onSelect: () => void;
  onMove: (delta: -1 | 1) => void;
}) {
  return (
    <ListItem
      id={`sector-row-${item.rank}`}
      isSelected={selected}
      onClick={onSelect}
      onKeyDown={(event: KeyboardEvent) => {
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
          event.preventDefault();
          onMove(event.key === "ArrowDown" ? 1 : -1);
        }
      }}
      startContent={
        <span className={`num w-6 text-xs font-semibold ${item.rank <= 3 ? "text-accent" : "text-ink-muted"}`}>
          {item.rank}
        </span>
      }
      label={<span className="block truncate text-sm font-semibold text-ink">{item.name}</span>}
      description={<span className="block truncate text-[10px] text-ink-muted">{kind} · {item.stage}</span>}
      endContent={
        <span className="grid grid-cols-[44px_54px_36px] items-center gap-1 sm:grid-cols-[44px_54px_54px_36px]">
          <span className="num text-right text-sm font-semibold text-ink">{Math.round(item.score)}</span>
          <span className={`num text-right text-xs ${trendClass(item.delta3)}`}>{signed(item.delta3, 1)}</span>
          <span className="num hidden text-right text-xs text-ink-secondary sm:block">{item.breadth_ma10 == null ? "—" : `${Math.round(item.breadth_ma10)}%`}</span>
          <span className={`num text-right text-xs ${b1Count ? "text-bull" : "text-ink-muted"}`}>{b1Count}</span>
        </span>
      }
    />
  );
}

function CandidateRow({ stock, onOpen, onSelect }: { stock: SectorDetailStock; onOpen: () => void; onSelect: () => void }) {
  const weekly = stock.weekly;
  const weeklyLabel = weekly?.passed === true ? "四线通过" : weekly?.passed === false ? "影子未过" : "未计算";
  const action = stock.action === "buy" ? "合格" : stock.action === "avoid" ? "未通过" : stock.action === "observe" ? "观察" : "未入池";
  return (
    <div className="grid min-h-[58px] grid-cols-[minmax(132px,1.35fr)_minmax(135px,1.2fr)_92px_70px_76px_62px_72px] items-center gap-3 border-b border-border/60 px-3 text-xs last:border-b-0">
      <div className="min-w-0">
        <Button label={`查看 ${stock.name}`} variant="ghost" size="sm" className="justify-start truncate font-semibold text-ink hover:text-accent" onClick={onSelect}>{stock.name} <span className="ml-1 font-mono text-[10px] font-normal text-ink-muted">{stock.code}</span></Button>
        <p className="mt-1 text-[10px] text-ink-muted">1日 {signed(stock.ret1, 2, "%")} · 5日 {signed(stock.ret5, 2, "%")}</p>
      </div>
      <div className="min-w-0">
        <p className={stock.b1 ? "truncate text-accent-light" : "truncate text-ink-secondary"}>{stock.b1 ? stock.b1_signals[0] ?? "Super B1" : "无 Super B1"}</p>
        <p className="mt-1 truncate text-[10px] text-ink-muted">辅助确认 {stock.confirmation_count} 项</p>
      </div>
      <span className={weekly?.passed ? "text-bear" : "text-ink-muted"}>{weeklyLabel}</span>
      <span className={stock.data_status === "complete" ? "text-bear" : "text-accent"}>{stock.data_status === "complete" ? "完整" : "部分"}</span>
      <span className={stock.risk_status === "blocked" ? "text-bull" : stock.risk_status === "passed" ? "text-bear" : "text-ink-muted"}>
        {stock.risk_status === "blocked" ? "已否决" : stock.risk_status === "passed" ? "通过" : "未评估"}
      </span>
      <span className={stock.action === "buy" ? "text-bull" : stock.action === "avoid" ? "text-bull" : "text-accent"}>{action}</span>
      <Button variant="secondary" size="sm" onClick={onOpen} className="min-h-8 px-2 text-[11px]">看 K 线</Button>
    </div>
  );
}

function CandidateCard({ stock, onOpen, onSelect }: { stock: SectorDetailStock; onOpen: () => void; onSelect: () => void }) {
  return (
    <article className="border-b border-border/60 p-4 last:border-b-0">
      <div className="flex items-start justify-between gap-3">
        <div>
          <Button label={`查看 ${stock.name}`} variant="ghost" size="sm" className="justify-start font-semibold text-ink hover:text-accent" onClick={onSelect}>{stock.name} <span className="font-mono text-[10px] font-normal text-ink-muted">{stock.code}</span></Button>
          <p className="mt-1 text-xs text-ink-muted">1日 {signed(stock.ret1, 2, "%")} · 5日 {signed(stock.ret5, 2, "%")}</p>
        </div>
        <span className="rounded-md border border-accent/25 bg-accent-dim px-2 py-1 text-[10px] text-accent">
          {stock.action === "buy" ? "合格" : stock.action === "avoid" ? "未通过" : stock.action === "observe" ? "观察" : "未入池"}
        </span>
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
        <div><dt className="text-ink-muted">量化依据</dt><dd className="mt-0.5 text-ink-secondary">{stock.b1 ? stock.b1_signals[0] ?? "Super B1" : "无 Super B1"}</dd></div>
        <div><dt className="text-ink-muted">周线四均线</dt><dd className="mt-0.5 text-ink-secondary">{stock.weekly?.passed === true ? "通过" : stock.weekly?.passed === false ? "影子未过" : "未计算"}</dd></div>
        <div><dt className="text-ink-muted">数据完整性</dt><dd className="mt-0.5 text-ink-secondary">{stock.data_status === "complete" ? "完整" : "部分"}</dd></div>
        <div><dt className="text-ink-muted">风险门禁</dt><dd className="mt-0.5 text-ink-secondary">{stock.risk_status === "blocked" ? "已否决" : stock.risk_status === "passed" ? "通过" : "未评估"}</dd></div>
      </dl>
      <Button variant="secondary" size="sm" onClick={onOpen} className="mt-3 w-full">查看 K 线</Button>
    </article>
  );
}

export function Component() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const sectors = useSectors();
  const b1 = useSuperB1();
  const pipeline = usePipelineStatus();
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [selectedName, setSelectedName] = useState(searchParams.get("sector") ?? "");
  const [selectedStockCode, setSelectedStockCode] = useState("");

  const data = sectors.data;
  const ranking = useMemo(() => data?.ranking ?? [], [data?.ranking]);
  const relayNames = useMemo(() => new Set((data?.relay ?? []).map((item) => item.name)), [data?.relay]);
  const b1Counts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const row of b1.data?.hits ?? []) {
      if (row.industry) counts[row.industry] = (counts[row.industry] ?? 0) + 1;
    }
    return counts;
  }, [b1.data?.hits]);

  const effectiveSelectedName = ranking.some((row) => row.name === selectedName)
    ? selectedName
    : ranking[0]?.name ?? "";
  const detail = useSectorDetail(effectiveSelectedName || null);
  const detailStocks = useMemo(() => detail.data?.stocks ?? [], [detail.data?.stocks]);
  const selectedStock = detailStocks.find((row) => row.code === selectedStockCode) ?? detailStocks[0];

  const filtered = ranking.filter((item) => {
    const matchesText = item.name.toLowerCase().includes(query.trim().toLowerCase());
    if (!matchesText) return false;
    if (filter === "leader") return item.score >= 80;
    if (filter === "warming") return relayNames.has(item.name) || item.delta3 >= 8;
    return true;
  });
  const selected = ranking.find((item) => item.name === effectiveSelectedName);

  const selectSector = (name: string) => {
    setSelectedName(name);
    setSelectedStockCode("");
    setSearchParams({ sector: name }, { replace: true });
  };
  const moveSelection = (item: RankingItem, delta: -1 | 1) => {
    const index = filtered.findIndex((row) => row.name === item.name);
    const next = filtered[index + delta];
    if (!next) return;
    selectSector(next.name);
    requestAnimationFrame(() =>
      document.getElementById(`sector-row-${next.rank}`)?.querySelector("button")?.focus(),
    );
  };

  if (sectors.isLoading) {
    return (
      <PageShell>
        <PageHeader
          title="板块工作台"
          description="当前仅展示研究候选，不构成交易动作"
          endContent={<Text type="supporting">正在读取板块数据</Text>}
        />
        <DataBrief data={pipeline.data} failed={Boolean(pipeline.error)} />
        <Skeleton className="h-[560px] w-full rounded-xl" />
      </PageShell>
    );
  }
  if (sectors.error) {
    return (
      <PageTransition>
        <PageShell>
          <PageHeader
            title="板块工作台"
            description="行情不可用时不展示旧板块结论"
            endContent={<Text type="supporting">等待正式快照</Text>}
          />
          <DataBrief data={pipeline.data} failed={Boolean(pipeline.error)} />
          <LoadError label="板块数据尚未就绪" onRetry={() => sectors.mutate()} />
        </PageShell>
      </PageTransition>
    );
  }

  const selectedKind = selected ? stageKind(selected, relayNames) : "观察";
  const conclusion = !selected
    ? "板块数据尚未准备完成"
    : selected.score >= 80 && selected.delta3 >= 0
      ? "强度领先，但只保留研究观察"
      : selected.score >= 80
        ? "仍在高位，但热度回落，只保留研究观察"
        : selected.delta3 >= 8
          ? "热度正在上升，等待规则候选与风险门禁确认"
          : "尚未形成明确主线，继续观察";
  return (
    <PageTransition>
      <PageShell>
        <PageHeader
          title="板块工作台"
          description="当前仅展示研究候选，不构成交易动作"
          endContent={<Text type="supporting" className="num">数据截至 {pipeline.data?.market.local_date ?? data?.trade_date ?? "待更新"} 收盘</Text>}
        />

        <DataBrief
          data={pipeline.data}
          failed={Boolean(pipeline.error)}
          contentSnapshotId={data?.snapshot_id}
        />

        <div className="mt-3 grid gap-3 lg:grid-cols-[420px_minmax(0,1fr)]">
          <section className="overflow-hidden rounded-xl border border-border bg-surface" aria-label="板块排名">
            <div className="border-b border-border p-3">
              <div className="flex items-center justify-between gap-3">
                <Heading level={2}>板块排名</Heading>
                <div className="relative w-48 max-w-[58%]">
                  <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索板块" aria-label="搜索板块" className="h-9 pr-8 text-xs" />
                  <Icon icon="search" size="xsm" className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2" color="secondary" />
                </div>
              </div>
              <div className="mt-3">
                <SegmentedControl value={filter} onChange={(value) => setFilter(value as Filter)} label="板块状态筛选" size="sm">
                  <SegmentedControlItem value="all" label="全部" />
                  <SegmentedControlItem value="leader" label="主线" />
                  <SegmentedControlItem value="warming" label="升温/接力" />
                </SegmentedControl>
              </div>
            </div>
            <div className="grid grid-cols-[28px_minmax(96px,1fr)_44px_54px_36px] gap-2 border-b border-border bg-inset px-3 py-2 text-[10px] text-ink-muted sm:grid-cols-[28px_minmax(118px,1fr)_44px_54px_54px_36px]">
              <span>#</span><span>板块 / 阶段</span><span className="text-right">强度</span><span className="text-right">3日变化</span><span className="hidden text-right sm:block">站上MA10</span><span className="text-right">B1</span>
            </div>
            <div className="max-h-[660px] overflow-y-auto lg:h-[660px]">
              {filtered.length ? (
                <List density="compact" hasDividers aria-label="板块排名列表">
                  {filtered.map((item) => (
                    <RankingRow
                      key={item.name}
                      item={item}
                      selected={item.name === effectiveSelectedName}
                      b1Count={b1Counts[item.name] ?? 0}
                      kind={stageKind(item, relayNames)}
                      onSelect={() => selectSector(item.name)}
                      onMove={(delta) => moveSelection(item, delta)}
                    />
                  ))}
                </List>
              ) : <Text type="supporting" className="block px-4 py-10 text-center">没有符合条件的板块</Text>}
            </div>
          </section>

          <div className="min-w-0 space-y-3">
            <section className="rounded-xl border border-border bg-surface p-4 sm:p-5">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <div className="flex items-center gap-2">
                    <Heading level={2}>{effectiveSelectedName || "未选择板块"}</Heading>
                    <span className="rounded-md border border-accent/25 bg-accent-dim px-2 py-0.5 text-[10px] text-accent">{selectedKind}</span>
                  </div>
                  <Text type="body" className="mt-2 block" weight="bold">结论：{conclusion}</Text>
                </div>
                <dl className="flex gap-5 text-right text-xs sm:gap-7">
                  <div><dt className="text-ink-muted">强度排名</dt><dd className="num mt-1 text-base font-semibold text-ink">{selected?.rank ?? "—"}<span className="ml-1 text-[10px] font-normal text-ink-muted">/ {selected?.total ?? "—"}</span></dd></div>
                  <div><dt className="text-ink-muted">强度</dt><dd className="num mt-1 text-lg font-semibold text-accent">{selected?.score == null ? "—" : Math.round(selected.score)}</dd></div>
                  <div><dt className="text-ink-muted">3日热度变化</dt><dd className={`num mt-1 text-base font-semibold ${trendClass(selected?.delta3)}`}>{signed(selected?.delta3, 1, " 分")}</dd></div>
                </dl>
              </div>

              <div className="mt-4 grid min-w-0 grid-cols-[minmax(0,1fr)] gap-3 xl:grid-cols-[minmax(0,1.25fr)_minmax(0,.95fr)]">
                <div className="min-w-0 rounded-lg border border-border bg-canvas/35 p-3">
                  <div className="flex items-center justify-between">
                    <h3 className="text-xs font-semibold text-ink-secondary">近 {selected?.heat_series?.length ?? 0} 个交易日热度</h3>
                    <span className="text-[10px] text-ink-muted">0–100 分 · 主线阈值 80</span>
                  </div>
                  <SectorHeatChart name={effectiveSelectedName} dates={data?.series_dates ?? []} values={selected?.heat_series ?? []} />
                </div>
                <div className="min-w-0 overflow-hidden rounded-lg border border-border bg-canvas/35">
                  <div className="border-b border-border px-3 py-2 text-xs font-semibold text-ink-secondary">指标说明</div>
                  {[
                    ["相对强度分", selected?.relative_strength, "同业横向百分位，0–100"],
                    ["上涨与趋势广度", selected?.breadth, "上涨、站上MA10与新高的组合比例"],
                    ["站上 MA10 占比", selected?.breadth_ma10, "当前成分股比例"],
                    ["成交活跃度", selected?.turn_ratio, "近3日占比 / 近20日占比"],
                  ].map(([label, value, note]) => (
                    <div key={String(label)} className="grid grid-cols-[1fr_auto] gap-3 border-b border-border/60 px-3 py-3 last:border-b-0">
                      <div><p className="text-xs text-ink-secondary">{label}</p><p className="mt-1 text-[10px] text-ink-muted">{note}</p></div>
                      <p className="num self-center text-sm font-semibold text-ink">{value == null ? "—" : label === "成交活跃度" ? `${Number(value).toFixed(2)}×` : `${Number(value).toFixed(1)}${label === "相对强度分" ? "" : "%"}`}</p>
                    </div>
                  ))}
                </div>
              </div>
            </section>

            <section className="overflow-hidden rounded-xl border border-border bg-surface">
              <div className="flex items-center justify-between border-b border-border px-4 py-3">
                <div>
                  <h3 className="text-sm font-semibold text-ink">候选对比</h3>
                  <p className="mt-1 text-[10px] text-ink-muted">B1 是规则命中；“观察”不等于推荐买入</p>
                </div>
                <span className="num text-xs text-ink-muted">{detailStocks.length} 只</span>
              </div>
              {detail.isLoading ? <Skeleton className="m-4 h-40" /> : detail.error ? <LoadError label="板块候选加载失败" onRetry={() => detail.mutate()} /> : detailStocks.length ? (
                <>
                  <div className="hidden grid-cols-[minmax(132px,1.35fr)_minmax(135px,1.2fr)_92px_70px_76px_62px_72px] gap-3 border-b border-border bg-inset px-3 py-2 text-[10px] text-ink-muted md:grid">
                    <span>股票 / 涨跌</span><span>量化依据</span><span>周线四均线</span><span>数据</span><span>风险门禁</span><span>动作</span><span></span>
                  </div>
                  <div className="hidden md:block">{detailStocks.slice(0, 8).map((stock) => <CandidateRow key={stock.code} stock={stock} onSelect={() => setSelectedStockCode(stock.code)} onOpen={() => navigate(`/stock/${stock.code}`)} />)}</div>
                  <div className="md:hidden">{detailStocks.slice(0, 6).map((stock) => <CandidateCard key={stock.code} stock={stock} onSelect={() => setSelectedStockCode(stock.code)} onOpen={() => navigate(`/stock/${stock.code}`)} />)}</div>
                </>
              ) : <p className="px-4 py-10 text-center text-sm text-ink-muted">{detail.data?.reason ?? "当前板块没有可用成分股"}</p>}
            </section>

            {selectedStock && (
              <section className="rounded-xl border border-border bg-surface p-4">
                <div className="flex min-h-8 items-center gap-2 text-left text-sm font-semibold text-ink">
                  <Icon icon="success" size="xsm" color="accent" />{selectedStock.name}<span className="font-mono text-[10px] font-normal text-ink-muted">{selectedStock.code}</span>
                </div>
                <div className="mt-3 grid gap-4 text-xs sm:grid-cols-3">
                  <div className="sm:border-r sm:border-border sm:pr-4">
                    <h4 className="font-semibold text-ink-secondary">量化依据</h4>
                    <ul className="mt-2 space-y-1.5 text-ink-muted">
                      <li>1日 {signed(selectedStock.ret1, 2, "%")}；5日 {signed(selectedStock.ret5, 2, "%")}</li>
                      <li>{selectedStock.b1 ? `Super B1：${selectedStock.b1_signals.join("、") || "命中"}` : "未命中 Super B1"}</li>
                      <li>辅助确认 {selectedStock.confirmation_count} 项</li>
                    </ul>
                  </div>
                  <div className="sm:border-r sm:border-border sm:pr-4">
                    <h4 className="font-semibold text-ink-secondary">反证条件</h4>
                    <ul className="mt-2 space-y-1.5 text-ink-muted">
                      {(selectedStock.reason_codes?.length ? selectedStock.reason_codes : ["no_recorded_counterevidence"]).map((code) => (
                        <li key={code}>{reasonText[code] ?? (code === "no_recorded_counterevidence" ? "当前没有已记录的量化反证" : code)}</li>
                      ))}
                    </ul>
                  </div>
                  <div>
                    <h4 className="font-semibold text-ink-secondary">数据缺口</h4>
                    <ul className="mt-2 space-y-1.5 text-ink-muted">
                      <li>日线数据：{selectedStock.data_status === "complete" ? "完整" : "部分缺失"}</li>
                      <li>周线四均线：{selectedStock.weekly ? "已计算" : "尚未计算"}</li>
                      <li>财报与公告：{selectedStock.decision_run_id ? "按决策账本记录" : "未进入当前决策账本"}</li>
                    </ul>
                  </div>
                </div>
              </section>
            )}
          </div>
        </div>

        <Text type="supporting" className="mt-3 flex items-center gap-2 px-1"><Icon icon="info" size="xsm" />板块热度是研究特征，尚未被证明能单独预测个股收益；页面不构成投资建议。</Text>
      </PageShell>
    </PageTransition>
  );
}
