import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "@/lib/spa-router";
import useSWR from "swr";
import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  TouchSensor,
  closestCenter,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Badge, type BadgeVariant } from "@astryxdesign/core/Badge";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { Icon } from "@astryxdesign/core/Icon";
import { Heading } from "@astryxdesign/core/Heading";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { Selector } from "@astryxdesign/core/Selector";
import { Table, pixel, proportional, type TableColumn } from "@astryxdesign/core/Table";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
import { api, type FactorHit, type FactorMeta, type FactorScanResponse, type SignalStock } from "@/lib/api";
import { useCoverage, useFactors, useStocks } from "@/lib/hooks";
import { useAppStore } from "@/lib/store";

type LibraryFilter = "all" | "verified" | "watch";
type ScanEntry = { data?: FactorScanResponse; error?: string };
type ScanMap = Record<string, ScanEntry>;

const COMBINED = "combined";
const MAX_RESULTS = 300;

const gradeMeta: Record<
  NonNullable<FactorMeta["track"]>["grade"],
  { label: string; variant: BadgeVariant }
> = {
  short_robust: { label: "已验证", variant: "success" },
  short_ok: { label: "可用", variant: "blue" },
  long_only: { label: "长线", variant: "neutral" },
  unstable: { label: "观察中", variant: "warning" },
  negative: { label: "不稳定", variant: "error" },
};

function factorStatus(factor: FactorMeta) {
  return factor.track ? gradeMeta[factor.track.grade] : { label: "待验证", variant: "neutral" as const };
}

function toNavStocks(hits: FactorHit[]): SignalStock[] {
  return hits.map((hit) => ({
    code: hit.code,
    name: hit.name,
    strategy: "factor-composition",
    category: hit.industry || "",
    close: hit.close,
    J: hit.J ?? 0,
    volume_ratio: 0,
    market_cap: (hit.cap_yi ?? 0) * 1e8,
    short_term_trend: 0,
    bull_bear_line: 0,
    reasons: [],
    similarity_score: null,
    matched_case: null,
    match_breakdown: null,
    industry: hit.industry,
  }));
}

function pctClass(value: number | null) {
  if (value === null || value === 0) return "text-ink-muted";
  return value > 0 ? "text-bull" : "text-bear";
}

function formatNumber(value: number | null, digits = 2) {
  return value === null || Number.isNaN(value) ? "—" : value.toFixed(digits);
}

function dedupeHits(hits: FactorHit[] | undefined) {
  return [...new Map((hits ?? []).map((hit) => [hit.code, hit])).values()];
}

function StrategyLibraryRow({
  factor,
  selected,
  active,
  dragDisabled,
  onInspect,
  onAdd,
}: {
  factor: FactorMeta;
  selected: boolean;
  active: boolean;
  dragDisabled?: boolean;
  onInspect: () => void;
  onAdd: () => void;
}) {
  const {
    setNodeRef,
    setActivatorNodeRef,
    attributes,
    listeners,
    isDragging,
  } = useDraggable({
    id: `library:${factor.key}`,
    disabled: dragDisabled || selected,
    data: { type: "library", key: factor.key },
  });
  const status = factorStatus(factor);

  return (
    <div
      ref={setNodeRef}
      className={`strategy-library-row grid grid-cols-[minmax(0,1fr)_40px_32px] sm:grid-cols-[32px_minmax(0,1fr)_40px_32px] ${active ? "is-active" : ""} ${isDragging ? "is-dragging" : ""}`}
    >
      <Button
        ref={setActivatorNodeRef}
        aria-label={`拖动添加 ${factor.name}`}
        label={`拖动添加 ${factor.name}`}
        variant="ghost"
        size="sm"
        isIconOnly
        className="strategy-drag-handle hidden sm:grid"
        icon={<Icon icon="arrowsUpDown" size="xsm" />}
        {...attributes}
        {...listeners}
      />
      <Button label={`查看 ${factor.name}`} variant="ghost" size="sm" className="min-w-0 w-full min-h-10 h-auto flex-1 justify-start py-1 text-left" onClick={onInspect}>
        <span className="min-w-0" title={factor.name}>
          <Text type="label" className="block truncate">{factor.name}</Text>
          <span className="mt-0.5 flex min-w-0 items-center gap-1">
            <Badge variant={status.variant} label={status.label} />
            <Text type="supporting" className="min-w-0 truncate">{factor.plain || factor.desc}</Text>
          </span>
        </span>
      </Button>
      <span className="w-10 shrink-0 text-right text-xs tabular-nums text-ink-secondary">
        {factor.today_hits === null ? "—" : factor.today_hits}
      </span>
      <Button
        label={selected ? `${factor.name} 已添加` : `添加 ${factor.name}`}
        variant="ghost"
        size="sm"
        isIconOnly
        icon={selected ? <Icon icon="check" size="xsm" /> : <span aria-hidden="true">＋</span>}
        isDisabled={selected}
        onClick={onAdd}
      />
    </div>
  );
}

