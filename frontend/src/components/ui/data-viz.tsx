/**
 * 数据可视化原子库 —— 现代金融 App 风的视觉词汇。
 * 让数字「被看见」：强度条、环形度量、信心分段、趋势箭头。
 */
import { TrendingUp, TrendingDown, Minus } from "lucide-react";

/** 按 0-100 的值给一个语义色：低=冷灰，中=琥珀，高=热红（热=涨=红，A股语义） */
export function toneForScore(value: number): string {
  if (value >= 75) return "var(--color-bull)";
  if (value >= 50) return "var(--color-accent)";
  if (value >= 30) return "var(--color-ink-secondary)";
  return "var(--color-ink-muted)";
}

/**
 * 水平强度条：把一个 0-100 的分数变成一根有颜色的条。
 * 现代金融 App 里「热度/强度」的标准表达，比裸数字直观。
 */
export function StrengthBar({
  value,
  max = 100,
  color,
  className = "",
  height = 6,
}: {
  value: number;
  max?: number;
  color?: string;
  className?: string;
  height?: number;
}) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  const fill = color ?? toneForScore((value / max) * 100);
  return (
    <div
      className={`rounded-full bg-inset overflow-hidden ${className}`}
      style={{ height }}
    >
      <div
        className="h-full rounded-full transition-[width] duration-500"
        style={{ width: `${pct}%`, background: fill }}
      />
    </div>
  );
}

/**
 * 环形度量：SVG 圆环进度，中心可放一个大数字。
 * 用于信心/胜率这类「占比感」的指标——一眼看出满不满。
 */
export function Gauge({
  value,
  max = 100,
  size = 52,
  stroke = 5,
  color,
  children,
}: {
  value: number;
  max?: number;
  size?: number;
  stroke?: number;
  color?: string;
  children?: React.ReactNode;
}) {
  const pct = Math.max(0, Math.min(1, value / max));
  const r = (size - stroke) / 2;
  const circ = 2 * Math.PI * r;
  const dash = circ * pct;
  const fill = color ?? toneForScore(pct * 100);
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="var(--color-inset)"
          strokeWidth={stroke}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={fill}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${dash} ${circ - dash}`}
          className="transition-[stroke-dasharray] duration-700"
        />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center">
        {children}
      </div>
    </div>
  );
}

const CONFIDENCE_LEVEL: Record<string, number> = { high: 3, medium: 2, low: 1 };
const CONFIDENCE_LABEL: Record<string, string> = {
  high: "信心足",
  medium: "信心中",
  low: "信心低",
};

/** 信心分段：三格填充，比文字标签更快读懂强弱 */
export function ConfidenceMeter({
  level,
  showLabel = true,
}: {
  level: string;
  showLabel?: boolean;
}) {
  const n = CONFIDENCE_LEVEL[level] ?? 2;
  const color = n >= 3 ? "bg-bull" : n >= 2 ? "bg-accent" : "bg-ink-muted";
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="inline-flex items-end gap-0.5" style={{ height: 12 }}>
        {[1, 2, 3].map((i) => (
          <span
            key={i}
            className={`w-1 rounded-sm ${i <= n ? color : "bg-inset"}`}
            style={{ height: 4 + i * 3 }}
          />
        ))}
      </span>
      {showLabel && (
        <span className="text-[11px] text-ink-muted">
          {CONFIDENCE_LABEL[level] ?? level}
        </span>
      )}
    </span>
  );
}

/** 趋势箭头：升温↗（红/涨）· 退潮↘（绿/跌）· 平→（灰），A股语义 */
export function DeltaArrow({
  trend,
  value,
  size = 13,
}: {
  trend: "up" | "down" | "flat";
  value?: number;
  size?: number;
}) {
  const map = {
    up: { Icon: TrendingUp, cls: "text-bull" },
    down: { Icon: TrendingDown, cls: "text-bear" },
    flat: { Icon: Minus, cls: "text-ink-muted" },
  } as const;
  const { Icon, cls } = map[trend];
  return (
    <span className={`inline-flex items-center gap-0.5 tabular-nums ${cls}`}>
      <Icon size={size} strokeWidth={2} />
      {value !== undefined && (
        <span className="text-xs font-medium">
          {value > 0 ? "+" : ""}
          {Math.round(value)}
        </span>
      )}
    </span>
  );
}

/** section 小标签：统一的段落标题排版（小字号、字重、字距） */
export function SectionLabel({
  children,
  icon,
  className = "",
}: {
  children: React.ReactNode;
  icon?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`flex items-center gap-1.5 text-[11px] font-semibold text-ink-muted tracking-[0.08em] ${className}`}
    >
      {icon}
      <span>{children}</span>
    </div>
  );
}
