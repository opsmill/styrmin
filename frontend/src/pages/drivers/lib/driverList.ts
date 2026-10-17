import type { ListDriversQuery } from "@/generated/graphql";
import { compareVersionsLatestFirst } from "@/lib/driverVersion";

export type DriverListItem = ListDriversQuery["applicationDrivers"][number];
export type DriverListVersion = DriverListItem["versions"][number];

/**
 * A driver group as the list displays it: `versions` may be narrowed by the
 * filter, while `latestVersion` / `totalVersions` are always computed from
 * the full loaded set — so filtering can never change which version reads as
 * "Latest" (it must stay the latest-wins winner deployments actually bind) or
 * whose logo the group header shows.
 */
export type FilteredDriver = DriverListItem & {
  /** The latest-wins winner across ALL loaded versions. */
  latestVersion: DriverListVersion | undefined;
  /** Count of all loaded versions, before filtering. */
  totalVersions: number;
};

/**
 * Human-readable source: the path for local, `repo @ branch` for git, followed
 * by ` · <driver directory>` when the git version was loaded from one.
 */
export function versionSource(v: DriverListVersion): string {
  if (v.sourceType === "local") return v.sourcePath ?? "local";
  const repo = v.sourceRepository || "";
  const source = v.sourceBranch ? `${repo} @ ${v.sourceBranch}` : repo;
  return v.sourcePath ? `${source} · ${v.sourcePath}` : source;
}

/** Versions ordered "latest first" per the backend latest-wins rule. */
export function versionsLatestFirst(
  versions: readonly DriverListVersion[],
): DriverListVersion[] {
  return [...versions].sort(compareVersionsLatestFirst);
}

/** The version that carries the "Latest" pill — the latest-wins winner. */
export function findLatestVersion(
  driver: DriverListItem,
): DriverListVersion | undefined {
  return versionsLatestFirst(driver.versions)[0];
}

function versionMatches(v: DriverListVersion, q: string): boolean {
  return (
    v.version.toLowerCase().includes(q) ||
    versionSource(v).toLowerCase().includes(q) ||
    (v.supportedVersions ?? "").toLowerCase().includes(q) ||
    (v.description ?? "").toLowerCase().includes(q)
  );
}

/**
 * Client-side filter over the loaded driver set. Matches on application/
 * driver name, version string, source, supported range, and description. When the name
 * matches, the whole group is kept; otherwise only matching versions remain.
 * Groups are returned sorted by name, versions newest-first.
 */
export function filterDrivers(
  drivers: readonly DriverListItem[],
  query: string,
): FilteredDriver[] {
  const q = query.trim().toLowerCase();
  const byName = [...drivers].sort((a, b) => a.name.localeCompare(b.name));

  if (!q) {
    return byName.map((d) => {
      const versions = versionsLatestFirst(d.versions);
      return {
        ...d,
        versions,
        latestVersion: versions[0],
        totalVersions: versions.length,
      };
    });
  }

  const result: FilteredDriver[] = [];
  for (const driver of byName) {
    const nameMatches = driver.name.toLowerCase().includes(q);
    const allVersions = versionsLatestFirst(driver.versions);
    const versions = allVersions.filter(
      (v) => nameMatches || versionMatches(v, q),
    );
    if (versions.length > 0) {
      result.push({
        ...driver,
        versions,
        latestVersion: allVersions[0],
        totalVersions: allVersions.length,
      });
    }
  }
  return result;
}

/**
 * Whether a version carries the "Latest" pill in the list. Two conditions:
 * it is the latest-wins winner across ALL loaded versions (not just the ones
 * the filter left visible), and the driver has more than one loaded version —
 * a single-version driver's only version is trivially latest, so the pill
 * would be noise.
 */
export function showsLatestBadge(
  driver: FilteredDriver,
  version: DriverListVersion,
): boolean {
  return driver.totalVersions > 1 && version.id === driver.latestVersion?.id;
}

/** Flatten a (already-filtered) driver set into per-version rows for the flat view. */
export function flattenVersions(drivers: readonly FilteredDriver[]): Array<{
  driver: FilteredDriver;
  version: DriverListVersion;
  isLatest: boolean;
}> {
  const rows: Array<{
    driver: FilteredDriver;
    version: DriverListVersion;
    isLatest: boolean;
  }> = [];
  for (const driver of drivers) {
    for (const version of driver.versions) {
      rows.push({
        driver,
        version,
        isLatest: showsLatestBadge(driver, version),
      });
    }
  }
  return rows.sort(
    (a, b) =>
      a.driver.name.localeCompare(b.driver.name) ||
      compareVersionsLatestFirst(a.version, b.version),
  );
}

/** Versions a group renders before the rest collapse into the footer row. */
export const GROUPED_VERSION_CAP = 3;

/**
 * The versions a group shows, plus how many the footer row stands in for.
 *
 * The cap does not fire while a query is active: the filter matches version
 * strings, sources and supported ranges, so capping would hide matches.
 */
export function cappedVersions(
  driver: FilteredDriver,
  isFiltering: boolean,
): { visible: DriverListVersion[]; hiddenCount: number } {
  if (isFiltering || driver.versions.length <= GROUPED_VERSION_CAP) {
    return { visible: driver.versions, hiddenCount: 0 };
  }
  return {
    visible: driver.versions.slice(0, GROUPED_VERSION_CAP),
    hiddenCount: driver.versions.length - GROUPED_VERSION_CAP,
  };
}

/** Versions on screen across a driver set. */
export function shownVersionCount(drivers: readonly FilteredDriver[]): number {
  return drivers.reduce((n, d) => n + d.versions.length, 0);
}
