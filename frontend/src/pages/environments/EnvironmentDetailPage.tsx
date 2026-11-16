import { useState, type ReactNode } from "react";
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
import { ExternalLink, Plus } from "lucide-react";
import { formatDriverVersionLabel } from "@/lib/driverVersion";
import { deriveEnvHealth } from "@/lib/environment-health";
import { AutoRefreshIndicator } from "@/components/AutoRefreshIndicator";
import { IfRole } from "@/auth/IfRole";
import { useEffectiveRole } from "@/auth/useEffectiveRole";
import EnvironmentConfigurationTab from "./EnvironmentConfigurationTab";
import { useDocumentTitle } from "@/hooks/use-document-title";
import { EnvironmentBackupsTab } from "@/components/environment/EnvironmentBackupsTab";
import { EnvironmentClonesSection } from "@/components/environment/EnvironmentClonesSection";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "parameters", label: "Parameters" },
  { id: "configuration", label: "Configuration" },
  { id: "backups", label: "Backups" },
  { id: "clones", label: "Clones" },
];

export default function EnvironmentDetailPage() {
  const { environmentId } = useParams({
    from: "/environments/$environmentId",
  });
  const navigate = useNavigate();
  const [autoRefreshEnabled, setAutoRefreshEnabled] = useState(true);
  const [activeTab, setActiveTab] = useState("overview");
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
  useDocumentTitle(environment?.name ?? "Environment");

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

  const { deployments } = environment;
  const envHealth = deriveEnvHealth(deployments);
  const envColors = getStatusColor(envHealth);

  // The options of the backup storage location select. Passed to its `items`,
  // so that its trigger shows the location's name instead of its id. The
  // assigned location comes from the environment too, so that its name shows
  // before the list of locations has loaded.
  const assignedBsl = environment.backupStorageLocation;
  const bslOptions = [
    { value: "__none__", label: "Cluster default" },
    ...(bslData?.backupStorageLocations ?? []).map((bsl) => ({
      value: bsl.id,
      label: bsl.name,
    })),
  ];
  const bslItems =
    assignedBsl && !bslOptions.some((option) => option.value === assignedBsl.id)
      ? [...bslOptions, { value: assignedBsl.id, label: assignedBsl.name }]
      : bslOptions;

  return (
    <div
      className="flex flex-col gap-6 p-8 px-10"
      data-testid="environment-detail"
      data-environment-id={environment.id}
      data-bsl-id={environment.backupStorageLocation?.id ?? ""}
      data-environment-status={envHealth}
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
          <span
            className="text-2xl font-bold tracking-tight text-foreground"
            data-testid="environment-application-count"
          >
            {deployments.length}
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
                {deployments.length} application
                {deployments.length !== 1 ? "s" : ""}
              </span>
            </div>
            <div className="flex items-center gap-2">
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

          {deployments.length === 0 ? (
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

              {deployments.map((deployment, i) => (
                <DeploymentRow
                  key={deployment.id}
                  deployment={deployment}
                  environmentId={environmentId}
                  index={i}
                />
              ))}
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
              items={bslItems}
              value={environment.backupStorageLocation?.id ?? "__none__"}
              onValueChange={handleBslChange}
            >
              <SelectTrigger className="w-64">
                <SelectValue placeholder="Cluster default" />
              </SelectTrigger>
              <SelectContent>
                {bslOptions.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
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
          deployments={deployments}
        />
      </TabPanel>

      {/* Backups Tab */}
      <TabPanel active={activeTab === "backups"}>
        {/* The AutoRefreshIndicator in the header renders for every tab, so the
            tab's own polls have to honour the same flag. */}
        <EnvironmentBackupsTab
          environmentId={environmentId}
          autoRefreshEnabled={autoRefreshEnabled}
        />
      </TabPanel>

      {/* Clones Tab */}
      <TabPanel active={activeTab === "clones"}>
        {/* The picker and the clear-field list are built from the source
            environment this page already fetched, so the dialog needs no query
            of its own. Deleted deployments only reach the picker (as disabled
            rows) while "Show deleted" is on — otherwise they are simply not in
            the list. */}
        <EnvironmentClonesSection
          environmentId={environmentId}
          environmentName={environment.name}
          deployments={deployments}
          config={environment.config}
          isActive={activeTab === "clones"}
          autoRefreshEnabled={autoRefreshEnabled}
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

interface ComponentPublicUrl {
  serviceId: string;
  component: string;
  url: string;
  componentEnabled: boolean;
}

// The public URL of each service of the deployment, with the component that
// serves it. `humanReadableUrl` is the URL of the service's readable host: the
// address that the deployment detail page labels PUBLIC.
function componentPublicUrls(deployment: {
  components: { name: string; enabled: boolean }[];
  deployedServices: {
    id: string;
    component: string;
    humanReadableUrl?: string | null;
  }[];
}): ComponentPublicUrl[] {
  const enabledByName = new Map(
    deployment.components.map((component) => [
      component.name,
      component.enabled,
    ]),
  );
  return deployment.deployedServices.flatMap((service) =>
    service.humanReadableUrl
      ? [
          {
            serviceId: service.id,
            component: service.component,
            url: service.humanReadableUrl,
            componentEnabled: enabledByName.get(service.component) ?? true,
          },
        ]
      : [],
  );
}

// A line break opportunity after each "/", "." and ":" of a URL, so that a
// long URL wraps between its parts instead of inside a host label or the
// port. <wbr> adds no character, so a copied URL stays the same.
function urlWithBreaks(url: string): ReactNode[] {
  return url
    .split(/(?<=[/.:])/)
    .flatMap((part, i) => (i === 0 ? [part] : [<wbr key={i} />, part]));
}

// Exported for component-level testing (see
// frontend/src/__tests__/environment-detail/DeploymentRow.test.tsx). The row
// is otherwise a private implementation detail of this page.
export function DeploymentRow({
  deployment,
  environmentId,
  index,
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
    components: { id: string; name: string; enabled: boolean }[];
    deployedServices: {
      id: string;
      component: string;
      humanReadableUrl?: string | null;
    }[];
    deletedAt?: string | null;
  };
  environmentId: string;
  index: number;
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
  // The cluster resources of a deployment that is being deleted, or is
  // deleted, are torn down, so its URLs no longer answer.
  const publicUrls =
    isDeleting || isDeleted ? [] : componentPublicUrls(deployment);

  // A link cannot contain another link, and the row holds links to public
  // URLs. So the deployment name is the link to the deployment, and its
  // ::after element covers the whole row (the nearest `relative` ancestor) to
  // keep the whole row clickable. The public URL links sit above it.
  return (
    <div
      data-testid="deployment-row"
      data-deployment-id={deployment.id}
      data-deployment-status={deployment.status}
    >
      <div
        className={`relative flex items-center gap-4 rounded-lg border-l-[3px] px-4 py-3 transition-colors hover:bg-accent/50 ${
          isTombstoned ? "border-border opacity-50 grayscale" : dc.border
        } ${index % 2 === 0 ? "bg-surface" : ""}`}
      >
        <div className="flex w-[180px] items-center gap-2">
          <div className={`h-2 w-2 flex-shrink-0 rounded-full ${dc.dot}`} />
          <Link
            to="/environments/$environmentId/deployments/$deploymentId"
            params={{
              environmentId,
              deploymentId: deployment.id,
            }}
            data-testid="deployment-row-link"
            className={`text-[13px] font-medium outline-none after:absolute after:inset-0 after:rounded-lg focus-visible:after:ring-2 focus-visible:after:ring-ring ${
              isTombstoned ? "text-muted-foreground" : "text-foreground"
            }`}
          >
            {deployment.name}
          </Link>
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
          className={`w-[90px] font-mono text-[13px] ${isTombstoned ? "text-muted-foreground/70" : "text-muted-foreground"}`}
        >
          {deployment.applicationVersion}
        </span>
        <div
          className={`w-[220px] text-[13px] ${isTombstoned ? "text-muted-foreground/70" : "text-muted-foreground"}`}
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
        <div
          className={`flex min-w-0 flex-1 flex-col gap-1 text-[13px] ${isTombstoned ? "text-muted-foreground/70" : "text-muted-foreground"}`}
          data-testid="deployment-components-cell"
        >
          {isDeleted && deployment.deletedAt ? (
            <span data-testid="deleted-at-relative">
              Deleted {relativeTimeFromNow(deployment.deletedAt)}
            </span>
          ) : (
            <span>
              {deployment.components.length} component
              {deployment.components.length !== 1 ? "s" : ""}
            </span>
          )}
          {publicUrls.length > 0 && (
            <ul className="flex flex-col gap-0.5">
              {publicUrls.map((entry) => (
                <li
                  key={entry.serviceId}
                  className="flex min-w-0 items-baseline gap-1.5 text-[11px]"
                  data-testid="component-public-url"
                  data-component={entry.component}
                >
                  <span
                    className={`flex-shrink-0 font-medium ${
                      entry.componentEnabled
                        ? "text-foreground"
                        : "text-muted-foreground"
                    }`}
                  >
                    {entry.component}
                  </span>
                  {/* The URL wraps instead of being cut, so that its port
                      stays visible in a narrow column. */}
                  <a
                    href={entry.url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className={`relative z-10 min-w-0 font-mono [overflow-wrap:anywhere] hover:underline ${
                      entry.componentEnabled
                        ? "text-primary"
                        : "text-muted-foreground"
                    }`}
                  >
                    <ExternalLink className="mr-1 inline h-3 w-3 align-[-2px]" />
                    {urlWithBreaks(entry.url)}
                  </a>
                  {!entry.componentEnabled && (
                    <span className="flex-shrink-0 text-muted-foreground">
                      (disabled)
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
