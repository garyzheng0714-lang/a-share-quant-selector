export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`bg-inset rounded-lg shimmer ${className}`} aria-hidden="true" />;
}
