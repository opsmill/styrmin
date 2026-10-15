import type { GetDeploymentQuery } from "@/generated/graphql";
import { Badge } from "@/components/ui/badge";
import { ConfigSummaryCard } from "../../ConfigSummaryCard";

type Deployment = NonNullable<GetDeploymentQuery["deployment"]>;
type DeploymentComponent = Deployment["components"][number];
type ImageOverride = Deployment["componentImageOverrides"][number];
type ContainerOverride = Deployment["componentContainerOverrides"][number];

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
  /** `Deployment.componentContainerOverrides` (022): stored `command`/`args`, applied. */
  containerOverrides?: readonly ContainerOverride[];
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
    parts.push("command");
  }
  if (Array.isArray(block.args) && block.args.length > 0) {
    parts.push("args");
  }
  if (typeof block.image === "string" && block.image !== "") {
    parts.push("image");
  }
  if (parts.length === 0) return "override (empty)";
  return parts.join(" · ");
}

function readComponentBlocks(
  deploymentConfig: Record<string, unknown> | null | undefined,
): Record<string, unknown> | null {
  const components = deploymentConfig?.components;
  if (components == null || typeof components !== "object") return null;
  if (Array.isArray(components)) return null;
  // `components` is persisted as a dict keyed by component name.
  return components as Record<string, unknown>;
}

function readComponentBlock(
  deploymentConfig: Record<string, unknown> | null | undefined,
  componentName: string,
): ComponentOverrideBlock | null {
  const components = readComponentBlocks(deploymentConfig);
  if (components == null) return null;
  const block = components[componentName];
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
      <AppliedBadge
        applicable={override.isApplicable}
        testId="component-image-applied-badge"
      />
    </div>
  );
}

function AppliedBadge({
  applicable,
  testId,
}: {
  applicable: boolean;
  testId: string;
}) {
  return (
    <Badge
      data-testid={testId}
      variant={applicable ? "success" : "warning"}
      className="px-1.5 py-0 text-[10px]"
    >
      {applicable ? "applied" : "not applied"}
    </Badge>
  );
}

/**
 * `command` and `args` lines under a component row, each list shown as JSON so
 * `["a b"]` and `["a", "b"]` read differently, with an applied / not applied badge.
 */
function ContainerOverrideLines({ override }: { override: ContainerOverride }) {
  return (
    <>
      {(["command", "args"] as const).map((field) => {
        const values = override[field];
        if (!values || values.length === 0) return null;
        return (
          <div
            key={field}
            data-testid="component-container-override"
            data-component={override.component}
            data-field={field}
            data-applicable={override.isApplicable ? "true" : "false"}
            className="ml-3.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs"
          >
            <span className="text-muted-foreground">{field}</span>
            <code
              data-testid="component-container-override-value"
              className="break-all font-mono text-foreground"
            >
              {JSON.stringify(values)}
            </code>
            <AppliedBadge
              applicable={override.isApplicable}
              testId="component-container-override-applied-badge"
            />
          </div>
        );
      })}
    </>
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
 * with an image, `command` or `args` override gets a line for each, with its
 * value and an applied / not applied badge; an override on a component the
 * driver no longer declares gets its own row.
 */
export function ComponentOverridesSummary({
  deploymentConfig,
  components,
  imageOverrides = [],
  containerOverrides = [],
}: Props) {
  const imageByComponent = new Map(
    imageOverrides.map((o) => [o.component, o] as const),
  );
  const containerByComponent = new Map(
    containerOverrides.map((o) => [o.component, o] as const),
  );
  const declared = new Set(components.map((c) => c.name));
  const storedNames = Object.keys(readComponentBlocks(deploymentConfig) ?? {});
  const orphanNames = [
    ...new Set([
      ...storedNames,
      ...imageOverrides.map((o) => o.component),
      ...containerOverrides.map((o) => o.component),
    ]),
  ]
    .filter((name) => !declared.has(name))
    .sort();
  return (
    <ConfigSummaryCard title="Component Overrides">
      {components.length === 0 && orphanNames.length === 0 ? (
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
            const containerOverride = containerByComponent.get(component.name);
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
                {containerOverride && (
                  <ContainerOverrideLines override={containerOverride} />
                )}
              </li>
            );
          })}
          {orphanNames.map((name) => {
            const block = readComponentBlock(deploymentConfig, name);
            const imageOverride = imageByComponent.get(name);
            const containerOverride = containerByComponent.get(name);
            return (
              <li
                key={`orphan-${name}`}
                data-testid="component-override-orphan-row"
                data-component={name}
                className="space-y-1 text-sm"
              >
                <div className="flex items-center gap-2">
                  <span
                    aria-hidden="true"
                    className="h-1.5 w-1.5 shrink-0 rounded-full bg-amber-500"
                  />
                  <span className="font-mono text-xs text-slate-900 dark:text-slate-100">
                    {name}
                  </span>
                  <span className="ml-2 truncate text-xs italic text-muted-foreground">
                    no longer declared by driver
                    {block ? ` · ${summariseOverride(block)}` : ""}
                  </span>
                </div>
                {imageOverride && (
                  <ImageOverrideLine override={imageOverride} />
                )}
                {containerOverride && (
                  <ContainerOverrideLines override={containerOverride} />
                )}
              </li>
            );
          })}
        </ul>
      )}
    </ConfigSummaryCard>
  );
}
