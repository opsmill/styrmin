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
  dedicated_ingress_type: z.union([
    z.enum(["ingress", "gateway"]),
    z.literal(""),
  ]),
  dedicated_ingress_service_type: z.union([
    z.enum(["LoadBalancer", "ClusterIP", "NodePort"]),
    z.literal(""),
  ]),
  dedicated_ingress_service_node_port: z.string(),
  dedicated_ingress_service_external_traffic_policy: z.union([
    z.enum(["Cluster", "Local"]),
    z.literal(""),
  ]),
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
    dedicated_ingress_type: oneOf(di?.type, ["ingress", "gateway"]),
    dedicated_ingress_service_type: oneOf(service?.type, [
      "LoadBalancer",
      "ClusterIP",
      "NodePort",
    ]),
    dedicated_ingress_service_node_port: asPortString(service?.node_port),
    dedicated_ingress_service_external_traffic_policy: oneOf(
      service?.external_traffic_policy,
      ["Cluster", "Local"],
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
  if (Object.keys(service).length > 0) merged.service = service;
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
