import { motion } from "framer-motion";
import { duration, ease } from "@/lib/tokens";

interface ProgressBarProps {
  value: number;
  max?: number;
  className?: string;
  colorByValue?: boolean;
}

export function ProgressBar({
  value,
  max = 100,
  className = "",
  colorByValue = false,
}: ProgressBarProps) {
  const pct = Math.min(100, (value / max) * 100);
  let barColor = "bg-accent";
  if (colorByValue) {
    if (pct >= 85) barColor = "bg-bear";
    else if (pct < 60) barColor = "bg-ink-muted";
  }
  return (
    <div
      className={`h-1.5 rounded-full overflow-hidden bg-elevated ${className}`}
    >
      <motion.div
        className={`h-full rounded-full ${barColor}`}
        initial={{ width: 0 }}
        animate={{ width: `${pct}%` }}
        transition={{ duration: duration.slow, ease: ease.default as unknown as number[] }}
      />
    </div>
  );
}
