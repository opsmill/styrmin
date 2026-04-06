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
import { StatusBadge } from "@/components/StatusBadge";
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
import { AutoRefreshIndicator } from "@/components/AutoRefreshIndicator";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "parameters", label: "Parameters" },
  { id: "backups", label: "Backups", badge: "SOON" },
];

export default function EnvironmentDetailPage() {
  const { environmentId } = useParams({
    from: "/environments/$environmentId",
  });
  const navigate = useNavigate();
  const [autoRefreshEnabled, setAutoRefreshEnabled] = useState(true);
  const [activeTab, setActiveTab] = useState("overview");
  const { data, isLoading, error, refetch, dataUpdatedAt } =
    useGetEnvironmentQuery(
      { environmentId },
      { refetchInterval: autoRefreshEnabled ? 10_000 : false },
    );

  const { data: bslData } = useListBackupStorageLocationsQuery();
  const assignBslMutation = useAssignBackupStorageLocationMutation();
  const unassignBslMutation = useUnassignBackupStorageLocationMutation();
  const queryClient = useQueryClient();

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

  return (
    <div className="flex flex-col gap-6 p-8 px-10">
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
          <h1 className="text-[22px] font-semibold tracking-tight text-foreground">
            {environment.name}
          </h1>
          <StatusBadge
            status={environment.deployments.length > 0 ? "ACTIVE" : "PENDING"}
          />
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
        </div>
      </div>

      {/* Stats */}
      <div className="flex gap-4">
        <div className="flex flex-1 flex-col gap-1 rounded-[10px] bg-surface p-4">
          <span className="text-[11px] uppercase tracking-wider text-muted-foreground">
            Applications
          </span>
          <span className="text-2xl font-bold tracking-tight text-foreground">
            {environment.deployments.length}
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
          <div className="flex items-center justify-between">
            <span className="text-[13px] font-semibold text-foreground">
              Deployed Applications
            </span>
          </div>

          {environment.deployments.length === 0 ? (
            <EmptyState
              title="No deployments"
              description="No applications have been deployed to this environment yet."
              actionLabel="Deploy an application"
              onAction={() =>
                navigate({
                  to: "/environments/$environmentId/deploy",
                  params: { environmentId },
                })
              }
            />
          ) : (
            <>
              {/* Table header */}
              <div className="flex items-center gap-4 px-4 py-2">
                <span className="w-[180px] text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                  Name
                </span>
                <span className="w-[100px] text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                  Version
                </span>
                <span className="w-[100px] text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                  Status
                </span>
                <span className="flex-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                  Components
                </span>
              </div>
              {/* Table rows */}
              {environment.deployments.map((deployment, i) => (
                <Link
                  key={deployment.id}
                  to="/environments/$environmentId/deployments/$deploymentId"
                  params={{
                    environmentId,
                    deploymentId: deployment.id,
                  }}
                >
                  <div
                    className={`flex items-center gap-4 rounded-lg px-4 py-3 transition-colors hover:bg-accent/50 ${
                      i % 2 === 0 ? "bg-surface" : ""
                    }`}
                  >
                    <span className="w-[180px] text-[13px] font-medium text-foreground">
                      {deployment.name}
                    </span>
                    <span className="w-[100px] font-mono text-[13px] text-muted-foreground">
                      {deployment.applicationVersion}
                    </span>
                    <div className="w-[100px]">
                      <StatusBadge status={deployment.status} />
                    </div>
                    <span className="flex-1 text-[13px] text-muted-foreground">
                      {deployment.components.length} component
                      {deployment.components.length !== 1 ? "s" : ""}
                    </span>
                  </div>
                </Link>
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
        <div className="mt-6 flex items-center gap-3 rounded-[10px] border border-border p-4">
          <Label className="text-[13px] text-muted-foreground whitespace-nowrap">
            Backup Storage Location:
          </Label>
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
        </div>
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
