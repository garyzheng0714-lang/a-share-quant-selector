import { useCallback, useMemo, useState, type KeyboardEvent, type ReactNode } from "react";
import { useNavigate } from "@/lib/spa-router";
import { Button } from "@astryxdesign/core/Button";
import { Card } from "@astryxdesign/core/Card";
import { Collapsible } from "@astryxdesign/core/Collapsible";
import { Heading } from "@astryxdesign/core/Heading";
import { Icon } from "@astryxdesign/core/Icon";
import { List, ListItem } from "@astryxdesign/core/List";
import { ProgressBar } from "@astryxdesign/core/ProgressBar";
import { StatusDot } from "@astryxdesign/core/StatusDot";
import { Table, pixel, proportional, type TableColumn, type TablePlugin } from "@astryxdesign/core/Table";
import { Text } from "@astryxdesign/core/Text";
import { LoadError, Skeleton } from "@/components/ui";
import { useEvolutionStatus, useLatestDecision } from "@/lib/hooks";
import { useAppStore } from "@/lib/store";
import type {
  DecisionAction,
  DecisionCandidate,
  DecisionModel,
  EvolutionStatus,
  SignalStock,
} from "@/lib/api";

type CandidateRow = DecisionCandidate & Record<string, unknown>;

const ACTION: Record<
  DecisionAction,
  { label: string; tone: "success" | "accent" | "error" | "neutral" }
> = {
  buy: { label: "通过复核", tone: "success" },
  observe: { label: "研究候选", tone: "accent" },
  avoid: { label: "未通过", tone: "error" },
  none: { label: "无信号", tone: "neutral" },
};

function modelFor(models: DecisionModel[], key: string) {
  return models.find((model) => model.model_key === key);
}

function layerState(mode?: "off" | "shadow" | "active") {
  if (mode === "active") return "已启用";
  if (mode === "shadow") return "影子验证";
  return "未启用";
}

function layerTone(mode?: "off" | "shadow" | "active"): "success" | "accent" | "neutral" {
  if (mode === "active") return "success";
  if (mode === "shadow") return "accent";
  return "neutral";
}

function modelState(model: DecisionModel | undefined, mode?: "off" | "shadow" | "active") {
  if (mode) return layerState(mode);
  if (model?.mode === "active" || model?.status === "active") return "已启用";
  if (model?.mode === "shadow" || model?.status === "shadow") return "影子验证";
  return "未验证，当前不启用";
}

function toNav(list: DecisionCandidate[]): SignalStock[] {
  return list.map((item) => ({
    code: item.code,
    name: item.name,
    strategy: "hierarchical_decision",
    category: item.industry || "",
    close: item.baseline.close ?? 0,
    J: item.baseline.J ?? 0,
    volume_ratio: 0,
    market_cap: (item.baseline.cap_yi ?? 0) * 1e8,
    short_term_trend: 0,
    bull_bear_line: 0,
    reasons: item.baseline.signal_labels ?? [],
    similarity_score: null,
    matched_case: null,
    match_breakdown: null,
    industry: item.industry,
  }));
}

function weeklySummary(item: DecisionCandidate) {
  const weekly = item.baseline.weekly;
  const weeklyLines = (["MA5", "MA10", "MA20", "MA60"] as const).map((line) => weekly?.directions?.[line]);
  const hasWeeklyDirections = weeklyLines.every((rising) => rising != null);
  return {
    label: hasWeeklyDirections
      ? `${weekly?.rising_count ?? 0}/4 向上 · ${weekly?.aligned ? "多头排列" : "未多头"}`
      : "历史数据不足",
    hint: weekly?.gate_mode === "shadow" ? "影子门槛，不影响当前结果" : "四周线均线证据",
  };
}

function CandidateStatus({ action }: { action: DecisionAction }) {
  const meta = ACTION[action];
  return (
    <span className="inline-flex items-center gap-2 whitespace-nowrap text-xs font-medium text-ink">
      <StatusDot variant={meta.tone} label={meta.label} />
      {meta.label}
    </span>
  );
}

