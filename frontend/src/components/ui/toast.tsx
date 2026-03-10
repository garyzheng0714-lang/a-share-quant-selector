import { AnimatePresence, motion } from "framer-motion";
import { useToastStore } from "@/lib/toast-store";

const dotColors = { info: "bg-accent", success: "bg-bear", error: "bg-bull" };

export function ToastContainer() {
  const toasts = useToastStore((s) => s.toasts);
  return (
    <div className="fixed top-4 right-4 z-[100] flex flex-col gap-2">
      <AnimatePresence>
        {toasts.map((toast) => (
          <motion.div
            key={toast.id}
            initial={{ x: 100, opacity: 0, scale: 0.95 }}
            animate={{ x: 0, opacity: 1, scale: 1 }}
            exit={{ x: 100, opacity: 0 }}
            transition={{ type: "spring", damping: 25, stiffness: 300 }}
            className="glass-elevated rounded-full px-4 py-2.5 shadow-float flex items-center gap-2.5"
          >
            <span
              className={`w-2 h-2 rounded-full ${dotColors[toast.type]}`}
            />
            <span className="text-sm text-ink whitespace-nowrap">
              {toast.message}
            </span>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}
