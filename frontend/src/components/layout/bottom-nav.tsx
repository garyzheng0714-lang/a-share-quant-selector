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
