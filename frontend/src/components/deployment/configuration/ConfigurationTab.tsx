import { useMemo, useState } from "react";
import type {
  GetDeploymentQuery,
  UpdateDeploymentInput,
} from "@/generated/graphql";
import { useEffectiveRole } from "@/auth/useEffectiveRole";
import {
  deploymentConfigToInput,
  deploymentParametersToInput,
} from "@/lib/deployment-input";
import { computeInheritance } from "@/lib/config-inheritance";
import type {
  DriverParameterSchema,
  InheritanceState,
  SectionId,
} from "@/lib/configuration-types";
import { HeroSummaryBar } from "./HeroSummaryBar";
import { ViewJsonDialog } from "./ViewJsonDialog";
import { DriverParametersSummary } from "./sections/read/DriverParametersSummary";
import { SchedulingSummary } from "./sections/read/SchedulingSummary";
import { NetworkingSummary } from "./sections/read/NetworkingSummary";
import { EnvVarsSummary } from "./sections/read/EnvVarsSummary";
import { StorageRuntimeSummary } from "./sections/read/StorageRuntimeSummary";
import { ServiceOverridesSummary } from "./sections/read/ServiceOverridesSummary";

/**
 * Non-null `deployment` payload returned by the `GetDeployment` query.
 *
 * Extracted as a discrete type so the tab component's prop signature stays
 * narrow (the page-level loader filters out the `null` case before it ever
 * mounts the tab).
 */
type Deployment = NonNullable<GetDeploymentQuery["deployment"]>;

interface Props {
  deployment: Deployment;
}

const DEFAULT_INHERITED: InheritanceState = { kind: "inherited" };

/**
 * Top-level composition for the Configuration tab on the Deployment detail
 * page (Paper mock `D2 — Configuration Tab (Read)`).
 *
 * Composes:
 *   - `HeroSummaryBar` (dark navy strip with aggregate counts + actions)
 *   - 6 section summary cards in the order:
 *     Driver Parameters → Scheduling → Networking → Env Vars
 *     → Storage & Runtime → Service Overrides
 *
 * Component Overrides is added by Phase 6 (US4), so it is intentionally
 * omitted here.
 *
 * The Edit drawer wiring lives in Phase 4 (US2). For this slice, the Edit
 * CTA's `onClick` is a no-op placeholder.
 */
export function ConfigurationTab({ deployment }: Props) {
  const [viewJsonOpen, setViewJsonOpen] = useState(false);

  // Project the deployment's persisted config + parent environment's persisted
  // config through the same read-side helper so every section sees the same
  // typed shape and the diff/inheritance helpers can run unchanged.
  const current = useMemo<UpdateDeploymentInput>(() => {
    const base = deploymentConfigToInput(deployment.config);
    // `deploymentConfigToInput` intentionally ignores the row-level
    // `parameters`, `name`, and `serviceNameOverrides` fields. Merge them in
    // here so the inheritance/diff helpers see the full deployment view.
    return {
      ...base,
      name: deployment.name,
      parameters: deploymentParametersToInput(deployment.parameters),
    };
  }, [deployment.config, deployment.name, deployment.parameters]);

  const environment = useMemo<UpdateDeploymentInput>(
    () => deploymentConfigToInput(deployment.environment.config),
    [deployment.environment.config],
  );

  const driverSchema = useMemo<DriverParameterSchema>(
    () => deployment.applicationDriverVersion?.parameters ?? [],
    [deployment.applicationDriverVersion?.parameters],
  );

  const inheritanceMap = useMemo(
    () => computeInheritance(current, environment, driverSchema),
    [current, environment, driverSchema],
  );

  const effectiveRole = useEffectiveRole();
  // FR-030: the Edit CTA mirrors the server-side authorization on
  // `updateDeployment`, which requires READ_WRITE or higher. The full
  // per-deployment permission helper is wired in slice 2 (US2); for the
  // read-only tab the role check is sufficient because the CTA itself is
  // a no-op stub here.
  const canEdit = effectiveRole === "READ_WRITE" || effectiveRole === "ADMIN";

  const getInheritance = (section: SectionId): InheritanceState =>
    inheritanceMap.get(section) ?? DEFAULT_INHERITED;

  return (
    <div className="flex flex-col gap-5" data-testid="configuration-tab">
      <HeroSummaryBar
        deployment={{ id: deployment.id, name: deployment.name }}
        environment={{
          id: deployment.environment.id,
          name: deployment.environment.name,
        }}
        driverSchema={driverSchema}
        inheritance={inheritanceMap}
        current={current}
        canEdit={canEdit}
        onEditClick={() => {
          // TODO(US2 / slice 2): open the ConfigEditDrawer once it lands.
          // Intentionally a no-op for the read-only Configuration tab slice.
          console.info(
            "[ConfigurationTab] Edit configuration clicked — drawer arrives in US2",
          );
        }}
        onViewJsonClick={() => setViewJsonOpen(true)}
      />

      <DriverParametersSummary
        current={current}
        environment={environment}
        driverSchema={driverSchema}
        inheritance={getInheritance("driverParameters")}
      />
      <SchedulingSummary
        current={current}
        environment={environment}
        inheritance={getInheritance("scheduling")}
      />
      <NetworkingSummary
        current={current}
        environment={environment}
        inheritance={getInheritance("networking")}
      />
      <EnvVarsSummary
        current={current}
        environment={environment}
        inheritance={getInheritance("envVars")}
      />
      <StorageRuntimeSummary
        current={current}
        environment={environment}
        inheritance={getInheritance("storageRuntime")}
      />
      <ServiceOverridesSummary
        current={current}
        environment={environment}
        inheritance={getInheritance("serviceOverrides")}
      />

      <ViewJsonDialog
        open={viewJsonOpen}
        onOpenChange={setViewJsonOpen}
        deployment={{
          id: deployment.id,
          name: deployment.name,
          config: deployment.config,
        }}
      />
    </div>
  );
}
