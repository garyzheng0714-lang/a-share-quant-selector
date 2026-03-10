export const ease = {
  default: [0.25, 0.1, 0.25, 1],
  spring: { type: "spring" as const, damping: 25, stiffness: 300 },
  springGentle: { type: "spring" as const, damping: 30, stiffness: 200 },
} as const;

export const duration = {
  fast: 0.15,
  normal: 0.3,
  slow: 0.4,
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
