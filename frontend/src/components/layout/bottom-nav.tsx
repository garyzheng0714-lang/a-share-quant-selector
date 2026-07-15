import { NavLink, useLocation } from "react-router-dom";
import { motion } from "framer-motion";
import { ChartNoAxesColumnIncreasing, ListOrdered } from "lucide-react";

/** 顶层只保留板块与个股；板块详情属于板块分区。 */
const navItems = [
  { to: "/sectors", label: "板块", end: false, matches: ["/sectors"], Icon: ChartNoAxesColumnIncreasing },
  { to: "/stocks", label: "个股", end: false, matches: ["/stocks", "/stock/"], Icon: ListOrdered },
];

export function BottomNav() {
  const location = useLocation();

  const activeIndex = navItems.findIndex((item) => item.matches.some((path) => location.pathname.startsWith(path)));

  return (
    <nav className="glass fixed inset-x-0 bottom-0 z-50 border-t pb-[env(safe-area-inset-bottom)] sm:hidden" aria-label="手机主导航">
      <div className="grid h-15 grid-cols-2">
        {navItems.map((item, i) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className="relative flex flex-col items-center justify-center gap-1 active:scale-[0.98]"
          >
            {i === activeIndex && (
              <motion.span
                layoutId="bottom-nav-surface"
                className="absolute inset-x-7 inset-y-2 rounded-[10px] bg-accent-dim"
                transition={{ type: "spring", damping: 26, stiffness: 320 }}
              />
            )}
            <item.Icon
              size={20}
              strokeWidth={1.8}
              className={`relative transition-colors duration-150 ${
                i === activeIndex ? "text-accent" : "text-ink-muted"
              }`}
            />
            <span
              className={`relative text-[10px] transition-colors duration-150 ${
                i === activeIndex
                  ? "text-accent font-medium"
                  : "text-ink-muted"
              }`}
            >
              {item.label}
            </span>
            {i === activeIndex && (
              <motion.div
                layoutId="bottom-nav-indicator"
                className="absolute top-0 left-1/2 h-px w-12 -translate-x-1/2 bg-accent"
                transition={{
                  type: "spring",
                  damping: 25,
                  stiffness: 300,
                }}
              />
            )}
          </NavLink>
        ))}
      </div>
    </nav>
  );
}
