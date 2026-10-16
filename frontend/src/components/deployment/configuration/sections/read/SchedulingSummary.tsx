import { resolveConfigValue } from "@/lib/effective-config";
import { ConfigSummaryCard } from "../../ConfigSummaryCard";
import { SummaryRow } from "./SummaryRow";

interface Props {
  /** Raw `Deployment.config` JSON blob (snake_case). */
  deploymentConfig: Record<string, unknown> | null | undefined;
  /** Raw `Environment.config` JSON blob (snake_case). */
  environmentConfig: Record<string, unknown> | null | undefined;
}

/**
 * Read-only summary of the deployment's effective scheduling fields.
 *
 * Walks environment → deployment for each leaf: a cluster does not take
 * scheduling (ADR-033, #482). The per-row dot lights up whenever the
 * deployment layer carries an explicit value for that field; the rest of
 * the row renders the resolved value with no inheritance-specific styling.
 */
export function SchedulingSummary({
  deploymentConfig,
  environmentConfig,
}: Props) {
  const resolve = <T,>(path: string) =>
    resolveConfigValue<T>(null, environmentConfig, deploymentConfig, path);

  const cpuReq = resolve<string>("scheduling.resources.requests.cpu");
  const cpuLim = resolve<string>("scheduling.resources.limits.cpu");
  const memReq = resolve<string>("scheduling.resources.requests.memory");
  const memLim = resolve<string>("scheduling.resources.limits.memory");

  const resourcesFromDeployment =
    cpuReq.fromDeployment ||
    cpuLim.fromDeployment ||
    memReq.fromDeployment ||
    memLim.fromDeployment;
  const resourcesValue = `CPU: ${cpuReq.value ?? "—"}/${cpuLim.value ?? "—"}, Mem: ${memReq.value ?? "—"}/${memLim.value ?? "—"}`;

  const runtimeClass = resolve<string>("scheduling.runtime_class");
  const tolerations = resolve<readonly unknown[]>("scheduling.tolerations");
  const topology = resolve<readonly unknown[]>(
    "scheduling.topology_spread_constraints",
  );
  const nodeAffinity = resolve<unknown>("scheduling.node_affinity");
  const podAffinity = resolve<unknown>("scheduling.pod_affinity");
  const podAntiAffinity = resolve<unknown>("scheduling.pod_anti_affinity");

  const countLabel = (
    arr: readonly unknown[] | null,
    singular: string,
    plural: string,
  ): string => {
    const n = arr?.length ?? 0;
    if (n === 0) return "None";
    return `${n} ${n === 1 ? singular : plural}`;
  };

  return (
    <ConfigSummaryCard title="Scheduling">
      <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
        <SummaryRow
          label="Resources"
          mono
          value={resourcesValue}
          fromDeployment={resourcesFromDeployment}
        />
        <SummaryRow
          label="Runtime class"
          mono
          value={runtimeClass.value ?? "Not set"}
          fromDeployment={runtimeClass.fromDeployment}
        />
        <SummaryRow
          label="Tolerations"
          value={countLabel(tolerations.value, "toleration", "tolerations")}
          fromDeployment={tolerations.fromDeployment}
        />
        <SummaryRow
          label="Topology spread"
          value={countLabel(topology.value, "constraint", "constraints")}
          fromDeployment={topology.fromDeployment}
        />
        <SummaryRow
          label="Node affinity"
          value={nodeAffinity.value != null ? "Configured" : "Not configured"}
          fromDeployment={nodeAffinity.fromDeployment}
        />
        <SummaryRow
          label="Pod affinity"
          value={podAffinity.value != null ? "Configured" : "Not configured"}
          fromDeployment={podAffinity.fromDeployment}
        />
        <SummaryRow
          label="Pod anti-affinity"
          value={
            podAntiAffinity.value != null ? "Configured" : "Not configured"
          }
          fromDeployment={podAntiAffinity.fromDeployment}
        />
      </dl>
    </ConfigSummaryCard>
  );
}
