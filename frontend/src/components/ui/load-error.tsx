import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";

/**
 * 数据加载失败态：错误必须留在上下文中，不伪装成空数据。
 * 视觉与交互由 Astryx Banner/Button 负责。
 */
export function LoadError({
  label = "数据加载失败",
  onRetry,
}: {
  label?: string;
  onRetry?: () => void;
}) {
  return (
    <Banner
      status="error"
      title={label}
      description="数据没有成功返回，可以重试；原有筛选条件会保留。"
      endContent={
        onRetry ? (
          <Button
            label="重试"
            variant="secondary"
            size="sm"
            onClick={onRetry}
          />
        ) : undefined
      }
    />
  );
}
