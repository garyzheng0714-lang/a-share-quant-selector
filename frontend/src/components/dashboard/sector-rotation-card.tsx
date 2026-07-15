import { Flame, Rocket } from "lucide-react";
import { useSectors } from "@/lib/hooks";
import { Skeleton, StrengthBar, DeltaArrow, SectionLabel } from "@/components/ui";
import type { SectorHot, SectorRelay } from "@/lib/api";

/** 最热行：名称 + 强度条 + 分数 + 趋势箭头 */
function HotRow({ item }: { item: SectorHot }) {
  return (
    <div className="flex items-center gap-2.5 py-1.5">
      <div className="w-24 sm:w-28 shrink-0 flex items-center gap-1.5 min-w-0">
        <span className="text-[13px] text-ink truncate">{item.name}</span>
      </div>
      <StrengthBar value={item.score} className="flex-1 min-w-0" height={6} />
      <span className="text-[13px] font-semibold num text-ink w-7 text-right shrink-0">
        {Math.round(item.score)}
      </span>
      <span className="w-10 shrink-0 flex justify-end">
        <DeltaArrow trend={item.trend} value={item.delta3} />
      </span>
    </div>
  );
}

/** 接力行：名称 + 潜力分 + 理由 */
function RelayRow({ item }: { item: SectorRelay }) {
  return (
    <div className="py-1.5 min-w-0">
      <div className="flex items-center gap-2">
        <span className="text-[13px] text-ink truncate">{item.name}</span>
        <StrengthBar
          value={item.score}
          className="flex-1 min-w-0"
          height={6}
          color="var(--color-accent)"
        />
        <span className="text-[13px] font-semibold num text-accent-light w-7 text-right shrink-0">
          {Math.round(item.score)}
        </span>
      </div>
      <p className="text-[11px] text-ink-muted truncate mt-1 pl-0.5">
        {item.reasons.join(" · ")}
      </p>
    </div>
  );
}

/** 板块风向：现在哪个板块热、下一个可能是谁（趁大势） */
export function SectorRotationCard() {
  const { data, isLoading } = useSectors();

  if (isLoading) {
    return <Skeleton className="h-40 w-full rounded-3xl" />;
  }
  if (!data) return null;

  // 全量展示：原来截前 5 是因为它挤在主页的窄侧栏里；2026-07-14 搬到复盘页后
  // 地方够了，8 个热门 + 8 个接力全给出来
  const hot = data.hot ?? [];
  const relay = data.relay ?? [];

  return (
    <div className="card-modern px-4 py-4" data-testid="sectors">
      <div className="flex items-baseline gap-2 mb-3">
        <h2 className="text-sm font-semibold text-ink">板块风向</h2>
        {data.trade_date && (
          <span className="text-[11px] text-ink-muted num">
            {data.trade_date} 收盘
          </span>
        )}
      </div>

      {!data.available || hot.length === 0 ? (
        <p className="text-xs text-ink-muted leading-relaxed">
          {data.reason ?? "板块热度将在每个交易日 16:00 数据更新后自动计算。"}
        </p>
      ) : (
        <div>
          <div className="min-w-0">
            <SectionLabel
              icon={<Flame size={12} className="text-bull" />}
              className="mb-1.5"
            >
              当前最热
            </SectionLabel>
            {hot.map((h) => (
              <HotRow key={h.name} item={h} />
            ))}
          </div>
          <div className="mt-4 min-w-0">
            <SectionLabel
              icon={<Rocket size={12} className="text-accent" />}
              className="mb-1.5"
            >
              接力观察
            </SectionLabel>
            {relay.length === 0 ? (
              <p className="text-[11px] text-ink-muted leading-relaxed py-1.5">
                暂无满足条件的板块（要求热度 45~70 且加速度领先——不能太冷，也不能已在高潮）
              </p>
            ) : (
              relay.map((r) => <RelayRow key={r.name} item={r} />)
            )}
          </div>
        </div>
      )}
    </div>
  );
}
