import { describe, it, expect } from "vitest";

import {
  type DriverListItem,
  type DriverListVersion,
  versionSource,
  latestVersion,
  filterDrivers,
  flattenVersions,
} from "@/pages/drivers/lib/driverList";

function mkVersion(
  over: Partial<DriverListVersion> & {
    id: string;
    version: string;
    createdOn: string;
  },
): DriverListVersion {
  return {
    supportedVersions: ">=1.0,<2.0",
    sourceType: "git",
    sourceRepository: "opsmill/drivers",
    sourceBranch: "main",
    sourcePath: null,
    sourceCommitSha: "abc1234",
    contentHash: null,
    ...over,
  } as DriverListVersion;
}

function mkDriver(name: string, versions: DriverListVersion[]): DriverListItem {
  return { id: `id-${name}`, name, versions } as DriverListItem;
}

describe("versionSource", () => {
  it("formats a git source as `repo @ branch`", () => {
    expect(
      versionSource(
        mkVersion({ id: "a", version: "1", createdOn: "2026-01-01" }),
      ),
    ).toBe("opsmill/drivers @ main");
  });

  it("uses the path for a local source", () => {
    expect(
      versionSource(
        mkVersion({
          id: "a",
          version: "1",
          createdOn: "2026-01-01",
          sourceType: "local",
          sourcePath: "/opt/drivers/x",
        }),
      ),
    ).toBe("/opt/drivers/x");
  });
});

describe("latestVersion", () => {
  it("returns the newest version by createdOn", () => {
    const driver = mkDriver("infrahub", [
      mkVersion({ id: "old", version: "1", createdOn: "2026-01-01T00:00:00Z" }),
      mkVersion({ id: "new", version: "2", createdOn: "2026-03-01T00:00:00Z" }),
    ]);
    expect(latestVersion(driver)?.id).toBe("new");
  });
});

describe("filterDrivers", () => {
  const drivers = [
    mkDriver("grafana", [
      mkVersion({
        id: "g1",
        version: "1.4.2",
        createdOn: "2026-02-01T00:00:00Z",
      }),
    ]),
    mkDriver("infrahub", [
      mkVersion({
        id: "i1",
        version: "2.0.3",
        createdOn: "2026-01-01T00:00:00Z",
      }),
      mkVersion({
        id: "i2",
        version: "2.1.0",
        createdOn: "2026-03-01T00:00:00Z",
      }),
    ]),
  ];

  it("sorts groups by name and versions newest-first with no query", () => {
    const res = filterDrivers(drivers, "");
    expect(res.map((d) => d.name)).toEqual(["grafana", "infrahub"]);
    expect(res[1].versions.map((v) => v.id)).toEqual(["i2", "i1"]);
  });

  it("keeps the whole group when the application name matches", () => {
    const res = filterDrivers(drivers, "infra");
    expect(res).toHaveLength(1);
    expect(res[0].name).toBe("infrahub");
    expect(res[0].versions).toHaveLength(2);
  });

  it("narrows to matching versions when only a version string matches", () => {
    const res = filterDrivers(drivers, "2.1.0");
    expect(res).toHaveLength(1);
    expect(res[0].versions.map((v) => v.id)).toEqual(["i2"]);
  });

  it("returns nothing when there is no match", () => {
    expect(filterDrivers(drivers, "postgres")).toHaveLength(0);
  });
});

describe("flattenVersions", () => {
  it("flattens to per-version rows and flags the latest of each driver", () => {
    const rows = flattenVersions([
      mkDriver("infrahub", [
        mkVersion({
          id: "i1",
          version: "2.0.3",
          createdOn: "2026-01-01T00:00:00Z",
        }),
        mkVersion({
          id: "i2",
          version: "2.1.0",
          createdOn: "2026-03-01T00:00:00Z",
        }),
      ]),
    ]);
    expect(rows.map((r) => r.version.id)).toEqual(["i2", "i1"]);
    expect(rows.find((r) => r.version.id === "i2")?.isLatest).toBe(true);
    expect(rows.find((r) => r.version.id === "i1")?.isLatest).toBe(false);
  });
});
