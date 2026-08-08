import { Heading } from "@astryxdesign/core/Heading";
import { StatusDot, type StatusDotVariant } from "@astryxdesign/core/StatusDot";
import { Text } from "@astryxdesign/core/Text";
import { Link } from "@/lib/spa-router";
import type { PipelineAttention, PipelineStatusResponse } from "@/lib/api";

function stateMeta(data?: PipelineStatusResponse, failed?: boolean) {
  if (failed) return { tone: "error" as const, label: "状态读取失败" };
  if (!data) return { tone: "neutral" as const, label: "正在检查数据" };
  const states: Record<PipelineStatusResponse["state"], { tone: StatusDotVariant; label: string }> = {
    healthy: { tone: "success", label: "数据就绪" },
    updating: { tone: "accent", label: "正在更新" },
    attention: { tone: "warning", label: "需要注意" },
    unavailable: { tone: "error", label: "数据不可用" },
  };
  return states[data.state];
}

function decisionText(data?: PipelineStatusResponse) {
  if (!data) return "等待系统状态";
  if (!data.market.fresh) return "等待行情更新后再生成结论";
  if (!data.decision.available) return "行情已就绪，收盘决策尚未生成";
  const counts = data.decision.candidate_counts;
  if (counts.buy > 0) return `${counts.buy} 只合格候选，需要进一步查看风险证据`;
  if (counts.observe > 0) return `没有买入结论，${counts.observe} 只处于观察状态`;
  return "今天没有合格候选";
}

function visibleAttention(data?: PipelineStatusResponse, contentSnapshotId?: string | null) {
  const items: PipelineAttention[] = [...(data?.attention ?? [])];
  if (
    data?.market.snapshot_id &&
    contentSnapshotId &&
    data.market.snapshot_id !== contentSnapshotId
  ) {
    items.unshift({
      code: "mixed_page_snapshot",
      level: "warning",
      message: "板块内容与数据状态来自不同快照，请刷新页面后再判断",
    });
  }
  return items.slice(0, 3);
}

export function DataBrief({
  data,
  failed = false,
  contentSnapshotId,
}: {
  data?: PipelineStatusResponse;
  failed?: boolean;
  contentSnapshotId?: string | null;
}) {
  const meta = stateMeta(data, failed);
  const attention = visibleAttention(data, contentSnapshotId);
  const date = data?.market.local_date ?? "尚无正式快照";
  const expected = data?.market.expected_date;

  return (
    <section className="rounded-xl border border-border bg-surface" aria-labelledby="daily-brief-title">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3">
        <div className="flex items-center gap-2">
          <StatusDot variant={meta.tone} label={meta.label} />
          <Heading id="daily-brief-title" level={2}>今天先看这三件事</Heading>
        </div>
        <Link className="text-xs font-medium text-accent hover:text-accent-light focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent" to="/data-pipeline">
          查看数据管线
        </Link>
      </div>

      <div className="grid md:grid-cols-[.9fr_1.1fr_1.35fr]">
        <div className="px-4 py-4 md:border-r md:border-border">
          <Text type="supporting">数据状态</Text>
          <Text type="body" weight="bold" className="mt-2 block">{meta.label}</Text>
          <Text type="supporting" className="mt-1 block">
            截至 {date}{expected && expected !== date ? ` · 应更新至 ${expected}` : ""}
          </Text>
        </div>

        <div className="border-t border-border px-4 py-4 md:border-r md:border-t-0">
          <Text type="supporting">今天结论</Text>
          <Text type="body" weight="bold" className="mt-2 block leading-6">{decisionText(data)}</Text>
        </div>

        <div className="border-t border-border px-4 py-4 md:border-t-0">
          <Text type="supporting">需要注意</Text>
          {attention.length ? (
            <ul className="mt-2 space-y-1.5 text-xs leading-5 text-ink-secondary">
              {attention.map((item) => <li key={item.code}>{item.message}</li>)}
            </ul>
          ) : (
            <Text type="body" weight="bold" className="mt-2 block">没有需要处理的异常</Text>
          )}
        </div>
      </div>
    </section>
  );
}
