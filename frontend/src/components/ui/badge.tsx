import { Badge as AstryxBadge } from "@astryxdesign/core/Badge";

type LegacyBadgeVariant = "bowl" | "duokong" | "short" | "active" | "inactive";

export interface BadgeProps {
  variant: LegacyBadgeVariant;
  children: React.ReactNode;
  className?: string;
}

const variantMap: Record<LegacyBadgeVariant, React.ComponentProps<typeof AstryxBadge>["variant"]> = {
  bowl: "error",
  duokong: "blue",
  short: "warning",
  active: "success",
  inactive: "neutral",
};

/** Compatibility adapter. The visual root is Astryx Badge. */
export function Badge({ variant, children, className }: BadgeProps) {
  return <AstryxBadge variant={variantMap[variant]} label={children} className={className} />;
}
