import type {
  ComponentConfigInput,
  DedicatedIngressInput,
  EnvVarInput,
  ExternalDnsEndpointsType,
  ExternalUrlScheme,
  FastStorageInput,
  SchedulingInput,
  StandardStorageInput,
  UpdateDeploymentInput,
} from "@/generated/graphql";

/**
 * Read-side projection of `Deployment.config`. The backend returns the
 * persisted JSON blob (snake_case keys) via the `Deployment.config: JSON`
 * GraphQL field, which is typed as `Record<string, unknown>` on the
 * frontend.
 *
 * Only the fields that map onto `UpdateDeploymentInput` are described here;
 * any extra keys are ignored by {@link deploymentConfigToInput}.
 */
export type DeploymentConfig = Record<string, unknown>;

/**
 * Read-side env-var dict: `{ [name]: value }`. The persisted Pydantic
 * `EnvironmentConfig.env_vars` and `ComponentConfigBlock.env_vars` are
 * `dict[str, str]`, so the JSON blob materialises as a `Record<string,
 * string>` after `JSON.parse`.
 */
type ReadEnvVars = Record<string, string>;

/**
 * Read-side per-component override block: `{ env_vars: {...} }`.
 */
type ReadComponentBlock = {
  env_vars?: ReadEnvVars | null;
};

function envVarsDictToList(
  dict: ReadEnvVars | null | undefined,
): EnvVarInput[] | undefined {
  if (dict == null) return undefined;
  return Object.entries(dict).map(([name, value]) => ({ name, value }));
}

function componentsDictToList(
  dict: Record<string, ReadComponentBlock> | null | undefined,
): ComponentConfigInput[] | undefined {
  if (dict == null) return undefined;
  return Object.entries(dict).map(([name, block]) => ({
    name,
    envVars: envVarsDictToList(block?.env_vars),
  }));
}

/**
 * Convert a read-side `Deployment.config` JSON blob into the typed
 * `UpdateDeploymentInput` shape expected by the new `updateDeployment`
 * mutation.
 *
 * Why this exists: the read API returns `envVars` and `components` as
 * dicts keyed by name (mirroring the persisted Pydantic models), but the
 * typed input expects them as lists of `{name, ...}` rows. Every other
 * field on `UpdateDeploymentInput` maps 1:1 from its `Deployment.config`
 * counterpart — this helper does that pass-through plus the two
 * dict-to-list translations (top-level `env_vars` and per-component
 * `env_vars`).
 *
 * Field-name translation between the persisted snake_case keys and the
 * camelCase `UpdateDeploymentInput` shape is performed explicitly per
 * field; unknown keys on the input are dropped silently.
 *
 * Note: `name`, `parameters`, and `serviceNameOverrides` live on the
 * `Deployment` row (not inside `config`) and are NOT populated by this
 * helper — callers that want to preserve those fields under the new
 * full-replacement contract must read them from the top-level `Deployment`
 * and set them on the returned input separately.
 */
/**
 * Convert the row-level `Deployment.parameters` dict (snake-case JSON,
 * `{ [name]: value }`) into the `ParameterValueInput[]` shape expected by
 * `UpdateDeploymentInput.parameters`.
 *
 * Returns `undefined` when the dict is empty/absent so the diff and
 * inheritance helpers see the same "unset" sentinel.
 *
 * Lives alongside {@link deploymentConfigToInput} because both project a
 * persisted GraphQL surface into the `UpdateDeploymentInput` shape; keeping
 * them next to each other prevents the projection layer from fragmenting
 * across multiple modules.
 */
export function deploymentParametersToInput(
  parameters: Record<string, unknown> | null | undefined,
): UpdateDeploymentInput["parameters"] {
  if (parameters == null) return undefined;
  const entries = Object.entries(parameters);
  if (entries.length === 0) return undefined;
  // The codegen narrows the JSON scalar to `Record<string, unknown>`. Real
  // parameter values may be primitives (string/integer/boolean), so cast at
  // the boundary. See generated/graphql.ts `Scalars.JSON`.
  return entries.map(([name, value]) => ({
    name,
    value: value as Record<string, unknown>,
  }));
}

export function deploymentConfigToInput(
  config: DeploymentConfig,
): UpdateDeploymentInput {
  return {
    envVars: envVarsDictToList(config.env_vars as ReadEnvVars | undefined),
    components: componentsDictToList(
      config.components as Record<string, ReadComponentBlock> | undefined,
    ),
    ipWhitelist: config.ip_whitelist as string[] | undefined,
    dedicatedIngress: config.dedicated_ingress as
      | DedicatedIngressInput
      | undefined,
    scheduling: config.scheduling as SchedulingInput | undefined,
    fqdnSuffix: config.fqdn_suffix as string | undefined,
    externalUrlScheme: config.external_url_scheme as
      | ExternalUrlScheme
      | undefined,
    externalUrlPort: config.external_url_port as number | undefined,
    externalDnsEndpointsType: config.external_dns_endpoints_type as
      | ExternalDnsEndpointsType
      | undefined,
    ingressClass: config.ingress_class as string | undefined,
    dbSize: config.db_size as string | undefined,
    runtimeClass: config.runtime_class as string | undefined,
    nodeSelector: config.node_selector as string | undefined,
    standardStorage: config.standard_storage as
      | StandardStorageInput
      | undefined,
    fastStorage: config.fast_storage as FastStorageInput | undefined,
  };
}
