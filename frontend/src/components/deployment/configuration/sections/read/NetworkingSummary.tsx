import { resolveConfigValue } from "@/lib/effective-config";
import { ConfigSummaryCard } from "../../ConfigSummaryCard";
import { SummaryRow } from "./SummaryRow";

interface Props {
  /** Raw `Deployment.config` JSON blob (snake_case). */
  deploymentConfig: Record<string, unknown> | null | undefined;
  /** Raw `Environment.config` JSON blob (snake_case). */
  environmentConfig: Record<string, unknown> | null | undefined;
  /** Raw `Cluster.config` JSON blob (snake_case). */
  clusterConfig: Record<string, unknown> | null | undefined;
}

/**
 * Read-only summary of the deployment's effective networking fields.
 *
 * Walks the cluster → environment → deployment chain for every leaf and
 * surfaces the most-specific defined value. Rows where the deployment layer
 * explicitly defines a value get a small blue dot at the row's left edge;
 * inherited rows render identically minus the dot.
 */
export function NetworkingSummary({
  deploymentConfig,
  environmentConfig,
  clusterConfig,
}: Props) {
  const resolve = <T,>(path: string) =>
    resolveConfigValue<T>(
      clusterConfig,
      environmentConfig,
      deploymentConfig,
      path,
    );

  const suffix = resolve<string>("fqdn_suffix");
  const scheme = resolve<string>("external_url_scheme");
  const port = resolve<number>("external_url_port");
  const ingressClass = resolve<string>("ingress_class");
  const externalDns = resolve<string>("external_dns_endpoints_type");
  const dedicated = resolve<Record<string, unknown>>("dedicated_ingress");
  const ipWhitelist = resolve<readonly string[]>("ip_whitelist");

  // Combined external URL row — the dot fires if EITHER scheme or port was
  // set at the deployment layer, since both contribute to the displayed
  // "scheme://:port" string.
  const externalUrlFromDeployment =
    scheme.fromDeployment || port.fromDeployment;
  const externalUrlValue =
    scheme.value == null && port.value == null
      ? "Not set"
      : `${scheme.value ?? "—"}://:${port.value ?? "—"}`;

  return (
    <ConfigSummaryCard title="Networking">
      <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
        <SummaryRow
          label="FQDN suffix"
          mono
          value={suffix.value ?? "Not set"}
          fromDeployment={suffix.fromDeployment}
        />
        <SummaryRow
          label="External URL"
          mono
          value={externalUrlValue}
          fromDeployment={externalUrlFromDeployment}
        />
        <SummaryRow
          label="Ingress class"
          mono
          value={ingressClass.value ?? "Not set"}
          fromDeployment={ingressClass.fromDeployment}
        />
        <SummaryRow
          label="External DNS source"
          value={externalDns.value ?? "Not set"}
          fromDeployment={externalDns.fromDeployment}
        />
        <SummaryRow
          label="Dedicated ingress"
          value={dedicated.value != null ? "Configured" : "Not configured"}
          fromDeployment={dedicated.fromDeployment}
        />
        <SummaryRow
          label="IP allowlist"
          mono
          value={
            ipWhitelist.value && ipWhitelist.value.length > 0
              ? ipWhitelist.value.join(", ")
              : "Not set"
          }
          fromDeployment={ipWhitelist.fromDeployment}
        />
      </dl>
    </ConfigSummaryCard>
  );
}
