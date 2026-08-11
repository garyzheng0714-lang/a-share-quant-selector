import { useMemo, useState } from "react";
import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { Icon } from "@astryxdesign/core/Icon";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { LoadError, Skeleton } from "@/components/ui";
import type { DailyStrategyRow, DailyStrategyWindow } from "@/lib/api";
import { useDailyStrategyReview } from "@/lib/hooks";

type EvidenceFilter = "all" | "eligible" | "warming_up";

const holdWindows = ["T+1", "T+5", "T+10", "T+20"] as const;

const reasonLabels: Record<string, string> = {
  daily_strategy_review_not_ready: "今日复盘尚未由收盘任务生成",
  stale_market_data: "行情数据不是最新交易日，复盘暂不发布",
  daily_strategy_review_unavailable: "每日策略复盘暂不可用",
  factor_snapshot_not_ready: "当日因子快照尚未齐全",
  llm_unconfigured: "AI 服务尚未配置",
  unsupported_llm_provider: "AI 服务配置暂不受支持",
};

function pct(value?: number | null, signedValue = false) {
  if (value == null || !Number.isFinite(value)) return "—";
  const prefix = signedValue && value > 0 ? "+" : "";
  return `${prefix}${value.toFixed(2)}%`;
}

function dateTimeLabel(value?: string) {
  if (!value) return "—";
  const normalized = value.replace("T", " ");
  return normalized.slice(0, 19);
}

function reasonLabel(reason?: string | null) {
  if (!reason) return "等待收盘任务完成全策略复盘。";
  return reasonLabels[reason] || reason;
}

function reportStatus(status?: string) {
  if (status === "ready") return { label: "评分已形成", variant: "success" as const };
  if (status === "factor_snapshot_not_ready") return { label: "因子快照待齐", variant: "warning" as const };
  return { label: "模型预热中", variant: "warning" as const };
}

function aiStatus(status?: string, reasons: string[] = [], model?: string | null) {
  if (status === "explained") {
    return { label: model ? `AI 已解释 · ${model}` : "AI 已解释", variant: "info" as const };
  }
  if (status === "failed") {
    return { label: "AI 解释失败 · 已回退确定性结论", variant: "warning" as const };
  }
  if (reasons.includes("llm_unconfigured")) {
    return { label: "AI 未配置 · 当前为确定性结论", variant: "neutral" as const };
  }
  return { label: "AI 未调用 · 当前为确定性结论", variant: "neutral" as const };
}

function evidenceStatus(row: DailyStrategyRow) {
  if (row.eligible && row.evidence_quality === "pit_verified") {
    return { label: "PIT 影子门槛", variant: "success" as const };
  }
  if (row.eligible) return { label: "近似影子门槛", variant: "warning" as const };
  if (
    row.eligibility.blocking_execution_failures > 0 ||
    (row.eligibility.blocking_overdue_evidence_days ?? 0) > 0
  ) {
    return { label: "证据不完整", variant: "error" as const };
  }
  return { label: "预热中", variant: "warning" as const };
}

function metricTone(value?: number | null) {
  if (value == null || value === 0) return "";
  return value > 0 ? "q-up" : "q-down";
}

function WindowEvidence({ label, data, primary }: { label: string; data: DailyStrategyWindow; primary: boolean }) {
  return (
    <section className={primary ? "q-review-window is-primary" : "q-review-window"}>
      <header>
        <strong>{label}</strong>
        {primary && <Badge variant="blue" label="主评分窗口" />}
      </header>
      <dl>
        <div><dt>贝叶斯胜率</dt><dd>{pct(data.bayesian_win_rate_pct)}</dd></div>
        <div><dt>95% 下界</dt><dd>{pct(data.wilson_lower_bound_pct)}</dd></div>
        <div><dt>日均净收益</dt><dd className={metricTone(data.daily_avg_net_return_pct)}>{pct(data.daily_avg_net_return_pct, true)}</dd></div>
        <div><dt>CVaR10</dt><dd className={metricTone(data.cvar10_net_return_pct)}>{pct(data.cvar10_net_return_pct, true)}</dd></div>
        <div><dt>已终局信号日</dt><dd>{data.signal_days}</dd></div>
        <div><dt>可计算票样本</dt><dd>{data.sample_count}</dd></div>
        <div><dt>PIT 已验证 / 状态近似</dt><dd>{data.pit_verified_sample_count} / {data.forward_approximation_sample_count}</dd></div>
        <div><dt>待成熟信号日</dt><dd>{data.pending_signal_day_count}</dd></div>
        <div><dt>逾期缺证据</dt><dd>{data.overdue_pending_signal_day_count ?? 0}</dd></div>
      </dl>
      {!data.evidence_complete && (
        <p>
          终局执行失败 {data.terminal_execution_failure_count} 个信号日，
          逾期仍缺证据 {data.overdue_pending_signal_day_count ?? 0} 个信号日，已阻止排名。
        </p>
      )}
    </section>
  );
}

