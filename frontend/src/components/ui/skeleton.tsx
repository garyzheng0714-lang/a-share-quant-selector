export function Skeleton({ className = "" }: { className?: string }) {
  return (
    <div
      className={`rounded-lg shimmer bg-surface ${className}`}
      aria-hidden="true"
    />
  );
}
