import type { UpdateDeploymentInput } from "@/generated/graphql";
import type { InheritanceState } from "@/lib/configuration-types";
import { ConfigSummaryCard } from "../../ConfigSummaryCard";

interface Props {
  current: UpdateDeploymentInput;
  environment: UpdateDeploymentInput;
  inheritance: InheritanceState;
}

/**
 * Read-only summary for `serviceNameOverrides` — the list of operator-chosen
 * renames mapping driver-declared service names to override names.
 *
 * Renders nothing more than a muted "no overrides" line when empty, since
 * service-name overrides only exist on deployments (no environment fallback).
 */
export function ServiceOverridesSummary({ current, inheritance }: Props) {
  const overrides = current.serviceNameOverrides ?? [];

  return (
    <ConfigSummaryCard title="Service Overrides" inheritance={inheritance}>
      {overrides.length === 0 ? (
        <p className="text-sm italic text-muted-foreground">no overrides</p>
      ) : (
        <ul className="space-y-1.5">
          {overrides.map((entry) => (
            <li
              key={entry.driverServiceName}
              data-testid="service-name-override"
              className="flex items-center gap-2 font-mono text-xs"
            >
              <span className="text-muted-foreground">
                {entry.driverServiceName}
              </span>
              <span aria-hidden="true" className="text-muted-foreground">
                →
              </span>
              <span className="font-medium text-blue-700 dark:text-blue-300">
                {entry.overrideName}
              </span>
            </li>
          ))}
        </ul>
      )}
    </ConfigSummaryCard>
  );
}