function StrategyLibrary({
  factors,
  groups,
  selectedKeys,
  inspectorKey,
  filter,
  search,
  dragDisabled,
  onFilterChange,
  onSearchChange,
  onInspect,
  onAdd,
}: {
  factors: FactorMeta[];
  groups: string[];
  selectedKeys: string[];
  inspectorKey: string;
  filter: LibraryFilter;
  search: string;
  dragDisabled?: boolean;
  onFilterChange: (value: LibraryFilter) => void;
  onSearchChange: (value: string) => void;
  onInspect: (key: string) => void;
  onAdd: (key: string) => void;
}) {
  const visible = factors.filter((factor) => {
    const textMatch = `${factor.name} ${factor.plain} ${factor.desc}`.toLowerCase().includes(search.toLowerCase());
    if (!textMatch) return false;
    if (filter === "verified") return ["short_robust", "short_ok"].includes(factor.track?.grade ?? "");
    if (filter === "watch") return !["short_robust", "short_ok"].includes(factor.track?.grade ?? "");
    return true;
  });

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="space-y-3 border-b border-border p-3">
        <div className="flex items-center justify-between">
          <Heading level={2}>策略库</Heading>
          <Badge label={factors.length} variant="neutral" />
        </div>
        <TextInput
          label="搜索策略"
          isLabelHidden
          value={search}
          onChange={onSearchChange}
          placeholder="搜索策略、说明"
          startIcon={<Icon icon="search" size="xsm" />}
          hasClear
          width="100%"
          size="sm"
        />
        <SegmentedControl
          value={filter}
          onChange={(value) => onFilterChange(value as LibraryFilter)}
          label="策略可靠性筛选"
          size="sm"
          layout="fill"
        >
          <SegmentedControlItem value="all" label="全部" />
          <SegmentedControlItem value="verified" label="已验证" />
          <SegmentedControlItem value="watch" label="观察中" />
        </SegmentedControl>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
        {groups.map((group) => {
          const groupFactors = visible.filter((factor) => factor.group === group);
          if (!groupFactors.length) return null;
          return (
            <section key={group} className="mb-3" aria-labelledby={`group-${group}`}>
              <Heading level={3} id={`group-${group}`} className="px-2 py-1" color="secondary">
                {group}
              </Heading>
              <div className="divide-y divide-border">
                {groupFactors.map((factor) => (
                  <StrategyLibraryRow
                    key={factor.key}
                    factor={factor}
                    selected={selectedKeys.includes(factor.key)}
                    active={inspectorKey === factor.key}
                    dragDisabled={dragDisabled}
                    onInspect={() => onInspect(factor.key)}
                    onAdd={() => onAdd(factor.key)}
                  />
                ))}
              </div>
            </section>
          );
        })}
        {!visible.length && <EmptyState title="没有匹配的策略" description="换一个关键词或可靠性范围。" isCompact />}
      </div>
    </div>
  );
}

