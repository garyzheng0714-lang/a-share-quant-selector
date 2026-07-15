import { useThermometer } from "@/lib/hooks";
import { Skeleton } from "@/components/ui";

/** 信号 → 主色（红=谨慎，金=机会，灰=中性，绿=正常放行） */
const SIGNAL_COLOR: Record<string, string> = {
  caution: "bg-bull",
  opportunity: "bg-accent",
  neutral: "bg-ink-muted",
  normal: "bg-bear",
};

/**
 * 市场状态条：回答「今天该不该出手」——一句话，仅此而已。
 *
 * 原来这里还挂着 4 个指标（成交热度分位/大盘20日/趋势/策略胜率），
 * 2026-07-14 砍掉：结论句里已经写着"最近941个信号胜率仅34.3%"，
 * 下面再摆一遍 34.3% 是同一件事说两次。用户不看分位数做买卖决定。
 */
export function ThermometerBanner() {
  const { data, isLoading } = useThermometer();

  if (isLoading) {
    return <Skeleton className="h-10 w-full rounded-xl mb-5" />;
  }
  if (!data?.available || !data.heat) {
    return null;
  }

  const { signal = "normal", conclusion } = data;
  const dot = SIGNAL_COLOR[signal] ?? SIGNAL_COLOR.normal;

  return (
    <div className="mb-5" data-testid="thermometer">
      <div className="border-t border-border pt-3 flex items-start gap-2.5">
        <span
          className={`w-2 h-2 rounded-full mt-1.5 shrink-0 ${dot} ${
            signal === "caution" ? "animate-pulse" : ""
          }`}
        />
        <p className="text-[13px] text-ink leading-relaxed flex-1 min-w-0">
          {conclusion}
        </p>
      </div>
    </div>
  );
}
