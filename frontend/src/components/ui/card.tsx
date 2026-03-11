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
            ? { y: -2, boxShadow: "0 8px 32px rgba(144,70,255,0.12)" }
            : undefined
        }
        transition={{ duration: 0.2 }}
        className={`glass-card rounded-3xl ${hoverable ? "cursor-pointer glass-card-hover" : ""} ${className}`}
        style={hoverable ? undefined : { transition: "border-color 0.2s" }}
        {...props}
      >
        {children}
      </motion.div>
    );
  },
);
