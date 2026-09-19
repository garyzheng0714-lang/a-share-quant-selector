import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "@/lib/spa-router";
import { Badge } from "@astryxdesign/core/Badge";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { Heading } from "@astryxdesign/core/Heading";
import { Icon } from "@astryxdesign/core/Icon";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { Selector } from "@astryxdesign/core/Selector";
import { Table, pixel, proportional, type TableColumn } from "@astryxdesign/core/Table";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
import { ToggleButton } from "@astryxdesign/core/ToggleButton";
import { Token } from "@astryxdesign/core/Token";
import { type ComposeHit, type ComposeJoin, type FactorMeta, type FactorPreset, type SignalStock } from "@/lib/api";
import { useFactorCompose, useFactors } from "@/lib/hooks";
import { useAppStore } from "@/lib/store";

type SortKey = "streak" | "vol" | "pct";

const MAX_RESULTS = 300;

function toNavStocks(hits: ComposeHit[]): SignalStock[] {
  return hits.map((hit) => ({ code: hit.code, name: hit.name, industry: hit.industry }));
}

function pctClass(value: number | null) {
  if (value === null || value === 0) return "text-ink-muted";
  return value > 0 ? "text-bull" : "text-bear";
}

function formatNumber(value: number | null | undefined, digits = 2) {
  return value === null || value === undefined || Number.isNaN(value) ? "—" : value.toFixed(digits);
}

