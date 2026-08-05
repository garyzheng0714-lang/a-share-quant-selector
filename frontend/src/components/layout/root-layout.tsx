import { useEffect } from "react";
import { Outlet, useLocation } from "@/lib/spa-router";
import { AppShell } from "@astryxdesign/core/AppShell";
import { NavBar } from "./nav-bar";
import { BottomNav } from "./bottom-nav";
import { ToastContainer } from "@/components/ui/toast";

export function RootLayout() {
  const location = useLocation();

  useEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
  }, [location.pathname]);

  return (
    <>
      <AppShell
        topNav={<NavBar />}
        contentPadding={0}
        height="auto"
        variant="section"
        mobileNav={false}
      >
        <div className="min-h-[calc(100dvh-56px)] pb-[calc(4rem+env(safe-area-inset-bottom))] sm:pb-0">
          <Outlet />
        </div>
      </AppShell>
      <BottomNav />
      <ToastContainer />
    </>
  );
}
