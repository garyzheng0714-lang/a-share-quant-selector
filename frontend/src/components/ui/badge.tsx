type BadgeVariant = "bowl" | "duokong" | "short" | "active" | "inactive";

const variantStyles: Record<BadgeVariant, string> = {
  bowl: "bg-bull-dim text-bull border border-bull/20",
  duokong: "bg-accent-dim text-accent border border-accent/20",
  short: "bg-bear-dim text-bear border border-bear/20",
  active: "bg-bear-dim text-bear border border-bear/20",
  inactive: "bg-elevated text-ink-muted border border-border",
};

interface BadgeProps {
  variant: BadgeVariant;
  children: React.ReactNode;
  className?: string;
}

export function Badge({ variant, children, className = "" }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-lg text-xs font-medium ${variantStyles[variant]} ${className}`}
    >
      {children}
    </span>
  );
}
