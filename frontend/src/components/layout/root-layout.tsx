import { Outlet } from "react-router-dom";
import { AnimatePresence } from "framer-motion";
import { NavBar } from "./nav-bar";
import { BottomNav } from "./bottom-nav";
import { ToastContainer } from "@/components/ui/toast";

export function RootLayout() {
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
