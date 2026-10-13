import type { ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { AlertTriangle } from "lucide-react";
import type {
  IngressControllerAction,
  UpdateClusterMutation,
} from "@/generated/graphql";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  DEFAULT_INGRESS_SERVICE_TYPE,
  clusterConfigChanges,
  nothingToSave,
  sameJson,
} from "@/components/cluster/ClusterConfigFields.helpers";

export type ClusterUpdateOutcome = UpdateClusterMutation["updateCluster"];
type Entry = ClusterUpdateOutcome["redeployed"][number];
type StoredConfig = Record<string, unknown>;

function asRecord(value: unknown): StoredConfig | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as StoredConfig)
    : null;
}

function environmentsWith(
  outcome: ClusterUpdateOutcome,
  action: IngressControllerAction,
): string[] {
  return outcome.ingressControllers
    .filter((controller) => controller.action === action)
    .map((controller) => controller.environmentName);
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2" aria-label={title}>
      <h3 className="text-sm font-semibold">{title}</h3>
      {children}
    </section>
  );
}

function Muted({ children }: { children: ReactNode }) {
  return <p className="text-sm text-muted-foreground">{children}</p>;
}

/** Deployments grouped by environment; linked to their page once their redeploy started. */
function DeploymentList({
  title,
  entries,
  description,
  link = false,
}: {
  title: string;
  entries: Entry[];
  description?: string;
  link?: boolean;
}) {
  if (entries.length === 0) return null;
  const byEnvironment = new Map<string, Entry[]>();
  for (const entry of entries) {
    byEnvironment.set(entry.environmentName, [
      ...(byEnvironment.get(entry.environmentName) ?? []),
      entry,
    ]);
  }
  return (
    <Section title={`${title} (${entries.length})`}>
      {description && <Muted>{description}</Muted>}
      <ul className="space-y-1 text-sm">
        {[...byEnvironment].map(([environment, deployments]) => (
          <li key={environment}>
            <span className="text-muted-foreground">{environment}: </span>
            {deployments.map((entry, i) => (
              <span key={entry.deploymentId}>
                {i > 0 && ", "}
                {link ? (
                  <Link
                    to="/environments/$environmentId/deployments/$deploymentId"
                    params={{
                      environmentId: entry.environmentId,
                      deploymentId: entry.deploymentId,
                    }}
                    className="font-medium hover:underline"
                  >
                    {entry.deploymentName}
                  </Link>
                ) : (
                  <span className="font-medium">{entry.deploymentName}</span>
                )}
              </span>
            ))}
          </li>
        ))}
      </ul>
    </Section>
  );
}

const ACTION_TEXT: Record<IngressControllerAction, string> = {
  CREATE: "created",
  REDEPLOY: "redeployed with the new values",
  REMOVE: "removed once no application uses it",
};

function ControllerList({ outcome }: { outcome: ClusterUpdateOutcome }) {
  if (outcome.ingressControllers.length === 0) return null;
  return (
    <Section title="Dedicated ingress controllers">
      <ul className="space-y-1 text-sm">
        {outcome.ingressControllers.map((controller) => (
          <li key={`${controller.environmentId}-${controller.action}`}>
            <span className="text-muted-foreground">
              {controller.environmentName}:{" "}
            </span>
            {controller.failed
              ? `could not be ${controller.action === "CREATE" ? "created" : "redeployed"}; its applications wait`
              : ACTION_TEXT[controller.action]}
          </li>
        ))}
      </ul>
    </Section>
  );
}

function Warning({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Alert role="note">
      <AlertTriangle className="h-4 w-4" />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription>{children}</AlertDescription>
    </Alert>
  );
}

function listOf(names: string[]): string {
  return [...new Set(names)].join(", ");
}

function ChangeWarnings({
  before,
  after,
  plan,
}: {
  before: StoredConfig;
  after: StoredConfig;
  plan: ClusterUpdateOutcome;
}) {
  const warnings: ReactNode[] = [];
  if (before.fqdn_suffix !== after.fqdn_suffix) {
    warnings.push(
      <Warning key="fqdn" title="Application URLs change">
        The URL of every application that takes the cluster&apos;s FQDN suffix
        changes. Users and integrations that use the old URLs stop reaching
        these applications.
      </Warning>,
    );
  }
  const storageChanged = (["standard_storage", "fast_storage"] as const).some(
    (key) =>
      asRecord(before[key])?.storage_class !==
      asRecord(after[key])?.storage_class,
  );
  if (storageChanged) {
    warnings.push(
      <Warning key="storage" title="Storage class change can fail deployments">
        Kubernetes refuses to change the storage class of an existing volume
        claim. Deployments whose StatefulSets use this storage class become
        FAILED, and saving again does not retry them. To recover, save the
        previous storage class again or recreate the deployment. Existing
        volumes are not moved.
      </Warning>,
    );
  }
  const created = environmentsWith(plan, "CREATE");
  const diBefore = asRecord(before.dedicated_ingress);
  const diAfter = asRecord(after.dedicated_ingress);
  if (created.length > 0 || (diBefore === null && diAfter !== null)) {
    const serviceType =
      asRecord(diAfter?.service)?.type ?? DEFAULT_INGRESS_SERVICE_TYPE;
    warnings.push(
      <Warning key="di-on" title="Dedicated ingress controllers are created">
        {created.length > 0
          ? `A dedicated ingress controller is created in ${listOf(created)}.`
          : "A dedicated ingress controller is created in each environment that takes the cluster's value once it has applications."}
        {serviceType === "LoadBalancer" &&
          " With the service type LoadBalancer, each controller can create a load balancer in your cloud provider."}
      </Warning>,
    );
  }
  const removed = environmentsWith(plan, "REMOVE");
  if (removed.length > 0 || (diBefore !== null && diAfter === null)) {
    warnings.push(
      <Warning key="di-off" title="Dedicated ingress controllers are removed">
        {removed.length > 0
          ? `The dedicated ingress controller of ${listOf(removed)} is removed once its applications are redeployed without it.`
          : "Dedicated ingress is turned off for the environments that take the cluster's value."}{" "}
        The service annotations and the load balancer IP are not kept.
      </Warning>,
    );
  }
  return <>{warnings}</>;
}

