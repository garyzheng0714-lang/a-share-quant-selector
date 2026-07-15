import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { Zap } from "lucide-react";
import { Skeleton, Gauge, LoadError } from "@/components/ui";
import { EmptyState } from "@/components/onboarding";
import { useSuperB1Performance } from "@/lib/hooks";
import { duration } from "@/lib/tokens";
import type { PerfAgg, SuperB1PerfRecord, WindowAgg } from "@/lib/api";

type RetKey = "ret_1" | "ret_5" | "ret_10" | "ret_20";

const WINDOWS: { key: RetKey; label: string }[] = [
  { key: "ret_1", label: "T+1" },
  { key: "ret_5", label: "T+5" },
  { key: "ret_10", label: "T+10" },
  { key: "ret_20", label: "T+20" },
];

function retColor(v: number | null): string {
  if (v === null || v === undefined) return "text-ink-muted";
  return v > 0 ? "text-bull" : v < 0 ? "text-bear" : "text-ink-muted";
}

function fmtRet(v: number | null): string {
  if (v === null || v === undefined) return "—";
  return `${v > 0 ? "+" : ""}${v.toFixed(1)}%`;
}

function StatCard({ label, agg }: { label: string; agg: WindowAgg }) {
  const hasData = agg.count > 0;
  const win = agg.win_rate ?? 0;
  return (
    <div className="card-modern px-3.5 py-3 min-w-0">
      <div className="text-xs text-ink-muted mb-2">持有{label}</div>
      {hasData ? (
        <div className="flex items-center gap-2.5">
          <Gauge
            value={win}
            size={44}
            stroke={4}
            color={win >= 50 ? "var(--color-bull)" : "var(--color-ink-muted)"}
          >
            <span className="text-[13px] font-bold num text-ink">{win}</span>
          </Gauge>
          <div className="min-w-0">
            <div className="text-[10px] text-ink-muted">胜率</div>
            <div className={`text-[15px] font-semibold num ${retColor(agg.avg)}`}>
              {fmtRet(agg.avg)}
            </div>
            <div className="text-[10px] text-ink-muted num">{agg.count}笔</div>
          </div>
        </div>
      ) : (
        <div className="text-sm text-ink-muted mt-1">暂无数据</div>
      )}
    </div>
  );
}

