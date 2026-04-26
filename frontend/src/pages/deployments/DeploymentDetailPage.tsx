import { useState } from "react";
import { useParams, Link } from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import {
  useGetDeploymentQuery,
  useGetDeploymentTimelineQuery,
  useCreateBackupMutation,
  useDeleteBackupMutation,
  useListBackupsQuery,
  useCreateRestoreMutation,
  useListRestoresQuery,
  useUpdateDeploymentVersionMutation,
  type ListRestoresQuery,
} from "@/generated/graphql";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { StatusBadge, getStatusColor } from "@/components/StatusBadge";
import { ParameterCards } from "@/components/ParameterCards";
import { Tabs, TabPanel } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Archive,
  ChevronRight,
  ExternalLink,
  Lock,
  RotateCcw,
} from "lucide-react";
import { AutoRefreshIndicator } from "@/components/AutoRefreshIndicator";
import { DeploymentTimeline } from "@/components/deployment/DeploymentTimeline";
import { SchedulingConfigDialog } from "@/components/deployment/scheduling/SchedulingConfigDialog";

const DEPLOYMENT_TABS = [
  { id: "overview", label: "Overview" },
  { id: "parameters", label: "Parameters" },
  { id: "backups", label: "Backups" },
  { id: "timeline", label: "Timeline" },
];

