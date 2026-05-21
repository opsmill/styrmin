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
 * Backend GraphQL enums declare a SCREAMING_SNAKE identifier with a
 * K8s-native string value (e.g. ``TolerationOperator.EQUAL = "Equal"``). The
 * GraphQL wire format uses the identifier, but the persisted
 * ``deployment.config`` JSON blob stores the value. When we project the
 * persisted blob back into ``UpdateDeploymentInput`` we have to translate
 * each enum-bearing field, otherwise re-submitting an unchanged toleration
 * sends ``operator: "Equal"`` and Strawberry rejects it.
 *
 * Symmetric with the backend's ``api/definitions/config/inputs.py``
 * conversion helper that translates the other direction at write time.
 */
const TOLERATION_OPERATOR_K8S_TO_GQL: Record<string, string> = {
  Exists: "EXISTS",
  Equal: "EQUAL",
};

const TOLERATION_EFFECT_K8S_TO_GQL: Record<string, string> = {
  NoSchedule: "NO_SCHEDULE",
  PreferNoSchedule: "PREFER_NO_SCHEDULE",
  NoExecute: "NO_EXECUTE",
};

const WHEN_UNSATISFIABLE_K8S_TO_GQL: Record<string, string> = {
  DoNotSchedule: "DO_NOT_SCHEDULE",
  ScheduleAnyway: "SCHEDULE_ANYWAY",
};

const LABEL_SELECTOR_OPERATOR_K8S_TO_GQL: Record<string, string> = {
  In: "IN",
  NotIn: "NOT_IN",
  Exists: "EXISTS",
  DoesNotExist: "DOES_NOT_EXIST",
};

const EXTERNAL_URL_SCHEME_K8S_TO_GQL: Record<string, string> = {
  http: "HTTP",
  https: "HTTPS",
};

const EXTERNAL_DNS_ENDPOINTS_TYPE_K8S_TO_GQL: Record<string, string> = {
  NodeExternalIP: "NODE_EXTERNAL_IP",
  ClusterIP: "CLUSTER_IP",
};

function translateEnum(
  table: Record<string, string>,
  raw: unknown,
): string | undefined {
  if (typeof raw !== "string") return undefined;
  return table[raw] ?? raw;
}

function normalizeLabelSelector(sel: unknown): unknown {
  if (sel == null || typeof sel !== "object") return sel;
  const s = sel as Record<string, unknown>;
  const matchExpressions = Array.isArray(s.matchExpressions)
    ? s.matchExpressions
    : Array.isArray(s.match_expressions)
      ? s.match_expressions
      : undefined;
  if (!matchExpressions) return sel;
  return {
    ...s,
    matchExpressions: matchExpressions.map((expr) => {
      if (expr == null || typeof expr !== "object") return expr;
      const e = expr as Record<string, unknown>;
      return {
        ...e,
        operator: translateEnum(LABEL_SELECTOR_OPERATOR_K8S_TO_GQL, e.operator),
      };
    }),
  };
}

function normalizeAffinityTerm(term: unknown): unknown {
  if (term == null || typeof term !== "object") return term;
  const t = term as Record<string, unknown>;
  const out: Record<string, unknown> = { ...t };
  if (t.label_selector !== undefined) {
    out.labelSelector = normalizeLabelSelector(t.label_selector);
    delete out.label_selector;
  } else if (t.labelSelector !== undefined) {
    out.labelSelector = normalizeLabelSelector(t.labelSelector);
  }
  if (t.namespace_selector !== undefined) {
    out.namespaceSelector = normalizeLabelSelector(t.namespace_selector);
    delete out.namespace_selector;
  } else if (t.namespaceSelector !== undefined) {
    out.namespaceSelector = normalizeLabelSelector(t.namespaceSelector);
  }
  return out;
}

