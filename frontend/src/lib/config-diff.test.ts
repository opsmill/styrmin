import { describe, expect, it } from "vitest";

import type {
  ComponentConfigInput,
  EnvVarInput,
  UpdateDeploymentInput,
} from "@/generated/graphql";

import { diff } from "./config-diff";
import type { DriverParameterSchema } from "./configuration-types";

const emptySchema: DriverParameterSchema = [];

function emptyInput(): UpdateDeploymentInput {
  return {};
}

describe("config-diff: diff()", () => {
  it("returns an empty diff for identical inputs", () => {
    const result = diff(emptyInput(), emptyInput(), emptySchema);
    expect(result.entries).toEqual([]);
    expect(result.hasChanges).toBe(false);
    expect(result.sectionsChanged).toEqual([]);
  });

  it("returns an empty diff when null/undefined fields are equivalent", () => {
    const before: UpdateDeploymentInput = {
      name: null,
      envVars: undefined,
    };
    const after: UpdateDeploymentInput = {
      // Same effective state — undefined everywhere.
    };
    const result = diff(before, after, emptySchema);
    expect(result.entries).toEqual([]);
    expect(result.hasChanges).toBe(false);
  });

  it("produces a single `change` entry for a scalar update", () => {
    const before: UpdateDeploymentInput = { name: "old-name" };
    const after: UpdateDeploymentInput = { name: "new-name" };
    const result = diff(before, after, emptySchema);
    expect(result.hasChanges).toBe(true);
    expect(result.entries).toEqual([
      {
        section: "identity",
        path: "name",
        label: "Name",
        before: "old-name",
        after: "new-name",
        kind: "change",
      },
    ]);
    expect(result.sectionsChanged).toEqual(["identity"]);
  });

  it("produces add/remove entries on env-var changes keyed by name", () => {
    const before: UpdateDeploymentInput = {
      envVars: [
        { name: "KEEP", value: "1" },
        { name: "DROP", value: "2" },
      ],
    };
    const after: UpdateDeploymentInput = {
      envVars: [
        { name: "KEEP", value: "1" },
        { name: "NEW", value: "3" },
      ],
    };
    const result = diff(before, after, emptySchema);
    const byPath = new Map(result.entries.map((e) => [e.path, e]));
    expect(byPath.get("envVars[DROP]")).toMatchObject({
      kind: "remove",
      section: "envVars",
      before: "2",
      after: "",
    });
    expect(byPath.get("envVars[NEW]")).toMatchObject({
      kind: "add",
      section: "envVars",
      before: "",
      after: "3",
    });
    expect(byPath.has("envVars[KEEP]")).toBe(false);
  });

  it("reorders env vars produce no diff entries", () => {
    const original: EnvVarInput[] = [
      { name: "A", value: "1" },
      { name: "B", value: "2" },
      { name: "C", value: "3" },
    ];
    const reordered: EnvVarInput[] = [
      { name: "C", value: "3" },
      { name: "A", value: "1" },
      { name: "B", value: "2" },
    ];
    const result = diff(
      { envVars: original },
      { envVars: reordered },
      emptySchema,
    );
    expect(result.entries).toEqual([]);
  });

  it("env-var value change emits a single `change` entry keyed by name", () => {
    const before: UpdateDeploymentInput = {
      envVars: [{ name: "LOG_LEVEL", value: "info" }],
    };
    const after: UpdateDeploymentInput = {
      envVars: [{ name: "LOG_LEVEL", value: "debug" }],
    };
    const result = diff(before, after, emptySchema);
    expect(result.entries).toEqual([
      {
        section: "envVars",
        path: "envVars[LOG_LEVEL]",
        label: 'Env var "LOG_LEVEL"',
        before: "info",
        after: "debug",
        kind: "change",
      },
    ]);
  });

  it("attributes nested component override changes to the componentOverrides section", () => {
    const before: UpdateDeploymentInput = {
      components: [
        { name: "rate-limiter", envVars: [{ name: "BURST", value: "10" }] },
      ],
    };
    const after: UpdateDeploymentInput = {
      components: [
        { name: "rate-limiter", envVars: [{ name: "BURST", value: "20" }] },
      ],
    };
    const result = diff(before, after, emptySchema);
    expect(result.entries).toHaveLength(1);
    const [entry] = result.entries;
    expect(entry.section).toBe("componentOverrides");
    expect(entry.path).toBe("components[rate-limiter].envVars[BURST]");
    expect(entry.kind).toBe("change");
    expect(entry.before).toBe("10");
    expect(entry.after).toBe("20");
    expect(result.sectionsChanged).toEqual(["componentOverrides"]);
  });

  it("treats toleration reorders as no-op, but a key-change as add+remove", () => {
    const before: UpdateDeploymentInput = {
      scheduling: {
        tolerations: [
          {
            key: "gpu",
            operator: "EQUAL",
            value: "true",
            effect: "NO_SCHEDULE",
          },
          { key: "spot", operator: "EXISTS", effect: "PREFER_NO_SCHEDULE" },
        ],
      },
    };
    const reordered: UpdateDeploymentInput = {
      scheduling: {
        tolerations: [
          { key: "spot", operator: "EXISTS", effect: "PREFER_NO_SCHEDULE" },
          {
            key: "gpu",
            operator: "EQUAL",
            value: "true",
            effect: "NO_SCHEDULE",
          },
        ],
      },
    };
    expect(diff(before, reordered, emptySchema).entries).toEqual([]);
  });

  it("emits granular toleration effect changes keyed by toleration key", () => {
    const before: UpdateDeploymentInput = {
      scheduling: {
        tolerations: [
          {
            key: "gpu",
            operator: "EQUAL",
            value: "true",
            effect: "NO_SCHEDULE",
          },
        ],
      },
    };
    const after: UpdateDeploymentInput = {
      scheduling: {
        tolerations: [
          {
            key: "gpu",
            operator: "EQUAL",
            value: "true",
            effect: "NO_EXECUTE",
          },
        ],
      },
    };
    const result = diff(before, after, emptySchema);
    expect(result.entries).toHaveLength(1);
    expect(result.entries[0]).toMatchObject({
      section: "scheduling",
      path: "scheduling.tolerations[gpu].effect",
      before: "NO_SCHEDULE",
      after: "NO_EXECUTE",
      kind: "change",
    });
  });

  it("scheduling.resources changes emit one entry per leaf path", () => {
    const before: UpdateDeploymentInput = {
      scheduling: {
        resources: {
          requests: { cpu: "100m", memory: "128Mi" },
          limits: { cpu: "500m" },
        },
      },
    };
    const after: UpdateDeploymentInput = {
      scheduling: {
        resources: {
          requests: { cpu: "200m", memory: "128Mi" },
          limits: { cpu: "500m", memory: "1Gi" },
        },
      },
    };
    const result = diff(before, after, emptySchema);
    const paths = result.entries.map((e) => e.path).sort();
    expect(paths).toEqual([
      "scheduling.resources.limits.memory",
      "scheduling.resources.requests.cpu",
    ]);
    for (const entry of result.entries) {
      expect(entry.section).toBe("scheduling");
    }
  });

  it("ipWhitelist changes are membership-only (set semantics)", () => {
    const before: UpdateDeploymentInput = {
      ipWhitelist: ["10.0.0.0/8", "192.168.0.0/16"],
    };
    const reordered: UpdateDeploymentInput = {
      ipWhitelist: ["192.168.0.0/16", "10.0.0.0/8"],
    };
    expect(diff(before, reordered, emptySchema).entries).toEqual([]);

    const expanded: UpdateDeploymentInput = {
      ipWhitelist: ["10.0.0.0/8", "192.168.0.0/16", "172.16.0.0/12"],
    };
    const result = diff(before, expanded, emptySchema);
    expect(result.entries).toHaveLength(1);
    expect(result.entries[0].path).toBe("ipWhitelist");
    expect(result.entries[0].section).toBe("networking");
  });

  it("parameters are diffed keyed by name and attributed to driverParameters", () => {
    const before: UpdateDeploymentInput = {
      parameters: [
        { name: "replicas", value: 1 as unknown as Record<string, unknown> },
      ],
    };
    const after: UpdateDeploymentInput = {
      parameters: [
        { name: "replicas", value: 3 as unknown as Record<string, unknown> },
      ],
    };
    const result = diff(before, after, emptySchema);
    expect(result.entries).toHaveLength(1);
    expect(result.entries[0]).toMatchObject({
      section: "driverParameters",
      path: "parameters.replicas",
      before: "1",
      after: "3",
      kind: "change",
    });
  });

  it("service overrides are diffed keyed by driverServiceName", () => {
    const before: UpdateDeploymentInput = {
      serviceNameOverrides: [
        { driverServiceName: "api", overrideName: "old-api" },
      ],
    };
    const after: UpdateDeploymentInput = {
      serviceNameOverrides: [
        { driverServiceName: "api", overrideName: "new-api" },
      ],
    };
    const result = diff(before, after, emptySchema);
    expect(result.entries).toHaveLength(1);
    expect(result.entries[0]).toMatchObject({
      section: "serviceOverrides",
      path: "serviceNameOverrides[api]",
      before: "old-api",
      after: "new-api",
      kind: "change",
    });
  });

  it("attributes backupTtl changes to the storageRuntime section", () => {
    // 016 / FR-005: a retention change must be visible in the pre-save diff,
    // otherwise an operator cannot tell that the deployment's backup
    // lifetime is about to change.
    const before: UpdateDeploymentInput = { backupTtl: "720h" };
    const after: UpdateDeploymentInput = { backupTtl: "8760h" };
    const result = diff(before, after, emptySchema);
    expect(result.entries).toHaveLength(1);
    expect(result.entries[0]).toMatchObject({
      section: "storageRuntime",
      path: "backupTtl",
      label: "Backup retention TTL",
      before: "720h",
      after: "8760h",
      kind: "change",
    });
    expect(result.sectionsChanged).toEqual(["storageRuntime"]);
  });

  it("emits an add entry when backupTtl goes from unset to set", () => {
    const result = diff({}, { backupTtl: "2160h" }, emptySchema);
    expect(result.entries).toHaveLength(1);
    expect(result.entries[0]).toMatchObject({
      section: "storageRuntime",
      path: "backupTtl",
      before: "",
      after: "2160h",
      kind: "add",
    });
  });

  it("attributes fastStorage changes to the storageRuntime section", () => {
    // Pre-existing gap: `fastStorage` was never diffed, so changing the fast
    // storage class produced an empty diff — the review dialog told the
    // operator "no changes" while a real change was queued for save.
    const before: UpdateDeploymentInput = {
      fastStorage: { storageClass: "local-nvme" },
    };
    const after: UpdateDeploymentInput = {
      fastStorage: { storageClass: "premium-ssd" },
    };
    const result = diff(before, after, emptySchema);
    expect(result.entries).toHaveLength(1);
    expect(result.entries[0]).toMatchObject({
      section: "storageRuntime",
      path: "fastStorage",
      label: "Fast storage",
      kind: "change",
    });
    expect(result.entries[0].before).toContain("local-nvme");
    expect(result.entries[0].after).toContain("premium-ssd");
    expect(result.sectionsChanged).toEqual(["storageRuntime"]);
  });

  it("emits an add entry when fastStorage goes from unset to set", () => {
    const result = diff(
      {},
      { fastStorage: { storageClass: "local-nvme" } },
      emptySchema,
    );
    expect(result.entries).toHaveLength(1);
    expect(result.entries[0]).toMatchObject({
      section: "storageRuntime",
      path: "fastStorage",
      before: "",
      kind: "add",
    });
  });

  it("emits no fastStorage entry when the block is unchanged", () => {
    // `diffJsonObject` compares deeply, so an identical block re-submitted by
    // a form binding must not manufacture a phantom change.
    const block = { storageClass: "local-nvme" };
    const result = diff(
      { fastStorage: { ...block } },
      { fastStorage: { ...block } },
      emptySchema,
    );
    expect(result.entries).toEqual([]);
    expect(result.hasChanges).toBe(false);
  });

  it("orders sectionsChanged according to SECTION_ORDER", () => {
    const before: UpdateDeploymentInput = {};
    const after: UpdateDeploymentInput = {
      name: "x",
      envVars: [{ name: "A", value: "1" }],
      ingressClass: "nginx",
    };
    const result = diff(before, after, emptySchema);
    expect(result.sectionsChanged).toEqual([
      "identity",
      "envVars",
      "networking",
    ]);
  });

  /**
   * Build a `components` block whose env-var entries count how many times
   * `diff()` reads them.
   *
   * The count is the complexity probe: `diffComponents`/`diffEnvVars` key
   * their lookups by name, so each entry is visited a fixed number of times
   * regardless of input size. A regression to a nested scan — the O(n²) shape
   * this guard exists to catch — would read each entry once per sibling, and
   * the count would grow with the square of the input.
   */
  function countingComponents(
    componentCount: number,
    envVarCount: number,
    counter: { reads: number },
    mutate: boolean,
  ): ComponentConfigInput[] {
    return Array.from(
      { length: componentCount },
      (_, i): ComponentConfigInput => ({
        name: `c${i}`,
        envVars: Array.from({ length: envVarCount }, (__, j): EnvVarInput => {
          // Mutate roughly 10% of values so the diff actually does work.
          const resolved = mutate && j % 10 === 0 ? `mutated-${j}` : `v${j}`;
          return {
            // Both fields are counted. `name` is the important one: a nested
            // `find`-per-key scan reads it once per sibling, so it is where a
            // quadratic regression shows up, whereas `value` would still be
            // read only once per entry.
            get name() {
              counter.reads += 1;
              return `E${j}`;
            },
            get value() {
              counter.reads += 1;
              return resolved;
            },
          };
        }),
      }),
    );
  }

  /** Total env-var field reads `diff()` performs for a block of this size. */
  function envVarReads(componentCount: number, envVarCount: number): number {
    const counter = { reads: 0 };
    const before: UpdateDeploymentInput = {
      components: countingComponents(
        componentCount,
        envVarCount,
        counter,
        false,
      ),
    };
    const after: UpdateDeploymentInput = {
      components: countingComponents(
        componentCount,
        envVarCount,
        counter,
        true,
      ),
    };
    diff(before, after, emptySchema);
    return counter.reads;
  }

  // Replaces an `expect(elapsedAverage).toBeLessThan(5)` wall-clock assertion
  // that flaked on loaded machines. The intent worth keeping was never "the
  // diff takes under 5ms" — that measures the box, not the code — but "the
  // diff stays linear in the number of entries". These two tests assert that
  // directly and deterministically: no clock, no warm-up, no JIT sensitivity.
  it("visits each env-var entry a bounded number of times", () => {
    // 50 components x 50 env vars, the documented worst case.
    const entries = 50 * 50;
    const reads = envVarReads(50, 50);

    // Both sides are walked and both fields read, so a linear implementation
    // lands at ~4 reads per entry. The ceiling is deliberately loose: it
    // tolerates a refactor that reads an entry a few extra times, while a
    // nested scan over 50 siblings cannot fit under it.
    expect(reads).toBeGreaterThan(0);
    expect(reads).toBeLessThanOrEqual(entries * 12);
  });

  it("scales linearly, not quadratically, as the input doubles", () => {
    // Double the number of entries *within* each keyed list, holding the
    // component count fixed. That is the dimension the keyed lookup protects:
    // a nested scan compares every entry against every sibling, so its work
    // grows with the square of the list length. Doubling the component count
    // instead would not expose it — each component's list would stay 50 long.
    const single = envVarReads(50, 25);
    const double = envVarReads(50, 50);

    const ratio = double / single;
    // Linear ≈ 2.0, quadratic ≈ 4.0. A 3.0 ceiling separates them with room
    // to spare and, being a pure operation count, cannot drift under load.
    expect(ratio).toBeLessThan(3);
  });
});
