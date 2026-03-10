import { motion } from "framer-motion";

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
      className={`h-1.5 rounded-full overflow-hidden ${className}`}
      style={{ background: "rgba(255,255,255,0.06)" }}
    >
      <motion.div
        className={`h-full rounded-full ${barColor}`}
        initial={{ width: 0 }}
        animate={{ width: `${pct}%` }}
        transition={{ duration: 0.5, ease: [0.25, 0.1, 0.25, 1] }}
      />
    </div>
  );
}