function formatPct(value: number | null) {
  return value === null ? "—" : `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

/** 20 日收盘迷你走势：数据可视化元素，颜色跟随首尾涨跌 */
function Sparkline({ values }: { values: number[] }) {
  if (values.length < 2) return <span className="text-ink-muted">—</span>;
  const w = 56;
  const h = 20;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const points = values
    .map((v, i) => `${((i / (values.length - 1)) * (w - 2) + 1).toFixed(1)},${(h - 1 - ((v - min) / span) * (h - 2)).toFixed(1)}`)
    .join(" ");
  const up = values[values.length - 1] >= values[0];
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true" className={up ? "text-bull" : "text-bear"}>
      <polyline points={points} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

function FactorRow({
  factor,
  selected,
  onToggle,
}: {
  factor: FactorMeta;
  selected: boolean;
  onToggle: (checked: boolean) => void;
}) {
  return (
    <div className={`strategy-library-row grid grid-cols-[28px_minmax(0,1fr)_40px] ${selected ? "is-active" : ""}`}>
      <CheckboxInput label={`选择 ${factor.name}`} isLabelHidden value={selected} onChange={onToggle} size="sm" />
      <Button
        label={selected ? `取消 ${factor.name}` : `选中 ${factor.name}，直接出结果`}
        variant="ghost"
        size="sm"
        className="min-w-0 w-full min-h-10 h-auto justify-start py-1 text-left"
        onClick={() => onToggle(!selected)}
      >
        <span className="min-w-0" title={factor.name}>
          <Text type="label" className="block truncate">{factor.name}</Text>
          <Text type="supporting" className="mt-0.5 block min-w-0 truncate">{factor.plain || factor.desc}</Text>
        </span>
      </Button>
      <span className="w-10 shrink-0 text-right text-xs tabular-nums text-ink-secondary">
        {factor.today_hits === null ? "—" : factor.today_hits}
      </span>
    </div>
  );
}

export function FactorWorkbench() {
  const { data: meta, isLoading: metaLoading, error: metaError, mutate: retryMeta } = useFactors();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const setStockNav = useAppStore((state) => state.setStockNav);
  const [librarySearch, setLibrarySearch] = useState("");
  const [resultSearch, setResultSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("streak");
  const [industry, setIndustry] = useState("");

  const factorKeys = useMemo(() => new Set(meta?.factors.map((factor) => factor.key) ?? []), [meta]);
  const selectedKeys = useMemo(() => {
    const raw = searchParams.get("strategies")?.split(",").filter(Boolean) ?? [];
    return raw.filter((key, index) => factorKeys.has(key) && raw.indexOf(key) === index);
  }, [factorKeys, searchParams]);
  const join: ComposeJoin = searchParams.get("join") === "or" ? "or" : "and";
  const date = searchParams.get("date") || undefined;
  const activePreset = useMemo(() => {
    if (!meta) return null;
    return meta.presets.find((preset) =>
      preset.join === join
      && preset.keys.length === selectedKeys.length
      && preset.keys.every((key) => selectedKeys.includes(key)),
    ) ?? null;
  }, [join, meta, selectedKeys]);

  const { data: compose, isLoading: composeLoading, error: composeError, mutate: retryCompose } = useFactorCompose(selectedKeys, join, date);

  const updateParams = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(searchParams);
    for (const [key, value] of Object.entries(patch)) {
      if (value === null || value === "") next.delete(key);
      else next.set(key, value);
    }
    setSearchParams(next, { replace: true });
  };

  const setSelection = (keys: string[], nextJoin: ComposeJoin = join) => {
    updateParams({ strategies: keys.length ? keys.join(",") : null, join: nextJoin === "or" ? "or" : null });
    setResultSearch("");
  };

  const toggleFactor = (key: string, checked: boolean) => {
    if (checked) {
      if (!selectedKeys.includes(key)) setSelection([...selectedKeys, key]);
    } else {
      setSelection(selectedKeys.filter((item) => item !== key));
    }
  };

  const applyPreset = (preset: FactorPreset) => {
    if (activePreset?.key === preset.key) setSelection([]);
    else setSelection(preset.keys, preset.join);
  };

  const selectedFactors = selectedKeys
    .map((key) => meta?.factors.find((factor) => factor.key === key))
    .filter((factor): factor is FactorMeta => Boolean(factor));
  const nameOf = (key: string) => meta?.factors.find((factor) => factor.key === key)?.name ?? key;

  const allHits = useMemo(() => (compose?.available ? compose.hits ?? [] : []), [compose]);
  /** 当日结果里出现的行业及其数量，供筛选 */
  const industries = useMemo(() => {
    const counts = new Map<string, number>();
    for (const hit of allHits) if (hit.industry) counts.set(hit.industry, (counts.get(hit.industry) ?? 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [allHits]);
  const hits = useMemo(() => {
    const filtered = allHits.filter((hit) =>
      (!industry || hit.industry === industry)
      && `${hit.code} ${hit.name} ${hit.industry}`.toLowerCase().includes(resultSearch.toLowerCase()),
    );
    const sorted = [...filtered];
    if (sortKey === "streak") sorted.sort((a, b) => b.matched.length - a.matched.length || b.streak - a.streak || (a.J ?? 999) - (b.J ?? 999));
    if (sortKey === "vol") sorted.sort((a, b) => (b.vol_ratio ?? -1) - (a.vol_ratio ?? -1));
    if (sortKey === "pct") sorted.sort((a, b) => (b.pct_change ?? -999) - (a.pct_change ?? -999));
    return sorted;
  }, [allHits, industry, resultSearch, sortKey]);

  const totalHits = compose?.available ? compose.hits?.length ?? 0 : 0;
  const resultError = composeError
    ? "组合结果读取失败。"
    : compose && !compose.available
      ? compose.reason || "至少一个因子结果不可用，已停止计算，避免展示不完整结果。"
      : undefined;
  const resultPending = selectedKeys.length > 0 && !compose && composeLoading;

  const openStock = (hit: ComposeHit) => {
    const index = Math.max(0, hits.findIndex((item) => item.code === hit.code));
    setStockNav(toNavStocks(hits), index);
    navigate(`/stock/${hit.code}`);
  };

  const columns: TableColumn<ComposeHit>[] = [
    {
      key: "name",
      header: "股票",
      width: proportional(1.3, { minWidth: 140 }),
      renderCell: (hit) => (
        <Button label={`查看 ${hit.name || hit.code}`} variant="ghost" size="sm" className="justify-start text-left" onClick={() => openStock(hit)}>
          <span className="block text-xs font-medium text-ink">{hit.name || "未知"}</span>
          <span className="mt-0.5 block font-mono text-[11px] text-ink-muted">{hit.code}</span>
        </Button>
      ),
    },
    { key: "spark", header: "20日", width: pixel(72), renderCell: (hit) => <Sparkline values={hit.spark ?? []} /> },
    {
      key: "close",
      header: "最新价 / 涨跌",
      width: pixel(104),
      align: "end",
      renderCell: (hit) => (
        <span className="block text-right">
          <span className="block tabular-nums text-ink">{formatNumber(hit.close)}</span>
          <span className={`block text-[11px] tabular-nums ${pctClass(hit.pct_change)}`}>{formatPct(hit.pct_change)}</span>
        </span>
      ),
    },
    {
      key: "J",
      header: "J / RSI",
      width: pixel(76),
      align: "end",
      renderCell: (hit) => (
        <span className="block text-right">
          <span className="block tabular-nums">{formatNumber(hit.J, 1)}</span>
          <span className="block text-[11px] tabular-nums text-ink-muted">RSI {formatNumber(hit.RSI, 0)}</span>
        </span>
      ),
    },
    { key: "industry", header: "行业", width: proportional(1, { minWidth: 96 }), renderCell: (hit) => hit.industry || "—" },
    { key: "cap", header: "流通市值", width: pixel(80), align: "end", renderCell: (hit) => <span className="tabular-nums">{hit.cap_yi === null ? "—" : `${hit.cap_yi}亿`}</span> },
    { key: "vol", header: "量比", width: pixel(60), align: "end", renderCell: (hit) => <span className={`tabular-nums ${(hit.vol_ratio ?? 0) >= 1.5 ? "text-bull" : ""}`}>{hit.vol_ratio == null ? "—" : hit.vol_ratio.toFixed(1)}</span> },
    {
      key: "matched",
      header: "命中因子",
      width: proportional(1.1, { minWidth: 120 }),
      renderCell: (hit) => (
        <span className="flex flex-wrap gap-1">
          {hit.matched.map((key) => <Token key={key} label={nameOf(key)} size="sm" color={hit.matched.length > 1 ? "green" : "default"} />)}
        </span>
      ),
    },
    { key: "streak", header: "连命中", width: pixel(64), align: "end", renderCell: (hit) => <span className="tabular-nums">{hit.streak} 天</span> },
  ];

  if (metaLoading) {
    return <div className="grid min-h-[620px] place-items-center text-sm text-ink-muted">正在读取真实策略因子…</div>;
  }
  if (metaError || !meta) {
    return (
      <div className="mx-auto max-w-xl p-6">
        <Banner status="error" title="策略清单读取失败" description="没有策略元数据时不能构造选股工作台。" endContent={<Button label="重试" onClick={() => retryMeta()} />} />
      </div>
    );
  }

  const visibleFactors = meta.factors.filter((factor) =>
    `${factor.name} ${factor.plain} ${factor.desc}`.toLowerCase().includes(librarySearch.toLowerCase()),
  );
  const resultDate = compose?.trade_date ?? meta.trade_date;
  const resultTitle = selectedFactors.length
    ? selectedFactors.map((factor) => factor.name).join(join === "and" ? " 且 " : " 或 ")
    : "";

  return (
    <>
      <div className="strategy-toolbar">
        <div className="flex min-w-0 items-center gap-2">
          <Icon icon="viewColumns" size="xsm" color="accent" />
          <Text type="supporting" className="truncate">
            数据截至 {meta.trade_date}{compose?.total_scanned ? ` · 全市场 ${compose.total_scanned.toLocaleString("zh-CN")} 只已扫描` : ""}
          </Text>
        </div>
        <Selector
          label="数据日期"
          isLabelHidden
          options={meta.recent_dates}
          value={date ?? meta.trade_date}
          onChange={(value) => updateParams({ date: value === meta.trade_date ? null : value })}
          size="sm"
          width={132}
        />
      </div>

      <div className="strategy-presets" role="group" aria-label="常用组合">
        <Text type="supporting" className="shrink-0">常用组合</Text>
        {meta.presets.map((preset) => (
          <ToggleButton
            key={preset.key}
            label={preset.name}
            size="sm"
            isPressed={activePreset?.key === preset.key}
            onPressedChange={() => applyPreset(preset)}
          >
            <span className="flex items-center gap-1.5">
              {preset.name}
              <Badge label={preset.today_hits === null ? "—" : preset.today_hits} variant="neutral" />
            </span>
          </ToggleButton>
        ))}
      </div>

      <div className="strategy-workbench" data-testid="factor-workbench">
        <aside className="strategy-library-panel" aria-label="因子库">
          <div className="flex h-full min-h-0 flex-col">
            <div className="space-y-3 border-b border-border p-3">
              <div className="flex items-center justify-between">
                <Heading level={2}>因子</Heading>
                <Text type="supporting">点一下就出结果</Text>
              </div>
              <TextInput
                label="搜索因子"
                isLabelHidden
                value={librarySearch}
                onChange={setLibrarySearch}
                placeholder="搜索因子"
                startIcon={<Icon icon="search" size="xsm" />}
                hasClear
                width="100%"
                size="sm"
              />
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
              {meta.groups.map((group) => {
                const groupFactors = visibleFactors.filter((factor) => factor.group === group);
                if (!groupFactors.length) return null;
                return (
                  <section key={group} className="mb-3" aria-labelledby={`group-${group}`}>
                    <Heading level={3} id={`group-${group}`} className="px-2 py-1" color="secondary">{group}</Heading>
                    <div className="divide-y divide-border">
                      {groupFactors.map((factor) => (
                        <FactorRow
                          key={factor.key}
                          factor={factor}
                          selected={selectedKeys.includes(factor.key)}
                          onToggle={(checked) => toggleFactor(factor.key, checked)}
                        />
                      ))}
                    </div>
                  </section>
                );
              })}
              {!visibleFactors.length && <EmptyState title="没有匹配的因子" description="换一个关键词试试。" isCompact />}
            </div>
          </div>
        </aside>

        <section className="strategy-results" aria-labelledby="result-heading">
          <div className="strategy-condition-bar">
            <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
              {selectedFactors.length ? selectedFactors.map((factor, index) => (
                <span key={factor.key} className="flex items-center gap-2">
                  {index > 0 && <Text type="supporting">{join === "and" ? "且" : "或"}</Text>}
                  <Token
                    label={factor.name}
                    color="blue"
                    endContent={<Badge label={compose?.per_key_counts?.[factor.key] ?? factor.today_hits ?? "—"} variant="neutral" />}
                    onRemove={() => toggleFactor(factor.key, false)}
                  />
                </span>
              )) : (
                <Text type="supporting">在左侧点一个因子，结果立刻出来；点第二个可以选「且 / 或」。</Text>
              )}
            </div>
            <div className="flex shrink-0 items-center gap-2">
              {selectedKeys.length > 1 && (
                <SegmentedControl value={join} onChange={(value) => setSelection(selectedKeys, value as ComposeJoin)} label="组合关系" size="sm">
                  <SegmentedControlItem value="and" label="全部满足" />
                  <SegmentedControlItem value="or" label="任一满足" />
                </SegmentedControl>
              )}
              <Button label="清空" variant="ghost" size="sm" isDisabled={!selectedKeys.length} onClick={() => setSelection([])} />
            </div>
          </div>

          <div className="strategy-region-header gap-3">
            <div className="min-w-0">
              <span className="flex min-w-0 items-baseline gap-2">
                <Heading level={2} id="result-heading" className="truncate">
                  {selectedKeys.length ? (resultPending ? "计算中" : `${totalHits} 只`) : "选股结果"}
                </Heading>
                <Text type="supporting" className="min-w-0 truncate">
                  {selectedKeys.length ? `${resultTitle} · ${resultDate} 收盘` : `数据截至 ${resultDate}`}
                </Text>
              </span>
            </div>
            {selectedKeys.length > 0 && (
              <SegmentedControl value={sortKey} onChange={(value) => setSortKey(value as SortKey)} label="排序" size="sm">
                <SegmentedControlItem value="streak" label="连命中" />
                <SegmentedControlItem value="vol" label="量比" />
                <SegmentedControlItem value="pct" label="涨跌幅" />
              </SegmentedControl>
            )}
          </div>

          {selectedKeys.length > 0 && (
            <div className="flex items-center gap-2 border-b border-border p-3">
              <TextInput
                label="搜索结果"
                isLabelHidden
                value={resultSearch}
                onChange={setResultSearch}
                placeholder="搜索股票、代码、行业"
                startIcon={<Icon icon="search" size="xsm" />}
                hasClear
                width="100%"
                size="sm"
              />
              <Selector
                label="行业"
                isLabelHidden
                options={[{ value: "", label: `全部行业 (${allHits.length})` }, ...industries.map(([name, count]) => ({ value: name, label: `${name} (${count})` }))]}
                value={industry}
                onChange={(value) => setIndustry(value)}
                size="sm"
                width={168}
              />
            </div>
          )}

          {!selectedKeys.length ? (
            <div className="grid min-h-72 place-items-center p-5">
              <EmptyState
                icon={<Icon icon="funnel" size="md" />}
                title="还没有选因子"
                description="点顶部的常用组合，或在左侧因子库里点任意一个因子。"
                isCompact
              />
            </div>
          ) : resultError ? (
            <div className="p-3">
              <Banner status="error" title="结果不可用" description={resultError} endContent={<Button label="重试" variant="secondary" size="sm" onClick={() => retryCompose()} />} />
            </div>
          ) : resultPending ? (
            <div className="grid min-h-72 place-items-center text-sm text-ink-muted">正在读取并计算真实结果…</div>
          ) : hits.length ? (
            <>
              <div className="hidden min-h-0 flex-1 overflow-auto md:block">
                <Table
                  data={hits.slice(0, MAX_RESULTS)}
                  columns={columns}
                  idKey="code"
                  density="compact"
                  dividers="rows"
                  hasHover
                  textOverflow="truncate"
                  aria-label={`${resultTitle} 股票列表`}
                />
              </div>
              <div className="min-h-0 flex-1 divide-y divide-border overflow-y-auto md:hidden">
                {hits.slice(0, MAX_RESULTS).map((hit) => (
                  <Button key={hit.code} label={`查看 ${hit.name || hit.code}`} variant="ghost" width="100%" className="mobile-stock-row" onClick={() => openStock(hit)}>
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-medium text-ink">{hit.name || "未知"}</span>
                      <span className="mt-0.5 block font-mono text-[11px] text-ink-muted">{hit.code} · {hit.industry || "未分类"} · 连 {hit.streak} 天</span>
                    </span>
                    <span className="text-right">
                      <span className="block text-sm tabular-nums text-ink">{formatNumber(hit.close)}</span>
                      <span className={`mt-0.5 block text-xs tabular-nums ${pctClass(hit.pct_change)}`}>{formatPct(hit.pct_change)}</span>
                    </span>
                    <Icon icon="chevronRight" size="sm" color="secondary" />
                  </Button>
                ))}
              </div>
              {totalHits > MAX_RESULTS && (
                <p className="border-t border-border px-3 py-2 text-[11px] text-ink-muted">为保持交互流畅，仅显示前 {MAX_RESULTS} 只；组合计算仍使用全部 {totalHits} 只。</p>
              )}
            </>
          ) : (
            <div className="grid min-h-72 place-items-center p-5">
              <EmptyState
                icon={<Icon icon="funnel" size="md" />}
                title={resultSearch ? "没有匹配的股票" : "当前条件没有命中"}
                description={resultSearch ? "清除搜索词查看完整结果。" : "这是有效结果，不会用旧数据或部分结果补位。换个日期或改成「任一满足」再看。"}
                isCompact
              />
            </div>
          )}

          <footer className="strategy-result-footer">
            <span>{selectedKeys.length ? `${resultTitle} · ${totalHits} 只` : "未选因子"}</span>
            <span>{resultDate ? `数据截至 ${resultDate}` : "日期待确认"}</span>
          </footer>
        </section>
      </div>
    </>
  );
}
