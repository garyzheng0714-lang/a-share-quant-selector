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
        whileHover={
          hoverable
            ? { y: -2, boxShadow: "var(--shadow-card-hover)" }
            : undefined
        }
        transition={{ duration: 0.2 }}
        className={`glass-card rounded-2xl ${hoverable ? "cursor-pointer glass-card-hover" : ""} ${className}`}
        style={hoverable ? undefined : { transition: "border-color 0.2s" }}
        {...props}
      >
        {children}
      </motion.div>
    );
  },
);
