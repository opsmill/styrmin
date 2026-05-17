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
import type { DriverParameterSchema } from "@/lib/configuration-types";
import { ConfigEditDrawer } from "./ConfigEditDrawer";
import { DeploymentContextDialog } from "./DeploymentContextDialog";
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

/**
 * Top-level composition for the Settings tab on the Deployment detail page.
 *
 * Layout (top to bottom):
 *   - A thin toolbar with "View Context" (open to all roles) and, when
 *     the operator has edit permission per FR-030, "Update Settings".
 *   - 7 section summary cards. Each card shows the *effective* value at
 *     every row (cluster → environment → deployment chain) with a small
 *     blue dot when the deployment layer explicitly defines the field.
 *
 * The unified edit surface (drawer + diff/impact dialog) opens from the
 * Update Settings CTA. "View Context" opens a read-only JSON dialog
 * fed by the existing REST endpoint at `/deployments/{id}/context`.
 */
export function ConfigurationTab({ deployment }: Props) {
  const [editDrawerOpen, setEditDrawerOpen] = useState(false);
  const [contextDialogOpen, setContextDialogOpen] = useState(false);

  // Project the deployment's persisted config + parent environment's persisted
  // config through the same read-side helper so the legacy summaries (driver
  // parameters, storage & runtime) still see the typed shape they expect.
  const current = useMemo<UpdateDeploymentInput>(() => {
    const base = deploymentConfigToInput(deployment.config);
    // `deploymentConfigToInput` intentionally ignores the row-level
    // `parameters`, `name`, and `serviceNameOverrides` fields. Merge them in
    // here so the diff helpers see the full deployment view.
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

  const effectiveRole = useEffectiveRole();
  // FR-030: the Update CTA mirrors the server-side authorization on
  // `updateDeployment`, which requires READ_WRITE or higher.
  const canEdit = effectiveRole === "READ_WRITE" || effectiveRole === "ADMIN";

  return (
    <div className="flex flex-col gap-5" data-testid="settings-tab">
      <div className="flex justify-end gap-2">
        <Button
          type="button"
          variant="outline"
          data-testid="settings-view-context-button"
          onClick={() => setContextDialogOpen(true)}
        >
          View Context
        </Button>
        {canEdit ? (
          <Button
            data-testid="settings-update-button"
            onClick={() => setEditDrawerOpen(true)}
          >
            Update Settings
          </Button>
        ) : null}
      </div>

      <EnvVarsSummary
        deploymentConfig={deployment.config}
        environmentConfig={deployment.environment.config}
        clusterConfig={deployment.environment.cluster.config}
        environmentName={deployment.environment.name}
        clusterName={deployment.environment.cluster.name}
      />
      <ServiceOverridesSummary deployedServices={deployment.deployedServices} />
      <DriverParametersSummary
        current={current}
        environment={environment}
        driverSchema={driverSchema}
      />
      <NetworkingSummary
        deploymentConfig={deployment.config}
        environmentConfig={deployment.environment.config}
        clusterConfig={deployment.environment.cluster.config}
      />
      <StorageRuntimeSummary current={current} environment={environment} />
      <ComponentOverridesSummary
        deploymentConfig={deployment.config}
        environmentConfig={deployment.environment.config}
        clusterConfig={deployment.environment.cluster.config}
        components={deployment.components}
      />
      <SchedulingSummary
        deploymentConfig={deployment.config}
        environmentConfig={deployment.environment.config}
        clusterConfig={deployment.environment.cluster.config}
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

      <DeploymentContextDialog
        deploymentId={deployment.id}
        open={contextDialogOpen}
        onOpenChange={setContextDialogOpen}
      />
    </div>
  );
}
