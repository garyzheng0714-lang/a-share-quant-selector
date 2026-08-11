import { Heading } from "@astryxdesign/core/Heading";
import { StatusDot, type StatusDotVariant } from "@astryxdesign/core/StatusDot";
import { Text } from "@astryxdesign/core/Text";
import { LoadError } from "@/components/ui/load-error";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader, PageShell } from "@/components/layout/page-shell";
import { PageTransition } from "@/components/layout/page-transition";
import { usePipelineStatus } from "@/lib/hooks";
import type { PipelineStage, PipelineStageStatus, PipelineStatusResponse } from "@/lib/api";

const stageMeta: Record<PipelineStageStatus, { tone: StatusDotVariant; label: string }> = {
  running: { tone: "accent", label: "进行中" },
  complete: { tone: "success", label: "已完成" },
  attention: { tone: "warning", label: "已完成，有缺口" },
  failed: { tone: "error", label: "失败" },
};

const stateMeta: Record<PipelineStatusResponse["state"], { tone: StatusDotVariant; label: string }> = {
  healthy: { tone: "success", label: "数据管线正常" },
  updating: { tone: "accent", label: "数据管线正在运行" },
  attention: { tone: "warning", label: "数据管线需要注意" },
  unavailable: { tone: "error", label: "数据管线不可用" },
};