function SignalGroupCard({ name, agg }: { name: string; agg: PerfAgg }) {
  return (
    <div className="card-modern px-4 py-3">
      <div className="text-sm font-medium text-ink mb-2">{name}</div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-1.5">
        {WINDOWS.map((w) => {
          const a = agg[w.key];
          return (
            <div key={w.key} className="flex items-baseline gap-1.5 tabular-nums min-w-0">
              <span className="text-[10px] text-ink-muted w-8 shrink-0">{w.label}</span>
              {a.count > 0 ? (
                <>
                  <span className="text-xs text-ink font-medium">{a.win_rate}%</span>
                  <span className={`text-xs ${retColor(a.avg)}`}>{fmtRet(a.avg)}</span>
                </>
              ) : (
                <span className="text-xs text-ink-muted">—</span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** 超级B1独立战绩：这套公式选出的票后续真实涨跌（与碗口策略战绩完全隔离） */
export function SuperB1PerformanceSection() {
  const { data, isLoading, error, mutate } = useSuperB1Performance();
  const navigate = useNavigate();

  if (isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-24 w-full rounded-2xl" />
        <Skeleton className="h-40 w-full rounded-2xl" />
      </div>
    );
  }
  if (error) {
    return <LoadError label="超级B1战绩加载失败" onRetry={() => mutate()} />;
  }
  if (!data || data.total_recorded === 0) {
    return (
      <EmptyState
        icon={<Zap size={24} strokeWidth={1.5} />}
        title="超级B1战绩还没开始积累"
        description="每个交易日收盘扫描后，命中的票会自动录入并追踪后续真实涨跌"
      />
    );
  }

  const records = data.records ?? [];

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: duration.normal }}
    >
      <p className="text-xs text-ink-muted mb-4 leading-relaxed">
        超级B1公式命中的票自动追踪后续真实涨跌（按信号次日开盘价买入模拟计算）·
        已录入 {data.total_recorded} 条，其中 {data.total_records} 条已有后续行情
      </p>

      {data.total_records === 0 ? (
        <div className="card-modern px-4 py-4 mb-4">
          <p className="text-[13px] text-ink-secondary leading-relaxed">
            信号已录入，等下一个交易日行情落地后开始逐日回填收益。
            首批统计需要至少 1 个交易日，完整的 T+20 结论需要约一个月。
          </p>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 sm:gap-2.5 mb-4">
            {WINDOWS.map((w) => (
              <StatCard key={w.key} label={w.label} agg={data.overall[w.key]} />
            ))}
          </div>

          {data.benchmark && (
            <div className="card-modern px-4 py-3 mb-6">
              <div className="text-[10px] text-ink-muted mb-1.5">
                对比同期上证指数（超额 = 超级B1均值 − 指数均值，指数以收盘价近似）
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-1.5">
                {WINDOWS.map((w) => {
                  const s = data.overall[w.key].avg;
                  const b = data.benchmark?.[w.key];
                  if (s === null || b === null || b === undefined) return null;
                  const excess = Math.round((s - b) * 100) / 100;
                  return (
                    <div
                      key={w.key}
                      className="flex items-baseline gap-1.5 tabular-nums min-w-0"
                    >
                      <span className="text-[10px] text-ink-muted w-8 shrink-0">
                        {w.label}
                      </span>
                      <span
                        className={`text-xs font-medium ${excess > 0 ? "text-bull" : excess < 0 ? "text-bear" : "text-ink-muted"}`}
                      >
                        超额 {excess > 0 ? "+" : ""}
                        {excess}%
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {Object.keys(data.by_signal).length > 0 && (
            <div className="mb-6">
              <h3 className="text-sm font-semibold text-ink mb-2">
                按信号类型（哪种B更靠谱）
              </h3>
              <div className="grid sm:grid-cols-2 gap-2">
                {Object.entries(data.by_signal).map(([name, agg]) => (
                  <SignalGroupCard key={name} name={name} agg={agg} />
                ))}
              </div>
            </div>
          )}
        </>
      )}

      <h3 className="text-sm font-semibold text-ink mb-2">明细</h3>
      <div className="divide-y divide-border/40">
        {records.map((r: SuperB1PerfRecord) => (
          <button
            key={r.id}
            onClick={() => navigate(`/stock/${r.code}`)}
            className="w-full px-3 sm:px-4 py-2.5 rounded-xl hover:bg-elevated active:bg-inset transition-colors duration-100 text-left"
          >
            <div className="flex items-center gap-2 min-w-0">
              <span className="text-sm font-medium text-ink truncate">
                {r.name || r.code}
              </span>
              <span className="font-mono text-xs text-ink-muted shrink-0">{r.code}</span>
              <span className="ml-auto flex items-center gap-1 shrink-0">
                {r.signals.map((s) => (
                  <span
                    key={s}
                    className="px-1.5 py-0.5 text-[10px] rounded bg-accent/10 text-accent whitespace-nowrap"
                  >
                    {s}
                  </span>
                ))}
              </span>
            </div>
            <div className="flex items-center gap-2 mt-1 tabular-nums">
              <span className="text-[11px] text-ink-muted w-[74px] shrink-0">
                {r.run_date}
              </span>
              {r.days_tracked > 0 ? (
                <div className="grid grid-cols-4 flex-1 gap-x-2">
                  {WINDOWS.map((w) => {
                    const v = r[w.key];
                    return (
                      <div
                        key={w.key}
                        className="flex items-baseline gap-0.5 justify-end min-w-0"
                      >
                        <span className="text-[10px] text-ink-muted shrink-0">
                          {w.label}
                        </span>
                        <span className={`text-[11px] font-medium ${retColor(v)}`}>
                          {fmtRet(v)}
                        </span>
                      </div>
                    );
                  })}
                </div>
              ) : r.status === "invalid" ? (
                <span className="text-[11px] text-ink-muted">
                  无法追踪（买入价异常）
                </span>
              ) : (
                <span className="text-[11px] text-ink-muted">等待行情回填</span>
              )}
            </div>
          </button>
        ))}
      </div>
    </motion.div>
  );
}
