import type { UpdateDeploymentInput } from "@/generated/graphql";
import type { InheritanceState } from "@/lib/configuration-types";
import { ConfigSummaryCard } from "../../ConfigSummaryCard";

interface Props {
  current: UpdateDeploymentInput;
  environment: UpdateDeploymentInput;
  inheritance: InheritanceState;
}

/**
 * Read-only summary for deployment-scoped env-var overrides. Lists each
 * deployment override as `NAME → value` with the blue overridden treatment,
 * then notes the inherited count from the environment at the bottom.
 */
export function EnvVarsSummary({ current, environment, inheritance }: Props) {
  const overrides = current.envVars ?? [];
  const envCount = environment.envVars?.length ?? 0;

  return (
    <ConfigSummaryCard title="Environment Variables" inheritance={inheritance}>
      {overrides.length === 0 ? (
        <p className="text-sm italic text-muted-foreground">
          no deployment-scoped overrides
        </p>
      ) : (
        <ul className="space-y-1.5">
          {overrides.map((entry) => (
            <li
              key={entry.name}
              data-testid="env-var-override"
              className="flex items-center justify-between gap-3 text-sm"
            >
              <span className="truncate font-mono text-xs text-blue-700 dark:text-blue-300">
                <span className="font-semibold">{entry.name}</span>
                <span className="mx-1 text-muted-foreground">→</span>
                <span>{entry.value === "" ? '""' : entry.value}</span>
              </span>
              <span className="shrink-0 rounded-md border border-blue-200 bg-blue-50 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-blue-700 dark:border-blue-900 dark:bg-blue-950/40 dark:text-blue-300">
                override
              </span>
            </li>
          ))}
        </ul>
      )}
      {envCount > 0 ? (
        <p className="mt-3 text-xs italic text-muted-foreground">
          + {envCount} inherited from environment
        </p>
      ) : null}
    </ConfigSummaryCard>
  );
}
