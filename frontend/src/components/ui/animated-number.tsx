import { Text } from "@astryxdesign/core/Text";

interface AnimatedNumberProps {
  value: number;
  format?: (n: number) => string;
  className?: string;
}

/** Data display remains deterministic; motion is intentionally delegated to the design system. */
export function AnimatedNumber({ value, format = (n) => Math.round(n).toString(), className }: AnimatedNumberProps) {
  return <Text type="large" className={className} hasTabularNumbers>{format(value)}</Text>;
}
