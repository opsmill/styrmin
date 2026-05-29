import type { GetDeploymentQuery } from "@/generated/graphql";
import { ConfigSummaryCard } from "../../ConfigSummaryCard";

type DeploymentComponent = NonNullable<
  GetDeploymentQuery["deployment"]
>["components"][number];

interface Props {
  /** Raw `Deployment.config` JSON blob (snake_case). */
  deploymentConfig: Record<string, unknown> | null | undefined;
  /**
   * Raw `Environment.config` JSON blob (snake_case). Accepted for API
   * parity with the other read summaries; components are deployment-only
   * today, so this isn't used to drive behaviour.
   */
  environmentConfig: Record<string, unknown> | null | undefined;
  /**
   * Raw `Cluster.config` JSON blob (snake_case). Accepted for API
   * parity — not used today.
   */
  clusterConfig: Record<string, unknown> | null | undefined;
  components: readonly DeploymentComponent[];
}

interface ComponentOverrideBlock {
  env_vars?: Record<string, unknown> | null;
  /** Container-override slots (014-component-container-overrides). */
  command?: string[] | null;
  args?: string[] | null;
  [key: string]: unknown;
}

/**
 * One-line override summary for a component override block. Each scope
 * the block carries is rendered as a small token; the persisted
 * `components` shape carries env vars plus the `command`/`args`
 * container overrides (014-component-container-overrides), and the
 * future-extension hook (resources / replicas) plugs in here without
 * touching callers.
 */
function summariseOverride(block: ComponentOverrideBlock): string {
  const parts: string[] = [];
  const envVars = block.env_vars;
  const envVarCount =
    envVars && typeof envVars === "object" && !Array.isArray(envVars)
      ? Object.keys(envVars).length
      : 0;
  if (envVarCount > 0) {
    parts.push(`env_vars: ${envVarCount} key${envVarCount === 1 ? "" : "s"}`);
  }
  if (Array.isArray(block.command) && block.command.length > 0) {
    parts.push(`command: ${block.command.length}`);
  }
  if (Array.isArray(block.args) && block.args.length > 0) {
    parts.push(`args: ${block.args.length}`);
  }
  if (parts.length === 0) return "override (empty)";
  return parts.join(" · ");
}

function readComponentBlock(
  deploymentConfig: Record<string, unknown> | null | undefined,
  componentName: string,
): ComponentOverrideBlock | null {
  if (deploymentConfig == null) return null;
  const components = deploymentConfig.components;
  if (components == null || typeof components !== "object") return null;
  // `components` is persisted as a dict keyed by component name.
  const block = (components as Record<string, unknown>)[componentName];
  if (block == null || typeof block !== "object" || Array.isArray(block)) {
    return null;
  }
  return block as ComponentOverrideBlock;
}

/**
 * Read-only summary for `Component Overrides`.
 *
 * Renders every component declared by the deployment's currently-pinned
 * driver. A component with a per-component block in `deployment.config`
 * lights up the per-row blue dot and gets a one-line scope summary;
 * components without an override block render the dot slot empty plus
 * a muted "no override" label.
 *
 * Components are a deployment-only concept — the cluster/environment
 * layers don't define them — so the dot fires whenever any per-component
 * block exists for that component at the deployment layer.
 */
export function ComponentOverridesSummary({
  deploymentConfig,
  components,
}: Props) {
  return (
    <ConfigSummaryCard title="Component Overrides">
      {components.length === 0 ? (
        <p className="text-sm italic text-muted-foreground">
          driver declares no components
        </p>
      ) : (
        <ul className="space-y-1.5">
          {components.map((component) => {
            const override = readComponentBlock(
              deploymentConfig,
              component.name,
            );
            const fromDeployment = override !== null;
            return (
              <li
                key={component.id}
                data-testid="component-override-row"
                data-component={component.name}
                data-from-deployment={fromDeployment ? "true" : "false"}
                className="flex items-center gap-2 text-sm"
              >
                <span
                  aria-hidden="true"
                  className={
                    fromDeployment
                      ? "h-1.5 w-1.5 shrink-0 rounded-full bg-blue-500"
                      : "h-1.5 w-1.5 shrink-0 rounded-full bg-transparent"
                  }
                />
                <span className="font-mono text-xs text-slate-900 dark:text-slate-100">
                  {component.name}
                </span>
                <span
                  className={
                    fromDeployment
                      ? "ml-2 truncate text-xs text-foreground"
                      : "ml-2 truncate text-xs italic text-muted-foreground"
                  }
                >
                  {fromDeployment && override
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
