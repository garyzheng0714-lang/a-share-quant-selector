"use client";

import { motion, type HTMLMotionProps } from "framer-motion";
import { forwardRef } from "react";

interface CardProps extends Omit<HTMLMotionProps<"div">, "ref"> {
  hoverable?: boolean;
}

export const Card = forwardRef<HTMLDivElement, CardProps>(
  function Card({ hoverable = false, className = "", children, ...props }, ref) {
    return (
      <motion.div
        ref={ref}
        whileHover={hoverable ? { y: -4, boxShadow: "var(--shadow-card-hover)" } : undefined}
        transition={{ duration: 0.2 }}
        className={`bg-surface rounded-2xl shadow-card ${hoverable ? "cursor-pointer" : ""} ${className}`}
        {...props}
      >
        {children}
      </motion.div>
    );
  },
);
