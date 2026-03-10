import { motion } from "framer-motion";
import { useLocation } from "react-router-dom";
import { duration, ease } from "@/lib/tokens";

interface PageTransitionProps {
  children: React.ReactNode;
}

export function PageTransition({ children }: PageTransitionProps) {
  const location = useLocation();
  return (
    <motion.div
      key={location.pathname}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: duration.normal, ease: ease.default as unknown as number[] }}
    >
      {children}
    </motion.div>
  );
}
