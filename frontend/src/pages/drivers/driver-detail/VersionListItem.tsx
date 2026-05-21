import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { formatRelativeTime } from "./relative-time";
import type { DriverVersionDetail } from "./types";

interface VersionListItemProps {
  version: DriverVersionDetail;
  selected: boolean;
  onSelect: (versionId: string) => void;
}

/**
 * One row in the driver-version left rail. Renders as a focusable button per
 * FR-016a — Enter/Space activate and the selected row advertises its state via
 * `aria-pressed`.
 *
 * Long `version` strings truncate with an ellipsis; the full value remains
 * discoverable via the `title` attribute (mouse hover + screen readers).
 */
export function VersionListItem({
  version,
  selected,
  onSelect,
}: VersionListItemProps) {
  const isGit = version.sourceType === "git";
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={() => onSelect(version.id)}
      data-testid="driver-version-row"
      data-version-id={version.id}
      data-version-label={version.version}
      data-source-type={version.sourceType}
      data-selected={selected}
      className={cn(
        "flex w-full flex-col items-start gap-1 rounded-md border border-transparent px-3 py-2 text-left transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        selected
          ? "bg-accent text-accent-foreground"
          : "hover:bg-accent/50 text-foreground",
      )}
    >
      <div className="flex w-full items-center gap-2">
        <span
          className="flex-1 truncate font-mono text-[13px] font-medium"
          title={version.version}
        >
          {version.version}
        </span>
        <Badge
          variant={isGit ? "secondary" : "outline"}
          className="shrink-0 px-1.5 py-0 text-[10px] font-medium uppercase tracking-wide"
        >
          {isGit ? "git" : "local"}
        </Badge>
      </div>
      <span className="text-[11px] text-muted-foreground">
        {formatRelativeTime(version.createdOn)}
      </span>
    </button>
  );
}
