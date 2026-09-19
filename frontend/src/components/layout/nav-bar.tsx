import { TopNav, TopNavHeading } from "@astryxdesign/core/TopNav";
import { Icon } from "@astryxdesign/core/Icon";
import { StatusDot } from "@astryxdesign/core/StatusDot";
import { Text } from "@astryxdesign/core/Text";
import { useStats } from "@/lib/hooks";

export function NavBar() {
  const stats = useStats();
  const scanDate = stats.data?.scan_date;
  const label = stats.error
    ? "数据状态读取失败"
    : scanDate
      ? `选股结果 · ${scanDate}`
      : stats.data
        ? "还没有扫描结果"
        : "正在读取数据";

  return (
    <TopNav
      className="app-top-nav bg-surface"
      label="主导航"
      heading={<TopNavHeading heading="QSelect 选股" headingHref="/select" logo={<Icon icon="funnel" size="sm" />} />}
      endContent={
        <div className="flex items-center gap-2" role="status" aria-live="polite" title={label}>
          <StatusDot variant={stats.error ? "error" : scanDate ? "success" : "neutral"} label={label} />
          <Text type="supporting" className="hidden md:inline">{label}</Text>
        </div>
      }
    />
  );
}
