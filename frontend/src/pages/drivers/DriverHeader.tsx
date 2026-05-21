import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { AutoRefreshIndicator } from "@/components/AutoRefreshIndicator";
import { IfRole } from "@/auth/IfRole";
import type { DriverDetail, DriverVersionDetail } from "./driver-detail/types";

interface DriverHeaderProps {
  driver: DriverDetail;
  autoRefreshEnabled: boolean;
  onToggleAutoRefresh: (enabled: boolean) => void;
  lastRefreshedAt: Date | null;
  onRefreshNow: () => void;
  onAddVersion: () => void;
}

/**
 * Right-side cluster surfaced via `<PageLayout actions=...>` on the driver
 * detail page. Renders:
 *
 *   - The metadata strip ("Latest" version label + "Source" line),
 *     derived from the newest-by-`createdOn` driver version.
 *   - The auto-refresh indicator + manual refresh control.
 *   - The "Add Version" mutation entry, gated by
 *     `IfRole minimum="READ_WRITE"` per FR-015.
 *
 * The driver name and the breadcrumb are owned by `PageLayout`; this
 * component intentionally does not re-render them.
 */
export function DriverHeader({
  driver,
  autoRefreshEnabled,
  onToggleAutoRefresh,
  lastRefreshedAt,
  onRefreshNow,
  onAddVersion,
}: DriverHeaderProps) {
  const latest = pickLatestVersion(driver.versions);

  return (
    <div
      className="flex items-center gap-4"
      data-testid="driver-header-actions"
    >
      {latest && (
        <div
          className="flex items-center gap-3 text-xs"
          data-testid="driver-metadata-strip"
        >
          <span className="text-muted-foreground">
            Latest{" "}
            <span
              className="font-mono font-semibold text-foreground"
              data-testid="driver-metadata-latest"
            >
              {latest.version}
            </span>
          </span>
          <span className="h-3 w-px bg-border" />
          <span className="text-muted-foreground">
            Source{" "}
            <span
              className="font-mono font-semibold text-foreground"
              data-testid="driver-metadata-source"
            >
              {formatSource(latest)}
            </span>
          </span>
        </div>
      )}
      <AutoRefreshIndicator
        enabled={autoRefreshEnabled}
        onToggle={onToggleAutoRefresh}
        lastRefreshedAt={lastRefreshedAt}
        onRefreshNow={onRefreshNow}
      />
      <IfRole minimum="READ_WRITE">
        <Button onClick={onAddVersion} data-testid="driver-add-version">
          <Plus className="h-4 w-4" />
          Add Version
        </Button>
      </IfRole>
    </div>
  );
}

function pickLatestVersion(
  versions: readonly DriverVersionDetail[],
): DriverVersionDetail | null {
  if (versions.length === 0) {
    return null;
  }
  return [...versions].sort(
    (a, b) => Date.parse(b.createdOn) - Date.parse(a.createdOn),
  )[0];
}

function formatSource(version: DriverVersionDetail): string {
  if (version.sourceType === "local") {
    return version.sourcePath ?? "local";
  }
  return version.sourceRepository;
}
