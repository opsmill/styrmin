import { describe, it, expect } from "vitest";

import {
  type DriverListItem,
  type DriverListVersion,
  type FilteredDriver,
  versionSource,
  findLatestVersion,
  filterDrivers,
  flattenVersions,
  showsLatestBadge,
  cappedVersions,
  shownVersionCount,
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
    icon: null,
    description: null,
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

  it("appends the driver directory of a git source as `repo @ branch · dir`", () => {
    expect(
      versionSource(
        mkVersion({
          id: "a",
          version: "1",
          createdOn: "2026-01-01",
          sourcePath: "drivers/simple-app",
        }),
      ),
    ).toBe("opsmill/drivers @ main · drivers/simple-app");
  });

  it("appends the driver directory of a git source without a branch as `repo · dir`", () => {
    expect(
      versionSource(
        mkVersion({
          id: "a",
          version: "1",
          createdOn: "2026-01-01",
          sourceBranch: null,
          sourcePath: "drivers/simple-app",
        }),
      ),
    ).toBe("opsmill/drivers · drivers/simple-app");
  });
});

describe("findLatestVersion", () => {
  it("returns the newest version by createdOn", () => {
    const driver = mkDriver("infrahub", [
      mkVersion({ id: "old", version: "1", createdOn: "2026-01-01T00:00:00Z" }),
      mkVersion({ id: "new", version: "2", createdOn: "2026-03-01T00:00:00Z" }),
    ]);
    expect(findLatestVersion(driver)?.id).toBe("new");
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

  it("matches the description of a version, ignoring case", () => {
    const described = [
      mkDriver("infrahub", [
        mkVersion({
          id: "i1",
          version: "2.0.3",
          createdOn: "2026-01-01T00:00:00Z",
          description: "Source of truth for infrastructure",
        }),
      ]),
      mkDriver("grafana", [
        mkVersion({ id: "g1", version: "1.0.0", createdOn: "2026-01-01" }),
      ]),
    ];
    const res = filterDrivers(described, "SOURCE OF TRUTH");
    expect(res.map((d) => d.name)).toEqual(["infrahub"]);
    expect(res[0].versions.map((v) => v.id)).toEqual(["i1"]);
  });

  it("keeps the unfiltered latest identity when narrowing to an older version", () => {
    const res = filterDrivers(drivers, "2.0.3");
    expect(res).toHaveLength(1);
    // only the older version is displayed…
    expect(res[0].versions.map((v) => v.id)).toEqual(["i1"]);
    // …but the latest-wins winner is still the hidden i2, over all 2 versions
    expect(res[0].latestVersion?.id).toBe("i2");
    expect(res[0].totalVersions).toBe(2);
    expect(showsLatestBadge(res[0], res[0].versions[0])).toBe(false);
  });

  it("sets latestVersion to the latest-wins version with no query", () => {
    const res = filterDrivers(drivers, "");
    expect(res.map((d) => d.latestVersion?.id)).toEqual(["g1", "i2"]);
  });

  it("keeps latestVersion on the latest-wins version when the query filters it out", () => {
    const withIcons = [
      mkDriver("infrahub", [
        mkVersion({
          id: "i1",
          version: "2.0.3",
          createdOn: "2026-01-01T00:00:00Z",
          icon: "https://example.com/old.svg",
        }),
        mkVersion({
          id: "i2",
          version: "2.1.0",
          createdOn: "2026-03-01T00:00:00Z",
          icon: "https://example.com/new.svg",
        }),
      ]),
    ];
    const res = filterDrivers(withIcons, "2.0.3");
    expect(res[0].versions.map((v) => v.id)).toEqual(["i1"]);
    expect(res[0].latestVersion?.id).toBe("i2");
    expect(res[0].latestVersion?.icon).toBe("https://example.com/new.svg");
  });
});

describe("showsLatestBadge", () => {
  it("flags only the latest-wins winner of a multi-version driver", () => {
    const [grafana, infrahub] = filterDrivers(
      [
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
      ],
      "",
    );
    const version = (d: FilteredDriver, id: string) =>
      d.versions.find((v) => v.id === id)!;
    expect(showsLatestBadge(infrahub, version(infrahub, "i2"))).toBe(true);
    expect(showsLatestBadge(infrahub, version(infrahub, "i1"))).toBe(false);
    // single-version driver: its only version is trivially latest — no badge
    expect(showsLatestBadge(grafana, version(grafana, "g1"))).toBe(false);
  });
});

describe("flattenVersions", () => {
  it("flattens to per-version rows and flags the latest of each driver", () => {
    const rows = flattenVersions(
      filterDrivers(
        [
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
        ],
        "",
      ),
    );
    expect(rows.map((r) => r.version.id)).toEqual(["i2", "i1"]);
    expect(rows.find((r) => r.version.id === "i2")?.isLatest).toBe(true);
    expect(rows.find((r) => r.version.id === "i1")?.isLatest).toBe(false);
  });

  it("never flags the only version of a single-version driver", () => {
    const rows = flattenVersions(
      filterDrivers(
        [
          mkDriver("grafana", [
            mkVersion({
              id: "g1",
              version: "1.4.2",
              createdOn: "2026-02-01T00:00:00Z",
            }),
          ]),
        ],
        "",
      ),
    );
    expect(rows).toHaveLength(1);
    expect(rows[0].isLatest).toBe(false);
  });
});

describe("cappedVersions", () => {
  const many = (n: number) =>
    Array.from({ length: n }, (_, i) =>
      mkVersion({
        id: `v${i}`,
        version: `${n - i}.0.0`,
        createdOn: `2026-01-${String(n - i).padStart(2, "0")}T00:00:00Z`,
      }),
    );

  const filtered = (versions: DriverListVersion[]): FilteredDriver =>
    filterDrivers([mkDriver("infrahub", versions)], "")[0];

  it("shows only the newest three and counts the rest as hidden", () => {
    const { visible, hiddenCount } = cappedVersions(filtered(many(47)), false);
    expect(visible).toHaveLength(3);
    expect(hiddenCount).toBe(44);
  });

  it("does not fire for a driver at or below the cap", () => {
    const { visible, hiddenCount } = cappedVersions(filtered(many(3)), false);
    expect(visible).toHaveLength(3);
    expect(hiddenCount).toBe(0);
  });

  it("shows every match uncapped while a filter is active", () => {
    // The filter matches version strings, so capping here would hide rows the
    // user searched for and label them "older".
    const { visible, hiddenCount } = cappedVersions(filtered(many(47)), true);
    expect(visible).toHaveLength(47);
    expect(hiddenCount).toBe(0);
  });
});

describe("shownVersionCount", () => {
  it("sums the versions actually on screen, not the loaded total", () => {
    const drivers = filterDrivers(
      [
        mkDriver("grafana", [
          mkVersion({ id: "g1", version: "1.4.2", createdOn: "2026-02-01" }),
          mkVersion({ id: "g2", version: "1.4.1", createdOn: "2026-01-01" }),
        ]),
        mkDriver("infrahub", [
          mkVersion({ id: "i1", version: "2.0.3", createdOn: "2026-01-01" }),
        ]),
      ],
      "1.4.2",
    );
    expect(shownVersionCount(drivers)).toBe(1);
  });
});
