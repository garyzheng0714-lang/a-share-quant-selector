import { useNavigate } from "react-router-dom";
import { Bot } from "lucide-react";
import { Skeleton, Gauge } from "@/components/ui";
import { EmptyState } from "@/components/onboarding";
import { useDailyPickHistory } from "@/lib/hooks";
import type { DailyPick } from "@/lib/api";

const WINDOWS = [
  { key: "ret_1", label: "T+1" },
  { key: "ret_5", label: "T+5" },
  { key: "ret_10", label: "T+10" },
  { key: "ret_20", label: "T+20" },
] as const;

function retColor(v: number | null): string {
  if (v === null || v === undefined) return "text-ink-muted";
  return v > 0 ? "text-bull" : v < 0 ? "text-bear" : "text-ink-muted";
}

function fmtRet(v: number | null): string {
  if (v === null || v === undefined) return "—";
  return `${v > 0 ? "+" : ""}${v.toFixed(1)}%`;
}

/**
 * 荐票记录行：两行式。
 * 第一行：日期 + 场次 + 票名 + 信心
 * 第二行：四窗口真实收益
 */
function PickRow({ pick, onClick }: { pick: DailyPick; onClick: () => void }) {
  const perf = pick.performance;
  return (
    <button
      onClick={onClick}
      className="w-full px-3 sm:px-4 py-2.5 rounded-xl hover:bg-elevated active:bg-inset transition-colors duration-100 text-left"
    >
      <div className="flex items-center gap-2 min-w-0">
        <span className="text-[11px] text-ink-muted tabular-nums shrink-0 w-[74px]">
          {pick.pick_date}
        </span>
        <span className="text-sm font-medium text-ink truncate">
          {pick.name || pick.code || "—"}
        </span>
        {pick.code && (
          <span className="font-mono text-xs text-ink-muted shrink-0">
            {pick.code}
          </span>
        )}
      </div>
      <div className="flex items-center gap-2 mt-1 tabular-nums">
        <span className="w-[74px] shrink-0" />
        {perf && perf.buy_price !== null ? (
          <div className="grid grid-cols-4 flex-1 gap-x-2">
            {WINDOWS.map((w) => {
              const v = perf[w.key];
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
        ) : (
          <span className="text-[11px] text-ink-muted">
            {pick.skipped ? "当日建议观望" : "等待行情回填"}
          </span>
        )}
      </div>
    </button>
  );
}

/** 旧版 AI 自主荐股只读档案；新策略不会继续写入。 */
export function PicksHistory() {
  const { data, isLoading } = useDailyPickHistory();
  const navigate = useNavigate();

  if (isLoading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 5 }, (_, i) => (
          <Skeleton key={i} className="h-14 w-full rounded-xl" />
        ))}
      </div>
    );
  }

  // 观望决策也是决策：skipped 记录保留在列表里（AI 说"今天别买"必须有迹可查），
  // 只是不参与胜率统计
  const picks = (data?.picks ?? []).filter((p) => p.code || p.skipped);
  if (picks.length === 0) {
    return (
      <EmptyState
        icon={<Bot size={24} strokeWidth={1.5} />}
        title="旧版 AI 档案为空"
        description="自主荐股已经停用，后续策略决策不会写入这里"
      />
    );
  }

  const judged = picks.filter(
    (p) => !p.skipped && p.performance && p.performance.ret_5 !== null,
  );
  const wins = judged.filter((p) => (p.performance!.ret_5 ?? 0) > 0);
  const avg =
    judged.length > 0
      ? judged.reduce((sum, p) => sum + (p.performance!.ret_5 ?? 0), 0) /
        judged.length
      : null;

  return (
    <div>
      {judged.length > 0 && (
        <div className="grid grid-cols-3 gap-2 mb-4">
          <div className="card-modern px-3.5 py-3 flex flex-col justify-center">
            <div className="text-xs text-ink-muted mb-1">历史推荐</div>
            <div>
              <span className="text-xl font-bold num text-ink">
                {picks.filter((p) => !p.skipped).length}
              </span>
              <span className="text-[10px] text-ink-muted ml-1">次</span>
            </div>
          </div>
          <div className="card-modern px-3.5 py-3 flex items-center gap-2">
            <Gauge
              value={Math.round((wins.length / judged.length) * 100)}
              size={42}
              stroke={4}
              color={
                wins.length / judged.length >= 0.5
                  ? "var(--color-bull)"
                  : "var(--color-ink-muted)"
              }
            >
              <span className="text-[12px] font-bold num text-ink">
                {Math.round((wins.length / judged.length) * 100)}
              </span>
            </Gauge>
            <div className="min-w-0">
              <div className="text-[10px] text-ink-muted leading-tight">
                T+5
                <br />
                胜率
              </div>
            </div>
          </div>
          <div className="card-modern px-3.5 py-3 flex flex-col justify-center">
            <div className="text-xs text-ink-muted mb-1">T+5 均收益</div>
            <span className={`text-xl font-bold num ${retColor(avg)}`}>
              {fmtRet(avg)}
            </span>
          </div>
        </div>
      )}

      <div className="divide-y divide-border/40">
        {picks.map((p) => (
          <PickRow
            key={`${p.pick_date}-${p.session ?? "close"}`}
            pick={p}
            onClick={() => p.code && navigate(`/stock/${p.code}`)}
          />
        ))}
      </div>
      <p className="text-[11px] text-ink-muted leading-relaxed mt-3">
        这里仅保留旧版 AI 自主荐股记录。该入口已停用，收益为历史模拟值。
      </p>
    </div>
  );
}
