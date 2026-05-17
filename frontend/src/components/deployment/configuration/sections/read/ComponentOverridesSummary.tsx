import type {
  ComponentConfigInput,
  GetDeploymentQuery,
  UpdateDeploymentInput,
} from "@/generated/graphql";
import type { InheritanceState } from "@/lib/configuration-types";
import { ConfigSummaryCard } from "../../ConfigSummaryCard";

type DeploymentComponent = NonNullable<
  GetDeploymentQuery["deployment"]
>["components"][number];

interface Props {
  current: UpdateDeploymentInput;
  environment: UpdateDeploymentInput;
  inheritance: InheritanceState;
  components: readonly DeploymentComponent[];
}

/**
 * One-line override summary for a component override block. Each scope
 * the block carries is rendered as a small token; today the backend
 * `ComponentConfigInput` only carries env vars, but the future-extension
 * hook (resources / replicas) plugs in here without touching callers.
 */
function summariseOverride(block: ComponentConfigInput): string {
  const parts: string[] = [];
  const envVarCount = block.envVars?.length ?? 0;
  if (envVarCount > 0) {
    parts.push(`${envVarCount} env var${envVarCount === 1 ? "" : "s"}`);
  }
  if (parts.length === 0) return "override (empty)";
  return parts.join(" · ");
}

/**
 * Read-only summary for `Component Overrides` (FR-009).
 *
 * Renders every component declared by the deployment's currently-pinned
 * driver. A component with a matching entry in `current.components` is
 * marked overridden (green dot + one-line scope summary); a component
 * without an entry is muted ("no override").
 *
 * `environment` is unused for this section — component overrides live
 * only on the deployment row — but it's accepted to keep the section
 * summary contract uniform with the other six cards.
 */
export function ComponentOverridesSummary({
  current,
  inheritance,
  components,
}: Props) {
  const overrideMap = new Map<string, ComponentConfigInput>(
    (current.components ?? []).map((c) => [c.name, c] as const),
  );

  return (
    <ConfigSummaryCard title="Component Overrides" inheritance={inheritance}>
      {components.length === 0 ? (
        <p className="text-sm italic text-muted-foreground">
          driver declares no components
        </p>
      ) : (
        <ul className="space-y-1.5">
          {components.map((component) => {
            const override = overrideMap.get(component.name);
            const isOverridden = override !== undefined;
            return (
              <li
                key={component.id}
                data-testid="component-override-row"
                data-component={component.name}
                data-overridden={isOverridden ? "true" : "false"}
                className="flex items-center gap-2 text-sm"
              >
                <span
                  aria-hidden="true"
                  className={
                    isOverridden
                      ? "h-2 w-2 shrink-0 rounded-full bg-emerald-500"
                      : "h-2 w-2 shrink-0 rounded-full bg-slate-300 dark:bg-slate-600"
                  }
                />
                <span className="font-mono text-xs text-slate-900 dark:text-slate-100">
                  {component.name}
                </span>
                <span
                  className={
                    isOverridden
                      ? "ml-2 truncate text-xs text-blue-700 dark:text-blue-300"
                      : "ml-2 truncate text-xs italic text-muted-foreground"
                  }
                >
                  {isOverridden && override
                    ? summariseOverride(override)
                    : "no override"}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </ConfigSummaryCard>
  );
}
