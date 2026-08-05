import { ProgressBar as AstryxProgressBar } from "@astryxdesign/core/ProgressBar";

interface ProgressBarProps {
  value: number;
  max?: number;
  className?: string;
  colorByValue?: boolean;
}

export function ProgressBar({ value, max = 100, className, colorByValue = false }: ProgressBarProps) {
  const percentage = max > 0 ? (value / max) * 100 : 0;
  const variant = colorByValue ? (percentage >= 85 ? "success" : percentage < 60 ? "neutral" : "accent") : "accent";
  return (
    <AstryxProgressBar
      className={className}
      value={value}
      max={max}
      variant={variant}
      label="进度"
      isLabelHidden
    />
  );
}
