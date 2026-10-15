import { describe, expect, it } from "vitest";

import { diff } from "./config-diff";
import { evaluateImpact, matchPath } from "./config-impact";
import type {
  ConfigurationDiff,
  DiffEntry,
  ImpactRule,
} from "./configuration-types";
import { impactRules } from "./impact-rules";

// ---------------------------------------------------------------------------
// matchPath: glob engine suite
// ---------------------------------------------------------------------------

describe("matchPath glob engine", () => {
  it("exact-match a literal path", () => {
    expect(matchPath("name", "name", "change", "x")).toBe(true);
    expect(matchPath("name", "nameOther", "change", "x")).toBe(false);
  });

  it("`*` matches a single plain segment", () => {
    expect(
      matchPath(
        "scheduling.resources.*",
        "scheduling.resources.cpu",
        "change",
        "",
      ),
    ).toBe(true);
    // Does not match nested segments.
    expect(
      matchPath(
        "scheduling.resources.*",
        "scheduling.resources.requests.cpu",
        "change",
        "",
      ),
    ).toBe(false);
    // Does not match a bracket segment.
    expect(matchPath("envVars.*", "envVars.[FOO]", "change", "")).toBe(false);
  });

  it("`**` matches zero or more segments", () => {
    expect(
      matchPath(
        "scheduling.resources.**",
        "scheduling.resources.requests.cpu",
        "change",
        "",
      ),
    ).toBe(true);
    expect(
      matchPath(
        "scheduling.**",
        "scheduling.tolerations[gpu].effect",
        "change",
        "",
      ),
    ).toBe(true);
    // Matches zero segments at the end.
    expect(matchPath("scheduling.**", "scheduling", "change", "")).toBe(true);
    // Mismatched prefix still fails.
    expect(
      matchPath("scheduling.**", "networking.ipWhitelist", "change", ""),
    ).toBe(false);
  });

  it("`[*]` matches any bracket segment", () => {
    expect(matchPath("envVars[*]", "envVars[FOO]", "change", "")).toBe(true);
    expect(matchPath("envVars[*]", "envVars[BAR_BAZ]", "change", "")).toBe(
      true,
    );
    // `[*]` does NOT match a plain (non-bracket) segment.
    expect(matchPath("envVars[*]", "envVars.plain", "change", "")).toBe(false);
  });

  it("`value:X` qualifier requires DiffEntry.after === X", () => {
    expect(
      matchPath(
        "scheduling.tolerations[*].effect value:NO_EXECUTE",
        "scheduling.tolerations[gpu].effect",
        "change",
        "NO_EXECUTE",
      ),
    ).toBe(true);
    expect(
      matchPath(
        "scheduling.tolerations[*].effect value:NO_EXECUTE",
        "scheduling.tolerations[gpu].effect",
        "change",
        "NoSchedule",
      ),
    ).toBe(false);
  });

  it("`kind:X` qualifier requires DiffEntry.kind === X", () => {
    expect(matchPath("envVars[*] kind:add", "envVars[NEW]", "add", "")).toBe(
      true,
    );
    expect(matchPath("envVars[*] kind:add", "envVars[NEW]", "change", "")).toBe(
      false,
    );
    expect(
      matchPath("envVars[*] kind:remove", "envVars[OLD]", "remove", ""),
    ).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// evaluateImpact: empty diff + ordering
// ---------------------------------------------------------------------------

function emptyDiff(): ConfigurationDiff {
  return { entries: [], sectionsChanged: [], hasChanges: false };
}

function asDiff(entries: DiffEntry[]): ConfigurationDiff {
  return {
    entries,
    sectionsChanged: [],
    hasChanges: entries.length > 0,
  };
}

function diffEntry(path: string, partial: Partial<DiffEntry> = {}): DiffEntry {
  return {
    section: partial.section ?? "scheduling",
    path,
    label: partial.label ?? path,
    before: partial.before ?? "",
    after: partial.after ?? "",
    kind: partial.kind ?? "change",
  };
}

describe("evaluateImpact: contract behaviour", () => {
  it("returns an informational summary for an empty diff", () => {
    const summary = evaluateImpact(emptyDiff(), impactRules);
    expect(summary.entries).toEqual([]);
    expect(summary.topSeverity).toBe("informational");
  });

  it("deduplicates rule firings by consequence text and lists every triggering path", () => {
    const summary = evaluateImpact(
      asDiff([
        diffEntry("envVars[FOO]", {
          section: "envVars",
          kind: "add",
          after: "1",
        }),
        diffEntry("envVars[BAR]", {
          section: "envVars",
          kind: "change",
          after: "2",
        }),
      ]),
      impactRules,
    );
    const envVarEntry = summary.entries.find((e) =>
      e.consequence.startsWith(
        "Pods will be recreated to pick up new environment",
      ),
    );
    expect(envVarEntry).toBeDefined();
    expect(envVarEntry?.triggeringPaths).toEqual([
      "envVars[FOO]",
      "envVars[BAR]",
    ]);
  });

  it("orders entries by descending severity then first-appearance", () => {
    const rules: ImpactRule[] = [
      { matcher: "a", consequence: "Low", severity: "informational" },
      { matcher: "b", consequence: "Mid", severity: "warning" },
      { matcher: "c", consequence: "High", severity: "high" },
    ];
    const summary = evaluateImpact(
      asDiff([diffEntry("a"), diffEntry("b"), diffEntry("c")]),
      rules,
    );
    expect(summary.entries.map((e) => e.consequence)).toEqual([
      "High",
      "Mid",
      "Low",
    ]);
    expect(summary.topSeverity).toBe("high");
  });
});

// ---------------------------------------------------------------------------
// Per-rule positive / negative coverage
// ---------------------------------------------------------------------------

interface RuleCase {
  matcher: string;
  positive: DiffEntry;
  negative: DiffEntry;
}

const ruleCases: RuleCase[] = [
  {
    matcher: "name",
    positive: diffEntry("name", { section: "identity" }),
    negative: diffEntry("nameOther", { section: "identity" }),
  },
  {
    matcher: "parameters.**",
    positive: diffEntry("parameters.replicas", { section: "driverParameters" }),
    negative: diffEntry("ingressClass", { section: "networking" }),
  },
  {
    matcher: "scheduling.resources.**",
    positive: diffEntry("scheduling.resources.requests.cpu"),
    negative: diffEntry("scheduling.runtimeClass"),
  },
  {
    matcher: "scheduling.tolerations",
    positive: diffEntry("scheduling.tolerations"),
    negative: diffEntry("scheduling.runtimeClass"),
  },
  {
    matcher: "scheduling.tolerations[*].effect value:NO_EXECUTE",
    positive: diffEntry("scheduling.tolerations[gpu].effect", {
      after: "NO_EXECUTE",
    }),
    negative: diffEntry("scheduling.tolerations[gpu].effect", {
      after: "NO_SCHEDULE",
    }),
  },
  {
    matcher: "scheduling.nodeAffinity",
    positive: diffEntry("scheduling.nodeAffinity"),
    negative: diffEntry("scheduling.podAffinity"),
  },
  {
    matcher: "scheduling.podAffinity",
    positive: diffEntry("scheduling.podAffinity"),
    negative: diffEntry("scheduling.podAntiAffinity"),
  },
  {
    matcher: "scheduling.podAntiAffinity",
    positive: diffEntry("scheduling.podAntiAffinity"),
    negative: diffEntry("scheduling.podAffinity"),
  },
  {
    matcher: "scheduling.topologySpreadConstraints",
    positive: diffEntry("scheduling.topologySpreadConstraints"),
    negative: diffEntry("scheduling.tolerations"),
  },
  {
    matcher: "scheduling.runtimeClass",
    positive: diffEntry("scheduling.runtimeClass"),
    negative: diffEntry("runtimeClass", { section: "storageRuntime" }),
  },
  {
    matcher: "envVars[*]",
    positive: diffEntry("envVars[FOO]", { section: "envVars" }),
    negative: diffEntry("envVars", { section: "envVars" }),
  },
  {
    matcher: "ipWhitelist",
    positive: diffEntry("ipWhitelist", { section: "networking" }),
    negative: diffEntry("ingressClass", { section: "networking" }),
  },
  {
    matcher: "dedicatedIngress",
    positive: diffEntry("dedicatedIngress", { section: "networking" }),
    negative: diffEntry("ingressClass", { section: "networking" }),
  },
  {
    matcher: "ingressClass",
    positive: diffEntry("ingressClass", { section: "networking" }),
    negative: diffEntry("fqdnSuffix", { section: "networking" }),
  },
  {
    matcher: "fqdnSuffix",
    positive: diffEntry("fqdnSuffix", { section: "networking" }),
    negative: diffEntry("ingressClass", { section: "networking" }),
  },
  {
    matcher: "externalUrlScheme",
    positive: diffEntry("externalUrlScheme", { section: "networking" }),
    negative: diffEntry("externalUrlPort", { section: "networking" }),
  },
  {
    matcher: "externalUrlPort",
    positive: diffEntry("externalUrlPort", { section: "networking" }),
    negative: diffEntry("externalUrlScheme", { section: "networking" }),
  },
  {
    matcher: "externalDnsEndpointsType",
    positive: diffEntry("externalDnsEndpointsType", { section: "networking" }),
    negative: diffEntry("ingressClass", { section: "networking" }),
  },
  {
    matcher: "dbSize",
    positive: diffEntry("dbSize", { section: "storageRuntime" }),
    negative: diffEntry("runtimeClass", { section: "storageRuntime" }),
  },
  {
    matcher: "backupTtl",
    positive: diffEntry("backupTtl", { section: "storageRuntime" }),
    negative: diffEntry("dbSize", { section: "storageRuntime" }),
  },
  {
    matcher: "standardStorage.storageClass",
    positive: diffEntry("standardStorage.storageClass", {
      section: "storageRuntime",
    }),
    negative: diffEntry("standardStorage", { section: "storageRuntime" }),
  },
  {
    matcher: "fastStorage",
    positive: diffEntry("fastStorage", { section: "storageRuntime" }),
    negative: diffEntry("standardStorage", { section: "storageRuntime" }),
  },
  {
    matcher: "serviceNameOverrides",
    positive: diffEntry("serviceNameOverrides", {
      section: "serviceOverrides",
    }),
    negative: diffEntry("serviceNameOverrides[api]", {
      section: "serviceOverrides",
    }),
  },
  {
    matcher: "components[*].resources.**",
    positive: diffEntry("components[web].resources.requests.cpu", {
      section: "componentOverrides",
    }),
    negative: diffEntry("components[web].envVars[FOO]", {
      section: "componentOverrides",
    }),
  },
  {
    matcher: "components[*].replicas",
    positive: diffEntry("components[web].replicas", {
      section: "componentOverrides",
      before: "3",
      after: "1",
    }),
    negative: diffEntry("components[web].image", {
      section: "componentOverrides",
    }),
  },
  {
    matcher: "components[*].envVars[*]",
    positive: diffEntry("components[web].envVars[FOO]", {
      section: "componentOverrides",
    }),
    negative: diffEntry("components[web].replicas", {
      section: "componentOverrides",
    }),
  },
  {
    matcher: "components[*].image",
    positive: diffEntry("components[web].image", {
      section: "componentOverrides",
    }),
    negative: diffEntry("components[web]", { section: "componentOverrides" }),
  },
  {
    matcher: "components[*].command",
    positive: diffEntry("components[web].command", {
      section: "componentOverrides",
    }),
    negative: diffEntry("components[web].args", {
      section: "componentOverrides",
    }),
  },
  {
    matcher: "components[*].args",
    positive: diffEntry("components[web].args", {
      section: "componentOverrides",
    }),
    negative: diffEntry("components[web].command", {
      section: "componentOverrides",
    }),
  },
];

describe("impact-rules.ts: every shipped rule has positive + negative coverage", () => {
  // Sanity: the test table must cover every matcher in `impactRules`.
  it("covers every shipped rule", () => {
    const covered = new Set(ruleCases.map((c) => c.matcher));
    for (const rule of impactRules) {
      expect(covered.has(rule.matcher)).toBe(true);
    }
  });

  for (const ruleCase of ruleCases) {
    it(`rule "${ruleCase.matcher}" fires on a matching diff`, () => {
      const rule = impactRules.find((r) => r.matcher === ruleCase.matcher);
      expect(rule).toBeDefined();
      const summary = evaluateImpact(asDiff([ruleCase.positive]), [rule!]);
      expect(summary.entries).toHaveLength(1);
      expect(summary.entries[0].consequence).toBe(
        rule!.describe
          ? rule!.describe(ruleCase.positive, {})
          : rule!.consequence,
      );
      expect(summary.entries[0].triggeringPaths).toContain(
        ruleCase.positive.path,
      );
    });

    it(`rule "${ruleCase.matcher}" does NOT fire on a non-matching diff`, () => {
      const rule = impactRules.find((r) => r.matcher === ruleCase.matcher);
      expect(rule).toBeDefined();
      const summary = evaluateImpact(asDiff([ruleCase.negative]), [rule!]);
      expect(summary.entries).toEqual([]);
    });
  }
});

// ---------------------------------------------------------------------------
// End-to-end: every path `diff()` can emit must be explicable by a rule
// ---------------------------------------------------------------------------

describe("impact-rules.ts: backup retention TTL (016)", () => {
  it("attaches a consequence to a real backupTtl diff entry", () => {
    // Regression guard: `config-diff` emits a `storageRuntime`/`backupTtl`
    // entry, but no rule matched it, so the drawer rendered a diff row with
    // an empty consequence list. Drive the full pipeline — real `diff()`
    // output through the shipped rule table — rather than a hand-built
    // DiffEntry, so a future rename of either side is caught.
    const result = diff({ backupTtl: "720h" }, { backupTtl: "2160h" }, []);
    expect(result.entries.map((e) => e.path)).toContain("backupTtl");

    const summary = evaluateImpact(result, impactRules);
    expect(summary.entries).toHaveLength(1);
    expect(summary.entries[0].triggeringPaths).toEqual(["backupTtl"]);
  });

  it("states that the change affects future backups only (FR-009)", () => {
    // Velero freezes a backup's expiration at creation time, so an operator
    // shortening retention must not be led to believe existing backups will
    // be culled sooner. The consequence text carries that guarantee.
    const rule = impactRules.find((r) => r.matcher === "backupTtl");
    expect(rule).toBeDefined();
    expect(rule!.consequence).toMatch(/future backups only/);
    expect(rule!.consequence).toMatch(/already created/);
  });

  it("is informational — no workload disruption", () => {
    // Retention is metadata on future Velero Backup objects: no pod is
    // recreated, no volume reprovisioned, nothing is deleted that would
    // not have been deleted anyway. That is the same blast radius as
    // `standardStorage.storageClass`, which is likewise informational.
    const rule = impactRules.find((r) => r.matcher === "backupTtl");
    expect(rule!.severity).toBe("informational");
    const summary = evaluateImpact(
      asDiff([diffEntry("backupTtl", { section: "storageRuntime" })]),
      impactRules,
    );
    expect(summary.topSeverity).toBe("informational");
  });
});

describe("impact-rules.ts: replica changes (023)", () => {
  const replicas = (before: string, after: string, component = "server") =>
    diffEntry(`components[${component}].replicas`, {
      section: "componentOverrides",
      before,
      after,
    });
  const context = {
    replicaDefaults: new Map<string, number | null>([
      ["server", 1],
      ["worker", null],
    ]),
  };

  it.each([
    ["3", "1", "server: 3 → 1 pod"],
    ["1", "4", "server: 1 → 4 pods"],
    ["", "3", "server: 1 → 3 pods"],
    ["3", "", "server: 3 → 1 pod"],
  ])("describes %s → %s on server", (before, after, expected) => {
    const summary = evaluateImpact(
      asDiff([replicas(before, after)]),
      impactRules,
      context,
    );
    expect(summary.entries.map((e) => e.consequence)).toEqual([expected]);
  });

  it("names the chart's count when no driver default applies", () => {
    const summary = evaluateImpact(
      asDiff([replicas("", "2", "worker"), replicas("5", "", "web")]),
      impactRules,
      context,
    );
    expect(summary.entries.map((e) => e.consequence)).toEqual([
      "worker: the chart's count → 2 pods",
      "web: 5 pods → the chart's count",
    ]);
  });

  it("gives each component its own line from a real diff", () => {
    const result = diff(
      { components: [{ name: "server", replicas: 3 }] },
      {
        components: [
          { name: "server", replicas: 1 },
          { name: "worker", replicas: 2 },
        ],
      },
      [],
    );
    const summary = evaluateImpact(result, impactRules, context);
    expect(summary.entries.map((e) => e.consequence)).toEqual([
      "server: 3 → 1 pod",
      "worker: the chart's count → 2 pods",
    ]);
  });
});
