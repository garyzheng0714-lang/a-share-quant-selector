import { RefreshCw } from "lucide-react";

/**
 * 数据加载失败态：对交易决策系统，接口挂了必须明说，
 * 绝不能伪装成"暂无数据"的空态误导用户（诚实优先）。
 */
export function LoadError({
  label = "数据加载失败",
  onRetry,
}: {
  label?: string;
  onRetry?: () => void;
}) {
  return (
    <div className="flex items-center justify-center gap-2 py-6 text-xs text-bull/90">
      <span>{label}</span>
      {onRetry && (
        <button
          onClick={onRetry}
          className="inline-flex items-center gap-1 px-2 py-1 rounded-lg bg-inset text-ink-secondary hover:text-ink transition-colors"
        >
          <RefreshCw size={11} />
          重试
        </button>
      )}
    </div>
  );
}
