export const ease = {
  default: [0.25, 0.1, 0.25, 1],
  spring: { type: "spring" as const, damping: 25, stiffness: 300 },
  springGentle: { type: "spring" as const, damping: 30, stiffness: 200 },
} as const;

export const duration = {
  fast: 0.15,
  normal: 0.3,
  slow: 0.4,
  count: 0.8,
} as const;

export const chartColors = {
  bull: "#ef4444",
  bear: "#22c55e",
  axisText: "#8b95a8",
  gridLine: "rgba(255,255,255,0.05)",
  tooltipBg: "rgba(14,17,24,0.85)",
  priceLine: "rgba(228,168,83,0.6)",
  trend: "#ffffff",
  dk: "#facc15",
  kdjK: "#3b82f6",
  kdjD: "#f59e0b",
  kdjJ: "#ef4444",
  ma5: "#f59e0b",
  ma10: "#3b82f6",
  ma20: "#a855f7",
  ma60: "#22c55e",
  datazoomFill: "rgba(245,158,11,0.08)",
  datazoomHandle: "#f59e0b",
} as const;

export const CATEGORY_LABELS: Record<string, string> = {
  bowl_center: "回落碗中",
  near_duokong: "靠近多空线",
  near_short_trend: "靠近趋势线",
};

export const CATEGORY_BADGE_VARIANT: Record<string, "bowl" | "duokong" | "short"> = {
  bowl_center: "bowl",
  near_duokong: "duokong",
  near_short_trend: "short",
};
