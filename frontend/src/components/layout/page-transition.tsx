import { motion, useReducedMotion } from "framer-motion";
import { useLocation } from "react-router-dom";
import { duration, ease } from "@/lib/tokens";

interface PageTransitionProps {
  children: React.ReactNode;
}

export function PageTransition({ children }: PageTransitionProps) {
  const location = useLocation();
  const reduceMotion = useReducedMotion();
  return (
    <motion.div
      key={location.pathname}
      initial={reduceMotion ? false : { opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      exit={reduceMotion ? undefined : { opacity: 0, y: -4 }}
      transition={{ duration: reduceMotion ? 0 : duration.normal, ease: [...ease.default] }}
    >
      {children}
    </motion.div>
  );
}
