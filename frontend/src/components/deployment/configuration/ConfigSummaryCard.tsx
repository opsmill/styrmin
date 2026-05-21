import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

interface Props {
  title: string;
  children: ReactNode;
  className?: string;
}

/**
 * Shared shell for every read-only section card on the Settings tab.
 *
 * Renders the section heading, a divider, and a slot for the section-specific
 * body. The previous section-level "inherited" / "overridden" badge was
 * removed — the per-row "deployment-defined" highlighting that lives inside
 * each card body is enough signal.
 */
export function ConfigSummaryCard({ title, children, className }: Props) {
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