function SortableStrategyBlock({
  factor,
  index,
  total,
  entry,
  active,
  onInspect,
  onRemove,
  onMove,
}: {
  factor: FactorMeta;
  index: number;
  total: number;
  entry?: ScanEntry;
  active: boolean;
  onInspect: () => void;
  onRemove: () => void;
  onMove: (direction: -1 | 1) => void;
}) {
  const {
    setNodeRef,
    setActivatorNodeRef,
    attributes,
    listeners,
    isDragging,
    transform,
    transition,
  } = useSortable({ id: `selected:${factor.key}`, data: { type: "selected", key: factor.key } });
  const hitCount = entry?.data?.available ? entry.data.hits?.length ?? 0 : factor.today_hits;
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.35 : 1,
  };

  return (
    <div ref={setNodeRef} style={style} className="strategy-block-wrap">
      {index > 0 && <div className="strategy-and" aria-hidden="true"><span>AND</span></div>}
      <div className={`strategy-block ${active ? "is-active" : ""}`}>
        <Button
          ref={setActivatorNodeRef}
          aria-label={`拖动排序 ${factor.name}`}
          label={`拖动排序 ${factor.name}`}
          variant="ghost"
          size="sm"
          isIconOnly
          className="strategy-drag-handle"
          icon={<Icon icon="arrowsUpDown" size="xsm" />}
          {...attributes}
          {...listeners}
        />
        <span className="strategy-order" aria-label={`第 ${index + 1} 个条件`}>
          {String(index + 1).padStart(2, "0")}
        </span>
        <Button label={`查看 ${factor.name}`} variant="ghost" size="sm" width="100%" className="min-w-0 flex-1 justify-start text-left" onClick={onInspect} aria-pressed={active}>
          <Text type="label" className="block truncate">{factor.name}</Text>
          <Text type="supporting" className="mt-1 block truncate">
            {factor.plain || factor.desc} · {entry?.error ? "读取失败" : hitCount === null ? "待计算" : `命中 ${hitCount} 只`}
          </Text>
        </Button>
        <div className="hidden items-center gap-0.5 lg:flex">
          <Button label={`上移 ${factor.name}`} variant="ghost" size="sm" isIconOnly icon={<Icon icon="arrowUp" size="xsm" />} isDisabled={index === 0} onClick={() => onMove(-1)} />
          <Button label={`下移 ${factor.name}`} variant="ghost" size="sm" isIconOnly icon={<Icon icon="arrowDown" size="xsm" />} isDisabled={index === total - 1} onClick={() => onMove(1)} />
        </div>
        <Button label={`移除 ${factor.name}`} variant="ghost" size="sm" isIconOnly icon={<Icon icon="close" size="xsm" />} onClick={onRemove} />
      </div>
    </div>
  );
}

function StrategyCanvas({
  factors,
  selectedKeys,
  inspectorKey,
  scans,
  traceCounts,
  totalPool,
  isOver,
  setNodeRef,
  onInspect,
  onRemove,
  onMove,
  onOpenLibrary,
}: {
  factors: FactorMeta[];
  selectedKeys: string[];
  inspectorKey: string;
  scans: ScanMap;
  traceCounts: number[] | null;
  totalPool: number;
  isOver: boolean;
  setNodeRef: (node: HTMLElement | null) => void;
  onInspect: (key: string) => void;
  onRemove: (key: string) => void;
  onMove: (key: string, direction: -1 | 1) => void;
  onOpenLibrary: () => void;
}) {
  const selectedFactors = selectedKeys
    .map((key) => factors.find((factor) => factor.key === key))
    .filter((factor): factor is FactorMeta => Boolean(factor));

  return (
    <section className="strategy-canvas" aria-labelledby="composition-heading">
      <div className="strategy-region-header">
        <div>
          <span className="flex items-center gap-2">
            <Heading level={2} id="composition-heading">组合条件</Heading>
            <Badge label={selectedKeys.length} variant="blue" />
          </span>
          <Text type="supporting" className="mt-1 block">顺序用于阅读和过程追踪，最终结果为全部条件的交集。</Text>
        </div>
        <Badge label="全部满足 AND" variant="blue" />
      </div>

      <div ref={setNodeRef} className={`strategy-drop-zone ${isOver ? "is-over" : ""}`}>
        <SortableContext items={selectedKeys.map((key) => `selected:${key}`)} strategy={verticalListSortingStrategy}>
          {selectedFactors.map((factor, index) => (
            <SortableStrategyBlock
              key={factor.key}
              factor={factor}
              index={index}
              total={selectedFactors.length}
              entry={scans[factor.key]}
              active={inspectorKey === factor.key}
              onInspect={() => onInspect(factor.key)}
              onRemove={() => onRemove(factor.key)}
              onMove={(direction) => onMove(factor.key, direction)}
            />
          ))}
        </SortableContext>

        <Button type="button" variant="ghost" width="100%" className="strategy-add-zone" label="添加策略" onClick={onOpenLibrary}>
          <span aria-hidden="true">＋</span>
          <span>{selectedKeys.length ? "继续拖入策略，或点击添加" : "拖入策略，或点击选择策略"}</span>
        </Button>
      </div>

      <div className="strategy-trace" aria-live="polite">
              <Text type="label">筛选路径</Text>
        {traceCounts ? (
          <span className="tabular-nums text-accent">
            {[totalPool, ...traceCounts].map((count) => count.toLocaleString("zh-CN")).join(" → ")}
          </span>
        ) : (
          <span className="text-ink-muted">{selectedKeys.length ? "正在计算真实交集…" : `${totalPool.toLocaleString("zh-CN")} 只股票等待筛选`}</span>
        )}
      </div>
    </section>
  );
}

