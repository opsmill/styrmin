import { useState } from "react";
import { useParams, Link, useNavigate } from "@tanstack/react-router";
import {
  useGetEnvironmentQuery,
  useListBackupStorageLocationsQuery,
  useAssignBackupStorageLocationMutation,
  useUnassignBackupStorageLocationMutation,
} from "@/generated/graphql";
import { useQueryClient } from "@tanstack/react-query";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState } from "@/components/EmptyState";
import { StatusBadge, getStatusColor } from "@/components/StatusBadge";
import { ParameterCards } from "@/components/ParameterCards";
import { Tabs, TabPanel } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { Plus } from "lucide-react";
import { formatDriverVersionLabel } from "@/lib/driverVersion";
import { AutoRefreshIndicator } from "@/components/AutoRefreshIndicator";
import { IfRole } from "@/auth/IfRole";
import { useEffectiveRole } from "@/auth/useEffectiveRole";
import EnvironmentConfigurationTab from "./EnvironmentConfigurationTab";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "parameters", label: "Parameters" },
  { id: "configuration", label: "Configuration" },
  { id: "backups", label: "Backups", badge: "SOON" },
];

export default function EnvironmentDetailPage() {
  const { environmentId } = useParams({
    from: "/environments/$environmentId",
  });
  const navigate = useNavigate();
  const [autoRefreshEnabled, setAutoRefreshEnabled] = useState(true);
  const [activeTab, setActiveTab] = useState("overview");
  const [showInternal, setShowInternal] = useState(false);
  const [showDeleted, setShowDeleted] = useState(false);
  const { data, isLoading, error, refetch, dataUpdatedAt } =
    useGetEnvironmentQuery(
      { environmentId, includeDeleted: showDeleted },
      { refetchInterval: autoRefreshEnabled ? 10_000 : false },
    );

  const { data: bslData } = useListBackupStorageLocationsQuery();
  const assignBslMutation = useAssignBackupStorageLocationMutation();
  const unassignBslMutation = useUnassignBackupStorageLocationMutation();
  const queryClient = useQueryClient();
  const effectiveRole = useEffectiveRole();
  const canWrite = effectiveRole === "READ_WRITE" || effectiveRole === "ADMIN";

  const environment = data?.environment;

  const handleBslChange = async (value: string) => {
    try {
      if (value === "__none__") {
        await unassignBslMutation.mutateAsync({ environmentId });
      } else {
        await assignBslMutation.mutateAsync({
          environmentId,
          backupStorageLocationId: value,
        });
      }
      queryClient.invalidateQueries({ queryKey: ["GetEnvironment"] });
    } catch {
      // Error handling can be added if needed
    }
  };

  if (isLoading) return <LoadingState message="Loading environment..." />;
  if (error)
    return <ErrorState message={error.message} onRetry={() => refetch()} />;
  if (!environment) return <ErrorState message="Environment not found" />;

  const configParams = environment.config
    ? Object.entries(environment.config)
        .filter(([, v]) => v != null)
        .map(([key, value]) => ({ key, value }))
    : [];

  const userDeployments = environment.deployments.filter((d) => !d.internal);
  const internalDeployments = environment.deployments.filter((d) => d.internal);

  const hasFailures = environment.deployments.some(
    (d) => d.status === "FAILED" || d.status === "failed",
  );
  const hasPending = environment.deployments.some(
    (d) =>
      d.status === "PENDING" ||
      d.status === "pending" ||
      d.status === "in_progress",
  );
  const envHealth =
    environment.deployments.length === 0
      ? "pending"
      : hasFailures
        ? "failed"
        : hasPending
          ? "pending"
          : "active";
  const envColors = getStatusColor(envHealth);

  return (
    <div
      className="flex flex-col gap-6 p-8 px-10"
      data-testid="environment-detail"
      data-environment-id={environment.id}
      data-bsl-id={environment.backupStorageLocation?.id ?? ""}
    >
      {/* Breadcrumb */}
      <nav className="flex items-center gap-1.5 text-xs">
        <Link to="/" className="text-muted-foreground hover:text-foreground">
          Environments
        </Link>
        <span className="text-muted-foreground">/</span>
        <span className="font-medium text-foreground">{environment.name}</span>
      </nav>

      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <div className={`h-3 w-3 rounded-full ${envColors.dot}`} />
          <h1 className="text-[22px] font-semibold tracking-tight text-foreground">
            {environment.name}
          </h1>
          <StatusBadge status={envHealth} />
          <span className="text-xs text-muted-foreground">
            {environment.cluster.name} cluster
          </span>
        </div>
        <div className="flex items-center gap-2">
          <AutoRefreshIndicator
            enabled={autoRefreshEnabled}
            onToggle={setAutoRefreshEnabled}
            lastRefreshedAt={dataUpdatedAt ? new Date(dataUpdatedAt) : null}
            onRefreshNow={() => refetch()}
          />
          <IfRole minimum="READ_WRITE">
            <Button
              onClick={() =>
                navigate({
                  to: "/environments/$environmentId/deploy",
                  params: { environmentId },
                })
              }
            >
              <Plus className="h-4 w-4" />
              Deploy
            </Button>
          </IfRole>
        </div>
      </div>

      {/* Stats */}
      <div className="flex gap-4">
        <div className="flex flex-1 flex-col gap-1 rounded-[10px] bg-surface p-4">
          <span className="text-[11px] uppercase tracking-wider text-muted-foreground">
            Applications
          </span>
          <span className="text-2xl font-bold tracking-tight text-foreground">
            {userDeployments.length}
          </span>
        </div>
        <div className="flex flex-1 flex-col gap-1 rounded-[10px] bg-surface p-4">
          <span className="text-[11px] uppercase tracking-wider text-muted-foreground">
            Cluster
          </span>
          <span className="mt-1 text-[15px] font-semibold text-foreground">
            {environment.cluster.name}
          </span>
        </div>
        <div className="flex flex-1 flex-col gap-1 rounded-[10px] bg-surface p-4">
          <span className="text-[11px] uppercase tracking-wider text-muted-foreground">
            Backup Storage
          </span>
          <span className="mt-1 text-[15px] font-semibold text-foreground">
            {environment.backupStorageLocation?.name ?? "Default"}
          </span>
        </div>
      </div>

      {/* Tabs */}
      <Tabs tabs={TABS} activeTab={activeTab} onTabChange={setActiveTab} />

      {/* Overview Tab */}
      <TabPanel active={activeTab === "overview"}>
        <div className="flex flex-col gap-3">
          {/* Header with toggle */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <span className="text-[13px] font-semibold text-foreground">
                Deployed Applications
              </span>
              <span className="text-xs text-muted-foreground">
                {userDeployments.length} application
                {userDeployments.length !== 1 ? "s" : ""}
                {showInternal &&
                  internalDeployments.length > 0 &&
                  ` · ${internalDeployments.length} internal`}
              </span>
            </div>
            <div className="flex items-center gap-2">
              {internalDeployments.length > 0 && (
                <button
                  onClick={() => setShowInternal((prev) => !prev)}
                  className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-colors ${
                    showInternal
                      ? "border-primary bg-primary/5 text-primary"
                      : "border-border text-muted-foreground hover:text-foreground"
                  }`}
                >
                  <div
                    className={`flex h-4 w-7 items-center rounded-full p-0.5 transition-colors ${
                      showInternal ? "justify-end bg-primary" : "bg-border"
                    }`}
                  >
                    <div className="h-3 w-3 rounded-full bg-white" />
                  </div>
                  Show internal
                </button>
              )}
              <button
                onClick={() => setShowDeleted((prev) => !prev)}
                className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-colors ${
                  showDeleted
                    ? "border-primary bg-primary/5 text-primary"
                    : "border-border text-muted-foreground hover:text-foreground"
                }`}
                data-testid="show-deleted-toggle"
              >
                <div
                  className={`flex h-4 w-7 items-center rounded-full p-0.5 transition-colors ${
                    showDeleted ? "justify-end bg-primary" : "bg-border"
                  }`}
                >
                  <div className="h-3 w-3 rounded-full bg-white" />
                </div>
                Show deleted
              </button>
            </div>
          </div>

          {userDeployments.length === 0 && !showInternal ? (
            <EmptyState
              title="No deployments"
              description="No applications have been deployed to this environment yet."
              actionLabel={canWrite ? "Deploy an application" : undefined}
              onAction={
                canWrite
                  ? () =>
                      navigate({
                        to: "/environments/$environmentId/deploy",
                        params: { environmentId },
                      })
                  : undefined
              }
            />
          ) : (
            <>
              {/* Table header */}
              <div className="flex items-center gap-4 px-4 py-2">
                <span className="w-[180px] text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                  Name
                </span>
                <span className="w-[90px] text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                  Version
                </span>
                <span className="w-[220px] text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                  Driver
                </span>
                <span className="w-[100px] text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                  Status
                </span>
                <span className="flex-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                  Components
                </span>
              </div>

              {/* User deployments */}
              {userDeployments.map((deployment, i) => (
                <DeploymentRow
                  key={deployment.id}
                  deployment={deployment}
                  environmentId={environmentId}
                  index={i}
                />
              ))}

              {/* Internal deployments */}
              {showInternal && internalDeployments.length > 0 && (
                <>
                  {/* Dashed separator */}
                  <div className="flex items-center gap-2.5 py-1">
                    <div className="h-px flex-1 border-t border-dashed border-border" />
                    <span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                      Internal
                    </span>
                    <div className="h-px flex-1 border-t border-dashed border-border" />
                  </div>

                  {internalDeployments.map((deployment, i) => (
                    <DeploymentRow
                      key={deployment.id}
                      deployment={deployment}
                      environmentId={environmentId}
                      index={i}
                      internal
                    />
                  ))}
                </>
              )}
            </>
          )}
        </div>
      </TabPanel>

      {/* Parameters Tab */}
      <TabPanel active={activeTab === "parameters"}>
        {configParams.length > 0 ? (
          <ParameterCards
            parameters={configParams}
            title="Environment Parameters"
            description="Configuration values applied to all deployments in this environment"
          />
        ) : (
          <EmptyState
            title="No parameters"
            description="This environment has no configuration parameters."
          />
        )}

        {/* BSL selector */}
        <div
          className="mt-6 flex items-center gap-3 rounded-[10px] border border-border p-4"
          data-testid="bsl-selector"
        >
          <Label className="text-[13px] text-muted-foreground whitespace-nowrap">
            Backup Storage Location:
          </Label>
          {canWrite ? (
            <Select
              value={environment.backupStorageLocation?.id ?? "__none__"}
              onValueChange={handleBslChange}
            >
              <SelectTrigger className="w-64">
                <SelectValue placeholder="Cluster default" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__none__">Cluster default</SelectItem>
                {bslData?.backupStorageLocations.map((bsl) => (
                  <SelectItem key={bsl.id} value={bsl.id}>
                    {bsl.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : (
            <span className="text-[13px] text-foreground">
              {environment.backupStorageLocation?.name ?? "Cluster default"}
            </span>
          )}
        </div>
      </TabPanel>

      {/* Configuration Tab */}
      <TabPanel active={activeTab === "configuration"}>
        <EnvironmentConfigurationTab
          environmentId={environmentId}
          config={environment.config}
          deployments={environment.deployments}
        />
      </TabPanel>

      {/* Backups Tab (Coming Soon) */}
      <TabPanel active={activeTab === "backups"}>
        <EmptyState
          title="Environment Backups"
          description="Schedule and manage backups across all deployments in this environment. Configure retention policies and restore points from a single place."
          icon="package"
          comingSoon
        />
      </TabPanel>
    </div>
  );
}

// ---------------------------------------------------------------------------
// DeploymentRow
// ---------------------------------------------------------------------------

function relativeTimeFromNow(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const seconds = Math.floor((Date.now() - then) / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

// Exported for component-level testing (see
// frontend/src/__tests__/environment-detail/DeploymentRow.test.tsx). The row
// is otherwise a private implementation detail of this page.
export function DeploymentRow({
  deployment,
  environmentId,
  index,
  internal = false,
}: {
  deployment: {
    id: string;
    name: string;
    status: string;
    applicationVersion: string;
    applicationDriverVersion?: {
      version: string;
      contentHash?: string | null;
      sourceCommitSha?: string | null;
      applicationDriver: { name: string };
    } | null;
    components: { id: string }[];
    deletedAt?: string | null;
  };
  environmentId: string;
  index: number;
  internal?: boolean;
}) {
  const dc = getStatusColor(deployment.status);
  const isDeleting = deployment.status === "deleting";
  const isDeleted =
    deployment.status === "deleted" ||
    (deployment.deletedAt !== null && deployment.deletedAt !== undefined);
  const adv = deployment.applicationDriverVersion;
  const driverName = adv?.applicationDriver.name ?? null;
  const driverVersionLabel = adv ? formatDriverVersionLabel(adv) : null;
  // Tombstoned rows render visually de-emphasised with no inline action
  // affordances. The detail page is still reachable by clicking the row
  // (US7 — direct id lookup is unfiltered).
  const isTombstoned = isDeleted;

  return (
    <Link
      to="/environments/$environmentId/deployments/$deploymentId"
      params={{
        environmentId,
        deploymentId: deployment.id,
      }}
      data-testid="deployment-row"
      data-deployment-id={deployment.id}
      data-deployment-status={deployment.status}
    >
      <div
        className={`flex items-center gap-4 rounded-lg border-l-[3px] px-4 py-3 transition-colors hover:bg-accent/50 ${
          isTombstoned
            ? "border-border opacity-50 grayscale"
            : internal
              ? "border-border opacity-70"
              : dc.border
        } ${index % 2 === 0 ? "bg-surface" : ""}`}
      >
        <div className="flex w-[180px] items-center gap-2">
          <div className={`h-2 w-2 flex-shrink-0 rounded-full ${dc.dot}`} />
          <span
            className={`text-[13px] font-medium ${
              isTombstoned || internal
                ? "text-muted-foreground"
                : "text-foreground"
            }`}
          >
            {deployment.name}
          </span>
          {internal && (
            <span className="rounded bg-muted px-1 py-px text-[10px] font-medium text-muted-foreground">
              INT
            </span>
          )}
          {isDeleting && (
            <span
              className="rounded bg-amber-500/10 px-1.5 py-px text-[10px] font-medium uppercase tracking-wider text-amber-700 dark:text-amber-400"
              data-testid="deleting-badge"
            >
              Deleting…
            </span>
          )}
        </div>
        <span
          className={`w-[90px] font-mono text-[13px] ${isTombstoned || internal ? "text-muted-foreground/70" : "text-muted-foreground"}`}
        >
          {deployment.applicationVersion}
        </span>
        <div
          className={`w-[220px] text-[13px] ${isTombstoned || internal ? "text-muted-foreground/70" : "text-muted-foreground"}`}
          data-testid="deployment-driver-cell"
        >
          {driverName ? (
            <div className="flex flex-col">
              <span className="truncate">{driverName}</span>
              {driverVersionLabel && (
                <span className="truncate font-mono text-[11px] text-muted-foreground/80">
                  v{driverVersionLabel}
                </span>
              )}
            </div>
          ) : (
            <span className="text-muted-foreground/50">—</span>
          )}
        </div>
        <div className="w-[100px]">
          <StatusBadge status={deployment.status} />
        </div>
        <span
          className={`flex-1 text-[13px] ${isTombstoned || internal ? "text-muted-foreground/70" : "text-muted-foreground"}`}
        >
          {isDeleted && deployment.deletedAt ? (
            <span data-testid="deleted-at-relative">
              Deleted {relativeTimeFromNow(deployment.deletedAt)}
            </span>
          ) : (
            <>
              {deployment.components.length} component
              {deployment.components.length !== 1 ? "s" : ""}
            </>
          )}
        </span>
      </div>
    </Link>
  );
}
