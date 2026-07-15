import { NavLink, Link, useLocation } from "react-router-dom";

const navItems = [
  { to: "/sectors", label: "板块", matches: ["/sectors"] },
  { to: "/stocks", label: "个股", matches: ["/stocks", "/stock/"] },
];

export function NavBar() {
  const location = useLocation();
  return (
    <header className="nav-island fixed inset-x-0 top-0 z-50">
      <nav className="mx-auto flex h-14 max-w-6xl items-center px-4 sm:px-6" aria-label="主导航">
        <Link to="/sectors" className="shrink-0 text-[15px] font-semibold tracking-[-0.03em] text-ink">
          Q<span className="text-accent">Select</span>
        </Link>
        <div className="ml-8 hidden h-full items-center gap-1 sm:flex">
          {navItems.map((item) => {
            const active = item.matches.some((path) => location.pathname.startsWith(path));
            return (
              <NavLink
                key={item.to}
                to={item.to}
                className={`relative flex h-full items-center px-4 text-[13px] font-medium transition-colors ${
                  active ? "text-ink" : "text-ink-muted hover:text-ink-secondary"
                }`}
              >
                {item.label}
                {active && <span className="absolute inset-x-4 bottom-0 h-0.5 rounded-full bg-accent" />}
              </NavLink>
            );
          })}
        </div>
        <div className="ml-auto flex items-center gap-2 text-[11px] text-ink-muted">
          <span className="h-1.5 w-1.5 rounded-full bg-bear" aria-hidden="true" />
          <span>数据就绪</span>
        </div>
      </nav>
    </header>
  );
}
