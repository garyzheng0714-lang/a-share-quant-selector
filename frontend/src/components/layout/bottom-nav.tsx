import { NavLink, useLocation } from "react-router-dom";
import { motion } from "framer-motion";

const navItems = [
  {
    to: "/",
    label: "排名",
    end: true,
    icon: (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
        <path
          d="M10 2.5l2.47 5 5.53.8-4 3.9.94 5.5L10 14.9l-4.94 2.8.94-5.5-4-3.9 5.53-.8L10 2.5z"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinejoin="round"
        />
      </svg>
    ),
  },
  {
    to: "/history",
    label: "历史",
    icon: (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
        <circle cx="10" cy="10" r="7" stroke="currentColor" strokeWidth="1.5" />
        <path
          d="M10 6v4l2.5 2.5"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    ),
  },
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
            <span
              className={`transition-colors duration-150 ${
                i === activeIndex ? "text-accent" : "text-ink-muted"
              }`}
            >
              {item.icon}
            </span>
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
