import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import type { InheritanceState } from "@/lib/configuration-types";
import { InheritanceBadge } from "./InheritanceBadge";

interface Props {
  title: string;
  inheritance: InheritanceState;
  children: ReactNode;
  className?: string;
}

/**
 * Shared shell for every read-only section card on the Configuration tab.
 *
 * Renders the section heading, the inheritance badge, a divider, and a slot
 * for the section-specific body. Matches Paper mock `D2 — Configuration Tab
 * (Read)`: white background, 1px light-gray border, 12px (rounded-xl) radius.
 *
 * See `specs/011-unified-deployment-config/plan.md` and `data-model.md`.
 */
export function ConfigSummaryCard({
  title,
  inheritance,
  children,
  className,
}: Props) {
  return (
    <section
      className={cn(
        "rounded-xl border border-border bg-card text-card-foreground shadow-sm",
        className,
      )}
      aria-labelledby={`config-summary-${slugify(title)}`}
    >
      <header className="flex items-center justify-between gap-3 px-5 py-4">
        <h3
          id={`config-summary-${slugify(title)}`}
          className="text-base font-semibold leading-none tracking-tight"
        >
          {title}
        </h3>
        <InheritanceBadge inheritance={inheritance} />
      </header>
      <div className="border-t border-border" />
      <div className="px-5 py-4">{children}</div>
    </section>
  );
}

function slugify(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}
