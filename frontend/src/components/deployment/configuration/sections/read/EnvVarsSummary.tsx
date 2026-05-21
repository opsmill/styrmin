import {
  computeEffectiveEnvVars,
  type ConfigOrigin,
  type EffectiveEnvVar,
} from "@/lib/effective-config";
import { ConfigSummaryCard } from "../../ConfigSummaryCard";

interface Props {
  /** Raw `Deployment.config` JSON blob (snake_case). */
  deploymentConfig: Record<string, unknown> | null | undefined;
  /** Raw `Environment.config` JSON blob (snake_case). */
  environmentConfig: Record<string, unknown> | null | undefined;
  /** Raw `Cluster.config` JSON blob (snake_case). */
  clusterConfig: Record<string, unknown> | null | undefined;
  /** Display name of the parent environment, for the badge. */
  environmentName: string;
  /** Display name of the parent cluster, for the badge. */
  clusterName: string;
}

/**
 * Read-only summary of *effective* environment variables. Walks the
 * `Cluster.config → Environment.config → Deployment.config` chain and lists
 * each variable that would actually land on the deployment's pods, attributed
 * to the layer that defined it.
 *
 * Deployment-defined vars come first (the operator is most likely to inspect
 * those); environment-only and cluster-only vars follow, alphabetical within
 * each origin.
 */
export function EnvVarsSummary({
  deploymentConfig,
  environmentConfig,
  clusterConfig,
  environmentName,
  clusterName,
}: Props) {
  const effective = computeEffectiveEnvVars(
    clusterConfig,
    environmentConfig,
    deploymentConfig,
  );

  return (
    <ConfigSummaryCard title="Environment Variables">
      {effective.length === 0 ? (
        <p className="text-sm italic text-muted-foreground">
          no environment variables defined at any level
        </p>
      ) : (
        <ul className="space-y-1.5" data-testid="env-vars-effective-list">
          {effective.map((entry) => (
            <EnvVarRow
              key={entry.name}
              entry={entry}
              environmentName={environmentName}
              clusterName={clusterName}
            />
          ))}
        </ul>
      )}
    </ConfigSummaryCard>
  );
}

function EnvVarRow({
  entry,
  environmentName,
  clusterName,
}: {
  entry: EffectiveEnvVar;
  environmentName: string;
  clusterName: string;
}) {
  const valueDisplay = entry.value === "" ? '""' : entry.value;
  return (
    <li
      data-testid="env-var-row"
      data-origin={entry.origin}
      className="flex items-center justify-between gap-3 text-sm"
    >
      <span className="truncate font-mono text-xs">
        <span className="font-semibold text-foreground">{entry.name}</span>
        <span className="mx-1 text-muted-foreground">→</span>
        <span className="text-foreground">{valueDisplay}</span>
      </span>
      <OriginBadge
        origin={entry.origin}
        environmentName={environmentName}
        clusterName={clusterName}
      />
    </li>
  );
}

const ORIGIN_STYLES: Record<ConfigOrigin, string> = {
  cluster:
    "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300",
  environment:
    "border-violet-200 bg-violet-50 text-violet-800 dark:border-violet-900 dark:bg-violet-950/40 dark:text-violet-300",
  deployment:
    "border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-900 dark:bg-blue-950/40 dark:text-blue-300",
};

function OriginBadge({
  origin,
  environmentName,
  clusterName,
}: {
  origin: ConfigOrigin;
  environmentName: string;
  clusterName: string;
}) {
  const label =
    origin === "deployment"
      ? "deployment"
      : origin === "environment"
        ? `env: ${environmentName}`
        : `cluster: ${clusterName}`;
  return (
    <span
      data-testid={`env-var-origin-${origin}`}
      className={`shrink-0 rounded-md border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${ORIGIN_STYLES[origin]}`}
    >
      {label}
    </span>
  );
}
