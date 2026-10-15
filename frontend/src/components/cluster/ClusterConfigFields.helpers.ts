/**
 * Form schema and value conversions for the cluster config fields shared by
 * the create and edit cluster dialogs. Kept apart from the component file so
 * that file only exports components (`react-refresh/only-export-components`).
 *
 * The form edits the config in the stored format (snake_case keys, stored enum
 * values such as `http` and `NodeExternalIP`).
 */
import { z } from "zod/v4";

type StoredConfig = Record<string, unknown>;

export const clusterConfigShape = {
  ingress_class: z.string(),
  fqdn_suffix: z.string(),
  runtime_class: z.string(),
  external_url_scheme: z.union([z.enum(["http", "https"]), z.literal("")]),
  external_url_port: z.string(),
  external_dns_endpoints_type: z.union([
    z.enum(["NodeExternalIP", "ClusterIP"]),
    z.literal(""),
  ]),
  dedicated_ingress_enabled: z.boolean(),
  dedicated_ingress_implementation: z.string(),
  // Free strings in the backend: a stored value the form does not list is kept.
  dedicated_ingress_type: z.string(),
  dedicated_ingress_service_type: z.string(),
  dedicated_ingress_service_node_port: z.string(),
  dedicated_ingress_service_external_traffic_policy: z.string(),
  dedicated_ingress_service_ip_family_policy: z.union([
    z.enum(["SingleStack", "PreferDualStack", "RequireDualStack"]),
    z.literal(""),
  ]),
  dedicated_ingress_service_ip_family_ipv4: z.boolean(),
  dedicated_ingress_service_ip_family_ipv6: z.boolean(),
  standard_storage_enabled: z.boolean(),
  standard_storage_class: z.string(),
  fast_storage_enabled: z.boolean(),
  fast_storage_class: z.string(),
};

const clusterConfigObject = z.object(clusterConfigShape);

export type ClusterConfigFormValues = z.infer<typeof clusterConfigObject>;

function isPortNumber(value: string): boolean {
  const n = Number(value);
  return Number.isInteger(n) && n >= 1 && n <= 65535;
}

/** Rules across fields, shared by every schema built on `clusterConfigShape`. */
export function refineClusterConfig(
  data: ClusterConfigFormValues,
  ctx: z.RefinementCtx,
): void {
  const issue = (path: keyof ClusterConfigFormValues, message: string) =>
    ctx.addIssue({ code: "custom", message, path: [path] });

  if (data.standard_storage_enabled && !data.standard_storage_class) {
    issue(
      "standard_storage_class",
      "Storage class is required when standard storage is enabled",
    );
  }
  if (data.fast_storage_enabled && !data.fast_storage_class) {
    issue(
      "fast_storage_class",
      "Storage class is required when fast storage is enabled",
    );
  }
  if (data.external_url_port && !isPortNumber(data.external_url_port)) {
    issue(
      "external_url_port",
      "External URL port must be an integer between 1 and 65535",
    );
  }
  const nodePort = data.dedicated_ingress_service_node_port;
  if (data.dedicated_ingress_enabled && nodePort) {
    if (!isPortNumber(nodePort)) {
      issue(
        "dedicated_ingress_service_node_port",
        "NodePort must be an integer between 1 and 65535",
      );
    }
    if (data.dedicated_ingress_service_type !== "NodePort") {
      issue(
        "dedicated_ingress_service_node_port",
        "NodePort is only valid when Service Type is NodePort",
      );
    }
  }
}

export const clusterConfigSchema =
  clusterConfigObject.superRefine(refineClusterConfig);

/** Map schema issues to the `{ fields }` shape a TanStack Form validator returns. */
export function schemaFieldErrors(
  schema: z.ZodType,
  value: unknown,
): { fields: Record<string, string> } | undefined {
  const result = schema.safeParse(value);
  if (result.success) return undefined;
  const fields: Record<string, string> = {};
  for (const issue of result.error.issues) {
    const path = issue.path.join(".");
    if (path) fields[path] = issue.message;
  }
  return { fields };
}

export const EMPTY_CLUSTER_CONFIG_VALUES: ClusterConfigFormValues = {
  ingress_class: "",
  fqdn_suffix: "",
  runtime_class: "",
  external_url_scheme: "",
  external_url_port: "",
  external_dns_endpoints_type: "",
  dedicated_ingress_enabled: false,
  dedicated_ingress_implementation: "",
  dedicated_ingress_type: "",
  dedicated_ingress_service_type: "",
  dedicated_ingress_service_node_port: "",
  dedicated_ingress_service_external_traffic_policy: "",
  dedicated_ingress_service_ip_family_policy: "",
  dedicated_ingress_service_ip_family_ipv4: false,
  dedicated_ingress_service_ip_family_ipv6: false,
  standard_storage_enabled: false,
  standard_storage_class: "",
  fast_storage_enabled: false,
  fast_storage_class: "",
};

