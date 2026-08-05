import { Card as AstryxCard, type CardProps as AstryxCardProps } from "@astryxdesign/core/Card";
import { forwardRef } from "react";

export interface CardProps extends AstryxCardProps {
  /** Retained for old call sites; Astryx owns the hover/focus treatment. */
  hoverable?: boolean;
}

/** Compatibility adapter. The rendered container is Astryx Card. */
export const Card = forwardRef<HTMLDivElement, CardProps>(function Card(
  { hoverable: _hoverable, ...props },
  ref,
) {
  void _hoverable;
  return <AstryxCard ref={ref} {...props} />;
});
