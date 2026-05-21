import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { InheritanceState } from "@/lib/configuration-types";

interface Props {
  inheritance: InheritanceState;
  className?: string;
}

/**
 * Read-only inheritance badge rendered next to each section's heading on the
 * Configuration tab and inside the unified drawer's section nav.
 *
 * - `inherited`  → neutral gray outline, "inherited"
 * - `overridden` → solid blue, "overridden (N)" where N is `overrideCount`
 *
 * See `specs/011-unified-deployment-config/data-model.md` — `InheritanceState`.
 */
export function InheritanceBadge({ inheritance, className }: Props) {
  if (inheritance.kind === "inherited") {
    return (
      <Badge
        variant="outline"
        className={cn(
          "text-muted-foreground border-muted-foreground/40",
          className,
        )}
        data-testid="inheritance-badge-inherited"
      >
        inherited
      </Badge>
    );
  }

  return (
    <Badge
      variant="default"
      className={cn(
        "border-transparent bg-blue-600 text-white hover:bg-blue-600",
        className,
      )}
      data-testid="inheritance-badge-overridden"
    >
      overridden ({inheritance.overrideCount})
    </Badge>
  );
}
