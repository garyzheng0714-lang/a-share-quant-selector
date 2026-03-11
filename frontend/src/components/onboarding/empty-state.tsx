import { type ReactNode } from "react";
import { motion } from "framer-motion";
import { Button } from "@/components/ui";
import { duration, ease } from "@/lib/tokens";

interface EmptyStateProps {
  icon: ReactNode;
  title: string;
  description: string;
  ctaLabel?: string;
  onCta?: () => void;
}

export function EmptyState({
  icon,
  title,
  description,
  ctaLabel,
  onCta,
}: EmptyStateProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: duration.normal, ease: ease.default }}
      className="flex flex-col items-center py-12 sm:py-16 px-4"
    >
      <div className="bg-elevated w-14 h-14 rounded-2xl flex items-center justify-center mb-5 text-ink-muted">
        {icon}
      </div>
      <h3 className="text-sm font-semibold text-ink mb-1.5">{title}</h3>
      <p className="text-xs text-ink-muted text-center max-w-xs mb-5">
        {description}
      </p>
      {ctaLabel && onCta && (
        <Button size="sm" onClick={onCta}>
          {ctaLabel}
        </Button>
      )}
    </motion.div>
  );
}
