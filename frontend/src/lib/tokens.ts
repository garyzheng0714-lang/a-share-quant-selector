export const ease = {
  default: [0.25, 0.1, 0.25, 1],
  spring: { type: "spring" as const, damping: 25, stiffness: 300 },
  springGentle: { type: "spring" as const, damping: 30, stiffness: 200 },
} as const;

export const duration = {
  fast: 0.15,
  normal: 0.2,
  slow: 0.3,
  count: 0.8,
} as const;

export const typography = {
  heading: { letterSpacing: "-0.03em", fontWeight: 700 },
  subheading: { letterSpacing: "-0.02em", fontWeight: 600 },
  body: { letterSpacing: "-0.02em", fontWeight: 400 },
} as const;

export const stagger = {
  fast: 0.03,
  normal: 0.05,
  list: 0.04,
} as const;

export const chartColors = {
  bull: "#ef4444",
  bear: "#22c55e",
  axisText: "#c1bec6",
  gridLine: "rgba(255,255,255,0.05)",
  tooltipBg: "rgba(10,8,18,0.9)",
  priceLine: "rgba(144,70,255,0.6)",
  trend: "#ffffff",
  dk: "#c6a0ff",
  kdjK: "#3b82f6",
  kdjD: "#f59e0b",
  kdjJ: "#ef4444",
  ma5: "#f59e0b",
  ma10: "#3b82f6",
  ma20: "#a855f7",
  ma60: "#22c55e",
  datazoomFill: "rgba(144,70,255,0.08)",
  datazoomHandle: "#9046FF",
  markLineBg: "rgba(10,8,18,0.9)",
  datazoomBg: "rgba(255,255,255,0.03)",
  dataBackgroundLine: "rgba(148,163,184,0.15)",
  dataBackgroundArea: "rgba(148,163,184,0.05)",
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
