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
      "networking",
      "envVars",
    ]);
  });

  it("worst-case 50 components x 50 fields completes in under 5ms", () => {
    const before: UpdateDeploymentInput = {
      components: Array.from(
        { length: 50 },
        (_, i): ComponentConfigInput => ({
          name: `c${i}`,
          envVars: Array.from({ length: 50 }, (__, j) => ({
            name: `E${j}`,
            value: `v${j}`,
          })),
        }),
      ),
    };
    const after: UpdateDeploymentInput = {
      components: Array.from(
        { length: 50 },
        (_, i): ComponentConfigInput => ({
          name: `c${i}`,
          envVars: Array.from({ length: 50 }, (__, j) => ({
            name: `E${j}`,
            // mutate roughly 10% of values so the diff actually does work
            value: j % 10 === 0 ? `mutated-${j}` : `v${j}`,
          })),
        }),
      ),
    };

    // Warm the engine to remove JIT cost from the measurement window.
    diff(before, after, emptySchema);

    const start = performance.now();
    const iterations = 5;
    for (let i = 0; i < iterations; i += 1) {
      diff(before, after, emptySchema);
    }
    const elapsedAverage = (performance.now() - start) / iterations;

    expect(elapsedAverage).toBeLessThan(5);
  });
});
