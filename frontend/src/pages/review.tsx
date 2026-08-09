import { Badge } from "@astryxdesign/core/Badge";
import { Icon } from "@astryxdesign/core/Icon";
import { LoadError, Skeleton } from "@/components/ui";
import type { StrategyWindowAgg } from "@/lib/api";
import { useCloudStairReview } from "@/lib/hooks";

function signed(value?: number | null, digits = 1, suffix = "") {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}${suffix}`;
}

function gradeFor(row: StrategyWindowAgg) {
  if (row.count < 30) return { label: "样本不足", variant: "warning" as const };
  if ((row.avg || 0) > 0 && (row.win_rate || 0) >= 50) return { label: "正向", variant: "success" as const };
  return { label: "待验证", variant: "neutral" as const };
}

export function Component() {
  const review = useCloudStairReview(1000);

  if (review.isLoading) return <main className="q-review-page"><Skeleton className="q-review-skeleton" /></main>;
  if (review.error) return <main className="q-review-page"><LoadError label="云阶复盘加载失败" onRetry={() => review.mutate()} /></main>;

  const response = review.data;
  const windows = response?.summary?.windows || {};
  const rows = [1, 5, 10, 20].map((days) => ({
    days,
    data: windows[`ret_${days}`] || { count: 0, win_rate: null, avg: null },
  }));

  return (
    <main className="q-review-page">
      <header className="q-review-header">
        <h1>验证方法，不追逐结果</h1>
        <p>只复盘云阶真实历史命中，统一采用次日开盘入场口径；没有数据就明确显示，不补假结果。</p>
      </header>

      <section className="q-review-summary" aria-label="云阶复盘概览">
        <div><span>历史信号</span><strong>{response?.summary?.pick_count || 0}</strong></div>
        <div><span>覆盖日期</span><strong>{response?.date_span ? `${response.date_span.from} — ${response.date_span.to}` : "暂无"}</strong></div>
        <div><span>建议观察窗口</span><strong>{response?.summary?.recommended_hold?.label || "样本不足"}</strong></div>
      </section>

      <section className="q-review-table" aria-label="云阶各持有窗口表现">
        <div className="q-review-table-head">
          <span>方法 / 窗口</span><span>胜率</span><span>平均净收益</span><span>中位数</span><span>最好</span><span>最差</span><span>样本数</span><span>评级</span>
        </div>
        {rows.map(({ days, data }) => {
          const grade = gradeFor(data);
          return (
            <div className="q-review-table-row" key={days}>
              <span><strong>云阶 · T+{days}</strong><small>第一波大涨 → 缩量横盘 → 再次突破</small></span>
              <span>{data.win_rate == null ? "—" : `${data.win_rate.toFixed(1)}%`}</span>
              <span className={(data.avg || 0) >= 0 ? "q-up" : "q-down"}>{signed(data.avg, 2, "%")}</span>
              <span className={(data.median || 0) >= 0 ? "q-up" : "q-down"}>{signed(data.median, 2, "%")}</span>
              <span className="q-up">{signed(data.best, 2, "%")}</span>
              <span className="q-down">{signed(data.worst, 2, "%")}</span>
              <span>{data.count}</span>
              <span><Badge variant={grade.variant} label={grade.label} /></span>
            </div>
          );
        })}
      </section>

      {!response?.available && (
        <section className="q-review-empty">
          <Icon icon="info" size="sm" color="warning" label="复盘尚未就绪" />
          <div><strong>云阶复盘记录尚未形成</strong><p>{response?.reason || "等待历史命中与后续行情完成回读。"}</p></div>
        </section>
      )}

      <section className="q-review-note">
        <Icon icon="info" size="xsm" color="secondary" />
        <p>{response?.summary?.execution_note || "超额与收益必须来自真实历史回读。回测胜率不等于必买，只用于判断云阶方法是否稳定。"}</p>
      </section>
    </main>
  );
}