function formatTime(value?: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function sourceName(value: string | { source_id?: string }) {
  return typeof value === "string" ? value : value.source_id ?? "未标记来源";
}

function runStatusLabel(run?: PipelineStatusResponse["run"]) {
  if (run?.status === "queued") return run.attempt_count > 0 ? "等待自动重试" : "等待执行";
  if (run?.status === "running") return "正在执行";
  if (run?.status === "succeeded") return "执行成功";
  if (run?.status === "failed") return "执行失败";
  if (run?.status === "cancelled") return "已取消";
  return "尚无运行记录";
}

function stageDetail(stage: PipelineStage) {
  if (stage.detail?.total) {
    return `已处理 ${stage.detail.processed ?? 0} / ${stage.detail.total}`;
  }
  return stage.detail?.reason ?? stage.detail?.trade_date ?? "—";
}

export function Component() {
  const pipeline = usePipelineStatus();

  if (pipeline.isLoading) {
    return <PageShell><Skeleton className="h-[560px] w-full rounded-xl" /></PageShell>;
  }
  if (pipeline.error || !pipeline.data?.available) {
    return (
      <PageShell>
        <LoadError label="数据管线状态加载失败" onRetry={() => pipeline.mutate()} />
      </PageShell>
    );
  }

  const data = pipeline.data;
  const state = stateMeta[data.state];
  const sources = data.market.source_set ?? [];

  return (
    <PageTransition>
      <PageShell>
        <PageHeader
          title="数据管线"
          description="只展示真实采集、发布和决策状态；页面不会触发行情更新"
          endContent={
            <div className="flex items-center gap-2" role="status" aria-live="polite">
              <StatusDot variant={state.tone} label={state.label} />
              <Text type="supporting">{state.label}</Text>
            </div>
          }
        />

        <section className="rounded-xl border border-border bg-surface" aria-labelledby="pipeline-summary-title">
          <div className="border-b border-border px-4 py-3">
            <Heading id="pipeline-summary-title" level={2}>当前状态</Heading>
          </div>
          <dl className="grid sm:grid-cols-2 lg:grid-cols-4">
            <div className="px-4 py-4 sm:border-r sm:border-border">
              <dt className="text-xs text-ink-muted">正式行情</dt>
              <dd className="mt-2 text-sm font-semibold text-ink">{data.market.local_date ?? "尚无正式快照"}</dd>
              <p className="mt-1 text-xs text-ink-muted">应更新至 {data.market.expected_date ?? "待确认"}</p>
            </div>
            <div className="border-t border-border px-4 py-4 sm:border-t-0 lg:border-r">
              <dt className="text-xs text-ink-muted">行情覆盖</dt>
              <dd className="num mt-2 text-sm font-semibold text-ink">{(data.market.coverage_ratio * 100).toFixed(1)}%</dd>
              <p className="mt-1 text-xs text-ink-muted">{data.market.stock_count.toLocaleString("zh-CN")} 只股票</p>
            </div>
            <div className="border-t border-border px-4 py-4 sm:border-r lg:border-t-0">
              <dt className="text-xs text-ink-muted">最近数据任务</dt>
              <dd className="mt-2 text-sm font-semibold text-ink">{data.run?.task_label ?? "尚无运行记录"}</dd>
              <p className="mt-1 text-xs text-ink-muted">{runStatusLabel(data.run)} · {formatTime(data.run?.finished_at ?? data.run?.started_at)}</p>
            </div>
            <div className="border-t border-border px-4 py-4 lg:border-t-0">
              <dt className="text-xs text-ink-muted">下一次收盘更新</dt>
              <dd className="mt-2 text-sm font-semibold text-ink">{formatTime(data.scheduler.next_close_at)}</dd>
              <p className="mt-1 text-xs text-ink-muted">{data.scheduler.close_schedule}</p>
            </div>
          </dl>
        </section>

        <section className="rounded-xl border border-border bg-surface" aria-labelledby="pipeline-stage-title">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3">
            <Heading id="pipeline-stage-title" level={2}>最近一次运行路径</Heading>
            <Text type="supporting">
              {data.run ? `第 ${data.run.attempt_count}/${data.run.max_attempts} 次尝试` : "等待首次正式运行"}
            </Text>
          </div>
          {data.run?.stages.length ? (
            <ol>
              {data.run.stages.map((stage, index) => {
                const meta = stageMeta[stage.status];
                return (
                  <li key={stage.key} className="grid gap-2 border-b border-border px-4 py-3 last:border-b-0 sm:grid-cols-[32px_minmax(180px,1fr)_minmax(160px,1fr)_auto] sm:items-center">
                    <span className="num text-xs text-ink-muted">{String(index + 1).padStart(2, "0")}</span>
                    <div className="flex items-center gap-2">
                      <StatusDot variant={meta.tone} label={meta.label} />
                      <span className="text-sm font-medium text-ink">{stage.label}</span>
                    </div>
                    <span className="text-xs text-ink-muted">{stageDetail(stage)}</span>
                    <span className="text-xs text-ink-muted">{formatTime(stage.finished_at ?? stage.started_at)}</span>
                  </li>
                );
              })}
            </ol>
          ) : (
            <Text type="supporting" className="block px-4 py-10 text-center">还没有可回读的收盘管线记录</Text>
          )}
        </section>

        <div className="grid gap-5 lg:grid-cols-[1.1fr_.9fr]">
          <section className="rounded-xl border border-border bg-surface" aria-labelledby="pipeline-attention-title">
            <div className="border-b border-border px-4 py-3">
              <Heading id="pipeline-attention-title" level={2}>需要处理</Heading>
            </div>
            {data.attention.length ? (
              <ul>
                {data.attention.map((item) => (
                  <li key={item.code} className="flex items-start gap-3 border-b border-border px-4 py-3 last:border-b-0">
                    <StatusDot variant={item.level === "critical" ? "error" : "warning"} label={item.level === "critical" ? "严重" : "注意"} />
                    <span className="text-sm leading-5 text-ink-secondary">{item.message}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <Text type="body" className="block px-4 py-8">没有需要人工处理的异常</Text>
            )}
          </section>

          <section className="rounded-xl border border-border bg-surface" aria-labelledby="pipeline-storage-title">
            <div className="border-b border-border px-4 py-3">
              <Heading id="pipeline-storage-title" level={2}>存储与保留</Heading>
            </div>
            <dl className="divide-y divide-border text-sm">
              <div className="flex items-center justify-between gap-4 px-4 py-3"><dt className="text-ink-muted">正式快照</dt><dd className="num text-ink">{data.storage.snapshot_count}</dd></div>
              <div className="flex items-center justify-between gap-4 px-4 py-3"><dt className="text-ink-muted">暂存目录</dt><dd className="num text-ink">{data.storage.staging_count}</dd></div>
              <div className="px-4 py-3"><dt className="text-ink-muted">自动保留规则</dt><dd className="mt-1 leading-5 text-ink-secondary">{data.storage.retention_summary}</dd></div>
              <div className="px-4 py-3"><dt className="text-ink-muted">行情存储位置</dt><dd className="mt-1 break-all font-mono text-xs leading-5 text-ink-secondary">{data.storage.data_root}</dd></div>
              <div className="px-4 py-3"><dt className="text-ink-muted">任务与决策账本</dt><dd className="mt-1 break-all font-mono text-xs leading-5 text-ink-secondary">{data.storage.state_root}</dd></div>
            </dl>
          </section>
        </div>

        <section className="rounded-xl border border-border bg-surface" aria-labelledby="pipeline-source-title">
          <div className="border-b border-border px-4 py-3">
            <Heading id="pipeline-source-title" level={2}>来源与时间</Heading>
          </div>
          <div className="grid gap-5 px-4 py-4 text-sm md:grid-cols-2 lg:grid-cols-3">
            <div>
              <p className="text-xs text-ink-muted">日线 K 线</p>
              <p className="mt-1 leading-5 text-ink-secondary">
                主源 {data.sources.kline.primary}，采集备源 {data.sources.kline.fallback}
                {data.sources.kline.validation_fallback
                  ? `，独立校验备源 ${data.sources.kline.validation_fallback}`
                  : ""}
                ，前复权
              </p>
            </div>
            <div><p className="text-xs text-ink-muted">股票池</p><p className="mt-1 leading-5 text-ink-secondary">发现 {data.sources.universe.discovery_source_id ?? "待发布"}；校验 {data.sources.universe.verification_source_id ?? "待发布"}</p></div>
            <div><p className="text-xs text-ink-muted">行业分类</p><p className="mt-1 break-words leading-5 text-ink-secondary">{data.sources.industry.source_id ?? "待发布"}{data.sources.industry.coverage_ratio != null ? ` · ${(data.sources.industry.coverage_ratio * 100).toFixed(1)}%` : ""}</p></div>
            <div><p className="text-xs text-ink-muted">市值</p><p className="mt-1 break-words leading-5 text-ink-secondary">{data.sources.market_cap.source_id ?? "待发布"}{data.sources.market_cap.coverage_ratio != null ? ` · ${(data.sources.market_cap.coverage_ratio * 100).toFixed(1)}%` : ""}</p></div>
            <div><p className="text-xs text-ink-muted">停复牌状态</p><p className="mt-1 break-words leading-5 text-ink-secondary">{data.sources.security_status.source_id ?? "待发布"}</p></div>
            <div><p className="text-xs text-ink-muted">本快照实际行情源</p><p className="mt-1 break-words leading-5 text-ink-secondary">{sources.length ? sources.map(sourceName).join("、") : "尚无正式快照来源记录"}</p></div>
          </div>
          <Text type="supporting" className="block border-t border-border px-4 py-3">结果回填、全策略复盘和影子模型演进都已纳入每日收盘闭环；前向月份不足时只显示“预热中”，不会冒充已经训练完成。</Text>
        </section>
      </PageShell>
    </PageTransition>
  );
}