/** The review step: what saving changes and which deployments it redeploys (dry run). */
export function ClusterUpdateReview({
  openedConfig,
  newConfig,
  plan,
}: {
  openedConfig: StoredConfig;
  newConfig: StoredConfig;
  plan: ClusterUpdateOutcome;
}) {
  const current = plan.cluster.config;
  const changes = clusterConfigChanges(current, newConfig);
  const idle = nothingToSave(current, newConfig, plan);
  return (
    <div className="space-y-4" data-testid="cluster-update-review">
      {!sameJson(current, openedConfig) && (
        <Alert variant="destructive" role="note">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>
            The configuration changed after you opened this dialog
          </AlertTitle>
          <AlertDescription>
            Another administrator saved a change. The values below compare with
            their configuration, and saving replaces it.
          </AlertDescription>
        </Alert>
      )}

      <Section title="Changed values">
        {changes.length === 0 ? (
          <Muted>
            {idle
              ? "No value changed and every deployment already runs with this configuration. There is nothing to save."
              : "No value changed. Saving again redeploys the deployments listed below, which do not run with this configuration, for example because their redeploy could not start earlier."}
          </Muted>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-xs uppercase tracking-wide text-muted-foreground">
                <th className="py-1 pr-3 font-normal">Setting</th>
                <th className="py-1 pr-3 font-normal">Current</th>
                <th className="py-1 font-normal">New</th>
              </tr>
            </thead>
            <tbody>
              {changes.map((change) => (
                <tr key={change.label} className="border-b last:border-0">
                  <td className="py-1 pr-3">{change.label}</td>
                  <td className="py-1 pr-3 font-mono text-xs break-all">
                    {change.before}
                  </td>
                  <td className="py-1 font-mono text-xs break-all">
                    {change.after}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      <ChangeWarnings before={current} after={newConfig} plan={plan} />

      {plan.redeployed.length === 0 && changes.length > 0 && (
        <Muted>
          No deployment takes a changed value, so none is redeployed.
        </Muted>
      )}
      <DeploymentList
        title="Deployments to redeploy"
        entries={plan.redeployed}
      />
      <DeploymentList
        title="Waiting for the dedicated ingress controller"
        description="They are redeployed once the controller of their environment runs with the new values."
        entries={plan.waitingForIngress}
      />
      <DeploymentList
        title="Not redeployed while a restore runs"
        description="Save again after the restore has finished."
        entries={plan.skippedRestoring}
      />
      <DeploymentList
        title="Could not be evaluated"
        description="Styrmin could not compare the configuration of these deployments. Saving tries again."
        entries={plan.failedToStart}
      />
      {plan.failedEnvironments.length > 0 && (
        <Muted>
          These environments could not be evaluated:{" "}
          {listOf(plan.failedEnvironments.map((env) => env.environmentName))}.
        </Muted>
      )}
      <ControllerList outcome={plan} />
      {plan.unchangedCount > 0 && (
        <Muted>
          {plan.unchangedCount === 1
            ? "1 deployment already runs with this configuration."
            : `${plan.unchangedCount} deployments already run with this configuration.`}
        </Muted>
      )}
    </div>
  );
}

/** The result step: what the save started, and what to retry. */
export function ClusterUpdateResult({
  result,
}: {
  result: ClusterUpdateOutcome;
}) {
  const failedControllers = result.ingressControllers.filter((c) => c.failed);
  const anyFailed =
    result.failedToStart.length > 0 ||
    result.failedEnvironments.length > 0 ||
    failedControllers.length > 0;
  const started = result.redeployed.length;
  return (
    <div className="space-y-4" data-testid="cluster-update-result">
      <p className="text-sm font-medium" role="status">
        {started === 0
          ? "The configuration was saved. No deployment was redeployed."
          : `The configuration was saved. ${started === 1 ? "1 deployment is" : `${started} deployments are`} being redeployed.`}
      </p>
      {anyFailed && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>Some redeploys did not start</AlertTitle>
          <AlertDescription>Save again to retry them.</AlertDescription>
        </Alert>
      )}
      <DeploymentList
        title="Redeploying"
        description="Follow each redeploy in the tasks of its deployment."
        entries={result.redeployed}
        link
      />
      <DeploymentList
        title="Waiting for the dedicated ingress controller"
        description="They are redeployed once the controller of their environment runs with the new values."
        entries={result.waitingForIngress}
      />
      <DeploymentList
        title="Not redeployed while a restore runs"
        description="Save again after the restore has finished."
        entries={result.skippedRestoring}
      />
      <DeploymentList title="Could not start" entries={result.failedToStart} />
      {result.failedEnvironments.length > 0 && (
        <Muted>
          These environments could not be evaluated:{" "}
          {listOf(result.failedEnvironments.map((env) => env.environmentName))}.
        </Muted>
      )}
      <ControllerList outcome={result} />
    </div>
  );
}