function MobileCandidateRow({
  item,
  list,
}: {
  item: DecisionCandidate;
  list: DecisionCandidate[];
}) {
  const navigate = useNavigate();
  const setStockNav = useAppStore((state) => state.setStockNav);
  const weekly = weeklySummary(item);
  const close = item.baseline.close?.toFixed(2) ?? "—";
  const j = item.baseline.J?.toFixed(2) ?? "—";
  const sector = item.sector?.score != null ? Math.round(item.sector.score).toString() : "—";
  const signal = item.baseline.signal_labels?.[0] ?? "B1";

  return (
    <ListItem
      label={
        <span className="flex min-w-0 items-baseline gap-2">
          <span className="truncate text-sm font-semibold text-ink">{item.name}</span>
          <span className="shrink-0 font-mono text-[11px] text-ink-muted">{item.code}</span>
        </span>
      }
      description={
        <div className="mt-1 grid grid-cols-3 gap-x-3 gap-y-2 text-xs leading-5">
          <span>
            <span className="block text-[10px] text-ink-muted">收盘</span>
            <span className="num mt-0.5 block text-ink">{close}</span>
          </span>
          <span>
            <span className="block text-[10px] text-ink-muted">J</span>
            <span className="num mt-0.5 block text-ink">{j}</span>
          </span>
          <span>
            <span className="block text-[10px] text-ink-muted">板块</span>
            <span className="num mt-0.5 block text-ink">{sector}</span>
          </span>
          <span className="col-span-3 flex min-w-0 items-center gap-2 text-ink-muted">
            <span className="truncate">{item.industry || "未分类"}</span>
            <span className="shrink-0 text-ink-secondary">{signal}</span>
            <span className="ml-auto shrink-0 text-ink-secondary">{weekly.label}</span>
          </span>
        </div>
      }
      endContent={<CandidateStatus action={item.action} />}
      onClick={() => {
        setStockNav(toNav(list), list.findIndex((stock) => stock.code === item.code));
        navigate(`/stock/${item.code}`);
      }}
    />
  );
}

function EvolutionSummary({ evolution }: { evolution: EvolutionStatus }) {
  const coveragePercent = Math.max(0, Math.min(100, Math.round(evolution.coverage_ratio * 100)));
  const promoted = evolution.promotion_status === "promoted";
  const status = promoted
    ? "挑战模型已通过发布门槛"
    : evolution.coverage_ratio < 0.6
      ? "数据覆盖不足，保持既有策略"
      : evolution.reason_codes.includes("reference_history_insufficient")
        ? "时点快照仍在积累"
        : "挑战模型尚未通过验证";

  return (
    <div className="border-t border-border px-1 py-4">
      <ProgressBar
        label="验证进度"
        value={coveragePercent}
        max={100}
        hasValueLabel
        variant="accent"
      />
      <Text type="supporting" className="mt-3 block leading-5">
        {status}
      </Text>
      <Text type="supporting" className="mt-1 block leading-5">
        覆盖 {evolution.covered_count}/{evolution.universe_count} 只，可训练样本 {evolution.dataset_rows} 条。
      </Text>
    </div>
  );
}

function EvidenceRow({
  icon,
  label,
  value,
  hint,
  tone = "neutral",
}: {
  icon: ReactNode;
  label: string;
  value: string;
  hint: string;
  tone?: "success" | "accent" | "error" | "neutral";
}) {
  return (
    <ListItem
      label={
        <span className="flex w-full min-w-0 items-baseline justify-between gap-3">
          <span className="text-xs font-medium text-ink-secondary">{label}</span>
          <span className="inline-flex shrink-0 items-center gap-1.5 text-xs font-medium text-ink">
            <StatusDot variant={tone} label={value} />
            {value}
          </span>
        </span>
      }
      description={<span className="block text-[11px] leading-5 text-ink-muted">{hint}</span>}
      startContent={<span className="text-ink-muted">{icon}</span>}
    />
  );
}

