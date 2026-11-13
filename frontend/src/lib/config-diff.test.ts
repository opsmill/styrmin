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

  it.each([
    ["add", undefined, "app:{{ app.version }}", "", "app:{{ app.version }}"],
    ["change", "app:1", "app:2", "app:1", "app:2"],
    ["remove", "app:1", null, "app:1", ""],
    ["remove", "app:1", "", "app:1", ""],
  ] as const)(
    "emits an image %s entry for %j -> %j on an existing block (018)",
    (kind, beforeImage, afterImage, beforeText, afterText) => {
      const before: UpdateDeploymentInput = {
        components: [{ name: "server", envVars: [], image: beforeImage }],
      };
      const after: UpdateDeploymentInput = {
        components: [{ name: "server", envVars: [], image: afterImage }],
      };
      const result = diff(before, after, emptySchema);
      expect(result.entries).toEqual([
        {
          section: "componentOverrides",
          path: "components[server].image",
          label: 'Component "server" image',
          before: beforeText,
          after: afterText,
          kind,
        },
      ]);
      expect(result.hasChanges).toBe(true);
    },
  );

  it("treats an empty image field like an unset one", () => {
    const before: UpdateDeploymentInput = {
      components: [{ name: "server", envVars: [] }],
    };
    const after: UpdateDeploymentInput = {
      components: [{ name: "server", envVars: [], image: "" }],
    };
    expect(diff(before, after, emptySchema).hasChanges).toBe(false);
  });

  it.each([
    ["add", undefined, 2, "", "2"],
    ["change", 2, 3, "2", "3"],
    ["remove", 3, null, "3", ""],
    ["remove", 3, undefined, "3", ""],
  ] as const)(
    "emits a replicas %s entry for %j -> %j on an existing block",
    (kind, beforeReplicas, afterReplicas, beforeText, afterText) => {
      const before: UpdateDeploymentInput = {
        components: [{ name: "server", envVars: [], replicas: beforeReplicas }],
      };
      const after: UpdateDeploymentInput = {
        components: [{ name: "server", envVars: [], replicas: afterReplicas }],
      };
      const result = diff(before, after, emptySchema);
      expect(result.entries).toEqual([
        {
          section: "componentOverrides",
          path: "components[server].replicas",
          label: 'Component "server" replicas',
          before: beforeText,
          after: afterText,
          kind,
        },
      ]);
      expect(result.sectionsChanged).toEqual(["componentOverrides"]);
    },
  );

  it("treats a null replicas field like an unset one", () => {
    const before: UpdateDeploymentInput = {
      components: [{ name: "server", envVars: [] }],
    };
    const after: UpdateDeploymentInput = {
      components: [{ name: "server", envVars: [], replicas: null }],
    };
    expect(diff(before, after, emptySchema).hasChanges).toBe(false);
  });

  it.each([
    ["command", "add", undefined, ["/bin/sh"]],
    ["command", "change", ["/bin/sh"], ["/bin/bash"]],
    ["command", "remove", ["/bin/sh"], []],
    ["args", "add", [], ["-v"]],
    ["args", "change", ["-v"], ["-v", "-x"]],
    ["args", "remove", ["-v"], undefined],
  ] as const)(
    "emits a %s %s entry for %j -> %j on an existing block",
    (field, kind, beforeList, afterList) => {
      const before: UpdateDeploymentInput = {
        components: [{ name: "server", envVars: [], [field]: beforeList }],
      };
      const after: UpdateDeploymentInput = {
        components: [{ name: "server", envVars: [], [field]: afterList }],
      };
      const text = (list: readonly string[] | undefined) =>
        list?.length ? JSON.stringify(list) : "";
      expect(diff(before, after, emptySchema).entries).toEqual([
        {
          section: "componentOverrides",
          path: `components[server].${field}`,
          label: `Component "server" ${field}`,
          before: text(beforeList),
          after: text(afterList),
          kind,
        },
      ]);
    },
  );

  it("treats an empty command or args list like an unset one", () => {
    const before: UpdateDeploymentInput = {
      components: [{ name: "server", envVars: [] }],
    };
    const after: UpdateDeploymentInput = {
      components: [{ name: "server", envVars: [], command: [], args: [] }],
    };
    expect(diff(before, after, emptySchema).hasChanges).toBe(false);
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

// ---------------------------------------------------------------------------
// Service ingress overrides (#598, US3). Written before the diff learns the
// `services` field (T046): until then `diff()` ignores it and reports nothing.
// ---------------------------------------------------------------------------

describe("config-diff: service ingress overrides", () => {
  const taskManager = {
    name: "task-manager",
    ingressClass: "tailscale",
    fqdnSuffix: "tailnet.example.ts.net",
  };

  it("reports a new override as one add entry for the class and one for the suffix, in the Services section", () => {
    const result = diff({}, { services: [taskManager] }, emptySchema);

    expect(result.entries).toEqual([
      {
        section: "serviceOverrides",
        path: "services[task-manager].ingressClass",
        label: 'Service "task-manager" ingress class',
        before: "",
        after: "tailscale",
        kind: "add",
      },
      {
        section: "serviceOverrides",
        path: "services[task-manager].fqdnSuffix",
        label: 'Service "task-manager" FQDN suffix',
        before: "",
        after: "tailnet.example.ts.net",
        kind: "add",
      },
    ]);
    expect(result.sectionsChanged).toEqual(["serviceOverrides"]);
  });

  it("reports a cleared override as remove entries", () => {
    const result = diff(
      { services: [taskManager] },
      { services: [] },
      emptySchema,
    );

    expect(
      result.entries.map((e) => [e.path, e.kind, e.before, e.after]),
    ).toEqual([
      ["services[task-manager].ingressClass", "remove", "tailscale", ""],
      [
        "services[task-manager].fqdnSuffix",
        "remove",
        "tailnet.example.ts.net",
        "",
      ],
    ]);
  });

  it("reports only the field that changed", () => {
    const result = diff(
      { services: [taskManager] },
      { services: [{ ...taskManager, ingressClass: "traefik" }] },
      emptySchema,
    );

    expect(result.entries).toEqual([
      {
        section: "serviceOverrides",
        path: "services[task-manager].ingressClass",
        label: 'Service "task-manager" ingress class',
        before: "tailscale",
        after: "traefik",
        kind: "change",
      },
    ]);
  });

  it("keys the rows by service name, so a reorder is no change and each service has its own entries", () => {
    const web = {
      name: "web",
      ingressClass: "traefik",
      fqdnSuffix: "web.example.com",
    };

    expect(
      diff(
        { services: [taskManager, web] },
        { services: [web, taskManager] },
        emptySchema,
      ).hasChanges,
    ).toBe(false);

    const result = diff(
      { services: [taskManager, web] },
      { services: [taskManager, { ...web, fqdnSuffix: "other.example.com" }] },
      emptySchema,
    );
    expect(result.entries.map((e) => e.path)).toEqual([
      "services[web].fqdnSuffix",
    ]);
  });

  it.each([
    ["no row", undefined],
    ["a row with no value", { name: "task-manager" }],
    [
      "a row with null values",
      { name: "task-manager", ingressClass: null, fqdnSuffix: null },
    ],
    [
      "a row with empty strings, as an emptied field holds",
      { name: "task-manager", ingressClass: "", fqdnSuffix: "" },
    ],
  ])("treats %s as no override", (_what, row) => {
    const empty: UpdateDeploymentInput = row ? { services: [row] } : {};

    expect(diff({}, empty, emptySchema).hasChanges).toBe(false);
    expect(diff(empty, {}, emptySchema).hasChanges).toBe(false);
    // An emptied field next to a stored override is a removal, not a change to "".
    const emptied = diff(
      { services: [taskManager] },
      { services: [{ ...taskManager, ingressClass: "" }] },
      emptySchema,
    );
    expect(emptied.entries.map((e) => [e.path, e.kind])).toEqual([
      ["services[task-manager].ingressClass", "remove"],
    ]);
  });

  it("does not report service name overrides when only ingress overrides change", () => {
    const result = diff(
      {
        serviceNameOverrides: [{ driverServiceName: "api", overrideName: "x" }],
      },
      {
        serviceNameOverrides: [{ driverServiceName: "api", overrideName: "x" }],
        services: [taskManager],
      },
      emptySchema,
    );

    expect(result.entries.map((e) => e.path)).toEqual([
      "services[task-manager].ingressClass",
      "services[task-manager].fqdnSuffix",
    ]);
  });
});

it("shows a TLS-only service ingress change for review", () => {
  const entries = diff(
    {},
    { services: [{ name: "task-manager", tls: true }] },
    emptySchema,
  );
  expect(
    entries.entries.some(
      (entry) => entry.path === "services[task-manager].tls",
    ),
  ).toBe(true);
});
