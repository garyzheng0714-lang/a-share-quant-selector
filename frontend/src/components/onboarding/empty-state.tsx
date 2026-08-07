import { EmptyState as AstryxEmptyState } from "@astryxdesign/core/EmptyState";
import { Button } from "@astryxdesign/core/Button";
import type { ReactNode } from "react";

interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  description: string;
  ctaLabel?: string;
  onCta?: () => void;
}

export function EmptyState({ icon, title, description, ctaLabel, onCta }: EmptyStateProps) {
  return (
    <AstryxEmptyState
      icon={icon}
      title={title}
      description={description}
      actions={ctaLabel && onCta ? <Button label={ctaLabel} size="sm" onClick={onCta} /> : undefined}
    />
  );
}
