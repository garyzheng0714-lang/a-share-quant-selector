import { useState } from "react";
import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { Icon } from "@astryxdesign/core/Icon";
import { StatusDot } from "@astryxdesign/core/StatusDot";
import { LoadError, Skeleton } from "@/components/ui";
import { useLatestDecision, usePipelineStatus, useRecommend, useSystemStatus } from "@/lib/hooks";

type StageTone = "success" | "warning" | "error" | "neutral";

function stage(status: boolean | null, ready: string, waiting: string, failed = false) {
  const tone: StageTone = failed ? "error" : status === true ? "success" : status === false ? "warning" : "neutral";
  return { tone, text: status === true ? ready : failed ? waiting : waiting };
}

export function Component() {
  const pipeline = usePipelineStatus();
  const system = useSystemStatus();
  const decision = useLatestDecision();
  const recommend = useRecommend();
  const [showAudit, setShowAudit] = useState(false);

  if (pipeline.isLoading || system.isLoading || decision.isLoading || recommend.isLoading) {
    return <main className="q-admin-page"><Skeleton className="q-admin-skeleton" /></main>;
  }
  if (pipeline.error || !pipeline.data?.available) {
    return <main className="q-admin-page"><LoadError label="后台状态暂不可用" onRetry={() => pipeline.mutate()} /></main>;
  }

  const p = pipeline.data;
  const s = system.data;
  const d = decision.data;
  const cloud = recommend.data;
  const cloudCount = cloud?.candidates?.length || 0;
  const aiReady = s?.ai?.status === "explained" || s?.ai?.status === "shadow_ranked";
  const stages = [
    { label: "行情抓取", detail: `${p.market.stock_count} 只 · 覆盖率 ${(p.market.coverage_ratio * 100).toFixed(1)}%`, ...stage(p.market.fresh, "完成", "行情待更新") },
    { label: "契约校验", detail: p.attention.length ? `${p.attention.length} 项需处理` : "freshness / OHLC / 日历已通过", ...stage(p.attention.length === 0, "通过", "需复核", p.state === "unavailable") },
    { label: "快照切换", detail: p.market.snapshot_id || "快照尚未就绪", ...stage(Boolean(p.market.snapshot_id), "完成", "等待快照") },
    { label: "云阶决策", detail: cloud?.available ? `买点 ${cloudCount} 只` : "当前快照云阶决策未完成", ...stage(Boolean(cloud?.available), "完成", "等待决策") },
    { label: "AI 解释", detail: aiReady ? `${s?.ai?.model || "模型"} · 已绑定当前决策` : (s?.ai?.reason_codes || []).join(" / ") || "尚未调用", ...stage(aiReady, "完成", "未完成", s?.ai?.status === "failed") },
    { label: "调度器", detail: p.scheduler.running ? `下次收盘任务 ${p.scheduler.next_close_at || "待计算"}` : "调度器未运行", ...stage(p.scheduler.running, "运行中", "未运行", !p.scheduler.running) },
  ];
  const models = d?.models || [];

  return (
    <main className="q-admin-page">
      <header className="q-admin-header">
        <div><h1>后台管理</h1><p>前台只读已发布结果；这里集中查看数据、任务、策略、AI 与快照状态。</p></div>
        <div>
          <Button label={showAudit ? "收起审计日志" : "查看审计日志"} variant="secondary" size="sm" onClick={() => setShowAudit((value) => !value)} />
          <Badge variant="neutral" label="只读后台" />
        </div>
      </header>

      <section className="q-admin-pipeline">
        <div className="q-admin-section-head"><h2>数据管线</h2><span>状态时间 {p.as_of?.replace("T", " ") || "—"}</span></div>
        <div className="q-pipeline-stages">
          {stages.map((item) => (
            <div key={item.label}>
              <div><StatusDot variant={item.tone} label={`${item.label}：${item.text}`} /><strong>{item.label}</strong></div>
              <span className={`q-stage-bar q-stage-bar--${item.tone}`} />
              <p>{item.detail}</p>
            </div>
          ))}
        </div>
      </section>

      {showAudit && (
        <section className="q-admin-audit" aria-label="审计与告警">
          <div className="q-admin-section-head"><h2>审计与告警</h2><span>近 {p.alerts.summary.window_hours} 小时 {p.alerts.summary.total} 条</span></div>
          {p.alerts.latest.length ? p.alerts.latest.map((alert) => (
            <div key={alert.alert_id}><StatusDot variant={alert.severity === "critical" ? "error" : "warning"} label={alert.severity} /><span>{alert.message}</span><time>{alert.occurred_at}</time></div>
          )) : <p>当前窗口没有告警。</p>}
        </section>
      )}

      <div className="q-admin-grid">
        <section className="q-admin-card">
          <div className="q-admin-section-head"><h2>任务队列</h2><span>{p.run ? "最近任务" : "暂无任务"}</span></div>
          {p.run ? (
            <div className="q-admin-task">
              <StatusDot variant={p.run.status === "succeeded" ? "success" : p.run.status === "failed" ? "error" : "warning"} label={p.run.status} />
              <span><strong>{p.run.task_label}</strong><small>{p.run.task_id}</small></span>
              <Badge variant={p.run.status === "succeeded" ? "success" : p.run.status === "failed" ? "error" : "warning"} label={p.run.status} />
            </div>
          ) : <p className="q-admin-empty">当前没有已记录的数据任务。</p>}
          {p.run?.stages?.map((row) => (
            <div className="q-admin-stage-row" key={row.key}><span>{row.label}</span><Badge variant={row.status === "complete" ? "success" : row.status === "failed" ? "error" : "warning"} label={row.status} /></div>
          ))}
        </section>

        <section className="q-admin-card">
          <div className="q-admin-section-head"><h2>策略与模型版本</h2><span>{d?.strategy_version || "版本待就绪"}</span></div>
          {models.length ? models.map((model) => (
            <div className="q-admin-model" key={`${model.model_key}-${model.version}`}>
              <span><strong>{model.model_key}</strong><small>{model.version}</small></span>
              <Badge variant={model.status === "active" ? "success" : model.status === "shadow" ? "warning" : "neutral"} label={model.status === "active" ? "已激活" : model.status === "shadow" ? "影子" : "已拒绝"} />
            </div>
          )) : <p className="q-admin-empty">当前决策没有发布模型元数据。</p>}
        </section>

        <section className="q-admin-card">
          <div className="q-admin-section-head"><h2>快照与数据契约</h2><span>{p.market.snapshot_id || "未就绪"}</span></div>
          {[
            ["数据日期", p.market.local_date || "—"],
            ["预期交易日", p.market.expected_date || "—"],
            ["全市场覆盖率", `${(p.market.coverage_ratio * 100).toFixed(1)}%`],
            ["正式快照数量", String(p.storage.snapshot_count)],
            ["保留策略", p.storage.retention_summary],
          ].map(([label, value]) => (
            <div className="q-contract-row" key={label}><Icon icon="success" size="xsm" color="success" /><span>{label}</span><strong>{value}</strong></div>
          ))}
        </section>

        <section className="q-admin-card">
          <div className="q-admin-section-head"><h2>数据来源</h2><span>前复权</span></div>
          {[
            ["K 线主源", p.sources.kline.primary],
            ["K 线备用", p.sources.kline.fallback],
            ["行业分类", p.sources.industry.source_id || "未记录"],
            ["市值数据", p.sources.market_cap.source_id || "未记录"],
            ["证券状态", p.sources.security_status.source_id || "未记录"],
          ].map(([label, value]) => (
            <div className="q-contract-row" key={label}><span>{label}</span><strong>{value}</strong></div>
          ))}
        </section>

        <section className="q-admin-card">
          <div className="q-admin-section-head"><h2>云阶决策发布</h2><span>{cloud?.trade_date || "未发布"}</span></div>
          <div className="q-decision-counts">
            <div><span>买点</span><strong>{cloudCount}</strong></div>
            <div><span>规则</span><strong>云阶</strong></div>
            <div><span>AI 改票</span><strong>0</strong></div>
          </div>
          <p className="q-admin-empty">决策 Run：{cloud?.decision_run_id || p.decision.run_id || "尚未生成"}</p>
          <p className="q-admin-empty">云阶因子决定前台买点；分层模型只保留为影子证据，不降级云阶结论。</p>
        </section>

        <section className="q-admin-card">
          <div className="q-admin-section-head"><h2>AI 配置</h2><span>{aiReady ? "已调用" : "未完成"}</span></div>
          <div className="q-ai-admin-state"><StatusDot variant={aiReady ? "success" : s?.ai?.status === "failed" ? "error" : "warning"} label={s?.ai?.status || "unknown"} /><div><strong>{s?.ai?.model || "火山方舟"}</strong><p>{aiReady ? "解释已绑定当前决策 Run。" : (s?.ai?.reason_codes || []).join(" / ") || "等待 AI 解释。"}</p></div></div>
        </section>
      </div>
    </main>
  );
}
