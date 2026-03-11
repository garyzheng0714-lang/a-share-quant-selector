import { motion, useMotionValueEvent, useScroll } from "framer-motion";
import { NavLink, useLocation, Link } from "react-router-dom";
import { useState, useRef } from "react";

const navItems = [
  { to: "/", label: "排名", end: true },
  { to: "/history", label: "历史" },
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
      className="fixed top-3 left-1/2 -translate-x-1/2 z-50 nav-island"
      animate={{ y: hidden ? -60 : 0, opacity: hidden ? 0 : 1 }}
      transition={{ type: "spring", damping: 30, stiffness: 300 }}
    >
      <nav className="flex items-center h-11 px-2 gap-1">
        <Link to="/" className="px-3 text-sm font-semibold tracking-tight shrink-0 hover:opacity-80 transition-opacity">
          <span className="text-accent">QS</span>
          <span className="text-ink">elect</span>
        </Link>
        <div className="hidden sm:flex items-center">
          {navItems.map((item, i) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `relative px-3 py-1.5 text-[13px] font-medium tracking-[0.02em] uppercase whitespace-nowrap rounded-xl transition-colors duration-150 ${
                  isActive
                    ? "text-ink"
                    : "text-ink-muted hover:text-ink-secondary"
                }`
              }
            >
              {item.label}
              {i === activeIndex && (
                <motion.div
                  layoutId="nav-indicator"
                  className="absolute inset-0 rounded-xl -z-10 bg-white/10"
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
        <div className="ml-2 shrink-0">
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
