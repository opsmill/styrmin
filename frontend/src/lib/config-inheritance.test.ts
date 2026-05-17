import { describe, expect, it } from "vitest";

import type {
  ParameterDefinition,
  UpdateDeploymentInput,
} from "@/generated/graphql";

import { computeInheritance } from "./config-inheritance";
import type {
  DriverParameterSchema,
  InheritanceState,
  SectionId,
} from "./configuration-types";
import { SECTION_ORDER } from "./configuration-types";

const emptySchema: DriverParameterSchema = [];

// The codegen narrows the JSON scalar to `Record<string, unknown>`. Real
// parameter values and defaults are primitives in the test fixtures below;
// cast at the construction site. See generated/graphql.ts `Scalars.JSON`.
const j = <T>(v: T) => v as unknown as Record<string, unknown>;

function expectInherited(
  result: Map<SectionId, InheritanceState>,
  section: SectionId,
) {
  expect(result.get(section)).toEqual({ kind: "inherited" });
}

describe("computeInheritance", () => {
  it("returns `inherited` for every section when deployment matches environment", () => {
    const env: UpdateDeploymentInput = {
      ingressClass: "nginx",
      envVars: [{ name: "FOO", value: "bar" }],
      fqdnSuffix: ".prod.example.com",
    };
    // Deployment carries the same env-level fields and nothing else.
    const dep: UpdateDeploymentInput = { ...env };
    const result = computeInheritance(dep, env, emptySchema);
    for (const section of SECTION_ORDER) {
      expect(result.get(section)).toEqual({ kind: "inherited" });
    }
  });

  it("reports `overridden` with the correct count when a section diverges", () => {
    const env: UpdateDeploymentInput = {
      ingressClass: "nginx",
      fqdnSuffix: ".prod.example.com",
      envVars: [{ name: "INHERITED", value: "1" }],
    };
    const dep: UpdateDeploymentInput = {
      ingressClass: "traefik", // 1 override on networking
      fqdnSuffix: ".staging.example.com", // 2 overrides on networking
      envVars: [
        { name: "INHERITED", value: "1" },
        { name: "EXTRA", value: "2" }, // 1 override on envVars
      ],
    };
    const result = computeInheritance(dep, env, emptySchema);
    expect(result.get("networking")).toEqual({
      kind: "overridden",
      overrideCount: 2,
    });
    expect(result.get("envVars")).toEqual({
      kind: "overridden",
      overrideCount: 1,
    });
    // Sections that didn't diverge remain inherited.
    expectInherited(result, "storageRuntime");
    expectInherited(result, "serviceOverrides");
  });

  it("Driver Parameters always reports `overridden` when a parameter differs from its driver default", () => {
    const driverSchema: DriverParameterSchema = [
      {
        __typename: "ParameterDefinition",
        name: "replicas",
        label: "Replicas",
        kind: "integer",
        default: j(1),
        values: null,
      } as ParameterDefinition,
      {
        __typename: "ParameterDefinition",
        name: "logLevel",
        label: "Log level",
        kind: "string",
        default: j("info"),
        values: null,
      } as ParameterDefinition,
    ];
    // Even though the environment doesn't carry parameters at all,
    // the deployment-vs-default comparison must catch the divergence.
    const env: UpdateDeploymentInput = {};
    const dep: UpdateDeploymentInput = {
      parameters: [
        { name: "replicas", value: j(3) }, // != default 1
        { name: "logLevel", value: j("info") }, // == default
      ],
    };
    const result = computeInheritance(dep, env, driverSchema);
    expect(result.get("driverParameters")).toEqual({
      kind: "overridden",
      overrideCount: 1,
    });
  });

  it("Driver Parameters reports `inherited` when every parameter matches its driver default", () => {
    const driverSchema: DriverParameterSchema = [
      {
        __typename: "ParameterDefinition",
        name: "replicas",
        label: "Replicas",
        kind: "integer",
        default: j(1),
        values: null,
      } as ParameterDefinition,
    ];
    const dep: UpdateDeploymentInput = {
      parameters: [{ name: "replicas", value: j(1) }],
    };
    const result = computeInheritance(dep, {}, driverSchema);
    expectInherited(result, "driverParameters");
  });

  it("Component Overrides is `inherited` only when zero per-component blocks exist", () => {
    const dep: UpdateDeploymentInput = {};
    expectInherited(
      computeInheritance(dep, {}, emptySchema),
      "componentOverrides",
    );

    const withBlocks: UpdateDeploymentInput = {
      components: [
        { name: "web", envVars: [{ name: "X", value: "1" }] },
        { name: "api", envVars: [] },
      ],
    };
    const result = computeInheritance(withBlocks, {}, emptySchema);
    expect(result.get("componentOverrides")).toEqual({
      kind: "overridden",
      overrideCount: 2,
    });
  });

  it("Identity section is always `inherited`", () => {
    // Deployment names are deployment-only state, not "overrides" of any
    // environment-level field — we don't want the badge to flash whenever
    // a deployment has a name.
    const dep: UpdateDeploymentInput = { name: "my-deployment" };
    const result = computeInheritance(dep, {}, emptySchema);
    expectInherited(result, "identity");
  });
});
