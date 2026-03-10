import { Outlet } from "react-router-dom";
import { AnimatePresence } from "framer-motion";
import { NavBar } from "./nav-bar";
import { BottomNav } from "./bottom-nav";
import { ToastContainer } from "@/components/ui/toast";
import { WelcomeModal } from "@/components/onboarding";
import { useOnboardingState } from "@/lib/onboarding";

export function RootLayout() {
  const { welcomeDismissed, dismissWelcome } = useOnboardingState();

  return (
    <>
      <NavBar />
      <main className="pt-12 pb-16 sm:pb-0 min-h-screen">
        <AnimatePresence mode="wait">
          <Outlet />
        </AnimatePresence>
      </main>
      <BottomNav />
      <ToastContainer />
      <AnimatePresence>
        {!welcomeDismissed && <WelcomeModal onDismiss={dismissWelcome} />}
      </AnimatePresence>
    </>
  );
}