/** Top-level config keys the form shows; every other stored key is carried through. */
const FORM_KEYS = [
  "ingress_class",
  "fqdn_suffix",
  "runtime_class",
  "external_url_scheme",
  "external_url_port",
  "external_dns_endpoints_type",
  "dedicated_ingress",
  "standard_storage",
  "fast_storage",
] as const;

/** `dedicated_ingress.service` keys the form shows. */
const FORM_SERVICE_KEYS = [
  "type",
  "node_port",
  "external_traffic_policy",
  "ip_family_policy",
  "ip_families",
] as const;

function asRecord(value: unknown): StoredConfig | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as StoredConfig)
    : null;
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function asPortString(value: unknown): string {
  return typeof value === "number" ? String(value) : "";
}

function oneOf<T extends string>(
  value: unknown,
  options: readonly T[],
): T | "" {
  return options.find((option) => option === value) ?? "";
}

function without(record: StoredConfig, keys: readonly string[]): StoredConfig {
  return Object.fromEntries(
    Object.entries(record).filter(([key]) => !keys.includes(key)),
  );
}

/** Stored cluster config → form values. */
export function configToFormValues(
  config: StoredConfig | null | undefined,
): ClusterConfigFormValues {
  const di = asRecord(config?.dedicated_ingress);
  const service = asRecord(di?.service);
  const ipFamilies = Array.isArray(service?.ip_families)
    ? service.ip_families
    : [];
  const standard = asRecord(config?.standard_storage);
  const fast = asRecord(config?.fast_storage);
  return {
    ingress_class: asString(config?.ingress_class),
    fqdn_suffix: asString(config?.fqdn_suffix),
    runtime_class: asString(config?.runtime_class),
    external_url_scheme: oneOf(config?.external_url_scheme, ["http", "https"]),
    external_url_port: asPortString(config?.external_url_port),
    external_dns_endpoints_type: oneOf(config?.external_dns_endpoints_type, [
      "NodeExternalIP",
      "ClusterIP",
    ]),
    dedicated_ingress_enabled: di !== null,
    dedicated_ingress_implementation: asString(di?.implementation),
    dedicated_ingress_type: asString(di?.type),
    dedicated_ingress_service_type: asString(service?.type),
    dedicated_ingress_service_node_port: asPortString(service?.node_port),
    dedicated_ingress_service_external_traffic_policy: asString(
      service?.external_traffic_policy,
    ),
    dedicated_ingress_service_ip_family_policy: oneOf(
      service?.ip_family_policy,
      ["SingleStack", "PreferDualStack", "RequireDualStack"],
    ),
    dedicated_ingress_service_ip_family_ipv4: ipFamilies.includes("IPv4"),
    dedicated_ingress_service_ip_family_ipv6: ipFamilies.includes("IPv6"),
    standard_storage_enabled: standard !== null,
    standard_storage_class: asString(standard?.storage_class),
    fast_storage_enabled: fast !== null,
    fast_storage_class: asString(fast?.storage_class),
  };
}

