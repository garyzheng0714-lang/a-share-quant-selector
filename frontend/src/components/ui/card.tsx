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
            ? { y: -1 }
            : undefined
        }
        transition={{ duration: 0.15 }}
        className={`solid-card rounded-[32px] ${hoverable ? "cursor-pointer solid-card-hover" : ""} ${className}`}
        {...props}
      >
        {children}
      </motion.div>
    );
  },
);
