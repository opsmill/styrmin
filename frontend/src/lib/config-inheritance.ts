import type { UpdateDeploymentInput } from "@/generated/graphql";

import { diff } from "./config-diff";
import type {
  DriverParameterSchema,
  InheritanceState,
  SectionId,
} from "./configuration-types";
import { SECTION_ORDER } from "./configuration-types";

/**
 * Compute one `InheritanceState` per `SectionId` by diffing the
 * deployment input against the parent environment input (both projected
 * through `deploymentConfigToInput()`).
 *
 * Section semantics:
 *  - `identity`: the deployment name lives only on the deployment row
 *    (not on the environment), so this section is always `inherited` —
 *    there is nothing to inherit from and nothing to override.
 *  - `driverParameters`: parameters live on the deployment, not on the
 *    environment. A parameter is `overridden` when the deployment value
 *    differs from its driver default (or there is no driver default).
 *  - `componentOverrides`: components live on the deployment only. The
 *    section is `inherited` only when zero per-component blocks exist on
 *    the deployment input.
 *  - All other sections: `inherited` when every leaf matches the
 *    environment's leaf, else `overridden` with the override count.
 */
export function computeInheritance(
  deployment: UpdateDeploymentInput,
  environment: UpdateDeploymentInput,
  driverSchema: DriverParameterSchema,
): Map<SectionId, InheritanceState> {
  const result = new Map<SectionId, InheritanceState>();

  // Diff the deployment against the environment. `diff` returns entries
  // attributed to a `SectionId`, so the override count per section is
  // just a `filter().length`.
  const d = diff(environment, deployment, driverSchema);

  // Driver Parameters: ignore the environment-side diff (env has none) —
  // compare the deployment's parameter values against the driver defaults.
  const driverParametersOverrideCount = countDriverParameterOverrides(
    deployment,
    driverSchema,
  );

  // Component Overrides: inherited only when zero per-component blocks
  // exist on the deployment input. Any deployment-level component block
  // is, by definition, a deployment-only override (environments do not
  // carry per-component blocks).
  const componentBlocks = deployment.components ?? [];
  const componentOverrideCount = componentBlocks.length;

  // Identity: the deployment's name is not inherited from the environment.
  // We model this section as always `inherited` so it doesn't render an
  // "overridden" badge on a deployment that simply has a name.
  for (const section of SECTION_ORDER) {
    if (section === "identity") {
      result.set("identity", { kind: "inherited" });
      continue;
    }
    if (section === "driverParameters") {
      result.set(
        "driverParameters",
        driverParametersOverrideCount > 0
          ? {
              kind: "overridden",
              overrideCount: driverParametersOverrideCount,
            }
          : { kind: "inherited" },
      );
      continue;
    }
    if (section === "componentOverrides") {
      result.set(
        "componentOverrides",
        componentOverrideCount > 0
          ? { kind: "overridden", overrideCount: componentOverrideCount }
          : { kind: "inherited" },
      );
      continue;
    }
    const overrideCount = d.entries.filter((e) => e.section === section).length;
    result.set(
      section,
      overrideCount > 0
        ? { kind: "overridden", overrideCount }
        : { kind: "inherited" },
    );
  }

  return result;
}

function countDriverParameterOverrides(
  deployment: UpdateDeploymentInput,
  driverSchema: DriverParameterSchema,
): number {
  const params = deployment.parameters ?? [];
  if (params.length === 0) return 0;
  const defaults = new Map(
    driverSchema.map((p) => [p.name, p.default] as const),
  );
  let count = 0;
  for (const p of params) {
    const def = defaults.get(p.name);
    if (!sameJsonValue(def, p.value)) count += 1;
  }
  return count;
}

function sameJsonValue(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (a == null && b == null) return true;
  if (a == null || b == null) return false;
  return JSON.stringify(a) === JSON.stringify(b);
}
