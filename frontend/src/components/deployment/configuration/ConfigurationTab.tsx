import { useEffect, useMemo, useState } from "react";
import { Info, X } from "lucide-react";
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

  // Cluster scope, for the summaries that resolve a full deepest-wins chain
  // (backup retention). Projected through the same helper so every scope is
  // the one typed shape.
  const cluster = useMemo<UpdateDeploymentInput>(
    () => deploymentConfigToInput(deployment.environment.cluster.config),
    [deployment.environment.cluster.config],
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

      <SettingsMigrationHint />

      <EnvVarsSummary
        deploymentConfig={deployment.config}
        environmentConfig={deployment.environment.config}
        clusterConfig={deployment.environment.cluster.config}
        environmentName={deployment.environment.name}
        clusterName={deployment.environment.cluster.name}
      />
      <SchedulingSummary
        deploymentConfig={deployment.config}
        environmentConfig={deployment.environment.config}
        clusterConfig={deployment.environment.cluster.config}
      />
      <ServiceOverridesSummary deployedServices={deployment.deployedServices} />
      <DriverParametersSummary
        current={current}
        environment={environment}
        driverSchema={driverSchema}
      />
      <ComponentOverridesSummary
        deploymentConfig={deployment.config}
        environmentConfig={deployment.environment.config}
        clusterConfig={deployment.environment.cluster.config}
        components={deployment.components}
        imageOverrides={deployment.componentImageOverrides}
      />
      <NetworkingSummary
        deploymentConfig={deployment.config}
        environmentConfig={deployment.environment.config}
        clusterConfig={deployment.environment.cluster.config}
      />
      <StorageRuntimeSummary
        current={current}
        environment={environment}
        cluster={cluster}
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

const MIGRATION_HINT_DISMISS_KEY = "settings-tab-migration-hint-dismissed";

/**
 * One-time migration banner that explains where the Scheduling button and
 * the Parameters tab went, since both surfaces were folded into this
 * unified Settings tab. Persists dismissal in localStorage so the operator
 * sees it at most once per browser; older sessions that pre-date the
 * unification show it on first landing.
 */
function SettingsMigrationHint() {
  const [dismissed, setDismissed] = useState<boolean>(() => {
    if (typeof window === "undefined") return true;
    try {
      return window.localStorage.getItem(MIGRATION_HINT_DISMISS_KEY) === "1";
    } catch {
      return false;
    }
  });

  useEffect(() => {
    if (!dismissed) return;
    try {
      window.localStorage.setItem(MIGRATION_HINT_DISMISS_KEY, "1");
    } catch {
      // localStorage may be blocked (private mode, sandboxed iframe); silently
      // skip persistence — the banner just re-appears next session.
    }
  }, [dismissed]);

  if (dismissed) return null;

  return (
    <div
      role="note"
      data-testid="settings-migration-hint"
      className="flex items-start gap-3 rounded-md border border-sky-200 bg-sky-50 px-4 py-3 text-sky-900 dark:border-sky-900/60 dark:bg-sky-950/30 dark:text-sky-200"
    >
      <Info
        className="mt-0.5 h-4 w-4 shrink-0 text-sky-700 dark:text-sky-300"
        aria-hidden="true"
      />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold">Welcome to the Settings tab</p>
        <p className="mt-1 text-xs text-sky-900/80 dark:text-sky-200/80">
          Scheduling, environment variables, driver parameters, and
          per-component overrides now live here. The standalone Scheduling
          button has been removed — click <strong>Update Settings</strong> to
          edit any of them in one place, with a diff and impact review before
          you apply.
        </p>
      </div>
      <button
        type="button"
        onClick={() => setDismissed(true)}
        aria-label="Dismiss this hint"
        data-testid="settings-migration-hint-dismiss"
        className="rounded-md p-1 text-sky-800 transition-colors hover:bg-sky-100 hover:text-sky-950 dark:text-sky-300 dark:hover:bg-sky-900/40 dark:hover:text-sky-100"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}
