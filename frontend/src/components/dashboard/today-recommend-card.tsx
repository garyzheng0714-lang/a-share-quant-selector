import { useMemo, useState } from "react";
import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { Card } from "@astryxdesign/core/Card";
import { Collapsible } from "@astryxdesign/core/Collapsible";
import { Heading } from "@astryxdesign/core/Heading";
import { Icon } from "@astryxdesign/core/Icon";
import { List, ListItem } from "@astryxdesign/core/List";
import { MetadataList, MetadataListItem } from "@astryxdesign/core/MetadataList";
import { StatusDot } from "@astryxdesign/core/StatusDot";
import { Text } from "@astryxdesign/core/Text";
import { LoadError, Skeleton } from "@/components/ui";
import { useNavigate } from "@/lib/spa-router";
import { useRecommend } from "@/lib/hooks";
import { useAppStore } from "@/lib/store";
import type { RecommendResponse, RecommendStock, SignalStock } from "@/lib/api";

function signed(value: number | null | undefined, digits = 0) {
  if (value == null) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}`;
}

function price(value: number | null | undefined) {
  return value == null ? "—" : value.toFixed(2);
}

function toNav(list: RecommendStock[]): SignalStock[] {
  return list.map((item) => ({
    code: item.code,
    name: item.name,
    strategy: "云阶",
    category: item.industry,
    close: item.close ?? 0,
    J: item.J ?? 0,
    volume_ratio: 0,
    market_cap: (item.cap_yi ?? 0) * 1e8,
    short_term_trend: 0,
    bull_bear_line: 0,
    reasons: item.evidence ?? [],
    similarity_score: null,
    matched_case: null,
    match_breakdown: null,
    industry: item.industry,
  }));
}

function aiState(data: RecommendResponse) {
  if (data.ai?.available) {
    return {
      title: "AI 分析已生成",
      description: data.ai.market_note || "已按云阶结构、K 线和行业强度完成解释。",
      tone: "success" as const,
    };
  }
  const reasons = data.ai?.reason_codes ?? [];
  if (reasons.includes("llm_unconfigured")) {
    return {
      title: "AI 尚未配置",
      description: "规则结论已经生成，但服务器没有大模型密钥，因此不会伪造 AI 评论。",
      tone: "warning" as const,
    };
  }
  if (reasons.includes("no_cloud_stair_signals")) {
    return {
      title: "今日无需调用 AI",
      description: "云阶没有选出股票，系统不会让 AI 硬凑候选。",
      tone: "neutral" as const,
    };
  }
  if (reasons.some((reason) => reason.startsWith("llm_"))) {
    return {
      title: "AI 分析失败",
      description: "云阶选股结论不受影响，但本次 AI 解释没有成功落账。",
      tone: "error" as const,
    };
  }
  return {
    title: "AI 分析正在等待当前决策",
    description: "当 worker 把当前快照与云阶信号落账后，AI 才会基于同一批数据生成解释。",
    tone: "neutral" as const,
  };
}

function RankMark({ rank }: { rank: number }) {
  return (
    <span
      aria-hidden="true"
      className={`grid h-8 w-8 shrink-0 place-items-center rounded-full text-xs font-semibold tabular-nums ${
        rank === 1 ? "bg-accent-dim text-accent" : "bg-inset text-ink-muted"
      }`}
    >
      {rank}
    </span>
  );
}

function CandidateRow({
  item,
  selected,
  onSelect,
}: {
  item: RecommendStock;
  selected: boolean;
  onSelect: () => void;
}) {
  const sector = item.sector;
  return (
    <ListItem
      isSelected={selected}
      onClick={onSelect}
      startContent={<RankMark rank={item.rank ?? 0} />}
      label={
        <span className="flex min-w-0 items-baseline gap-2">
          <span className="truncate text-sm font-semibold text-ink">{item.name || item.code}</span>
          <span className="shrink-0 font-mono text-[11px] text-ink-muted">{item.code}</span>
        </span>
      }
      description={
        <span className="mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs leading-5 text-ink-muted">
          <span className={item.industry_available === false ? "text-bull" : "text-ink-secondary"}>
            {item.industry}
          </span>
          <span>
            {sector?.rank != null ? `行业 ${sector.rank}/${sector.total}` : "行业排名待补"}
          </span>
          <span>{sector?.score != null ? `热度 ${Math.round(sector.score)}` : "热度待补"}</span>
        </span>
      }
      endContent={
        <span className="text-right">
          <span className="num block text-sm font-semibold text-ink">{price(item.close)}</span>
          <span className="mt-1 block whitespace-nowrap text-[11px] font-medium text-bull">买点确认</span>
        </span>
      }
    />
  );
}

function DecisionDetail({ item, data }: { item: RecommendStock; data: RecommendResponse }) {
  const navigate = useNavigate();
  const setStockNav = useAppStore((state) => state.setStockNav);
  const list = data.candidates ?? data.today_buy ?? [];
  const sector = item.sector;
  const ai = item.ai_analysis;
  const fallbackRisk = item.breakout_price
    ? `若后续收盘重新跌回突破位 ${price(item.breakout_price)} 下方，应视为本次云阶突破失效。`
    : "若后续收盘重新跌回突破位下方，应视为本次云阶突破失效。";

  const openStock = () => {
    const navList = toNav(list);
    setStockNav(navList, list.findIndex((stock) => stock.code === item.code));
    navigate(`/stock/${item.code}`);
  };

  return (
    <Card className="overflow-hidden lg:sticky lg:top-20" aria-labelledby="cloud-detail-title">
      <div className="flex items-start justify-between gap-4 border-b border-border px-4 py-4 sm:px-5 sm:py-5">
        <div className="min-w-0">
          <div className="flex min-w-0 items-baseline gap-2">
            <Heading level={2} id="cloud-detail-title" className="truncate tracking-[-0.03em]">
              {item.name || item.code}
            </Heading>
            <span className="shrink-0 font-mono text-xs text-ink-muted">{item.code}</span>
          </div>
          <Text type="supporting" className="mt-1 block">
            当日云阶第 {item.rank}/{item.rank_total} 位
          </Text>
        </div>
        <div className="shrink-0 text-right">
          <Badge variant="success" label={item.action_label} />
          <span className="num mt-2 block text-lg font-semibold text-ink">{price(item.close)}</span>
        </div>
      </div>

      <div className="border-b border-border px-4 py-4 sm:px-5">
        <MetadataList columns={3} label={{ position: "top" }}>
          <MetadataListItem label="所属行业">
            <span className={item.industry_available === false ? "text-bull" : "text-ink"}>
              {item.industry}
            </span>
          </MetadataListItem>
          <MetadataListItem label="行业排名">
            <span className="num text-ink">
              {sector?.rank != null ? `${sector.rank} / ${sector.total}` : "待补全"}
            </span>
          </MetadataListItem>
          <MetadataListItem label="行业热度">
            <span className="num text-ink">
              {sector?.score != null ? `${Math.round(sector.score)} 分` : "待补全"}
              {sector?.delta3 != null ? ` · 3日 ${signed(sector.delta3)}` : ""}
            </span>
          </MetadataListItem>
        </MetadataList>
      </div>

      <div className="grid gap-0 divide-y divide-border">
        <section className="px-4 py-4 sm:px-5" aria-labelledby="cloud-reason-title">
          <p id="cloud-reason-title" className="section-kicker">为什么选它</p>
          <div className="mt-3 grid gap-2">
            {(item.evidence ?? [item.reason]).filter(Boolean).map((evidence) => (
              <div key={evidence} className="flex items-start gap-2 text-sm leading-6 text-ink-secondary">
                <Icon icon="check" size="xsm" color="success" />
                <span>{evidence}</span>
              </div>
            ))}
          </div>
        </section>

        <section className="px-4 py-4 sm:px-5" aria-labelledby="cloud-ai-title">
          <div className="flex items-center justify-between gap-3">
            <p id="cloud-ai-title" className="section-kicker">AI 研究判断</p>
            <StatusDot
              variant={data.ai?.available ? "success" : data.ai?.status === "failed" ? "error" : "neutral"}
              label={data.ai?.available ? "已生成" : "未生成"}
            />
          </div>
          {ai ? (
            <p className="mt-3 text-sm leading-6 text-ink-secondary">{ai.comment}</p>
          ) : (
            <p className="mt-3 text-sm leading-6 text-ink-secondary">{aiState(data).description}</p>
          )}
        </section>

        <section className="px-4 py-4 sm:px-5" aria-labelledby="cloud-risk-title">
          <p id="cloud-risk-title" className="section-kicker">什么时候不再值得买</p>
          <p className="mt-3 text-sm leading-6 text-ink-secondary">{ai?.risk || fallbackRisk}</p>
        </section>
      </div>

      <div className="border-t border-border px-4 py-3 sm:px-5">
        <Button
          label={`查看 ${item.name || item.code} K 线`}
          variant="primary"
          size="sm"
          icon={<Icon icon="viewColumns" size="xsm" />}
          onClick={openStock}
        >
          查看 K 线与详细指标
        </Button>
      </div>
    </Card>
  );
}

function EmptyDecision({ data }: { data: RecommendResponse }) {
  const ai = aiState(data);
  return (
    <Card className="p-5 sm:p-7">
      <div className="flex items-start gap-3">
        <div className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-inset text-ink-muted">
          <Icon icon="stop" size="sm" />
        </div>
        <div className="min-w-0">
          <Heading level={2}>今日没有云阶买点</Heading>
          <Text type="body" className="mt-2 block leading-6 text-ink-secondary">
            全市场没有股票同时完成“第一波大涨 → 缩量横盘 → 突破前高”，所以今日名单为空。
          </Text>
          <div className="mt-4 flex items-center gap-2 text-xs text-ink-muted">
            <StatusDot variant={ai.tone} label={ai.title} />
            <span>{ai.title}</span>
          </div>
        </div>
      </div>
    </Card>
  );
}

export function TodayRecommendCard() {
  const { data, error, isLoading, mutate } = useRecommend();
  const candidates = useMemo(() => data?.candidates ?? data?.today_buy ?? [], [data]);
  const [selectedCode, setSelectedCode] = useState<string | null>(null);
  const [methodOpen, setMethodOpen] = useState(false);

  const selected = candidates.find((item) => item.code === selectedCode) ?? candidates[0];

  if (isLoading) {
    return (
      <div className="grid gap-4 lg:grid-cols-[minmax(320px,0.72fr)_minmax(0,1.28fr)]">
        <Skeleton className="h-[420px] w-full rounded-[10px]" />
        <Skeleton className="h-[560px] w-full rounded-[10px]" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <Card className="p-5">
        <LoadError label="云阶决策加载失败" onRetry={() => mutate()} />
      </Card>
    );
  }

  if (!data.available) {
    return (
      <Card className="p-5" aria-live="polite">
        <div className="flex items-start gap-3">
          <Icon icon="warning" size="sm" color="warning" />
          <div>
            <Heading level={2}>云阶数据正在准备</Heading>
            <Text type="supporting" className="mt-1 block">
              {data.reason ?? "当前快照的云阶因子结果尚未固化。"}
            </Text>
          </div>
        </div>
      </Card>
    );
  }

  const ai = aiState(data);
  const track = data.core_factor?.track;

  return (
    <div className="grid gap-5" data-testid="cloud-stair-decision">
      <section className="cloud-decision-hero" aria-labelledby="cloud-summary-title">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2 text-xs text-ink-muted">
            <StatusDot variant={data.has_signal ? "success" : "neutral"} label="云阶信号" />
            <span>云阶信号</span>
            <span>·</span>
            <span>截至 {data.trade_date ?? "未知"} 收盘</span>
          </div>
          <Heading level={1} id="cloud-summary-title" className="mt-3 tracking-[-0.045em]">
            {data.summary ?? `今日云阶选出 ${candidates.length} 只`}
          </Heading>
          <Text type="body" className="mt-3 block max-w-3xl leading-6 text-ink-secondary">
            {candidates.length
              ? `答案：有。${candidates.map((item) => item.name || item.code).join("、")}已完成云阶突破确认，规则结论是值得买入。`
              : "答案：没有。今日不会用其他策略或 AI 硬凑一只股票。"}
          </Text>
        </div>
        <div className="cloud-decision-count" aria-label={`今日云阶选出 ${candidates.length} 只`}>
          <span className="num text-4xl font-semibold tracking-[-0.06em] text-ink">{candidates.length}</span>
          <span className="text-xs text-ink-muted">只入选</span>
        </div>
      </section>

      {candidates.length ? (
        <section className="grid items-start gap-4 lg:grid-cols-[minmax(320px,0.72fr)_minmax(0,1.28fr)]">
          <Card className="overflow-hidden">
            <div className="flex items-end justify-between gap-3 border-b border-border px-4 py-4 sm:px-5">
              <div>
                <Heading level={2} className="text-base">今日候选</Heading>
                <Text type="supporting" className="mt-1 block">按所属行业热度排序</Text>
              </div>
              <span className="num text-xs text-ink-muted">{candidates.length} 只</span>
            </div>
            <List density="spacious" hasDividers aria-label="今日云阶候选">
              {candidates.map((item) => (
                <CandidateRow
                  key={item.code}
                  item={item}
                  selected={item.code === selected?.code}
                  onSelect={() => setSelectedCode(item.code)}
                />
              ))}
            </List>
            <div className="border-t border-border px-4 py-3 sm:px-5">
              <Text type="supporting" className="leading-5">
                {data.ranking_note ?? data.honest_note}
              </Text>
            </div>
          </Card>

          {selected ? <DecisionDetail item={selected} data={data} /> : null}
        </section>
      ) : (
        <EmptyDecision data={data} />
      )}

      <section className="cloud-decision-proof" aria-label="云阶历史证据与数据链路">
        <div className="min-w-0">
          <p className="section-kicker">为什么只看云阶</p>
          <p className="mt-2 text-sm leading-6 text-ink-secondary">
            {data.core_factor?.plain}。这是现有 28 个因子中，唯一在两段互不重叠历史里、T+1 与 T+5 都跑赢基准的短线因子。
          </p>
        </div>
        {track ? (
          <div className="grid shrink-0 grid-cols-2 gap-x-8 gap-y-2 text-right">
            <div>
              <span className="block text-[11px] text-ink-muted">样本内 T+5 胜率</span>
              <span className="num mt-1 block text-sm font-semibold text-ink">{track.in_win.toFixed(1)}%</span>
            </div>
            <div>
              <span className="block text-[11px] text-ink-muted">样本外 T+5 超额</span>
              <span className="num mt-1 block text-sm font-semibold text-bull">+{track.oos_excess.toFixed(2)}%</span>
            </div>
          </div>
        ) : null}
      </section>

      <Collapsible
        trigger="数据与 AI 可追溯记录"
        isOpen={methodOpen}
        onOpenChange={setMethodOpen}
        className="rounded-lg border border-border bg-surface px-4 py-3 text-xs text-ink-muted sm:px-5"
      >
        <MetadataList columns={2} label={{ position: "top" }} className="mt-4">
          <MetadataListItem label="行情快照">
            <span className="break-all text-ink-secondary">
              {data.trade_date ?? "未知"} · {data.snapshot_id?.slice(0, 12) ?? "未落账"}
            </span>
          </MetadataListItem>
          <MetadataListItem label="云阶规则">
            <span className="text-ink-secondary">{data.core_factor?.decision_rule ?? "突破确认后入选"}</span>
          </MetadataListItem>
          <MetadataListItem label="AI 状态">
            <span className="text-ink-secondary">{ai.title}：{ai.description}</span>
          </MetadataListItem>
          <MetadataListItem label="决策记录">
            <span className="break-all text-ink-secondary">{data.decision_run_id ?? "当前快照决策待落账"}</span>
          </MetadataListItem>
        </MetadataList>
      </Collapsible>

      <p className="text-[11px] leading-5 text-ink-muted">
        规则结论只说明云阶买点是否成立，不代表保证收益；AI 只解释已选出的股票，不增删、不排序、不改写规则结论。
      </p>
    </div>
  );
}
