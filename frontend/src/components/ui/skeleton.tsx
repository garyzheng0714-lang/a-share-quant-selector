import { Skeleton as AstryxSkeleton } from "@astryxdesign/core/Skeleton";

interface SkeletonProps {
  className?: string;
  width?: number | string;
  height?: number | string;
  radius?: React.ComponentProps<typeof AstryxSkeleton>["radius"];
  index?: number;
}

/** Compatibility adapter. Loading placeholders use Astryx Skeleton tokens. */
export function Skeleton({ className, width = "100%", height = "100%", radius = 3, index = 0 }: SkeletonProps) {
  return <AstryxSkeleton className={className} width={width} height={height} radius={radius} index={index} />;
}
