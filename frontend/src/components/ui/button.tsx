import {
  Button as AstryxButton,
  type ButtonProps as AstryxButtonProps,
} from "@astryxdesign/core/Button";
import { forwardRef, type ReactNode } from "react";

type LegacyVariant = "primary" | "secondary" | "danger" | "ghost";
type LegacySize = "sm" | "md" | "lg";

export interface ButtonProps
  extends Omit<AstryxButtonProps, "label" | "variant" | "size" | "isLoading" | "isDisabled" | "children"> {
  variant?: LegacyVariant;
  size?: LegacySize;
  loading?: boolean;
  disabled?: boolean;
  label?: string;
  children?: ReactNode;
}

const variantMap: Record<LegacyVariant, AstryxButtonProps["variant"]> = {
  primary: "primary",
  secondary: "secondary",
  danger: "destructive",
  ghost: "ghost",
};

function getLabel(children: ReactNode, ariaLabel?: string) {
  if (typeof children === "string" && children.trim()) return children;
  if (typeof children === "number") return String(children);
  return ariaLabel || "操作";
}

/**
 * Compatibility adapter for legacy call sites.
 * The rendered control is always Astryx Button; this file only keeps the old
 * prop names stable while the remaining pages are migrated.
 */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  function Button(
    {
      variant = "primary",
      size = "md",
      loading = false,
      label: explicitLabel,
      children,
      "aria-label": ariaLabel,
      disabled,
      ...props
    },
    ref,
  ) {
    const label = explicitLabel || getLabel(children, ariaLabel);
    return (
      <AstryxButton
        ref={ref}
        {...props}
        label={label}
        aria-label={ariaLabel}
        variant={variantMap[variant]}
        size={size}
        isLoading={loading}
        isDisabled={disabled}
      >
        {children ?? explicitLabel}
      </AstryxButton>
    );
  },
);
