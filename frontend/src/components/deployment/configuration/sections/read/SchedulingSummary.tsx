import type {
  SchedulingInput,
  UpdateDeploymentInput,
} from "@/generated/graphql";
import type { InheritanceState } from "@/lib/configuration-types";
import { ConfigSummaryCard } from "../../ConfigSummaryCard";
import { SummaryRow } from "./SummaryRow";

interface Props {
  current: UpdateDeploymentInput;
  environment: UpdateDeploymentInput;
  inheritance: InheritanceState;
}

/**
 * Read-only summary for the `scheduling` slice of `UpdateDeploymentInput`.
 *
 * Each row pulls the deployment-set value when present, falls back to the
 * environment-set value when inherited, and renders muted italic when the
 * value came from the environment.
 */
export function SchedulingSummary({
  current,
  environment,
  inheritance,
}: Props) {
  const dep = current.scheduling ?? null;
  const env = environment.scheduling ?? null;

  const resources = resolve(dep?.resources, env?.resources, formatResources);
  const runtime = resolve(
    dep?.runtimeClass,
    env?.runtimeClass,
    (v) => v ?? "—",
  );
  const tolerations = resolve(
    dep?.tolerations,
    env?.tolerations,
    (list) => `${list?.length ?? 0} toleration${list?.length === 1 ? "" : "s"}`,
  );
  const topology = resolve(
    dep?.topologySpreadConstraints,
    env?.topologySpreadConstraints,
    (list) => {
      const n = list?.length ?? 0;
      if (n === 0) return "none";
      const first = list![0];
      return `${n} (${first.topologyKey}, maxSkew ${first.maxSkew})`;
    },
  );
  const nodeAffinity = resolve(
    dep?.nodeAffinity,
    env?.nodeAffinity,
    summarizeAffinity,
  );
  const podAntiAffinity = resolve(
    dep?.podAntiAffinity,
    env?.podAntiAffinity,
    summarizeAffinity,
  );

  return (
    <ConfigSummaryCard title="Scheduling" inheritance={inheritance}>
      <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
        <SummaryRow label="Resources" mono {...resources} />
        <SummaryRow label="Runtime class" mono {...runtime} />
        <SummaryRow label="Tolerations" {...tolerations} />
        <SummaryRow label="Topology spread" {...topology} />
        <SummaryRow label="Node affinity" {...nodeAffinity} />
        <SummaryRow label="Pod anti-affinity" {...podAntiAffinity} />
      </dl>
    </ConfigSummaryCard>
  );
}

function resolve<T>(
  deploymentValue: T | null | undefined,
  environmentValue: T | null | undefined,
  formatter: (v: T | null | undefined) => string,
): { value: string; inherited: boolean } {
  if (deploymentValue !== undefined && deploymentValue !== null) {
    return { value: formatter(deploymentValue), inherited: false };
  }
  if (environmentValue !== undefined && environmentValue !== null) {
    return { value: formatter(environmentValue), inherited: true };
  }
  return { value: "not set", inherited: true };
}

function formatResources(r: SchedulingInput["resources"]): string {
  if (!r) return "not set";
  const cpu = `${r.requests?.cpu ?? "—"}/${r.limits?.cpu ?? "—"}`;
  const mem = `${r.requests?.memory ?? "—"}/${r.limits?.memory ?? "—"}`;
  return `${cpu} · ${mem}`;
}

function summarizeAffinity(block: SchedulingInput["nodeAffinity"]): string {
  if (!block) return "not set";
  const required = block.required?.length ?? 0;
  const preferred = block.preferred?.length ?? 0;
  if (required === 0 && preferred === 0) return "empty";
  return `required: ${required}, preferred: ${preferred}`;
}
