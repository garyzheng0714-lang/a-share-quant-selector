export function Skeleton({ className = "" }: { className?: string }) {
  return (
    <div
      className={`rounded-lg shimmer ${className}`}
      style={{ background: "rgba(255,255,255,0.04)" }}
      aria-hidden="true"
    />
  );
}
