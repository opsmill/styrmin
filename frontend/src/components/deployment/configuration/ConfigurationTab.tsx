import { useMemo, useState } from "react";
import type {
  GetDeploymentQuery,
  UpdateDeploymentInput,
} from "@/generated/graphql";
import { useEffectiveRole } from "@/auth/useEffectiveRole";
import { Button } from "@/components/ui/button";
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
import { ConfigEditDrawer } from "./ConfigEditDrawer";
import { DriverParametersSummary } from "./sections/read/DriverParametersSummary";
import { SchedulingSummary } from "./sections/read/SchedulingSummary";
import { NetworkingSummary } from "./sections/read/NetworkingSummary";
import { EnvVarsSummary } from "./sections/read/EnvVarsSummary";
import { StorageRuntimeSummary } from "./sections/read/StorageRuntimeSummary";
import { ServiceOverridesSummary } from "./sections/read/ServiceOverridesSummary";
import { ComponentOverridesSummary } from "./sections/read/ComponentOverridesSummary";

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
 * Top-level composition for the Settings tab on the Deployment detail page.
 *
 * Layout (top to bottom):
 *   - A thin toolbar with a single "Update Settings" CTA (visible only when
 *     the operator has edit permission per FR-030).
 *   - 7 section summary cards in the order set by `SECTION_ORDER` minus the
 *     drawer-only "identity" section: env vars and service overrides come
 *     first (environment-shaped concerns), driver parameters and infrastructure
 *     in the middle, scheduling last as the advanced/disruptive section.
 *
 * The unified edit surface (drawer + diff/impact dialog) opens from the CTA.
 */
export function ConfigurationTab({ deployment }: Props) {
  const [editDrawerOpen, setEditDrawerOpen] = useState(false);

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
  // FR-030: the Update CTA mirrors the server-side authorization on
  // `updateDeployment`, which requires READ_WRITE or higher.
  const canEdit = effectiveRole === "READ_WRITE" || effectiveRole === "ADMIN";

  const getInheritance = (section: SectionId): InheritanceState =>
    inheritanceMap.get(section) ?? DEFAULT_INHERITED;

  return (
    <div className="flex flex-col gap-5" data-testid="settings-tab">
      {canEdit ? (
        <div className="flex justify-end">
          <Button
            data-testid="settings-update-button"
            onClick={() => setEditDrawerOpen(true)}
          >
            Update Settings
          </Button>
        </div>
      ) : null}

      <EnvVarsSummary
        deploymentConfig={deployment.config}
        environmentConfig={deployment.environment.config}
        clusterConfig={deployment.environment.cluster.config}
        environmentName={deployment.environment.name}
        clusterName={deployment.environment.cluster.name}
        inheritance={getInheritance("envVars")}
      />
      <ServiceOverridesSummary
        deployedServices={deployment.deployedServices}
        inheritance={getInheritance("serviceOverrides")}
      />
      <DriverParametersSummary
        current={current}
        environment={environment}
        driverSchema={driverSchema}
        inheritance={getInheritance("driverParameters")}
      />
      <NetworkingSummary
        current={current}
        environment={environment}
        inheritance={getInheritance("networking")}
      />
      <StorageRuntimeSummary
        current={current}
        environment={environment}
        inheritance={getInheritance("storageRuntime")}
      />
      <ComponentOverridesSummary
        current={current}
        environment={environment}
        inheritance={getInheritance("componentOverrides")}
        components={deployment.components}
      />
      <SchedulingSummary
        current={current}
        environment={environment}
        inheritance={getInheritance("scheduling")}
      />

      {canEdit ? (
        <ConfigEditDrawer
          open={editDrawerOpen}
          onOpenChange={setEditDrawerOpen}
          deployment={deployment}
          environment={deployment.environment}
          driverSchema={driverSchema}
        />
      ) : null}
    </div>
  );
}