export function QuantPickCard() {
  const [showAll, setShowAll] = useState(false);
  const navigate = useNavigate();
  const setStockNav = useAppStore((state) => state.setStockNav);
  const { data, isLoading, error, mutate } = useLatestDecision();
  const { data: evolutionResponse } = useEvolutionStatus();

  const candidates = useMemo(() => data?.candidates ?? [], [data?.candidates]);
  const visible = showAll ? candidates : candidates.slice(0, 8);
  const rows = useMemo(() => visible as CandidateRow[], [visible]);

  const openStock = useCallback(
    (item: DecisionCandidate) => {
      setStockNav(toNav(candidates), candidates.findIndex((stock) => stock.code === item.code));
      navigate(`/stock/${item.code}`);
    },
    [candidates, navigate, setStockNav],
  );

  const columns: TableColumn<CandidateRow>[] = useMemo(
    () => [
      {
        key: "name",
        header: "代码 / 名称",
        width: proportional(1.5, { minWidth: 168 }),
        renderCell: (item) => {
          const signal = item.baseline.signal_labels?.[0] ?? "B1";
          return (
            <div className="min-w-0 py-1">
              <div className="flex min-w-0 items-baseline gap-2">
                <span className="truncate text-sm font-semibold text-ink">{item.name}</span>
                <span className="shrink-0 font-mono text-[11px] text-ink-muted">{item.code}</span>
              </div>
              <div className="mt-1 flex min-w-0 items-center gap-2 text-[11px] leading-4 text-ink-muted">
                <span className="truncate">{item.industry || "未分类"}</span>
                <span className="shrink-0 text-ink-secondary">{signal}</span>
              </div>
            </div>
          );
        },
      },
      {
        key: "close",
        header: "收盘",
        width: pixel(72),
        align: "end",
        renderCell: (item) => (
          <span className="num text-sm font-medium text-ink">
            {item.baseline.close?.toFixed(2) ?? "—"}
          </span>
        ),
      },
      {
        key: "J",
        header: "J",
        width: pixel(68),
        align: "end",
        renderCell: (item) => (
          <span className="num text-sm text-ink-secondary">
            {item.baseline.J?.toFixed(2) ?? "—"}
          </span>
        ),
      },
      {
        key: "sector",
        header: "板块",
        width: pixel(72),
        align: "end",
        renderCell: (item) => (
          <span className="num text-sm text-ink-secondary">
            {item.sector?.score != null ? Math.round(item.sector.score) : "—"}
          </span>
        ),
      },
      {
        key: "weekly",
        header: "周线证据",
        width: proportional(1.2, { minWidth: 160 }),
        renderCell: (item) => {
          const weekly = weeklySummary(item);
          return (
            <div className="min-w-0 py-1">
              <div className="text-xs leading-5 text-ink-secondary">{weekly.label}</div>
              <div className="mt-0.5 truncate text-[11px] leading-4 text-ink-muted">{weekly.hint}</div>
            </div>
          );
        },
      },
      {
        key: "action",
        header: "状态",
        width: pixel(108),
        renderCell: (item) => <CandidateStatus action={item.action} />,
      },
      {
        key: "go",
        header: "",
        width: pixel(36),
        align: "end",
        renderCell: () => <Icon icon="externalLink" size="xsm" color="secondary" />,
      },
    ],
    [],
  );

  const rowClickPlugin = useMemo<Record<string, TablePlugin<CandidateRow>>>(
    () => ({
      rowClick: {
        transformBodyRow: (props, item) => ({
          ...props,
          htmlProps: {
            ...props.htmlProps,
            role: "link",
            tabIndex: 0,
            onClick: () => openStock(item),
            onKeyDown: (event: KeyboardEvent) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                openStock(item);
              }
            },
            style: {
              ...props.htmlProps?.style,
              cursor: "pointer",
            },
          },
        }),
      },
    }),
    [openStock],
  );

  if (isLoading) {
    return (
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px] xl:grid-cols-[minmax(0,1fr)_360px]">
        <Skeleton className="h-[520px] w-full rounded-[10px]" />
        <Skeleton className="h-[420px] w-full rounded-[10px]" />
      </div>
    );
  }

  if (error) {
    return (
      <Card className="p-5" aria-label="B1 决策加载失败">
        <LoadError label="B1 决策加载失败" onRetry={() => mutate()} />
      </Card>
    );
  }

  if (!data?.available) {
    const stale = data?.reason === "stale_market_data";
    return (
      <Card className="p-5" aria-labelledby="decision-unavailable-title">
        <div className="flex items-start gap-3">
          <Icon icon="warning" size="sm" color="accent" />
          <div className="min-w-0">
            <Heading level={2} id="decision-unavailable-title">
              {stale ? "行情未更新，暂无可回放决策" : "当前没有可用决策"}
            </Heading>
            <Text type="supporting" className="mt-1 block leading-5">
              {stale
                ? `当前数据截至 ${data?.freshness?.local_date ?? "未知"}，请在行情更新后重试。`
                : data?.reason ?? "数据准备中"}
            </Text>
          </div>
        </div>
      </Card>
    );
  }

  const buys = candidates.filter((item) => item.action === "buy");
  const models = data.models ?? [];
  const hasApproved = buys.length > 0;
  const decisionTitle = hasApproved
    ? `通过复核 ${buys.length} 只`
    : candidates.length
      ? `研究候选 ${candidates.length} 只`
      : "当前无 B1 信号";
  const decisionNote = hasApproved
    ? "候选已通过当前启用的策略门槛，仍需结合自身风险承受能力判断。"
    : candidates.length
      ? "B1 信号已记录，未验证模型和周线影子门槛不会被包装成买入结论。"
      : "当前规则没有产生候选，系统不会用模型补造股票。";
  const weeklyMode = data.market?.layer_modes?.weekly_four_ma;
  const marketMode = data.market?.layer_modes?.market;
  const sectorMode = data.market?.layer_modes?.sector;
  const localDate = data.freshness?.local_date ?? data.trade_date ?? "未知";
  const expectedDate = data.freshness?.expected_date;

  return (
    <section
      className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_320px] xl:grid-cols-[minmax(0,1fr)_360px]"
      data-testid="hierarchical-decision"
    >
      <Card className="overflow-hidden">
        {data.is_stale && (
          <div
            className="border-b border-accent/25 bg-accent-dim px-4 py-3 text-xs leading-5 text-ink-secondary sm:px-5"
            role="status"
          >
            正在回放最近一次有效决策。行情截至{" "}
            <span className="num text-ink">{localDate}</span>
            {expectedDate ? (
              <>
                ，当前应更新到 <span className="num text-ink">{expectedDate}</span>
              </>
            ) : null}
            。
          </div>
        )}

        <div className="px-4 py-5 sm:px-5 sm:py-6">
          <div className="flex items-start gap-3">
            <div
              className={`mt-0.5 grid h-10 w-10 shrink-0 place-items-center rounded-lg ${
                hasApproved ? "bg-bull-dim text-bull" : "bg-accent-dim text-accent"
              }`}
            >
              {hasApproved ? <Icon icon="success" size="sm" /> : <Icon icon="stop" size="sm" />}
            </div>
            <div className="min-w-0">
              <p className="section-kicker">策略决策</p>
              <Heading level={2} className="mt-1.5 tracking-[-0.04em]">
                {decisionTitle}
              </Heading>
              <Text type="body" className="mt-2 block max-w-3xl leading-6 text-ink-secondary">
                {decisionNote}
              </Text>
              <Text type="supporting" className="mt-3 block">
                面向 <span className="num text-ink-secondary">{data.market?.decision_for_date ?? "下一交易日"}</span>
                ，基于 <span className="num text-ink-secondary">{data.trade_date}</span> 收盘数据
              </Text>
            </div>
          </div>
        </div>

        <div className="flex items-end justify-between border-y border-border bg-inset px-4 py-3 sm:px-5">
          <div>
            <Heading level={3} className="text-sm">候选比较</Heading>
            <Text type="supporting" className="mt-1 block">
              点击任意一行打开个股 K 线并保留候选顺序
            </Text>
          </div>
          <span className="num text-xs text-ink-muted">{candidates.length} 只</span>
        </div>

        {candidates.length ? (
          <>
            <div className="hidden md:block">
              <Table
                data={rows}
                columns={columns}
                idKey="code"
                density="balanced"
                dividers="rows"
                hasHover
                verticalAlign="middle"
                textOverflow="wrap"
                plugins={rowClickPlugin}
                aria-label="研究候选列表"
              />
            </div>
            <div className="md:hidden">
              <List density="spacious" hasDividers aria-label="研究候选列表">
                {visible.map((item) => (
                  <MobileCandidateRow key={item.code} item={item} list={candidates} />
                ))}
              </List>
            </div>
            {candidates.length > 8 && (
              <div className="border-t border-border p-2">
                <Button
                  label={showAll ? "收起多余候选" : `查看全部 ${candidates.length} 只`}
                  variant="ghost"
                  width="100%"
                  onClick={() => setShowAll((value) => !value)}
                  aria-expanded={showAll}
                  endContent={<Icon icon="chevronDown" size="xsm" />}
                />
              </div>
            )}
          </>
        ) : (
          <div className="px-5 py-8">
            <Text type="body">当前规则没有产生 B1 候选。</Text>
          </div>
        )}
      </Card>

      <Card className="self-start lg:sticky lg:top-20" aria-labelledby="decision-evidence-title">
        <div className="border-b border-border px-4 py-4 sm:px-5">
          <Heading level={2} id="decision-evidence-title">决策依据</Heading>
          <Text type="supporting" className="mt-1 block leading-5">
            只展示真实的启用状态与可追溯证据。
          </Text>
        </div>

        <List density="balanced" hasDividers>
          <EvidenceRow
            icon={<Icon icon="clock" size="sm" />}
            label="数据时点"
            value={data.is_stale ? "数据过期" : "数据就绪"}
            tone={data.is_stale ? "error" : "success"}
            hint={
              data.is_stale && expectedDate
                ? `${localDate} 收盘；当前应更新到 ${expectedDate}。`
                : `${localDate} 收盘数据。`
            }
          />
          <EvidenceRow
            icon={<Icon icon="viewColumns" size="sm" />}
            label="周线四均线"
            value={layerState(weeklyMode)}
            tone={layerTone(weeklyMode)}
            hint={weeklyMode === "shadow" ? "只记录影子结果，不影响当前决策。" : "按当前完整策略记录。"}
          />
          <EvidenceRow
            icon={<Icon icon="viewColumns" size="sm" />}
            label="市场模型"
            value={modelState(modelFor(models, "market"), marketMode)}
            tone={layerTone(marketMode)}
            hint="未通过样本外验证时，不参与生产策略。"
          />
          <EvidenceRow
            icon={<Icon icon="viewColumns" size="sm" />}
            label="板块模型"
            value={modelState(modelFor(models, "sector"), sectorMode)}
            tone={layerTone(sectorMode)}
            hint="板块热度是研究特征，不单独构成买入理由。"
          />
        </List>

        <div className="px-4 sm:px-5">
          {evolutionResponse?.available && evolutionResponse.data ? (
            <EvolutionSummary evolution={evolutionResponse.data} />
          ) : (
            <div className="border-t border-border py-4">
              <Text type="supporting">当前没有可用的模型验证记录。</Text>
            </div>
          )}

          <Collapsible className="border-t border-border py-3 text-xs text-ink-muted" trigger="版本与可追溯记录">
            <dl className="mt-2 grid gap-2 rounded-md bg-inset p-3 text-[11px] leading-5">
              <div className="grid grid-cols-[72px_minmax(0,1fr)] gap-2">
                <dt>策略版本</dt>
                <dd className="break-all text-ink-secondary">{data.strategy_version ?? "未记录"}</dd>
              </div>
              <div className="grid grid-cols-[72px_minmax(0,1fr)] gap-2">
                <dt>模型版本</dt>
                <dd className="break-all text-ink-secondary">{data.model_version ?? "未记录"}</dd>
              </div>
              <div className="grid grid-cols-[72px_minmax(0,1fr)] gap-2">
                <dt>决策 run</dt>
                <dd className="break-all text-ink-secondary">{data.run_id ?? "未记录"}</dd>
              </div>
              <div className="grid grid-cols-[72px_minmax(0,1fr)] gap-2">
                <dt>来源记录</dt>
                <dd className="text-ink-secondary">{data.source_refs?.length ?? 0} 条</dd>
              </div>
            </dl>
          </Collapsible>

          <p className="border-t border-border py-4 text-[11px] leading-5 text-ink-muted">
            研究工具，不构成投资建议。任何决策都需要结合自身风险承受能力独立判断。
          </p>
        </div>
      </Card>
    </section>
  );
}
