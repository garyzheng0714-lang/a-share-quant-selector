import { useLocation } from "@/lib/spa-router";
import { TopNav, TopNavHeading, TopNavItem } from "@astryxdesign/core/TopNav";
import { Badge } from "@astryxdesign/core/Badge";
import { Icon } from "@astryxdesign/core/Icon";
import { StatusDot } from "@astryxdesign/core/StatusDot";
import { Text } from "@astryxdesign/core/Text";
import { useSystemStatus } from "@/lib/hooks";

const navItems = [
  { to: "/sectors", label: "市场环境", matches: ["/sectors"] },
  { to: "/stocks", label: "策略工作台", matches: ["/stocks", "/stock/"] },
  { to: "/review", label: "复盘", matches: ["/review"] },
];

export function NavBar() {
  const location = useLocation();
  const status = useSystemStatus();
  const fresh = status.data?.market_data?.fresh;
  const localDate = status.data?.market_data?.local_date;
  const expectedDate = status.data?.market_data?.expected_date;
  const statusLabel = status.error
    ? "数据状态读取失败"
    : fresh === true
      ? `数据就绪${localDate ? ` · ${localDate}` : ""}`
      : fresh === false
        ? `数据过期${localDate ? ` · 截至 ${localDate}` : ""}${expectedDate ? ` · 应更新至 ${expectedDate}` : ""}`
        : "正在检查数据";

  return (
    <TopNav
      className="app-top-nav bg-surface"
      label="主导航"
      heading={
        <TopNavHeading
          heading="QSelect 研究台"
          headingHref="/sectors"
          logo={<Icon icon="viewColumns" size="sm" />}
        />
      }
      startContent={
        <div className="hidden sm:flex">
          {navItems.map((item) => (
            <TopNavItem
              key={item.to}
              href={item.to}
              label={item.label}
              isSelected={item.matches.some((path) => location.pathname.startsWith(path))}
            />
          ))}
        </div>
      }
      endContent={
        <div className="flex items-center gap-2" role="status" aria-live="polite" title={statusLabel}>
          <StatusDot variant={fresh === true ? "success" : fresh === false || status.error ? "error" : "neutral"} label={statusLabel} />
          <Text type="supporting" className="hidden md:inline">{statusLabel}</Text>
          <span className="md:hidden">
            <Badge
              variant={fresh === true ? "success" : fresh === false || status.error ? "error" : "neutral"}
              label={fresh === true ? "就绪" : fresh === false ? "过期" : status.error ? "失败" : "检查中"}
            />
          </span>
        </div>
      }
    />
  );
}