export function FactorWorkbench() {
  const { data: meta, isLoading: metaLoading, error: metaError, mutate: retryMeta } = useFactors();
  const { data: coverage } = useCoverage();
  const { data: stockPage, isLoading: poolLoading, error: poolError, mutate: retryPool } = useStocks(1, 200);
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const setStockNav = useAppStore((state) => state.setStockNav);
  const [libraryFilter, setLibraryFilter] = useState<LibraryFilter>("all");
  const [librarySearch, setLibrarySearch] = useState("");
  const [resultSearch, setResultSearch] = useState("");
  const [mobileLibraryOpen, setMobileLibraryOpen] = useState(false);
  const [activeDragKey, setActiveDragKey] = useState<string | null>(null);

  const factorKeys = useMemo(() => new Set(meta?.factors.map((factor) => factor.key) ?? []), [meta]);
  const selectedKeys = useMemo(() => {
    const raw = searchParams.get("strategies")?.split(",").filter(Boolean) ?? [];
    return raw.filter((key, index) => factorKeys.has(key) && raw.indexOf(key) === index);
  }, [factorKeys, searchParams]);
  const requestedInspector = searchParams.get("inspect") || COMBINED;
  const inspectorKey = requestedInspector === COMBINED || factorKeys.has(requestedInspector) ? requestedInspector : COMBINED;
  const date = searchParams.get("date") || meta?.trade_date || undefined;
  const fetchKeys = useMemo(() => {
    const keys = [...selectedKeys];
    if (inspectorKey !== COMBINED && !keys.includes(inspectorKey)) keys.push(inspectorKey);
    return keys;
  }, [inspectorKey, selectedKeys]);

  const {
    data: scans = {},
    isLoading: scansLoading,
    mutate: retryScans,
  } = useSWR<ScanMap>(
    fetchKeys.length ? ["factor-composition", date ?? "latest", ...fetchKeys] : null,
    async () => {
      const entries = await Promise.all(
        fetchKeys.map(async (key): Promise<[string, ScanEntry]> => {
          try {
            const response = await api.getFactorScan(key, date);
            return [key, { data: { ...response, hits: dedupeHits(response.hits) } }];
          } catch (error) {
            return [key, { error: error instanceof Error ? error.message : "未知错误" }];
          }
        }),
      );
      return Object.fromEntries(entries);
    },
    { revalidateOnFocus: false },
  );

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 160, tolerance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );
  const dropZone = useDroppable({ id: "strategy-canvas" });

  const setSelectedKeys = (keys: string[], inspect = inspectorKey) => {
    const next = new URLSearchParams(searchParams);
    if (keys.length) next.set("strategies", keys.join(","));
    else next.delete("strategies");
    if (inspect === COMBINED) next.delete("inspect");
    else next.set("inspect", inspect);
    setSearchParams(next, { replace: true });
  };

  const setInspector = (key: string) => {
    const next = new URLSearchParams(searchParams);
    if (key === COMBINED) next.delete("inspect");
    else next.set("inspect", key);
    setSearchParams(next, { replace: true });
    if (key !== COMBINED) setResultSearch("");
  };

  const addFactor = (key: string, index = selectedKeys.length) => {
    if (selectedKeys.includes(key)) return;
    const next = [...selectedKeys];
    next.splice(index, 0, key);
    setSelectedKeys(next, COMBINED);
    setMobileLibraryOpen(false);
  };

  const removeFactor = (key: string) => {
    const next = selectedKeys.filter((item) => item !== key);
    setSelectedKeys(next, inspectorKey === key ? COMBINED : inspectorKey);
  };

  const moveFactor = (key: string, direction: -1 | 1) => {
    const from = selectedKeys.indexOf(key);
    const to = from + direction;
    if (from < 0 || to < 0 || to >= selectedKeys.length) return;
    setSelectedKeys(arrayMove(selectedKeys, from, to));
  };

  const handleDragStart = (event: DragStartEvent) => {
    setActiveDragKey(String(event.active.data.current?.key ?? ""));
  };

  const handleDragEnd = (event: DragEndEvent) => {
    setActiveDragKey(null);
    if (!event.over) return;
    const type = event.active.data.current?.type;
    const key = String(event.active.data.current?.key ?? "");
    const overId = String(event.over.id);
    if (!key) return;

    if (type === "library") {
      const targetIndex = overId.startsWith("selected:")
        ? Math.max(0, selectedKeys.indexOf(overId.replace("selected:", "")))
        : selectedKeys.length;
      addFactor(key, targetIndex);
      return;
    }

    if (type === "selected" && overId.startsWith("selected:")) {
      const from = selectedKeys.indexOf(key);
      const to = selectedKeys.indexOf(overId.replace("selected:", ""));
      if (from >= 0 && to >= 0 && from !== to) setSelectedKeys(arrayMove(selectedKeys, from, to));
    }
  };

  const selectedEntries = selectedKeys.map((key) => scans[key]);
  const combinationPending = selectedKeys.length > 0 && (scansLoading || selectedEntries.some((entry) => !entry));
  const combinationBlocked = selectedKeys.length > 0 && !combinationPending && selectedEntries.some(
    (entry) => entry?.error || entry?.data?.available !== true,
  );
  const scanDates = new Set(
    selectedEntries.map((entry) => entry?.data?.trade_date).filter((value): value is string => Boolean(value)),
  );
  const dateMismatch = scanDates.size > 1;

  const { combinedHits, traceCounts } = useMemo(() => {
    if (!selectedKeys.length || combinationPending || combinationBlocked || dateMismatch) {
      return { combinedHits: [] as FactorHit[], traceCounts: null as number[] | null };
    }
    let current: FactorHit[] | null = null;
    const counts: number[] = [];
    for (const key of selectedKeys) {
      const hits = scans[key]?.data?.hits ?? [];
      if (current === null) current = hits;
      else {
        const codes = new Set(hits.map((hit) => hit.code));
        current = current.filter((hit) => codes.has(hit.code));
      }
      counts.push(current.length);
    }
    return { combinedHits: current ?? [], traceCounts: counts };
  }, [combinationBlocked, combinationPending, dateMismatch, scans, selectedKeys]);

  const poolHits = useMemo<FactorHit[]>(
    () => {
      const uniqueStocks = new Map((stockPage?.data ?? []).map((stock) => [stock.code, stock]));
      return [...uniqueStocks.values()].map((stock) => ({
        code: stock.code,
        name: stock.name,
        date: stock.latest_date,
        close: stock.latest_price,
        pct_change: null,
        J: null,
        RSI: null,
        industry: "",
        cap_yi: stock.market_cap,
      }));
    },
    [stockPage],
  );

  const activeFactor = meta?.factors.find((factor) => factor.key === inspectorKey) ?? null;
  const activeScan = inspectorKey !== COMBINED ? scans[inspectorKey] : undefined;
  const displayMode = activeFactor ? "individual" : selectedKeys.length ? "combined" : "pool";
  const rawResults = displayMode === "individual"
    ? activeScan?.data?.available ? activeScan.data.hits ?? [] : []
    : displayMode === "combined" ? combinedHits : poolHits;
  const visibleResults = rawResults.filter((hit) =>
    `${hit.code} ${hit.name} ${hit.industry}`.toLowerCase().includes(resultSearch.toLowerCase()),
  );
  const firstScanTotal = selectedEntries.find((entry) => entry?.data?.total_scanned)?.data?.total_scanned;
  const totalPool = firstScanTotal ?? coverage?.universe_count ?? stockPage?.total ?? 0;
  const resultTitle = displayMode === "individual"
    ? activeFactor?.name ?? "当前策略"
    : displayMode === "combined" ? "组合结果" : "每日股票池";
  const resultDate = displayMode === "individual"
    ? activeScan?.data?.trade_date
    : displayMode === "combined" ? [...scanDates][0] : meta?.trade_date;
  const resultPending = displayMode === "individual" ? scansLoading && !activeScan : displayMode === "combined" ? combinationPending : poolLoading;
  const resultError = displayMode === "individual"
    ? activeScan?.error || (activeScan?.data?.available === false ? activeScan.data.reason : undefined)
    : displayMode === "combined"
      ? combinationBlocked ? "至少一个策略结果不可用，已停止计算交集，避免展示不完整结果。" : dateMismatch ? "策略结果日期不一致，已停止计算交集。" : undefined
      : poolError ? "每日股票池读取失败。" : undefined;

  const openStock = (hit: FactorHit) => {
    const list = toNavStocks(visibleResults);
    const index = Math.max(0, visibleResults.findIndex((item) => item.code === hit.code));
    setStockNav(list, index);
    navigate(`/stock/${hit.code}`);
  };

  const columns: TableColumn<FactorHit>[] = [
    {
      key: "name",
      header: "股票",
      width: proportional(1.4, { minWidth: 150 }),
      renderCell: (hit) => (
      <Button label={`查看 ${hit.name || hit.code}`} variant="ghost" size="sm" className="justify-start text-left" onClick={() => openStock(hit)}>
        <span className="block text-xs font-medium text-ink">{hit.name || "未知"}</span>
        <span className="mt-0.5 block font-mono text-[11px] text-ink-muted">{hit.code}</span>
      </Button>
      ),
    },
    { key: "close", header: "最新价", width: pixel(84), align: "end", renderCell: (hit) => <span className="tabular-nums">{formatNumber(hit.close)}</span> },
    {
      key: "pct_change",
      header: "涨跌幅",
      width: pixel(86),
      align: "end",
      renderCell: (hit) => <span className={`tabular-nums ${pctClass(hit.pct_change)}`}>{hit.pct_change === null ? "—" : `${hit.pct_change > 0 ? "+" : ""}${hit.pct_change.toFixed(2)}%`}</span>,
    },
    { key: "J", header: "J 值", width: pixel(72), align: "end", renderCell: (hit) => <span className="tabular-nums">{formatNumber(hit.J)}</span> },
    { key: "industry", header: "行业", width: proportional(1, { minWidth: 110 }), renderCell: (hit) => hit.industry || "—" },
    {
      key: "sector",
      header: "板块热度",
      width: pixel(120),
      align: "end",
      renderCell: (hit) => {
        const sector = hit.sector;
        if (!sector) return "—";
        const delta = sector.delta3 !== 0
          ? (sector.delta3 > 0 ? ` +${sector.delta3.toFixed(0)}` : ` ${sector.delta3.toFixed(0)}`)
          : "";
        return (
          <span
            className="tabular-nums text-ink-secondary"
            title={`板块热度 ${sector.score}（第 ${sector.rank}/${sector.total} 名）`}
          >
            {sector.score.toFixed(0)}
            <span className="text-ink-muted"> · {sector.rank}/{sector.total}</span>
            {delta && (
              <span className={sector.delta3 > 0 ? "text-bull" : "text-bear"}>{delta}</span>
            )}
          </span>
        );
      },
    },
    {
      key: "action",
      header: "",
      width: pixel(88),
      align: "end",
      renderCell: (hit) => <Button label={`查看 ${hit.name || hit.code} K线`} variant="ghost" size="sm" icon={<Icon icon="chevronRight" size="xsm" />} onClick={() => openStock(hit)}>K 线</Button>,
    },
  ];

  if (metaLoading) {
    return <div className="grid min-h-[620px] place-items-center text-sm text-ink-muted">正在读取真实策略与每日股票池…</div>;
  }
  if (metaError || !meta) {
    return (
      <div className="mx-auto max-w-xl p-6">
        <Banner status="error" title="策略清单读取失败" description="没有策略元数据时不能构造筛选工作台。" endContent={<Button label="重试" onClick={() => retryMeta()} />} />
      </div>
    );
  }

  const activeDragFactor = meta.factors.find((factor) => factor.key === activeDragKey);

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragStart={handleDragStart}
      onDragCancel={() => setActiveDragKey(null)}
      onDragEnd={handleDragEnd}
    >
      <div className="strategy-toolbar">
        <div className="flex min-w-0 items-center gap-2">
          <Icon icon="viewColumns" size="xsm" color="accent" />
              <Text type="supporting" className="truncate">
                {meta.trade_date} · {totalPool ? `${totalPool.toLocaleString("zh-CN")} 只可扫描` : "正在统计股票池"}
              </Text>
        </div>
        <div className="flex items-center gap-2">
          <Selector
            label="数据日期"
            isLabelHidden
            options={meta.recent_dates}
            value={date ?? meta.trade_date}
            onChange={(value) => {
              const next = new URLSearchParams(searchParams);
              if (value === meta.trade_date) next.delete("date");
              else next.set("date", value);
              setSearchParams(next, { replace: true });
            }}
            size="sm"
            width={132}
          />
          <Button
            label="清空组合"
            variant="ghost"
            size="sm"
            isDisabled={!selectedKeys.length}
            onClick={() => setSelectedKeys([], COMBINED)}
          />
        </div>
      </div>

      <div className="strategy-workbench" data-testid="factor-workbench">
        <aside className="strategy-library-panel hidden sm:block" aria-label="策略库">
          <StrategyLibrary
            factors={meta.factors}
            groups={meta.groups}
            selectedKeys={selectedKeys}
            inspectorKey={inspectorKey}
            filter={libraryFilter}
            search={librarySearch}
            onFilterChange={setLibraryFilter}
            onSearchChange={setLibrarySearch}
            onInspect={setInspector}
            onAdd={addFactor}
          />
        </aside>

        <StrategyCanvas
          factors={meta.factors}
          selectedKeys={selectedKeys}
          inspectorKey={inspectorKey}
          scans={scans}
          traceCounts={traceCounts}
          totalPool={totalPool}
          isOver={dropZone.isOver}
          setNodeRef={dropZone.setNodeRef}
          onInspect={setInspector}
          onRemove={removeFactor}
          onMove={moveFactor}
          onOpenLibrary={() => setMobileLibraryOpen(true)}
        />

        <section className="strategy-results" aria-labelledby="result-heading">
          <div className="strategy-region-header gap-3">
            <div className="min-w-0">
              <span className="flex min-w-0 items-center gap-2">
                <Heading level={2} id="result-heading" className="truncate">{resultTitle}</Heading>
                <Badge label={resultPending ? "计算中" : visibleResults.length} variant={resultError ? "error" : "blue"} />
              </span>
              <Text type="supporting" className="mt-1 block truncate">
                {displayMode === "pool" ? `显示前 ${poolHits.length} / ${totalPool.toLocaleString("zh-CN")}` : resultDate ? `数据截至 ${resultDate}` : "等待策略数据"}
              </Text>
            </div>
            {displayMode === "individual" && (
              <Button label="返回组合结果" variant="secondary" size="sm" icon={<Icon icon="viewColumns" size="xsm" />} onClick={() => setInspector(COMBINED)} />
            )}
          </div>

          <div className="border-b border-border p-3">
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
          </div>

          {resultError ? (
            <div className="p-3">
              <Banner
                status="error"
                title="结果不可用"
                description={resultError}
                endContent={<Button label="重试" variant="secondary" size="sm" onClick={() => displayMode === "pool" ? retryPool() : retryScans()} />}
              />
            </div>
          ) : resultPending ? (
            <div className="grid min-h-72 place-items-center text-sm text-ink-muted">正在读取并计算真实结果…</div>
          ) : visibleResults.length ? (
            <>
              <div className="hidden min-h-0 flex-1 overflow-auto md:block">
                <Table
                  data={visibleResults.slice(0, MAX_RESULTS)}
                  columns={columns}
                  idKey="code"
                  density="compact"
                  dividers="rows"
                  hasHover
                  textOverflow="truncate"
                  aria-label={`${resultTitle}股票列表`}
                />
              </div>
              <div className="min-h-0 flex-1 divide-y divide-border overflow-y-auto md:hidden">
                {visibleResults.slice(0, MAX_RESULTS).map((hit) => (
                  <Button key={hit.code} label={`查看 ${hit.name || hit.code}`} variant="ghost" width="100%" className="mobile-stock-row" onClick={() => openStock(hit)}>
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-medium text-ink">{hit.name || "未知"}</span>
                      <span className="mt-0.5 block font-mono text-[11px] text-ink-muted">
                        {hit.code} · {hit.industry || "未分类"}
                        {hit.sector ? ` · 板块 ${hit.sector.score.toFixed(0)}` : ""}
                      </span>
                    </span>
                    <span className="text-right">
                      <span className="block text-sm tabular-nums text-ink">{formatNumber(hit.close)}</span>
                      <span className={`mt-0.5 block text-xs tabular-nums ${pctClass(hit.pct_change)}`}>
                        {hit.pct_change === null ? `J ${formatNumber(hit.J)}` : `${hit.pct_change > 0 ? "+" : ""}${hit.pct_change.toFixed(2)}%`}
                      </span>
                    </span>
                    <Icon icon="chevronRight" size="sm" color="secondary" />
                  </Button>
                ))}
              </div>
              {rawResults.length > MAX_RESULTS && (
                <p className="border-t border-border px-3 py-2 text-[11px] text-ink-muted">为保持交互流畅，仅显示前 {MAX_RESULTS} 只；交集计算仍使用全部 {rawResults.length} 只。</p>
              )}
            </>
          ) : (
            <div className="grid min-h-72 place-items-center p-5">
              <EmptyState
                icon={<Icon icon="funnel" size="md" />}
                title={resultSearch ? "没有匹配的股票" : displayMode === "pool" ? "股票池为空" : "当前条件没有命中"}
                description={resultSearch ? "清除搜索词查看完整结果。" : displayMode === "combined" ? "这是有效结果，不会用旧数据或部分结果补位。" : "切换日期或点击其他策略继续研究。"}
                actions={displayMode === "pool" ? <Button label="添加第一个策略" variant="primary" icon={<span aria-hidden="true">＋</span>} onClick={() => setMobileLibraryOpen(true)} /> : undefined}
                isCompact
              />
            </div>
          )}

          <footer className="strategy-result-footer">
            <span>{displayMode === "combined" ? "交集结果" : resultTitle} · {rawResults.length} 只</span>
            <span>{resultDate ? `数据截至 ${resultDate}` : "日期待确认"}</span>
          </footer>
        </section>
      </div>

      <div className="strategy-mobile-action sm:hidden">
        <Button label="添加策略" variant="primary" icon={<span aria-hidden="true">＋</span>} width="100%" onClick={() => setMobileLibraryOpen(true)} />
      </div>

      <Dialog
        isOpen={mobileLibraryOpen}
        onOpenChange={setMobileLibraryOpen}
        width="100%"
        maxHeight="82dvh"
        position={{ bottom: 0, left: 0, right: 0 }}
        padding={0}
        aria-label="添加策略"
      >
        <div className="flex max-h-[82dvh] min-h-[60dvh] flex-col">
          <DialogHeader className="px-3" title="添加策略" subtitle="点击 + 添加；点击策略名称可先查看独立命中结果。" onOpenChange={setMobileLibraryOpen} hasDivider />
          <div className="min-h-0 flex-1">
            <StrategyLibrary
              factors={meta.factors}
              groups={meta.groups}
              selectedKeys={selectedKeys}
              inspectorKey={inspectorKey}
              filter={libraryFilter}
              search={librarySearch}
              dragDisabled
              onFilterChange={setLibraryFilter}
              onSearchChange={setLibrarySearch}
              onInspect={(key) => {
                setInspector(key);
                setMobileLibraryOpen(false);
              }}
              onAdd={addFactor}
            />
          </div>
        </div>
      </Dialog>

      <DragOverlay dropAnimation={{ duration: 140, easing: "ease-out" }}>
        {activeDragFactor ? (
          <div className="strategy-drag-overlay">
            <Icon icon="arrowsUpDown" size="sm" />
            <span>{activeDragFactor.name}</span>
            <Badge label={activeDragFactor.today_hits === null ? "待计算" : `${activeDragFactor.today_hits} 只`} variant="blue" />
          </div>
        ) : null}
      </DragOverlay>
    </DndContext>
  );
}
