import type {
  DiffEntry,
  ImpactContext,
  ImpactRule,
} from "./configuration-types";

const COMPONENT_OVERRIDE_CONSEQUENCE =
  "Component override changed; affected component will reconcile";

/** One line per replica change, for example `server: 3 → 1 pod` (023). */
export function describeReplicaChange(
  entry: DiffEntry,
  context: ImpactContext,
): string {
  const component = /^components\[(.+)\]\.replicas$/.exec(entry.path)?.[1];
  if (component === undefined) return entry.path;
  const fallback = context.replicaDefaults?.get(component) ?? null;
  // An empty side is no override: the driver default or the chart's count applies.
  const side = (value: string): number | null =>
    value !== "" ? Number(value) : fallback;
  const pods = (n: number) => `${n} ${n === 1 ? "pod" : "pods"}`;
  const before = side(entry.before);
  const after = side(entry.after);
  if (before != null && after != null) {
    return `${component}: ${before} → ${pods(after)}`;
  }
  const label = (n: number | null) =>
    n != null ? pods(n) : "the chart's count";
  return `${component}: ${label(before)} → ${label(after)}`;
}

/**
 * Initial impact rule table. Mirrors
 * `specs/011-unified-deployment-config/contracts/impact-rule-table.md`
 * verbatim (matcher / consequence / severity).
 *
 * The rules are intentionally approximate. They will be refined as
 * production telemetry shows which changes actually trigger restarts,
 * and eventually replaced by a backend-computed `previewUpdateDeployment`
 * response — at which point `lib/config-impact.ts` swaps the rule-table
 * evaluation for a query call without changing the `ImpactSummary`
 * return shape.
 */
export const impactRules: ImpactRule[] = [
  {
    matcher: "name",
    consequence: "Deployment will be renamed; no pod restart",
    severity: "informational",
  },
  {
    matcher: "parameters.**",
    consequence:
      "Driver will be re-rendered; pods may restart depending on parameter semantics",
    severity: "warning",
  },
  {
    matcher: "scheduling.resources.**",
    consequence: "Pods will be recreated with new resource limits",
    severity: "warning",
  },
  {
    matcher: "scheduling.tolerations",
    consequence: "Pods on affected tainted nodes may be evicted",
    severity: "warning",
  },
  {
    matcher: "scheduling.tolerations[*].effect value:NO_EXECUTE",
    consequence: "Existing pods on tainted nodes will be drained immediately",
    severity: "high",
  },
  {
    matcher: "scheduling.nodeAffinity",
    consequence: "Pods will be rescheduled to match new node affinity",
    severity: "warning",
  },
  {
    matcher: "scheduling.podAffinity",
    consequence: "Pods will be rescheduled to match new pod affinity",
    severity: "warning",
  },
  {
    matcher: "scheduling.podAntiAffinity",
    consequence: "Pods will be rescheduled to match new pod anti-affinity",
    severity: "warning",
  },
  {
    matcher: "scheduling.topologySpreadConstraints",
    consequence: "Pods will be redistributed across topology domains",
    severity: "warning",
  },
  {
    matcher: "scheduling.runtimeClass",
    consequence: "Pods will be recreated under new runtime class",
    severity: "warning",
  },
  {
    matcher: "envVars[*]",
    consequence: "Pods will be recreated to pick up new environment",
    severity: "warning",
  },
  {
    matcher: "ipWhitelist",
    consequence: "Ingress controller allowlist will be reconfigured",
    severity: "informational",
  },
  {
    matcher: "dedicatedIngress",
    consequence: "Dedicated ingress controller will be reconciled",
    severity: "warning",
  },
  {
    matcher: "ingressClass",
    consequence: "Ingress + external DNS records will be reconfigured",
    severity: "warning",
  },
  {
    matcher: "fqdnSuffix",
    consequence:
      "External DNS records will be republished under the new suffix",
    severity: "warning",
  },
  {
    matcher: "externalUrlScheme",
    consequence:
      "External URL scheme will change; clients with hard-coded schemes may need updates",
    severity: "warning",
  },
  {
    matcher: "externalUrlPort",
    consequence:
      "External URL port will change; clients with hard-coded ports may need updates",
    severity: "warning",
  },
  {
    matcher: "externalDnsEndpointsType",
    consequence:
      "External DNS endpoint source will change; records may be republished",
    severity: "warning",
  },
  {
    matcher: "dbSize",
    consequence:
      "Database resize may schedule a managed-DB action and trigger a brief unavailability window",
    severity: "warning",
  },
  {
    matcher: "backupTtl",
    consequence:
      "Retention change applies to future backups only; backups already created keep the expiration fixed at their creation",
    severity: "informational",
  },
  {
    matcher: "standardStorage.storageClass",
    consequence:
      "Standard storage class change applies to newly-provisioned volumes only; existing volumes are unaffected",
    severity: "informational",
  },
  {
    // Matches the bare `fastStorage` path because `config-diff` reports the
    // whole block as one entry (`diffJsonObject`) rather than descending into
    // `storageClass`. Note the neighbouring `standardStorage.storageClass`
    // matcher above expects a sub-path the diff never emits, so it is
    // currently dead — see this commit's message.
    matcher: "fastStorage",
    consequence:
      "Fast storage class change applies to newly-provisioned volumes only; existing volumes are unaffected",
    severity: "informational",
  },
  {
    matcher: "serviceNameOverrides",
    consequence:
      "Kubernetes Service objects will be renamed; DNS clients will see new names",
    severity: "high",
  },
  {
    matcher: "services[*].ingressClass",
    consequence:
      "Ingress of this service will be recreated under the new class; other services are not affected. An overridden Ingress carries only the ingress class: the IP allow-list, the external DNS record and the application address are not applied to it",
    severity: "warning",
  },
  {
    matcher: "services[*].fqdnSuffix",
    consequence:
      "Ingress of this service will use hosts under the new suffix; other services are not affected. An overridden Ingress carries only the ingress class: no entry-point, external DNS, Cloudflare or allow-list annotation is set, so the IP allow-list and the external DNS record are not applied to it, and the application address is not on it",
    severity: "warning",
  },
  {
    matcher: "services[*].tls",
    consequence:
      "TLS hosts on this service's Ingress will change. The ingress controller must provide TLS; other services are not affected. A service override removes the IP allow-list, the external DNS record and the application address from this Ingress; clearing the last override restores the defaults",
    severity: "warning",
  },
  {
    matcher: "components[*].resources.**",
    consequence: "Affected component's pods will be recreated",
    severity: "warning",
  },
  {
    matcher: "components[*].replicas",
    consequence: "Component pod count will change",
    severity: "warning",
    describe: describeReplicaChange,
  },
  {
    matcher: "components[*].envVars[*]",
    consequence: COMPONENT_OVERRIDE_CONSEQUENCE,
    severity: "warning",
  },
  {
    matcher: "components[*].image",
    consequence: COMPONENT_OVERRIDE_CONSEQUENCE,
    severity: "warning",
  },
  {
    matcher: "components[*].command",
    consequence: COMPONENT_OVERRIDE_CONSEQUENCE,
    severity: "warning",
  },
  {
    matcher: "components[*].args",
    consequence: COMPONENT_OVERRIDE_CONSEQUENCE,
    severity: "warning",
  },
];