/** Form values → the config keys the form shows, in the stored format. Empty values are left out. */
export function formValuesToConfig(
  values: ClusterConfigFormValues,
): StoredConfig {
  const config: StoredConfig = {};
  if (values.ingress_class) config.ingress_class = values.ingress_class;
  if (values.fqdn_suffix) config.fqdn_suffix = values.fqdn_suffix;
  if (values.runtime_class) config.runtime_class = values.runtime_class;
  if (values.external_url_scheme)
    config.external_url_scheme = values.external_url_scheme;
  if (values.external_url_port)
    config.external_url_port = Number(values.external_url_port);
  if (values.external_dns_endpoints_type)
    config.external_dns_endpoints_type = values.external_dns_endpoints_type;
  if (values.dedicated_ingress_enabled) {
    const di: StoredConfig = {};
    if (values.dedicated_ingress_implementation)
      di.implementation = values.dedicated_ingress_implementation;
    if (values.dedicated_ingress_type) di.type = values.dedicated_ingress_type;
    const service: StoredConfig = {};
    if (values.dedicated_ingress_service_type) {
      service.type = values.dedicated_ingress_service_type;
    }
    if (
      values.dedicated_ingress_service_type === "NodePort" &&
      values.dedicated_ingress_service_node_port
    ) {
      service.node_port = Number(values.dedicated_ingress_service_node_port);
    }
    if (values.dedicated_ingress_service_external_traffic_policy) {
      service.external_traffic_policy =
        values.dedicated_ingress_service_external_traffic_policy;
    }
    if (values.dedicated_ingress_service_ip_family_policy) {
      service.ip_family_policy =
        values.dedicated_ingress_service_ip_family_policy;
    }
    const ipFamilies: string[] = [];
    if (values.dedicated_ingress_service_ip_family_ipv4)
      ipFamilies.push("IPv4");
    if (values.dedicated_ingress_service_ip_family_ipv6)
      ipFamilies.push("IPv6");
    if (ipFamilies.length > 0) service.ip_families = ipFamilies;
    if (Object.keys(service).length > 0) di.service = service;
    config.dedicated_ingress = di;
  }
  if (values.standard_storage_enabled && values.standard_storage_class) {
    config.standard_storage = { storage_class: values.standard_storage_class };
  }
  if (values.fast_storage_enabled && values.fast_storage_class) {
    config.fast_storage = { storage_class: values.fast_storage_class };
  }
  return config;
}

function sameMembers(a: unknown, b: unknown): boolean {
  if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) {
    return false;
  }
  return a.every((item) => b.includes(item));
}

function mergeDedicatedIngress(
  stored: StoredConfig | null,
  fromForm: StoredConfig,
): StoredConfig {
  if (stored === null) return fromForm;
  const storedService = asRecord(stored.service) ?? {};
  const service = {
    ...without(storedService, FORM_SERVICE_KEYS),
    ...(asRecord(fromForm.service) ?? {}),
  };
  // Keep the stored order of the same IP families, so saving does not change the controller.
  if (sameMembers(service.ip_families, storedService.ip_families)) {
    service.ip_families = storedService.ip_families;
  }
  const merged: StoredConfig = {
    ...without(stored, ["implementation", "type", "service"]),
    ...without(fromForm, ["service"]),
  };
  if (Object.keys(service).length > 0 || "service" in stored) {
    merged.service = service;
  }
  return merged;
}

/**
 * The full config to save: the form values over the stored config. Keys and
 * `dedicated_ingress.service` fields the form does not show keep their stored
 * value; a value cleared in the form is removed.
 */
export function mergeFormValuesIntoConfig(
  stored: StoredConfig | null | undefined,
  values: ClusterConfigFormValues,
): StoredConfig {
  const fromForm = formValuesToConfig(values);
  const merged: StoredConfig = { ...without(stored ?? {}, FORM_KEYS) };
  for (const [key, value] of Object.entries(fromForm)) {
    merged[key] =
      key === "dedicated_ingress"
        ? mergeDedicatedIngress(
            asRecord(stored?.dedicated_ingress),
            value as StoredConfig,
          )
        : value;
  }
  return merged;
}

/** Labels shared by the cluster configuration view and the create and edit dialogs. */
export const CLUSTER_CONFIG_LABELS = {
  ingress_class: "Ingress class",
  fqdn_suffix: "FQDN suffix",
  runtime_class: "Runtime class",
  external_url_scheme: "External URL scheme",
  external_url_port: "External URL port",
  external_dns_endpoints_type: "External DNS endpoints type",
  dedicated_ingress: "Dedicated ingress",
  implementation: "Implementation",
  routing_type: "Routing type",
  service_type: "Service type",
  node_port: "NodePort",
  external_traffic_policy: "External traffic policy",
  ip_families: "IP families",
  ip_family_policy: "IP family policy",
  load_balancer_ip: "Load balancer IP",
  service_annotations: "Service annotations",
  standard_storage: "Standard storage",
  standard_storage_class: "Standard storage class",
  fast_storage: "Fast storage",
  fast_storage_class: "Fast storage class",
  db_size: "Database size",
  scheduling: "Scheduling defaults",
  backup_ttl: "Backup retention",
} as const;

// Defaults the backend applies when a key is absent (`_apply_cluster_defaults`,
// `DedicatedIngressConfig`, `IngressServiceConfig`, `build_external_url`).
export const DEFAULT_INGRESS_CLASS = "traefik";
export const DEFAULT_RUNTIME_CLASS = "default";
export const DEFAULT_EXTERNAL_URL_SCHEME = "https";
export const DEFAULT_DEDICATED_INGRESS_IMPLEMENTATION = "traefik";
export const DEFAULT_DEDICATED_INGRESS_TYPE = "ingress";
export const DEFAULT_INGRESS_SERVICE_TYPE = "LoadBalancer";

