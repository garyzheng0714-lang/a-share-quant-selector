import { useEffect } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { AnimatePresence } from "framer-motion";
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
      <NavBar />
      <main id="main-content" className="min-h-[100dvh] pt-14 pb-[calc(4rem+env(safe-area-inset-bottom))] sm:pb-8">
        <AnimatePresence mode="wait">
          <Outlet />
        </AnimatePresence>
      </main>
      <BottomNav />
      <ToastContainer />
    </>
  );
}
