import type { GetDeploymentQuery } from "@/generated/graphql";
import { Badge } from "@/components/ui/badge";
import { ConfigSummaryCard } from "../../ConfigSummaryCard";

type Deployment = NonNullable<GetDeploymentQuery["deployment"]>;
type DeploymentComponent = Deployment["components"][number];
type ImageOverride = Deployment["componentImageOverrides"][number];

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
  /** `Deployment.componentImageOverrides` (018): stored, resolved, applied. */
  imageOverrides?: readonly ImageOverride[];
}

interface ComponentOverrideBlock {
  env_vars?: Record<string, unknown> | null;
  /** Container-override slots (014-component-container-overrides). */
  command?: string[] | null;
  args?: string[] | null;
  /** Image override (018-component-image-overrides). */
  image?: string | null;
  [key: string]: unknown;
}

/**
 * One-line override summary for a component override block. Each scope
 * the block carries is rendered as a small token; the persisted
 * `components` shape carries env vars, the `command`/`args` container
 * overrides (014-component-container-overrides) and the image override
 * (018), and the future-extension hook (resources / replicas) plugs in
 * here without touching callers.
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
  if (typeof block.image === "string" && block.image !== "") {
    parts.push("image");
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
 * Image override line under a component row: the stored reference, the
 * resolved one when `{{ app.version }}` makes them differ, and an
 * applied / not applied badge from `isApplicable`.
 */
function ImageOverrideLine({ override }: { override: ImageOverride }) {
  const showResolved = override.resolvedReference !== override.reference;
  return (
    <div
      data-testid="component-image-override"
      data-component={override.component}
      data-applicable={override.isApplicable ? "true" : "false"}
      data-reference={override.reference}
      data-resolved-reference={override.resolvedReference}
      className="ml-3.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs"
    >
      <span className="text-muted-foreground">image</span>
      <code
        data-testid="component-image-reference"
        className="break-all font-mono text-foreground"
      >
        {override.reference}
      </code>
      {showResolved && (
        <span className="text-muted-foreground">
          {"→ "}
          <code
            data-testid="component-image-resolved-reference"
            className="break-all font-mono text-foreground"
          >
            {override.resolvedReference}
          </code>
        </span>
      )}
      <Badge
        data-testid="component-image-applied-badge"
        variant={override.isApplicable ? "success" : "warning"}
        className="px-1.5 py-0 text-[10px]"
      >
        {override.isApplicable ? "applied" : "not applied"}
      </Badge>
    </div>
  );
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
 * block exists for that component at the deployment layer. A component
 * with an image override gets an extra line from `imageOverrides`.
 */
export function ComponentOverridesSummary({
  deploymentConfig,
  components,
  imageOverrides = [],
}: Props) {
  const imageByComponent = new Map(
    imageOverrides.map((o) => [o.component, o] as const),
  );
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
            const imageOverride = imageByComponent.get(component.name);
            return (
              <li
                key={component.id}
                data-testid="component-override-row"
                data-component={component.name}
                data-from-deployment={fromDeployment ? "true" : "false"}
                className="space-y-1 text-sm"
              >
                <div className="flex items-center gap-2">
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
                </div>
                {imageOverride && (
                  <ImageOverrideLine override={imageOverride} />
                )}
              </li>
            );
          })}
        </ul>
      )}
    </ConfigSummaryCard>
  );
}