export const NOT_SET = "Not set";

function displayValue(value: unknown): string {
  if (value === undefined || value === null || value === "") return NOT_SET;
  if (typeof value === "string" || typeof value === "number") {
    return String(value);
  }
  if (Array.isArray(value) && value.every((v) => typeof v === "string")) {
    return value.join(", ");
  }
  return JSON.stringify(value);
}

/** Deep equality of JSON values; object key order does not matter. */
export function sameJson(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (Array.isArray(a) || Array.isArray(b)) {
    return (
      Array.isArray(a) &&
      Array.isArray(b) &&
      a.length === b.length &&
      a.every((item, i) => sameJson(item, b[i]))
    );
  }
  const ra = asRecord(a);
  const rb = asRecord(b);
  if (ra === null || rb === null) return false;
  const keys = new Set([...Object.keys(ra), ...Object.keys(rb)]);
  return [...keys].every((key) => sameJson(ra[key], rb[key]));
}

const SHOWN_KEYS = new Set([
  "ingress_class",
  "fqdn_suffix",
  "runtime_class",
  "external_url_scheme",
  "external_url_port",
  "external_dns_endpoints_type",
  "dedicated_ingress",
  "standard_storage",
  "fast_storage",
  "db_size",
  "scheduling",
  "backup_ttl",
]);

/** The config as label → displayed value, one entry per value an administrator can tell apart. */
function describedValues(config: StoredConfig): Array<[string, string]> {
  const L = CLUSTER_CONFIG_LABELS;
  const di = asRecord(config.dedicated_ingress);
  const service = asRecord(di?.service);
  const entries: Array<[string, unknown]> = [
    [L.ingress_class, config.ingress_class],
    [L.fqdn_suffix, config.fqdn_suffix],
    [L.runtime_class, config.runtime_class],
    [L.external_url_scheme, config.external_url_scheme],
    [L.external_url_port, config.external_url_port],
    [L.external_dns_endpoints_type, config.external_dns_endpoints_type],
    [L.dedicated_ingress, di === null ? "Off" : "On"],
    [L.implementation, di?.implementation],
    [L.routing_type, di?.type],
    [L.service_type, service?.type],
    [L.node_port, service?.node_port],
    [L.external_traffic_policy, service?.external_traffic_policy],
    [L.ip_families, service?.ip_families],
    [L.ip_family_policy, service?.ip_family_policy],
    [L.load_balancer_ip, service?.load_balancer_ip],
    [L.service_annotations, service?.annotations],
    [
      L.standard_storage_class,
      asRecord(config.standard_storage)?.storage_class,
    ],
    [L.fast_storage_class, asRecord(config.fast_storage)?.storage_class],
    [L.db_size, config.db_size],
    [L.scheduling, config.scheduling],
    [L.backup_ttl, config.backup_ttl],
  ];
  for (const [key, value] of Object.entries(config)) {
    if (!SHOWN_KEYS.has(key)) entries.push([key, value]);
  }
  return entries.map(([label, value]) => [label, displayValue(value)]);
}

export interface ConfigChange {
  label: string;
  before: string;
  after: string;
}

/** The values that differ between two stored cluster configs, with the labels of the form. */
export function clusterConfigChanges(
  before: StoredConfig | null | undefined,
  after: StoredConfig | null | undefined,
): ConfigChange[] {
  const beforeValues = new Map(describedValues(before ?? {}));
  const afterValues = new Map(describedValues(after ?? {}));
  const labels = [...new Set([...beforeValues.keys(), ...afterValues.keys()])];
  return labels
    .map((label) => ({
      label,
      before: beforeValues.get(label) ?? NOT_SET,
      after: afterValues.get(label) ?? NOT_SET,
    }))
    .filter((change) => change.before !== change.after);
}

/** True when saving would neither change a value nor start a redeploy or a controller action. */
export function nothingToSave(
  before: StoredConfig,
  after: StoredConfig,
  plan: {
    redeployed: readonly unknown[];
    ingressControllers: readonly { action: string }[];
  },
): boolean {
  return (
    clusterConfigChanges(before, after).length === 0 &&
    plan.redeployed.length === 0 &&
    plan.ingressControllers.every(
      (controller) => controller.action === "REMOVE",
    )
  );
}
