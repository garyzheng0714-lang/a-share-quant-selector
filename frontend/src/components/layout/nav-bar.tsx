import { useLocation } from "react-router";
import { TopNav, TopNavHeading, TopNavItem } from "@astryxdesign/core/TopNav";
import { StatusDot } from "@astryxdesign/core/StatusDot";
import { usePipelineStatus } from "@/lib/hooks";

const navItems = [
  { to: "/stocks", label: "决策台" },
  { to: "/review", label: "复盘" },
  { to: "/admin", label: "后台" },
];

export function NavBar() {
  const location = useLocation();
  const pipeline = usePipelineStatus();
  const fresh = pipeline.data?.market.fresh === true;
  const failed = Boolean(pipeline.error) || pipeline.data?.state === "unavailable";
  const date = pipeline.data?.market.local_date;
  const snapshot = pipeline.data?.market.snapshot_id;
  const statusLabel = failed ? "数据不可用" : fresh ? "数据就绪" : pipeline.isLoading ? "正在检查数据" : "数据需复核";

  return (
    <TopNav
      className="q-top-nav"
      label="主导航"
      heading={
        <TopNavHeading
          heading="QSelect 决策台"
          headingHref="/stocks"
          logo={<img src="/favicon.svg" alt="QSelect" className="q-nav-logo" />}
        />
      }
      startContent={
        <div className="q-nav-tabs">
          {navItems.map((item) => (
            <TopNavItem key={item.to} href={item.to} label={item.label} isSelected={location.pathname === item.to} />
          ))}
        </div>
      }
      endContent={
        <div className="q-nav-status" role="status" aria-live="polite">
          <span><StatusDot variant={failed ? "error" : fresh ? "success" : "warning"} label={statusLabel} /><b className="q-nav-status-label">{statusLabel}</b></span>
          {date && <time>{date} 收盘</time>}
          {snapshot && <><i /><span className="q-nav-snapshot">快照 <code title={snapshot}>{snapshot.slice(0, 8)}…</code></span></>}
        </div>
      }
    />
  );
}
