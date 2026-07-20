import type { ListDriversQuery } from "@/generated/graphql";
import { compareVersionsLatestFirst } from "@/lib/driverVersion";

export type DriverListItem = ListDriversQuery["applicationDrivers"][number];
export type DriverListVersion = DriverListItem["versions"][number];

/** Human-readable source: `repo @ branch` for git, the path for local. */
export function versionSource(v: DriverListVersion): string {
  if (v.sourceType === "local") return v.sourcePath ?? "local";
  const repo = v.sourceRepository || "";
  return v.sourceBranch ? `${repo} @ ${v.sourceBranch}` : repo;
}

/** Versions ordered "latest first" per the backend latest-wins rule. */
export function versionsLatestFirst(
  versions: readonly DriverListVersion[],
): DriverListVersion[] {
  return [...versions].sort(compareVersionsLatestFirst);
}

/** The version that carries the "Latest" pill — the latest-wins winner. */
export function latestVersion(
  driver: DriverListItem,
): DriverListVersion | undefined {
  return versionsLatestFirst(driver.versions)[0];
}

function versionMatches(v: DriverListVersion, q: string): boolean {
  return (
    v.version.toLowerCase().includes(q) ||
    versionSource(v).toLowerCase().includes(q) ||
    (v.supportedVersions ?? "").toLowerCase().includes(q)
  );
}

/**
 * Client-side filter over the loaded driver set. Matches on application/
 * driver name, version string, source, and supported range. When the name
 * matches, the whole group is kept; otherwise only matching versions remain.
 * Groups are returned sorted by name, versions newest-first.
 */
export function filterDrivers(
  drivers: readonly DriverListItem[],
  query: string,
): DriverListItem[] {
  const q = query.trim().toLowerCase();
  const byName = [...drivers].sort((a, b) => a.name.localeCompare(b.name));

  if (!q) {
    return byName.map((d) => ({
      ...d,
      versions: versionsLatestFirst(d.versions),
    }));
  }

  const result: DriverListItem[] = [];
  for (const driver of byName) {
    const nameMatches = driver.name.toLowerCase().includes(q);
    const versions = versionsLatestFirst(driver.versions).filter(
      (v) => nameMatches || versionMatches(v, q),
    );
    if (versions.length > 0) result.push({ ...driver, versions });
  }
  return result;
}

/** Flatten a (already-filtered) driver set into per-version rows for the flat view. */
export function flattenVersions(drivers: readonly DriverListItem[]): Array<{
  driver: DriverListItem;
  version: DriverListVersion;
  isLatest: boolean;
}> {
  const rows: Array<{
    driver: DriverListItem;
    version: DriverListVersion;
    isLatest: boolean;
  }> = [];
  for (const driver of drivers) {
    const latestId = latestVersion(driver)?.id;
    for (const version of driver.versions) {
      rows.push({ driver, version, isLatest: version.id === latestId });
    }
  }
  return rows.sort(
    (a, b) =>
      a.driver.name.localeCompare(b.driver.name) ||
      compareVersionsLatestFirst(a.version, b.version),
  );
}
