import { NavLink, useLocation } from "react-router-dom";
import { motion } from "framer-motion";
import { Compass, History } from "lucide-react";

/** 两个 tab = 用户的两个问题：今天怎么办 / 过去准不准 */
const navItems = [
  { to: "/", label: "今日", end: true, Icon: Compass },
  { to: "/review", label: "复盘", end: false, Icon: History },
];

export function BottomNav() {
  const location = useLocation();

  const activeIndex = navItems.findIndex((item) =>
    item.end
      ? location.pathname === item.to
      : location.pathname.startsWith(item.to),
  );

  return (
    <nav className="fixed bottom-0 left-0 right-0 z-50 sm:hidden glass border-t border-border pb-[env(safe-area-inset-bottom)]">
      <div className="grid grid-cols-2 h-14">
        {navItems.map((item, i) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className="relative flex flex-col items-center justify-center gap-0.5"
          >
            <item.Icon
              size={20}
              strokeWidth={1.75}
              className={`transition-colors duration-150 ${
                i === activeIndex ? "text-accent" : "text-ink-muted"
              }`}
            />
            <span
              className={`text-[10px] transition-colors duration-150 ${
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
                className="absolute top-0 left-1/2 -translate-x-1/2 w-8 h-0.5 rounded-full bg-accent"
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
