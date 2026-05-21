import { useMemo } from "react";
import { VersionListItem } from "./VersionListItem";
import type { DriverVersionDetail } from "./types";

interface VersionListProps {
  versions: readonly DriverVersionDetail[];
  selectedVersionId: string | null;
  onSelect: (versionId: string) => void;
}

/**
 * Left-rail list of driver versions. Sorted newest-first by `createdOn`.
 *
 * Renders a "VERSIONS" header and a vertical stack of {@link VersionListItem}
 * rows. The right-border divider is applied so the rail visually separates
 * from the right pane that hosts the tab strip.
 */
export function VersionList({
  versions,
  selectedVersionId,
  onSelect,
}: VersionListProps) {
  const sortedVersions = useMemo(
    () =>
      [...versions].sort(
        (a, b) => Date.parse(b.createdOn) - Date.parse(a.createdOn),
      ),
    [versions],
  );

  return (
    <aside
      data-testid="driver-version-list"
      className="flex w-[280px] shrink-0 flex-col gap-3 border-r border-border pr-4"
    >
      <h2 className="px-3 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
        Versions
      </h2>
      <nav className="flex flex-col gap-1" aria-label="Driver versions">
        {sortedVersions.map((version) => (
          <VersionListItem
            key={version.id}
            version={version}
            selected={version.id === selectedVersionId}
            onSelect={onSelect}
          />
        ))}
      </nav>
    </aside>
  );
}
