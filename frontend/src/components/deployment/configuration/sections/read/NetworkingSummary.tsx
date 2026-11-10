import { useId } from "react";

import { resolveConfigValue } from "@/lib/effective-config";
import { ConfigSummaryCard } from "../../ConfigSummaryCard";
import { SummaryRow } from "./SummaryRow";

/**
 * One service of the deployment, as `GetDeployment.deployment.deployedServices`
 * returns it. Only the fields the summary reads are listed.
 */
export interface NetworkingService {
  driverServiceName: string;
  scope: string;
  ingressClass?: string | null;
  ingressClassOverridden: boolean;
  humanReadableFqdn?: string | null;
  fqdnSuffixOverridden: boolean;
}

interface Props {
  /** Raw `Deployment.config` JSON blob (snake_case). */
  deploymentConfig: Record<string, unknown> | null | undefined;
  /** Raw `Environment.config` JSON blob (snake_case). */
  environmentConfig: Record<string, unknown> | null | undefined;
  /** Raw `Cluster.config` JSON blob (snake_case). */
  clusterConfig: Record<string, unknown> | null | undefined;
  /**
   * The services of the deployment (#598, FR-016). Each service that Styrmin
   * builds an Ingress for (`scope: external`) is listed with its effective
   * ingress class and host, each marked Overridden or Inherited. An internal
   * service is left out: Styrmin builds no Ingress for it, so it has no class
   * or host of its own to report.
   */
  services?: readonly NetworkingService[] | null;
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
  services,
}: Props) {
  const externalServices = (services ?? []).filter(
    (service) => service.scope === "external",
  );
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
      {externalServices.length > 0 ? (
        <div className="mt-4 space-y-3 border-t border-border pt-4">
          {externalServices.map((service) => (
            <ServiceIngressGroup
              key={service.driverServiceName}
              service={service}
            />
          ))}
        </div>
      ) : null}
    </ConfigSummaryCard>
  );
}

/** Class and host of one service, named by its driver service name. */
function ServiceIngressGroup({ service }: { service: NetworkingService }) {
  const headingId = useId();
  return (
    <div role="group" aria-labelledby={headingId} className="space-y-2">
      <p id={headingId} className="font-mono text-xs font-semibold">
        {service.driverServiceName}
      </p>
      <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
        <SummaryRow
          label="Ingress class"
          mono
          value={service.ingressClass ?? "Not set"}
          fromDeployment={service.ingressClassOverridden}
          mark={service.ingressClassOverridden ? "Overridden" : "Inherited"}
        />
        <SummaryRow
          label="Host"
          mono
          value={service.humanReadableFqdn ?? "Not set"}
          fromDeployment={service.fqdnSuffixOverridden}
          mark={service.fqdnSuffixOverridden ? "Overridden" : "Inherited"}
        />
      </dl>
    </div>
  );
}
