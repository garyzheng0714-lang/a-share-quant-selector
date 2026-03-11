import { Outlet } from "react-router-dom";
import { AnimatePresence } from "framer-motion";
import { NavBar } from "./nav-bar";
import { BottomNav } from "./bottom-nav";
import { ToastContainer } from "@/components/ui/toast";

export function RootLayout() {
  return (
    <>
      <NavBar />
      <main className="pt-16 pb-16 sm:pb-0 min-h-screen">
        <AnimatePresence mode="wait">
          <Outlet />
        </AnimatePresence>
      </main>
      <BottomNav />
      <ToastContainer />
    </>
  );
}
