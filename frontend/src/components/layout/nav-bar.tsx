import { motion, useMotionValueEvent, useScroll } from "framer-motion";
import { NavLink, useLocation } from "react-router-dom";
import { useState, useRef } from "react";

const navItems = [
  { to: "/", label: "概览", end: true },
  { to: "/selection", label: "选股" },
  { to: "/stocks", label: "股票" },
  { to: "/history", label: "历史" },
  { to: "/ranking", label: "排名" },
];

export function NavBar() {
  const location = useLocation();
  const [hidden, setHidden] = useState(false);
  const { scrollY } = useScroll();
  const lastY = useRef(0);

  useMotionValueEvent(scrollY, "change", (latest) => {
    const delta = latest - lastY.current;
    lastY.current = latest;
    if (latest < 48) {
      setHidden(false);
    } else if (delta > 5) {
      setHidden(true);
    } else if (delta < -5) {
      setHidden(false);
    }
  });

  const activeIndex = navItems.findIndex((item) =>
    item.end
      ? location.pathname === item.to
      : location.pathname.startsWith(item.to),
  );

  return (
    <motion.header
      className="fixed top-0 left-0 right-0 z-50 glass"
      animate={{ y: hidden ? -48 : 0 }}
      transition={{ type: "spring", damping: 30, stiffness: 300 }}
    >
      <nav className="max-w-7xl mx-auto h-12 px-3 sm:px-6 flex items-center gap-2 sm:gap-0 sm:justify-between overflow-x-auto scrollbar-none">
        <span className="text-sm font-semibold shrink-0 tracking-tight sm:mr-6">
          <span className="text-accent">QS</span>
          <span className="hidden sm:inline text-ink">elect</span>
        </span>
        <div className="relative flex items-center shrink-0">
          {navItems.map((item, i) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `relative px-2.5 sm:px-3 py-1.5 text-sm whitespace-nowrap rounded-lg transition-colors duration-150 ${
                  isActive
                    ? "text-ink font-medium"
                    : "text-ink-muted hover:text-ink-secondary"
                }`
              }
            >
              {item.label}
              {i === activeIndex && (
                <motion.div
                  layoutId="nav-indicator"
                  className="absolute inset-0 rounded-lg -z-10"
                  style={{ background: "rgba(255,255,255,0.06)" }}
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
        <div className="ml-auto shrink-0">
          <SchedulerDot />
        </div>
      </nav>
    </motion.header>
  );
}

function SchedulerDot() {
  return (
    <div className="flex items-center gap-1.5 text-xs text-ink-muted">
      <span className="w-1.5 h-1.5 rounded-full bg-bear animate-pulse" />
      <span className="hidden sm:inline">就绪</span>
    </div>
  );
}