export function Component() {
  const review = useDailyStrategyReview();
  const [group, setGroup] = useState("all");
  const [evidence, setEvidence] = useState<EvidenceFilter>("all");
  const [expanded, setExpanded] = useState<string | null>(null);

  const response = review.data;
  const report = response?.report;
  const groups = useMemo(
    () => Array.from(new Set((report?.strategies || []).map((row) => row.group).filter(Boolean))),
    [report?.strategies],
  );
  const strategies = useMemo(
    () => (report?.strategies || []).filter((row) => {
      if (group !== "all" && row.group !== group) return false;
      return evidence === "all" || row.status === evidence;
    }),
    [evidence, group, report?.strategies],
  );

  if (review.isLoading) {
    return <main className="q-review-page"><Skeleton className="q-review-skeleton" /></main>;
  }
  if (review.error) {
    return (
      <main className="q-review-page">
        <LoadError label="每日策略复盘加载失败" onRetry={() => review.mutate()} />
      </main>
    );
  }

  if (!response?.available || !report?.available) {
    return (
      <main className="q-review-page">
        <header className="q-review-header">
          <h1>每日策略复盘</h1>
          <p>T+5 是固定主评分窗口；只有已终局的前向证据进入次日开盘成交模拟。</p>
        </header>
        <section className="q-review-unavailable" aria-live="polite">
          <Icon icon="info" size="sm" color="warning" label="今日复盘尚未就绪" />
          <div>
            <Badge variant="warning" label="今日复盘未发布" />
            <h2>{reasonLabel(response?.reason || report?.reason)}</h2>
            <p>
              {response?.freshness?.local_date
                ? `当前行情日期 ${response.freshness.local_date}，期望交易日 ${response.freshness.expected_date || "待确认"}。`
                : "系统不会用旧数据或临时计算结果冒充今日复盘。"}
            </p>
            <Button label="重新读取" variant="secondary" size="sm" onClick={() => review.mutate()} />
          </div>
        </section>
      </main>
    );
  }

  const conclusion = response.ai_payload?.conclusion;
  const currentStatus = reportStatus(report.status);
  const currentAiStatus = aiStatus(response.ai_status, response.reason_codes, response.ai_model);
  const primary = report.primary_window || "T+5";

  return (
    <main className="q-review-page">
      <header className="q-review-header">
        <h1>每日策略复盘</h1>
        <p>{primary} 是固定主评分窗口；当前使用开盘价成交模拟，部分证券状态为近似证据，AI 只解释。</p>
      </header>

      <section className="q-review-conclusion" aria-labelledby="daily-review-conclusion">
        <div className="q-review-conclusion-copy">
          <div className="q-review-status-line">
            <Badge variant={currentStatus.variant} label={currentStatus.label} />
            <Badge variant={currentAiStatus.variant} label={currentAiStatus.label} />
          </div>
          <h2 id="daily-review-conclusion">{conclusion?.headline || "确定性复盘已生成"}</h2>
          <p>{conclusion?.summary || "今日策略证据已按固定统计口径完成回读。"}</p>
          {!!conclusion?.observations?.length && (
            <ul>
              {conclusion.observations.slice(0, 2).map((item) => <li key={item}>{item}</li>)}
            </ul>
          )}
          <div className="q-review-guidance">
            {!!conclusion?.risks?.length && (
              <section aria-label="今日风险">
                <strong>风险</strong>
                <ul>{conclusion.risks.slice(0, 2).map((item) => <li key={item}>{item}</li>)}</ul>
              </section>
            )}
            {!!conclusion?.next_actions?.length && (
              <section aria-label="下一步反馈">
                <strong>下一步</strong>
                <ul>{conclusion.next_actions.slice(0, 2).map((item) => <li key={item}>{item}</li>)}</ul>
              </section>
            )}
          </div>
        </div>
        <dl className="q-review-run-meta">
          <div><dt>交易日</dt><dd>{response.trade_date || report.trade_date}</dd></div>
          <div><dt>生成时间</dt><dd>{dateTimeLabel(response.as_of)}</dd></div>
          <div><dt>反馈模式</dt><dd>仅影子反馈</dd></div>
          <div><dt>模型版本</dt><dd title={response.model_version}>{response.model_version?.slice(0, 28) || report.model_version}</dd></div>
        </dl>
      </section>

      <section className="q-review-run-summary" aria-label="今日复盘摘要">
        <div><span>策略总数</span><strong>{report.strategy_count}</strong></div>
        <div><span>今日信号</span><strong>{report.today_hit_count == null ? "待齐" : report.today_hit_count}</strong></div>
        <div><span>达到影子门槛</span><strong>{report.eligible_strategy_count}</strong></div>
        <div><span>主评分窗口</span><strong>{primary}</strong></div>
      </section>

      <section className="q-review-leaderboard" aria-labelledby="strategy-leaderboard-title">
        <header className="q-review-board-header">
          <div>
            <h2 id="strategy-leaderboard-title">策略证据榜</h2>
            <p>保持后端固定排名；预热策略不参与名次，只展示当前成熟度。</p>
          </div>
          <div className="q-review-filters">
            <SegmentedControl value={group} onChange={setGroup} label="策略分组" size="sm">
              <SegmentedControlItem value="all" label="全部分组" />
              {groups.map((item) => <SegmentedControlItem key={item} value={item} label={item} />)}
            </SegmentedControl>
            <SegmentedControl value={evidence} onChange={(value) => setEvidence(value as EvidenceFilter)} label="证据状态" size="sm">
              <SegmentedControlItem value="all" label="全部状态" />
              <SegmentedControlItem value="eligible" label="影子门槛" />
              <SegmentedControlItem value="warming_up" label="预热中" />
            </SegmentedControl>
          </div>
        </header>

        <div className="q-strategy-table-head" aria-hidden="true">
          <span>名称 / 分组 / 状态</span>
          <span>{primary} 贝叶斯胜率</span>
          <span>95% 下界</span>
          <span>日均净收益</span>
          <span>CVaR10</span>
          <span>成熟日 / 样本</span>
          <span>今日命中</span>
          <span />
        </div>

        <div className="q-strategy-list">
          {strategies.map((row) => {
            const window = row.windows[primary as keyof typeof row.windows] || row.windows["T+5"];
            const state = evidenceStatus(row);
            const isExpanded = expanded === row.strategy;
            return (
              <article className={isExpanded ? "q-strategy-entry is-expanded" : "q-strategy-entry"} key={row.strategy}>
                <button
                  type="button"
                  className="q-strategy-row"
                  aria-label={`${row.name}，${state.label}，${primary} 贝叶斯胜率 ${pct(window.bayesian_win_rate_pct)}，95% 下界 ${pct(window.wilson_lower_bound_pct)}，日均净收益 ${pct(window.daily_avg_net_return_pct, true)}，CVaR10 ${pct(window.cvar10_net_return_pct, true)}，成熟日 ${window.signal_days}，样本 ${window.sample_count}，今日命中 ${row.today_hit_count == null ? "待齐" : row.today_hit_count}`}
                  aria-expanded={isExpanded}
                  aria-controls={`strategy-evidence-${row.strategy}`}
                  onClick={() => setExpanded(isExpanded ? null : row.strategy)}
                >
                  <span className="q-strategy-identity">
                    <span className="q-strategy-rank">{row.rank ? String(row.rank).padStart(2, "0") : "—"}</span>
                    <span>
                      <strong>{row.name}</strong>
                      <small>{row.group}</small>
                    </span>
                    <Badge variant={state.variant} label={state.label} />
                  </span>
                  <span className="q-strategy-metric"><small>{primary} 贝叶斯胜率</small><strong>{pct(window.bayesian_win_rate_pct)}</strong></span>
                  <span className="q-strategy-metric"><small>95% 下界</small><strong>{pct(window.wilson_lower_bound_pct)}</strong></span>
                  <span className="q-strategy-metric"><small>日均净收益</small><strong className={metricTone(window.daily_avg_net_return_pct)}>{pct(window.daily_avg_net_return_pct, true)}</strong></span>
                  <span className="q-strategy-metric"><small>CVaR10</small><strong className={metricTone(window.cvar10_net_return_pct)}>{pct(window.cvar10_net_return_pct, true)}</strong></span>
                  <span className="q-strategy-metric"><small>成熟日 / 样本</small><strong>{window.signal_days} / {window.sample_count}</strong></span>
                  <span className="q-strategy-metric"><small>今日命中</small><strong>{row.today_hit_count == null ? "待齐" : row.today_hit_count}</strong></span>
                  <span className={isExpanded ? "q-strategy-expand is-open" : "q-strategy-expand"}>
                    <Icon icon="chevronDown" size="xsm" color="secondary" label={isExpanded ? "收起证据" : "展开证据"} />
                  </span>
                </button>

                {isExpanded && (
                  <div className="q-strategy-evidence" id={`strategy-evidence-${row.strategy}`}>
                    <div className="q-review-window-grid">
                      {holdWindows.map((label) => (
                        <WindowEvidence key={label} label={label} data={row.windows[label]} primary={label === primary} />
                      ))}
                    </div>
                    <div className="q-review-method">
                      <div>
                        <strong>样本门槛</strong>
                        <p>
                          需要 {row.eligibility.required_signal_days} 个成熟信号日、{row.eligibility.required_sample_count} 条成熟记录。
                          当前还差 {row.eligibility.missing_signal_days} 日、{row.eligibility.missing_sample_count} 条。
                        </p>
                      </div>
                      <div><strong>固定评分公式</strong><p>{report.score_formula}</p></div>
                      <div><strong>执行与统计口径</strong><p>{report.methodology}</p></div>
                    </div>
                  </div>
                )}
              </article>
            );
          })}
          {!strategies.length && (
            <div className="q-review-filter-empty">当前筛选条件下没有策略。</div>
          )}
        </div>
      </section>

      <footer className="q-review-footnote">
        <Icon icon="info" size="xsm" color="secondary" />
        <p>这份榜单只进入影子反馈。当前大部分结果使用日线收盘价和次日开盘的近似成交口径，不是 PIT 实盘验证；正式动作仍只读取 canonical decision ledger。</p>
      </footer>
    </main>
  );
}
