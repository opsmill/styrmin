import type { ReactNode } from "react";

interface Props {
  title: string;
  description?: string;
  testid: string;
  children: ReactNode;
}

/**
 * Visual wrapper for a single scheduling sub-block (Resources, Tolerations,
 * Topology spread, Affinity, etc.). Centralises the heading, description,
 * and `data-testid` so the section root reads as a list of declarative
 * blocks.
 */
export function SubBlock({ title, description, testid, children }: Props) {
  return (
    <div className="space-y-2" data-testid={testid}>
      <h4 className="text-sm font-semibold text-foreground">{title}</h4>
      {description && (
        <p className="text-xs text-muted-foreground">{description}</p>
      )}
      {children}
    </div>
  );
}