function normalizeAffinityBlock(block: unknown): unknown {
  if (block == null || typeof block !== "object") return block;
  const b = block as Record<string, unknown>;
  const out: Record<string, unknown> = { ...b };
  if (Array.isArray(b.required)) {
    out.required = b.required.map(normalizeAffinityTerm);
  }
  if (Array.isArray(b.preferred)) {
    out.preferred = b.preferred.map((wt) => {
      if (wt == null || typeof wt !== "object") return wt;
      const w = wt as Record<string, unknown>;
      return { ...w, term: normalizeAffinityTerm(w.term) };
    });
  }
  return out;
}

function normalizeSchedulingEnums(
  scheduling: unknown,
): SchedulingInput | undefined {
  if (scheduling == null || typeof scheduling !== "object") return undefined;
  const s = scheduling as Record<string, unknown>;
  const out: Record<string, unknown> = { ...s };
  if (Array.isArray(s.tolerations)) {
    out.tolerations = s.tolerations.map((t) => {
      if (t == null || typeof t !== "object") return t;
      const row = t as Record<string, unknown>;
      const r: Record<string, unknown> = { ...row };
      if (row.operator !== undefined) {
        r.operator = translateEnum(
          TOLERATION_OPERATOR_K8S_TO_GQL,
          row.operator,
        );
      }
      if (row.effect !== undefined) {
        r.effect = translateEnum(TOLERATION_EFFECT_K8S_TO_GQL, row.effect);
      }
      if (
        row.toleration_seconds !== undefined &&
        r.tolerationSeconds === undefined
      ) {
        r.tolerationSeconds = row.toleration_seconds;
        delete r.toleration_seconds;
      }
      return r;
    });
  }
  const tsc = Array.isArray(s.topology_spread_constraints)
    ? (s.topology_spread_constraints as unknown[])
    : Array.isArray(s.topologySpreadConstraints)
      ? (s.topologySpreadConstraints as unknown[])
      : undefined;
  if (tsc) {
    out.topologySpreadConstraints = tsc.map((c) => {
      if (c == null || typeof c !== "object") return c;
      const row = c as Record<string, unknown>;
      const r: Record<string, unknown> = { ...row };
      if (
        row.whenUnsatisfiable !== undefined ||
        row.when_unsatisfiable !== undefined
      ) {
        r.whenUnsatisfiable = translateEnum(
          WHEN_UNSATISFIABLE_K8S_TO_GQL,
          row.whenUnsatisfiable ?? row.when_unsatisfiable,
        );
        delete r.when_unsatisfiable;
      }
      if (row.label_selector !== undefined) {
        r.labelSelector = normalizeLabelSelector(row.label_selector);
        delete r.label_selector;
      }
      return r;
    });
    delete out.topology_spread_constraints;
  }
  if (s.node_affinity !== undefined) {
    out.nodeAffinity = normalizeAffinityBlock(s.node_affinity);
    delete out.node_affinity;
  } else if (s.nodeAffinity !== undefined) {
    out.nodeAffinity = normalizeAffinityBlock(s.nodeAffinity);
  }
  if (s.pod_anti_affinity !== undefined) {
    out.podAntiAffinity = normalizeAffinityBlock(s.pod_anti_affinity);
    delete out.pod_anti_affinity;
  } else if (s.podAntiAffinity !== undefined) {
    out.podAntiAffinity = normalizeAffinityBlock(s.podAntiAffinity);
  }
  if (s.runtime_class !== undefined && out.runtimeClass === undefined) {
    out.runtimeClass = s.runtime_class;
    delete out.runtime_class;
  }
  return out as unknown as SchedulingInput;
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
    scheduling: normalizeSchedulingEnums(config.scheduling),
    fqdnSuffix: config.fqdn_suffix as string | undefined,
    externalUrlScheme: translateEnum(
      EXTERNAL_URL_SCHEME_K8S_TO_GQL,
      config.external_url_scheme,
    ) as ExternalUrlScheme | undefined,
    externalUrlPort: config.external_url_port as number | undefined,
    externalDnsEndpointsType: translateEnum(
      EXTERNAL_DNS_ENDPOINTS_TYPE_K8S_TO_GQL,
      config.external_dns_endpoints_type,
    ) as ExternalDnsEndpointsType | undefined,
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
