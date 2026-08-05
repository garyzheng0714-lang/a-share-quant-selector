import { Icon } from "@astryxdesign/core/Icon";
import { ProgressBar } from "@astryxdesign/core/ProgressBar";
import { Text } from "@astryxdesign/core/Text";

function toneForScore(value: number): "success" | "accent" | "neutral" | "warning" {
  if (value >= 75) return "success";
  if (value >= 50) return "accent";
  if (value >= 30) return "warning";
  return "neutral";
}

/** Domain visualization composed from Astryx progress and text primitives. */
export function StrengthBar({
  value,
  max = 100,
  className = "",
}: {
  value: number;
  max?: number;
  color?: string;
  className?: string;
  height?: number;
}) {
  return (
    <ProgressBar
      className={className}
      value={value}
      max={max}
      variant={toneForScore((value / max) * 100)}
      label="强度"
      isLabelHidden
    />
  );
}

/** SVG is retained only for the domain-specific circular metric; text and tokens remain Astryx-owned. */
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
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const dash = circumference * pct;
  const fill = color ?? `var(--color-${toneForScore(pct * 100)})`;
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }} aria-label={`完成度 ${Math.round(pct * 100)}%`}>
      <svg width={size} height={size} className="-rotate-90" aria-hidden="true">
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="var(--color-border)" strokeWidth={stroke} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={fill}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${dash} ${circumference - dash}`}
        />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center">{children}</div>
    </div>
  );
}

const confidenceLevel: Record<string, number> = { high: 3, medium: 2, low: 1 };
const confidenceLabel: Record<string, string> = { high: "信心足", medium: "信心中", low: "信心低" };

export function ConfidenceMeter({ level, showLabel = true }: { level: string; showLabel?: boolean }) {
  const count = confidenceLevel[level] ?? 2;
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="inline-flex items-end gap-0.5" aria-hidden="true" style={{ height: 12 }}>
        {[1, 2, 3].map((index) => (
          <span key={index} className={`w-1 rounded-sm ${index <= count ? "bg-accent" : "bg-border"}`} style={{ height: 4 + index * 3 }} />
        ))}
      </span>
      {showLabel && <Text type="supporting">{confidenceLabel[level] ?? level}</Text>}
    </span>
  );
}

export function DeltaArrow({ trend, value }: { trend: "up" | "down" | "flat"; value?: number; size?: number }) {
  const icon = trend === "up" ? "arrowUp" : trend === "down" ? "arrowDown" : "arrowsUpDown";
  const color = trend === "up" ? "error" : trend === "down" ? "success" : "secondary";
  return (
    <span className="inline-flex items-center gap-0.5 tabular-nums">
      <Icon icon={icon} size="xsm" color={color} />
      {value !== undefined && <Text type="supporting">{value > 0 ? "+" : ""}{Math.round(value)}</Text>}
    </span>
  );
}

export function SectionLabel({ children, icon, className = "" }: { children: React.ReactNode; icon?: React.ReactNode; className?: string }) {
  return (
    <div className={`flex items-center gap-1.5 ${className}`}>
      {icon}
      <Text type="label">{children}</Text>
    </div>
  );
}
