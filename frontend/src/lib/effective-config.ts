/**
 * Reconciliation helpers that walk the `Cluster.config → Environment.config →
 * Deployment.config` inheritance chain and produce the *effective* values an
 * operator would see at runtime, attributed to the level that defined them.
 *
 * The settings tab uses these to render "what is actually applied" rather
 * than the per-section "you have something from the environment" stub —
 * see Spec 011-unified-deployment-config follow-up that locks
 * env vars + services to the full-chain display.
 */

/**
 * Where an effective value came from. Walked most-specific to least-specific
 * during merge: a deployment-level value beats an environment-level value
 * beats a cluster-level value.
 */
export type ConfigOrigin = "cluster" | "environment" | "deployment";

/**
 * An env var as it would actually land on the running pods, plus the
 * config layer that contributed the value.
 */
export interface EffectiveEnvVar {
  name: string;
  value: string;
  origin: ConfigOrigin;
}

/**
 * The Pydantic models on the backend store env vars as `dict[str, str]`,
 * so they materialise as `Record<string, string>` after `JSON.parse`. Each
 * level of the chain is optional — an unset level passes `null`/`undefined`.
 */
type ReadEnvVarDict = Record<string, string> | null | undefined;

function readEnvVarDict(
  config: Record<string, unknown> | null | undefined,
): ReadEnvVarDict {
  if (config == null) return undefined;
  const raw = config.env_vars;
  if (raw == null || typeof raw !== "object") return undefined;
  return raw as Record<string, string>;
}

/**
 * Merge env vars across the inheritance chain into a single ordered list,
 * preferring the most-specific definition at every key.
 *
 * Ordering: deployment-defined keys first (most likely to be reviewed),
 * then environment-only keys, then cluster-only keys — within each origin,
 * alphabetical by name for a stable display.
 */
export function computeEffectiveEnvVars(
  clusterConfig: Record<string, unknown> | null | undefined,
  environmentConfig: Record<string, unknown> | null | undefined,
  deploymentConfig: Record<string, unknown> | null | undefined,
): EffectiveEnvVar[] {
  const cluster = readEnvVarDict(clusterConfig) ?? {};
  const environment = readEnvVarDict(environmentConfig) ?? {};
  const deployment = readEnvVarDict(deploymentConfig) ?? {};

  const seen = new Set<string>();
  const out: EffectiveEnvVar[] = [];

  // Most-specific first so the `seen` guard preserves origin attribution.
  const layers: Array<[ConfigOrigin, Record<string, string>]> = [
    ["deployment", deployment],
    ["environment", environment],
    ["cluster", cluster],
  ];

  for (const [origin, dict] of layers) {
    const names = Object.keys(dict).sort();
    for (const name of names) {
      if (seen.has(name)) continue;
      seen.add(name);
      out.push({ name, value: dict[name] ?? "", origin });
    }
  }

  return out;
}

/**
 * A `deployedServices` row reshaped for the read-view. The deployment row's
 * `resolvedName` already reflects the operator's override (if any) — the
 * `isOverridden` flag is derived by comparing it against `driverServiceName`,
 * since the driver-declared default is what the override replaces.
 */
export interface EffectiveService {
  id: string;
  /** The driver-declared default name for this service. */
  driverServiceName: string;
  /** The name actually applied on the cluster (overridden or default). */
  resolvedName: string;
  kind: string;
  port: number;
  /** True when the operator has set a deployment-level rename. */
  isOverridden: boolean;
  /** Optional external addresses. */
  primaryUrl?: string | null;
  primaryFqdn?: string | null;
  humanReadableUrl?: string | null;
  humanReadableFqdn?: string | null;
}

/**
 * Raw shape of a row in `deployment.deployedServices` from the
 * `GetDeployment` query — declared structurally so consumers don't have
 * to import the generated GraphQL type just to call this helper.
 */
export interface DeployedServiceRow {
  id: string;
  driverServiceName: string;
  resolvedName: string;
  kind: string;
  port: number;
  primaryUrl?: string | null;
  primaryFqdn?: string | null;
  humanReadableUrl?: string | null;
  humanReadableFqdn?: string | null;
}

/**
 * Reshape the GraphQL `deployedServices` rows into the settings-tab view
 * model: each service knows whether its name was overridden, plus carries
 * the URLs/FQDNs verbatim so the summary card can surface them.
 */
export function computeEffectiveServices(
  deployedServices: readonly DeployedServiceRow[] | null | undefined,
): EffectiveService[] {
  if (deployedServices == null) return [];
  return deployedServices.map((row) => ({
    id: row.id,
    driverServiceName: row.driverServiceName,
    resolvedName: row.resolvedName,
    kind: row.kind,
    port: row.port,
    isOverridden: row.resolvedName !== row.driverServiceName,
    primaryUrl: row.primaryUrl,
    primaryFqdn: row.primaryFqdn,
    humanReadableUrl: row.humanReadableUrl,
    humanReadableFqdn: row.humanReadableFqdn,
  }));
}

/**
 * Result of a chain-walk lookup on a single dotted path. `value` is the
 * most-specific defined value across the cluster → environment → deployment
 * chain (or `null` when no layer defines the path). `fromDeployment` is the
 * per-row signal the read summaries use to render the small "deployment-set"
 * dot: it's `true` iff the deployment layer carried a defined value at the
 * path (whether or not it differs from the env/cluster values — the operator's
 * explicit intent at the deployment level is what we surface).
 */
export interface ResolvedValue<T> {
  value: T | null;
  /** True when the deployment.config layer defined this exact field. */
  fromDeployment: boolean;
}

/**
 * Walk a dotted snake_case path through `cluster.config →
 * environment.config → deployment.config` and resolve the most-specific
 * defined value.
 *
 * The configs are raw JSON blobs (snake_case keys, matching the Pydantic
 * models on the backend) — same convention as `computeEffectiveEnvVars`.
 * `path` mirrors that convention (e.g. `"scheduling.resources.requests.cpu"`,
 * `"fqdn_suffix"`).
 *
 * Distinguishes "explicitly set" from "absent" using `Object.hasOwn` at each
 * segment so an explicit `null`/empty-string at a layer wins over a defined
 * value at a less-specific layer. Returns `{ value: null, fromDeployment:
 * false }` when no layer defines the path.
 */
export function resolveConfigValue<T = unknown>(
  clusterConfig: Record<string, unknown> | null | undefined,
  environmentConfig: Record<string, unknown> | null | undefined,
  deploymentConfig: Record<string, unknown> | null | undefined,
  path: string,
): ResolvedValue<T> {
  const segments = path.split(".");

  const lookup = (
    root: Record<string, unknown> | null | undefined,
  ): { found: boolean; value: unknown } => {
    if (root == null) return { found: false, value: undefined };
    let cursor: unknown = root;
    for (const segment of segments) {
      if (
        cursor == null ||
        typeof cursor !== "object" ||
        Array.isArray(cursor) ||
        !Object.hasOwn(cursor as Record<string, unknown>, segment)
      ) {
        return { found: false, value: undefined };
      }
      cursor = (cursor as Record<string, unknown>)[segment];
    }
    return { found: true, value: cursor };
  };

  const deployment = lookup(deploymentConfig);
  if (deployment.found) {
    return { value: deployment.value as T | null, fromDeployment: true };
  }
  const environment = lookup(environmentConfig);
  if (environment.found) {
    return { value: environment.value as T | null, fromDeployment: false };
  }
  const cluster = lookup(clusterConfig);
  if (cluster.found) {
    return { value: cluster.value as T | null, fromDeployment: false };
  }
  return { value: null, fromDeployment: false };
}
