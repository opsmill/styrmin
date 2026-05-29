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
 * Read-side per-component override block: `{ env_vars: {...}, command: [...],
 * args: [...] }`. `command`/`args` are the container-override slots
 * (014-component-container-overrides); each is a `list[str] | null` in the
 * persisted `ComponentConfigBlock`.
 */
type ReadComponentBlock = {
  env_vars?: ReadEnvVars | null;
  command?: string[] | null;
  args?: string[] | null;
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
    // Container overrides (014). Carry the persisted lists through unchanged;
    // `null`/absent stays absent so a full-replacement write omits the field
    // (omit = clear, never `[]`).
    command: block?.command ?? undefined,
    args: block?.args ?? undefined,
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

/**
 * Rename a snake_case key to its camelCase counterpart in place. If the
 * destination key is already present (e.g. because the value was already
 * normalized upstream), the snake_case key is dropped without overwriting.
 * Symmetric with the backend's ``_convert_value()`` round-trip in
 * ``api/definitions/config/inputs.py``.
 */
function renameKey(
  obj: Record<string, unknown>,
  from: string,
  to: string,
): void {
  if (from in obj) {
    if (!(to in obj)) obj[to] = obj[from];
    delete obj[from];
  }
}

/**
 * Like {@link renameKey} but also applies ``transform`` to the value (snake
 * branch *or* already-camel branch). Useful when the rename is paired with a
 * recursive normalization or an enum translation.
 */
function moveAndTransform(
  obj: Record<string, unknown>,
  from: string,
  to: string,
  transform: (value: unknown) => unknown,
): void {
  if (from in obj) {
    const src = obj[from];
    delete obj[from];
    if (!(to in obj)) obj[to] = transform(src);
  } else if (to in obj) {
    obj[to] = transform(obj[to]);
  }
}

function normalizeLabelSelector(sel: unknown): unknown {
  if (sel == null || typeof sel !== "object") return sel;
  const out: Record<string, unknown> = { ...(sel as Record<string, unknown>) };
  renameKey(out, "match_labels", "matchLabels");
  moveAndTransform(out, "match_expressions", "matchExpressions", (raw) => {
    if (!Array.isArray(raw)) return raw;
    return raw.map((expr) => {
      if (expr == null || typeof expr !== "object") return expr;
      const e = expr as Record<string, unknown>;
      return {
        ...e,
        operator: translateEnum(LABEL_SELECTOR_OPERATOR_K8S_TO_GQL, e.operator),
      };
    });
  });
  return out;
}

function normalizeAffinityTerm(term: unknown): unknown {
  if (term == null || typeof term !== "object") return term;
  const out: Record<string, unknown> = {
    ...(term as Record<string, unknown>),
  };
  renameKey(out, "topology_key", "topologyKey");
  renameKey(out, "match_label_keys", "matchLabelKeys");
  renameKey(out, "mismatch_label_keys", "mismatchLabelKeys");
  renameKey(out, "deployment_ref", "deploymentRef");
  moveAndTransform(
    out,
    "label_selector",
    "labelSelector",
    normalizeLabelSelector,
  );
  moveAndTransform(
    out,
    "namespace_selector",
    "namespaceSelector",
    normalizeLabelSelector,
  );
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

/**
 * Project the persisted ``scheduling.inject`` block (``PostRenderInjection``
 * Pydantic model, snake_case keys) onto its ``PostRenderInjectionInput``
 * camelCase counterpart. Without this step the snake_case keys leak into
 * the form's initial state; once the user toggles a checkbox the form
 * writes the camelCase key alongside, producing a dual-key payload that
 * Strawberry rejects with "Field 'node_affinity' is not defined".
 */
function normalizeInject(inject: unknown): unknown {
  if (inject == null || typeof inject !== "object") return inject;
  const out: Record<string, unknown> = {
    ...(inject as Record<string, unknown>),
  };
  renameKey(out, "node_affinity", "nodeAffinity");
  renameKey(out, "pod_affinity", "podAffinity");
  renameKey(out, "topology_spread", "topologySpread");
  renameKey(out, "runtime_class", "runtimeClass");
  return out;
}

function normalizeTopologySpreadConstraint(c: unknown): unknown {
  if (c == null || typeof c !== "object") return c;
  const r: Record<string, unknown> = { ...(c as Record<string, unknown>) };
  renameKey(r, "max_skew", "maxSkew");
  renameKey(r, "topology_key", "topologyKey");
  renameKey(r, "min_domains", "minDomains");
  renameKey(r, "node_affinity_policy", "nodeAffinityPolicy");
  renameKey(r, "node_taints_policy", "nodeTaintsPolicy");
  renameKey(r, "match_label_keys", "matchLabelKeys");
  moveAndTransform(r, "when_unsatisfiable", "whenUnsatisfiable", (v) =>
    translateEnum(WHEN_UNSATISFIABLE_K8S_TO_GQL, v),
  );
  moveAndTransform(
    r,
    "label_selector",
    "labelSelector",
    normalizeLabelSelector,
  );
  return r;
}

function normalizeSchedulingEnums(
  scheduling: unknown,
): SchedulingInput | undefined {
  if (scheduling == null || typeof scheduling !== "object") return undefined;
  const out: Record<string, unknown> = {
    ...(scheduling as Record<string, unknown>),
  };
  if (Array.isArray(out.tolerations)) {
    out.tolerations = out.tolerations.map((t) => {
      if (t == null || typeof t !== "object") return t;
      const r: Record<string, unknown> = { ...(t as Record<string, unknown>) };
      if (r.operator !== undefined) {
        r.operator = translateEnum(TOLERATION_OPERATOR_K8S_TO_GQL, r.operator);
      }
      if (r.effect !== undefined) {
        r.effect = translateEnum(TOLERATION_EFFECT_K8S_TO_GQL, r.effect);
      }
      renameKey(r, "toleration_seconds", "tolerationSeconds");
      return r;
    });
  }
  moveAndTransform(
    out,
    "topology_spread_constraints",
    "topologySpreadConstraints",
    (raw) =>
      Array.isArray(raw) ? raw.map(normalizeTopologySpreadConstraint) : raw,
  );
  moveAndTransform(
    out,
    "node_affinity",
    "nodeAffinity",
    normalizeAffinityBlock,
  );
  moveAndTransform(out, "pod_affinity", "podAffinity", normalizeAffinityBlock);
  moveAndTransform(
    out,
    "pod_anti_affinity",
    "podAntiAffinity",
    normalizeAffinityBlock,
  );
  renameKey(out, "runtime_class", "runtimeClass");
  if ("inject" in out) {
    out.inject = normalizeInject(out.inject);
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
