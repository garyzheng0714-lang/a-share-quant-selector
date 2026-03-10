import { useMotionValue, animate } from "framer-motion";
import { useEffect, useRef } from "react";
import { duration, ease } from "@/lib/tokens";

interface AnimatedNumberProps {
  value: number;
  format?: (n: number) => string;
  className?: string;
}

export function AnimatedNumber({ value, format = (n) => Math.round(n).toString(), className = "" }: AnimatedNumberProps) {
  const motionVal = useMotionValue(0);
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const controls = animate(motionVal, value, {
      duration: duration.count,
      ease: ease.default as unknown as number[],
      onUpdate: (v) => {
        if (ref.current) ref.current.textContent = format(v);
      },
    });
    return controls.stop;
  }, [value, motionVal, format]);

  return <span ref={ref} className={className} />;
}