export default function DeploymentDetailPage() {
  const { environmentId, deploymentId } = useParams({
    from: "/environments/$environmentId/deployments/$deploymentId",
  });
  const queryClient = useQueryClient();
  const [autoRefreshEnabled, setAutoRefreshEnabled] = useState(true);
  const [activeTab, setActiveTab] = useState("overview");

  const { data, isLoading, error, refetch, dataUpdatedAt } =
    useGetDeploymentQuery(
      { deploymentId },
      { refetchInterval: autoRefreshEnabled ? 10_000 : false },
    );

  const deployment = data?.deployment;

  const { data: timelineData } = useGetDeploymentTimelineQuery(
    { deploymentId },
    { refetchInterval: autoRefreshEnabled ? 10_000 : false },
  );
  const timelineEntries = timelineData?.deploymentTimeline ?? [];

  const instanceId = deployment?.applicationInstance?.id;

  // Mutations
  const createBackupMutation = useCreateBackupMutation();
  const [backupError, setBackupError] = useState<string | null>(null);
  const createRestoreMutation = useCreateRestoreMutation();
  const [restoreOpen, setRestoreOpen] = useState(false);
  const [selectedBackupId, setSelectedBackupId] = useState<string | null>(null);
  const [restoreError, setRestoreError] = useState<string | null>(null);
  const deleteBackupMutation = useDeleteBackupMutation();
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteBackupId, setDeleteBackupId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const updateVersionMutation = useUpdateDeploymentVersionMutation();
  const [upgradeOpen, setUpgradeOpen] = useState(false);
  const [newVersion, setNewVersion] = useState("");
  const [upgradeError, setUpgradeError] = useState<string | null>(null);
  const [schedulingOpen, setSchedulingOpen] = useState(false);

  const { data: backupsData, isLoading: backupsFetching } = useListBackupsQuery(
    { instanceId: instanceId ?? "" },
    {
      enabled: !!instanceId,
      refetchInterval: autoRefreshEnabled ? 10_000 : false,
    },
  );

  const selectedBackup = backupsData?.backups?.find(
    (b) => b.id === selectedBackupId,
  );
  const deleteBackupName = backupsData?.backups?.find(
    (b) => b.id === deleteBackupId,
  )?.name;
  const targetNamespace = deploymentId ? `styrmin-${deploymentId}` : "";

  async function handleBackup() {
    setBackupError(null);
    if (!instanceId) {
      setBackupError("Deployment has no instance yet");
      return;
    }
    try {
      await createBackupMutation.mutateAsync({ instanceId });
      queryClient.invalidateQueries({ queryKey: ["ListBackups"] });
    } catch (err) {
      console.error("[create-backup] mutation failed", err);
      setBackupError(err instanceof Error ? err.message : "Unknown error");
    }
  }

  async function handleRestore() {
    if (!selectedBackupId) return;
    setRestoreError(null);
    try {
      await createRestoreMutation.mutateAsync({
        backupId: selectedBackupId,
        targetNamespace,
      });
      queryClient.invalidateQueries({ queryKey: ["ListRestores"] });
      setRestoreOpen(false);
      setSelectedBackupId(null);
    } catch (err) {
      console.error("[create-restore] mutation failed", err);
      setRestoreError(err instanceof Error ? err.message : "Unknown error");
    }
  }

  async function handleDelete() {
    if (!deleteBackupId) return;
    setDeleteError(null);
    try {
      await deleteBackupMutation.mutateAsync({ backupId: deleteBackupId });
      queryClient.invalidateQueries({ queryKey: ["ListBackups"] });
      setDeleteOpen(false);
      setDeleteBackupId(null);
    } catch (err) {
      console.error("[delete-backup] mutation failed", err);
      setDeleteError(err instanceof Error ? err.message : "Unknown error");
    }
  }

  async function handleUpgrade() {
    setUpgradeError(null);
    try {
      await updateVersionMutation.mutateAsync({
        deploymentId,
        version: newVersion,
      });
      queryClient.invalidateQueries({ queryKey: ["GetDeployment"] });
      setUpgradeOpen(false);
      setNewVersion("");
    } catch (err) {
      console.error("[update-version] mutation failed", err);
      setUpgradeError(err instanceof Error ? err.message : "Unknown error");
    }
  }

  if (isLoading && !data)
    return <LoadingState message="Loading deployment..." />;
  if (error)
    return <ErrorState message={error.message} onRetry={() => refetch()} />;
  if (!deployment) return <ErrorState message="Deployment not found" />;

  const deploymentParams = deployment.parameters
    ? Object.entries(deployment.parameters).map(([key, value]) => ({
        key,
        value,
      }))
    : [];

  const deployColors = getStatusColor(deployment.status);
  // While the styrmin restore flow is in flight, the deployment status is
  // 'restoring'. Block conflicting actions client-side; the API also rejects
  // them with ALREADY_IN_PROGRESS, but greying the buttons matches the
  // intent and avoids racing pop-ups.
  const isRestoring = deployment.status === "restoring";

  return (
    <div
      className="flex flex-col gap-6 p-8 px-10"
      data-testid="deployment-detail"
      data-deployment-id={deployment.id}
      data-instance-id={instanceId ?? ""}
      data-application-version={deployment.applicationVersion ?? ""}
    >
      {/* Breadcrumb */}
      <nav className="flex items-center gap-1.5 text-xs">
        <Link to="/" className="text-muted-foreground hover:text-foreground">
          Environments
        </Link>
        <span className="text-muted-foreground">/</span>
        <Link
          to="/environments/$environmentId"
          params={{ environmentId }}
          className="text-muted-foreground hover:text-foreground"
        >
          Environment
        </Link>
        <span className="text-muted-foreground">/</span>
        <span className="font-medium text-foreground">{deployment.name}</span>
      </nav>

      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-3">
            <div className={`h-3 w-3 rounded-full ${deployColors.dot}`} />
            <h1 className="text-[22px] font-semibold tracking-tight text-foreground">
              {deployment.name}
            </h1>
            <StatusBadge status={deployment.status} />
          </div>
          <div className="flex items-center gap-4 text-xs">
            <span className="text-muted-foreground">
              Version{" "}
              <span className="font-semibold text-foreground">
                {deployment.applicationVersion}
              </span>
            </span>
            <div className="h-3 w-px bg-border" />
            <span className="text-muted-foreground">
              Driver{" "}
              <span className="font-semibold text-foreground">
                {deployment.applicationDriverVersionId}
              </span>
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <AutoRefreshIndicator
            enabled={autoRefreshEnabled}
            onToggle={setAutoRefreshEnabled}
            lastRefreshedAt={dataUpdatedAt ? new Date(dataUpdatedAt) : null}
            onRefreshNow={() => refetch()}
          />
          <Button
            variant="outline"
            size="sm"
            onClick={() => setSchedulingOpen(true)}
          >
            Scheduling
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={!instanceId || isRestoring}
            onClick={() => setUpgradeOpen(true)}
          >
            Upgrade
          </Button>
          <Button size="sm">Redeploy</Button>
        </div>
      </div>

      {backupError && (
        <Alert variant="destructive">
          <AlertDescription>{backupError}</AlertDescription>
        </Alert>
      )}

      {/* Tabs */}
      <Tabs
        tabs={DEPLOYMENT_TABS}
        activeTab={activeTab}
        onTabChange={setActiveTab}
      />

      {/* Overview Tab */}
      <TabPanel active={activeTab === "overview"}>
        <div className="flex gap-6">
          {/* Left: Endpoints */}
          <div className="flex flex-1 flex-col gap-3">
            <span className="text-[13px] font-semibold text-foreground">
              Endpoints
            </span>
            {deployment.deployedServices.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No services deployed
              </p>
            ) : (
              deployment.deployedServices.map((service) => (
                <div
                  key={service.id}
                  className="flex flex-col gap-2.5 rounded-[10px] border border-border p-4"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <div className="h-[7px] w-[7px] rounded-full bg-success" />
                      <span className="text-[13px] font-semibold text-foreground">
                        {service.driverServiceName}
                      </span>
                    </div>
                    <span className="rounded-lg bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary">
                      {service.kind} :{service.port}
                    </span>
                  </div>
                  <div className="flex flex-col gap-1.5">
                    {service.humanReadableFqdn && (
                      <ServiceAddressRow
                        url={service.humanReadableUrl}
                        fqdn={service.humanReadableFqdn}
                        port={service.port}
                        icon={<ExternalLink className="h-3 w-3 text-primary" />}
                        containerClass="bg-primary/5"
                        textClass="font-medium text-primary"
                        badgeLabel="PUBLIC"
                        badgeClass="bg-primary text-primary-foreground"
                      />
                    )}
                    {service.primaryFqdn && (
                      <ServiceAddressRow
                        url={service.primaryUrl}
                        fqdn={service.primaryFqdn}
                        port={service.port}
                        icon={
                          <Lock className="h-3 w-3 text-muted-foreground" />
                        }
                        containerClass="bg-surface"
                        textClass="text-muted-foreground"
                        badgeLabel="INTERNAL"
                        badgeClass="bg-muted text-muted-foreground"
                      />
                    )}
                  </div>
                </div>
              ))
            )}
          </div>

          {/* Right: Components + Recent Timeline */}
          <div className="flex w-[420px] flex-col gap-6">
            {/* Components */}
            <div className="flex flex-col gap-2.5">
              <span className="text-[13px] font-semibold text-foreground">
                Components
              </span>
              <div className="flex flex-col gap-1">
                {deployment.components.map((component, i) => (
                  <div
                    key={component.id}
                    className={`flex items-center justify-between rounded-lg px-3 py-2 ${
                      i % 2 === 0 ? "bg-surface" : ""
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <div
                        className={`h-[7px] w-[7px] rounded-full ${
                          component.enabled
                            ? "bg-success"
                            : "bg-muted-foreground/30"
                        }`}
                      />
                      <span
                        className={`text-[13px] font-medium ${
                          component.enabled
                            ? "text-foreground"
                            : "text-muted-foreground"
                        }`}
                      >
                        {component.name}
                      </span>
                    </div>
                    <span
                      className={`text-[11px] ${
                        component.enabled
                          ? "text-success"
                          : "text-muted-foreground"
                      }`}
                    >
                      {component.enabled ? "enabled" : "disabled"}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {/* Recent Timeline */}
            <div className="flex flex-col gap-2.5">
              <div className="flex items-center justify-between">
                <span className="text-[13px] font-semibold text-foreground">
                  Recent Timeline
                </span>
                <button
                  onClick={() => setActiveTab("timeline")}
                  className="text-xs font-medium text-primary hover:underline"
                >
                  View all
                </button>
              </div>
              {timelineEntries.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  No timeline entries
                </p>
              ) : (
                <div className="flex flex-col">
                  {timelineEntries.slice(0, 5).map((entry, i) => (
                    <div key={entry.task.id} className="flex gap-3">
                      <div
                        className="flex flex-col items-center"
                        style={{ width: 20 }}
                      >
                        <div
                          className={`mt-1 h-2.5 w-2.5 flex-shrink-0 rounded-full ${
                            entry.task.status === "failed"
                              ? "bg-destructive"
                              : entry.task.type.includes("stop")
                                ? "bg-warning"
                                : "bg-success"
                          }`}
                        />
                        {i < Math.min(timelineEntries.length, 5) - 1 && (
                          <div className="w-px flex-1 bg-border" />
                        )}
                      </div>
                      <div className="flex flex-col gap-0.5 pb-4">
                        <div className="flex items-center gap-1.5">
                          <span className="text-xs font-medium text-foreground">
                            {formatTaskType(entry.task.type)}
                          </span>
                          <StatusBadge status={entry.task.status} />
                        </div>
                        <span className="text-[11px] text-muted-foreground">
                          {entry.applicationVersion &&
                            `${entry.applicationVersion} — `}
                          {entry.task.createdOn &&
                            new Date(entry.task.createdOn).toLocaleString()}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </TabPanel>

      {/* Parameters Tab */}
      <TabPanel active={activeTab === "parameters"}>
        {deploymentParams.length > 0 ? (
          <ParameterCards
            parameters={deploymentParams}
            title="Deployment Parameters"
            description="Configuration values passed to the driver at deploy time"
          />
        ) : (
          <p className="text-sm text-muted-foreground">
            No parameters configured for this deployment.
          </p>
        )}
      </TabPanel>

      {/* Backups Tab */}
      <TabPanel active={activeTab === "backups"}>
        <div className="flex flex-col gap-4">
          <div className="flex items-center justify-between">
            <span className="text-[13px] font-semibold text-foreground">
              Backup History
            </span>
            <Button
              size="sm"
              disabled={
                !instanceId || createBackupMutation.isPending || isRestoring
              }
              onClick={handleBackup}
            >
              <Archive className="h-4 w-4" />
              {createBackupMutation.isPending ? "Creating..." : "Create Backup"}
            </Button>
          </div>

          {backupsFetching && !backupsData ? (
            <p className="text-sm text-muted-foreground">Loading backups...</p>
          ) : !backupsData?.backups || backupsData.backups.length === 0 ? (
            <p className="text-sm text-muted-foreground">No backups yet</p>
          ) : (
            <>
              {/* Table header */}
              <div className="flex items-center gap-4 px-4 py-2">
                <span className="w-[200px] text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                  Name
                </span>
                <span className="w-[100px] text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                  Status
                </span>
                <span className="w-[150px] text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                  Created
                </span>
                <span className="w-[100px] text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                  Size
                </span>
                <span className="flex-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                  Actions
                </span>
              </div>
              {backupsData.backups.map((backup, i) => (
                <BackupRow
                  key={backup.id}
                  backup={backup}
                  index={i}
                  onRestore={(backupId) => {
                    setSelectedBackupId(backupId);
                    setRestoreError(null);
                    setRestoreOpen(true);
                  }}
                  onDelete={(backupId) => {
                    setDeleteBackupId(backupId);
                    setDeleteError(null);
                    setDeleteOpen(true);
                  }}
                  autoRefreshEnabled={autoRefreshEnabled}
                />
              ))}
            </>
          )}
        </div>
      </TabPanel>

      {/* Timeline Tab */}
      <TabPanel active={activeTab === "timeline"}>
        <DeploymentTimeline entries={timelineEntries} />
      </TabPanel>

      {/* Restore dialog */}
      <Dialog
        open={restoreOpen}
        onOpenChange={(open) => {
          setRestoreOpen(open);
          if (!open) {
            setSelectedBackupId(null);
            setRestoreError(null);
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Restore Backup</DialogTitle>
            <DialogDescription>
              Restore from backup:{" "}
              <code className="font-mono">{selectedBackup?.name}</code>
            </DialogDescription>
          </DialogHeader>
          {restoreError && (
            <Alert variant="destructive">
              <AlertDescription>{restoreError}</AlertDescription>
            </Alert>
          )}
          <div className="space-y-2">
            <Label htmlFor="target-namespace">Target Namespace</Label>
            <Input
              id="target-namespace"
              value={targetNamespace}
              readOnly
              className="font-mono bg-muted"
            />
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setRestoreOpen(false);
                setSelectedBackupId(null);
                setRestoreError(null);
              }}
            >
              Cancel
            </Button>
            <Button
              onClick={handleRestore}
              disabled={!selectedBackupId || createRestoreMutation.isPending}
            >
              {createRestoreMutation.isPending ? "Restoring..." : "Restore"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete dialog */}
      <Dialog
        open={deleteOpen}
        onOpenChange={(open) => {
          setDeleteOpen(open);
          if (!open) {
            setDeleteBackupId(null);
            setDeleteError(null);
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Backup</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete{" "}
              <code className="font-mono">{deleteBackupName}</code>? This action
              cannot be undone.
            </DialogDescription>
          </DialogHeader>
          {deleteError && (
            <Alert variant="destructive">
              <AlertDescription>{deleteError}</AlertDescription>
            </Alert>
          )}
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setDeleteOpen(false);
                setDeleteBackupId(null);
                setDeleteError(null);
              }}
            >
              Cancel
            </Button>
            <Button variant="destructive" onClick={handleDelete}>
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Upgrade dialog */}
      <Dialog open={upgradeOpen} onOpenChange={setUpgradeOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Upgrade Deployment</DialogTitle>
            <DialogDescription>
              Current version:{" "}
              <code className="font-mono">{deployment.applicationVersion}</code>
            </DialogDescription>
          </DialogHeader>
          {upgradeError && (
            <Alert variant="destructive">
              <AlertDescription>{upgradeError}</AlertDescription>
            </Alert>
          )}
          <div className="space-y-2">
            <Label htmlFor="new-version">New Version</Label>
            <Input
              id="new-version"
              value={newVersion}
              onChange={(e) => setNewVersion(e.target.value)}
              placeholder="e.g. 2.0.0"
            />
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setUpgradeOpen(false);
                setUpgradeError(null);
              }}
            >
              Cancel
            </Button>
            <Button
              onClick={handleUpgrade}
              disabled={!newVersion.trim() || updateVersionMutation.isPending}
            >
              {updateVersionMutation.isPending ? "Upgrading..." : "Upgrade"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <SchedulingConfigDialog
        open={schedulingOpen}
        onOpenChange={setSchedulingOpen}
        deploymentId={deploymentId}
        currentConfig={deployment.config}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// ServiceAddressRow
// ---------------------------------------------------------------------------

function ServiceAddressRow({
  url,
  fqdn,
  port,
  icon,
  containerClass,
  textClass,
  badgeLabel,
  badgeClass,
}: {
  url?: string | null;
  fqdn: string;
  port: number;
  icon: React.ReactNode;
  containerClass: string;
  textClass: string;
  badgeLabel: string;
  badgeClass: string;
}) {
  // Display label: strip scheme from the URL so the visual density matches
  // the previous bare-FQDN rendering, while still showing the port.
  const displayLabel = url
    ? url.replace(/^[a-z]+:\/\//, "")
    : `${fqdn}:${port}`;

  const content = (
    <span className={`font-mono text-xs ${textClass}`}>{displayLabel}</span>
  );

  return (
    <div
      className={`flex items-center gap-2 rounded-lg ${containerClass} px-3 py-2`}
    >
      {icon}
      {url ? (
        <a
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          className="hover:underline"
        >
          {content}
        </a>
      ) : (
        content
      )}
      <span
        className={`ml-auto rounded px-1.5 py-px text-[10px] font-medium ${badgeClass}`}
      >
        {badgeLabel}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// BackupRow
// ---------------------------------------------------------------------------

type RestoreItem = ListRestoresQuery["restores"][number];

function BackupRow({
  backup,
  index,
  onRestore,
  onDelete,
  autoRefreshEnabled,
}: {
  backup: {
    id: string;
    name: string;
    status: string;
    createdOn: string;
    sizeBytes?: number | null;
    errorMessage?: string | null;
  };
  index: number;
  onRestore: (backupId: string) => void;
  onDelete: (backupId: string) => void;
  autoRefreshEnabled: boolean;
}) {
  const { data: restoresData } = useListRestoresQuery(
    { backupId: backup.id },
    {
      enabled: backup.status === "completed",
      refetchInterval: autoRefreshEnabled ? 10_000 : false,
    },
  );

  const restores = restoresData?.restores ?? [];
  const hasActiveRestore = restores.some(
    (r: { status: string }) =>
      r.status === "pending" || r.status === "in_progress",
  );
  const isRestoreDisabled = backup.status !== "completed" || hasActiveRestore;

  const bc = getStatusColor(backup.status);

  return (
    <div
      data-testid="backup-row"
      data-backup-id={backup.id}
      data-backup-name={backup.name}
      data-backup-status={backup.status}
    >
      <div
        className={`flex items-center gap-4 rounded-lg border-l-[3px] px-4 py-3 ${bc.border} ${
          index % 2 === 0 ? "bg-surface" : ""
        }`}
      >
        <div className="flex w-[200px] items-center gap-2">
          <div className={`h-2 w-2 flex-shrink-0 rounded-full ${bc.dot}`} />
          <span className="text-[13px] font-medium text-foreground">
            {backup.name}
          </span>
        </div>
        <div className="w-[100px]" data-testid="backup-status">
          <StatusBadge status={backup.status} />
        </div>
        <span className="w-[150px] text-[13px] text-muted-foreground">
          {new Date(backup.createdOn).toLocaleDateString()}
        </span>
        <span className="w-[100px] text-[13px] text-muted-foreground">
          {backup.sizeBytes != null ? formatBytes(backup.sizeBytes) : "—"}
        </span>
        <div className="flex flex-1 items-center gap-2">
          <button
            disabled={isRestoreDisabled}
            onClick={() => onRestore(backup.id)}
            className="text-xs font-medium text-primary hover:underline disabled:text-muted-foreground disabled:no-underline"
          >
            Restore
          </button>
          <span className="text-muted-foreground/30">|</span>
          <button
            onClick={() => onDelete(backup.id)}
            className="text-xs font-medium text-destructive hover:underline"
          >
            Delete
          </button>
        </div>
      </div>

      {/* Restore history */}
      {restores.map((restore) => (
        <RestoreRow key={restore.id} restore={restore} />
      ))}
    </div>
  );
}

function RestoreRow({ restore }: { restore: RestoreItem }) {
  const components = restore.componentStatuses ?? [];

  return (
    <div
      className="flex items-center gap-3 border-t border-border/50 px-4 py-2.5 pl-10"
      data-testid="restore-row"
      data-restore-id={restore.id}
      data-restore-status={restore.status}
      data-target-namespace={restore.targetNamespace}
    >
      <RotateCcw className="h-3.5 w-3.5 text-muted-foreground" />
      <span className="text-xs text-muted-foreground">Restored to</span>
      <span className="text-xs font-medium text-foreground">
        {restore.targetNamespace}
      </span>
      <span className="text-xs text-muted-foreground">—</span>
      <span data-testid="restore-status">
        <StatusBadge status={restore.status} />
      </span>
      <span className="text-xs text-muted-foreground">
        {new Date(restore.createdOn).toLocaleDateString()}
      </span>

      {components.length > 0 && (
        <Collapsible className="ml-auto">
          <CollapsibleTrigger className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors group">
            <ChevronRight className="h-3 w-3 transition-transform group-data-[panel-open]:rotate-90" />
            {components.length} components
          </CollapsibleTrigger>
          <CollapsibleContent className="mt-1 space-y-1">
            {components.map((comp) => (
              <div
                key={comp.componentName}
                className="flex items-center justify-between py-0.5"
              >
                <span className="text-xs">{comp.componentName}</span>
                <StatusBadge status={comp.status} />
              </div>
            ))}
          </CollapsibleContent>
        </Collapsible>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

function formatTaskType(type: string): string {
  return type.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}
