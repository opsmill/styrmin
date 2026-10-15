import type {
  DedicatedIngressInput,
  IngressServiceConfigInput,
  UpdateClusterInput,
} from "@/generated/graphql";
import {
  EXTERNAL_DNS_ENDPOINTS_TYPE_MAP,
  EXTERNAL_URL_SCHEME_MAP,
  transformEnumValue,
} from "@/pages/environments/EnvironmentConfigurationTab.helpers";
import { normalizeSchedulingEnums } from "./deployment-input";

type StoredConfig = Record<string, unknown>;

function asRecord(value: unknown): StoredConfig | undefined {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as StoredConfig)
    : undefined;
}

function asString(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function asNumber(value: unknown): number | undefined {
  return typeof value === "number" ? value : undefined;
}

/** Drop keys whose value is `undefined`, so an absent stored value stays absent in the input. */
function defined<T extends object>(input: T): T {
  return Object.fromEntries(
    Object.entries(input).filter(([, value]) => value !== undefined),
  ) as T;
}

function serviceToInput(service: StoredConfig): IngressServiceConfigInput {
  return defined({
    type: asString(service.type),
    annotations: asRecord(service.annotations),
    loadBalancerIp: asString(service.load_balancer_ip),
    externalTrafficPolicy: asString(service.external_traffic_policy),
    ipFamilies: Array.isArray(service.ip_families)
      ? service.ip_families.filter((v): v is string => typeof v === "string")
      : undefined,
    ipFamilyPolicy: asString(service.ip_family_policy),
    nodePort: asNumber(service.node_port),
  });
}

function dedicatedIngressToInput(
  di: StoredConfig | undefined,
): DedicatedIngressInput | undefined {
  if (di === undefined) return undefined;
  const service = asRecord(di.service);
  return defined({
    implementation: asString(di.implementation),
    type: asString(di.type),
    service: service ? serviceToInput(service) : undefined,
  });
}

function storageToInput(
  storage: StoredConfig | undefined,
): { storageClass: string } | undefined {
  const storageClass = asString(storage?.storage_class);
  return storageClass === undefined ? undefined : { storageClass };
}

/**
 * Stored cluster config (snake_case keys, stored enum values) → the
 * full-replacement `UpdateClusterInput` (camelCase keys, GraphQL enum names).
 * An absent value stays absent. Throws on an enum value it does not know.
 */
export function clusterConfigToInput(config: StoredConfig): UpdateClusterInput {
  return defined({
    ingressClass: asString(config.ingress_class),
    runtimeClass: asString(config.runtime_class),
    fqdnSuffix: asString(config.fqdn_suffix),
    externalUrlScheme:
      transformEnumValue(
        "externalUrlScheme",
        config.external_url_scheme,
        EXTERNAL_URL_SCHEME_MAP,
      ) ?? undefined,
    externalUrlPort: asNumber(config.external_url_port),
    externalDnsEndpointsType:
      transformEnumValue(
        "externalDnsEndpointsType",
        config.external_dns_endpoints_type,
        EXTERNAL_DNS_ENDPOINTS_TYPE_MAP,
      ) ?? undefined,
    dedicatedIngress: dedicatedIngressToInput(
      asRecord(config.dedicated_ingress),
    ),
    standardStorage: storageToInput(asRecord(config.standard_storage)),
    fastStorage: storageToInput(asRecord(config.fast_storage)),
    scheduling: normalizeSchedulingEnums(config.scheduling),
    dbSize: asString(config.db_size),
    backupTtl: asString(config.backup_ttl),
  });
}
