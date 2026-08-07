import { NavLink, useLocation } from "@/lib/spa-router";
import { Icon } from "@astryxdesign/core/Icon";

/** 手机与桌面共用三段主任务：市场环境 → 策略工作台 → 研究复盘。 */
const navItems = [
  { to: "/sectors", label: "市场", end: false, matches: ["/sectors"], icon: "viewColumns" as const },
  { to: "/stocks", label: "策略", end: false, matches: ["/stocks", "/stock/"], icon: "funnel" as const },
  { to: "/review", label: "复盘", end: false, matches: ["/review"], icon: "calendar" as const },
];

export function BottomNav() {
  const location = useLocation();

  const activeIndex = navItems.findIndex((item) => item.matches.some((path) => location.pathname.startsWith(path)));

  return (
    <nav className="fixed inset-x-0 bottom-0 z-50 border-t border-border bg-surface pb-[env(safe-area-inset-bottom)] sm:hidden" aria-label="手机主导航">
      <div className="grid h-16 grid-cols-3">
        {navItems.map((item, i) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={`relative flex min-h-12 flex-col items-center justify-center gap-1 transition-colors active:bg-inset ${
              i === activeIndex ? "text-accent" : "text-ink-muted"
            }`}
          >
            <Icon icon={item.icon} size="md" color={i === activeIndex ? "accent" : "secondary"} />
            <span className={`relative text-[10px] ${i === activeIndex ? "font-semibold" : ""}`}>
              {item.label}
            </span>
            {i === activeIndex && <span className="absolute inset-x-7 top-0 h-px bg-accent" />}
          </NavLink>
        ))}
      </div>
    </nav>
  );
}
