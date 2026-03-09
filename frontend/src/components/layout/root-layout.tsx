import { Outlet } from "react-router-dom";
import { AnimatePresence } from "framer-motion";
import { NavBar } from "./nav-bar";
import { ToastContainer } from "@/components/ui/toast";

export function RootLayout() {
  return (
    <>
      <NavBar />
      <main className="pt-12 min-h-screen">
        <AnimatePresence mode="wait">
          <Outlet />
        </AnimatePresence>
      </main>
      <ToastContainer />
    </>
  );
}
