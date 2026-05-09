/**
 * Helpers for EnvironmentConfigurationTab — extracted into a sibling
 * file so the component file stays Fast-Refresh-friendly
 * (``react-refresh/only-export-components``) and so unit tests can
 * import the helpers without instantiating the component.
 *
 * Scope (011/US2 — frontend enum value-transform layer):
 * - ``EXTERNAL_URL_SCHEME_MAP`` / ``EXTERNAL_DNS_ENDPOINTS_TYPE_MAP``:
 *   declarative Pydantic-string ↔ GraphQL-literal mapping tables.
 * - ``transformEnumValue``: generic write-side transform that throws
 *   on unrecognised values (FR-006) instead of silently corrupting
 *   data via TypeScript-only ``as`` casts.
 * - ``buildFullReplacementInput``: assembles the full
 *   ``UpdateEnvironmentInput`` from a persisted JSON config + the
 *   form's edited env-var rows. Carries every ``EnvironmentConfig``
 *   scalar field through unchanged; nests stay ``null`` (the form
 *   blocks submission upstream when the persisted config has nested
 *   overrides — see ``detectNestedOverridesBlock`` in the component
 *   file).
 */
import type { EnvVarPayload } from "@/components/environment/EnvVarsForm";
import type {
  ExternalDnsEndpointsType,
  ExternalUrlScheme,
  UpdateEnvironmentInput,
} from "@/generated/graphql";

/**
 * Pydantic-side ↔ GraphQL-literal mapping for ``external_url_scheme``.
 *
 * Persisted ``Environment.config`` carries lowercase strings ("http" /
 * "https") — Pydantic's ``Literal["http", "https"]``. The GraphQL
 * ``ExternalUrlScheme`` enum uses uppercase literals (``HTTP`` / ``HTTPS``).
 */
export const EXTERNAL_URL_SCHEME_MAP = {
  http: "HTTP",
  https: "HTTPS",
} as const satisfies Record<string, ExternalUrlScheme>;

/**
 * Pydantic-side ↔ GraphQL-literal mapping for ``external_dns_endpoints_type``.
 *
 * Persisted JSON carries Pydantic ``Literal["NodeExternalIP", "ClusterIP"]``;
 * GraphQL ``ExternalDnsEndpointsType`` uses ``NODE_EXTERNAL_IP`` / ``CLUSTER_IP``.
 */
export const EXTERNAL_DNS_ENDPOINTS_TYPE_MAP = {
  NodeExternalIP: "NODE_EXTERNAL_IP",
  ClusterIP: "CLUSTER_IP",
} as const satisfies Record<string, ExternalDnsEndpointsType>;

/**
 * Translate a persisted Pydantic-side enum string to its GraphQL literal.
 *
 * - ``null`` / ``undefined`` → ``null`` (unset; full-replacement intent).
 * - Recognised string → mapped literal.
 * - Unrecognised string OR non-string → throws a clear ``Error`` naming the
 *   field and the offending value (FR-006). The form's submit handler
 *   surfaces the message to the operator via ``submitError``; corrupt data
 *   is never sent to the backend.
 *
 * This helper is the single ``as``-cast site for these values (FR-005).
 */
export function transformEnumValue<E extends string>(
  field: string,
  value: unknown,
  mapping: Record<string, E>,
): E | null {
  if (value === null || value === undefined) return null;
  if (typeof value !== "string") {
    throw new Error(`Field ${field}: expected string, got ${typeof value}`);
  }
  const transformed = mapping[value];
  if (transformed === undefined) {
    throw new Error(
      `Field ${field}: unrecognised value "${value}". ` +
        `Expected one of: ${Object.keys(mapping).join(", ")}`,
    );
  }
  return transformed;
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((v): v is string => typeof v === "string");
}

/**
 * Build the full-replacement ``UpdateEnvironmentInput`` from the
 * persisted JSON config + the edited env-var rows.
 *
 * Every public ``EnvironmentConfig`` scalar field is carried through
 * unchanged; the two enum-valued fields go through
 * ``transformEnumValue``. The two nested input types
 * (``dedicatedIngress`` / ``scheduling``) stay ``null`` — the form
 * blocks submission upstream when either is set on the persisted
 * config, so this builder is only reached when both are absent.
 */
export function buildFullReplacementInput(
  config: Record<string, unknown> | null | undefined,
  envVars: EnvVarPayload[],
): UpdateEnvironmentInput {
  const ipWhitelist = asStringArray(config?.ip_whitelist);
  const fqdnSuffix =
    typeof config?.fqdn_suffix === "string" ? config.fqdn_suffix : null;
  const externalUrlScheme = transformEnumValue(
    "externalUrlScheme",
    config?.external_url_scheme,
    EXTERNAL_URL_SCHEME_MAP,
  );
  const externalUrlPort =
    typeof config?.external_url_port === "number"
      ? config.external_url_port
      : null;
  const externalDnsEndpointsType = transformEnumValue(
    "externalDnsEndpointsType",
    config?.external_dns_endpoints_type,
    EXTERNAL_DNS_ENDPOINTS_TYPE_MAP,
  );
  const ingressClass =
    typeof config?.ingress_class === "string" ? config.ingress_class : null;
  const dbSize = typeof config?.db_size === "string" ? config.db_size : null;

  return {
    envVars: envVars.map((v) => ({ name: v.name, value: v.value })),
    ipWhitelist: ipWhitelist.length > 0 ? ipWhitelist : null,
    fqdnSuffix,
    externalUrlScheme,
    externalUrlPort,
    externalDnsEndpointsType,
    ingressClass,
    dbSize,
    dedicatedIngress: null,
    scheduling: null,
  };
}
