type BadgeVariant = "bowl" | "duokong" | "short" | "active" | "inactive";

const variantStyles: Record<BadgeVariant, string> = {
  bowl: "bg-bull-dim text-bull",
  duokong: "bg-accent-dim text-accent",
  short: "bg-bear-dim text-bear",
  active: "bg-bear-dim text-bear",
  inactive: "bg-inset text-ink-muted",
};

interface BadgeProps {
  variant: BadgeVariant;
  children: React.ReactNode;
  className?: string;
}

export function Badge({ variant, children, className = "" }: BadgeProps) {
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium ${variantStyles[variant]} ${className}`}>
      {children}
    </span>
  );
}
