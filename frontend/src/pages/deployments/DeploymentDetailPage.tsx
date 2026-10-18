import { useState } from "react";
import { useParams, Link, useNavigate } from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import {
  useGetDeploymentQuery,
  useGetDeploymentTimelineQuery,
  useGetDriverQuery,
  useCreateBackupMutation,
  useDeleteBackupMutation,
  useDeleteDeploymentMutation,
  useListBackupsQuery,
  useCreateRestoreMutation,
  useListRestoresQuery,
  useUpdateDeploymentVersionMutation,
  type ListRestoresQuery,
} from "@/generated/graphql";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { StatusBadge, getStatusColor } from "@/components/StatusBadge";
import { ConfigurationTab } from "@/components/deployment/configuration";
import { UpgradeErrorAlert } from "@/components/deployment/UpgradeErrorAlert";
import { Tabs, TabPanel } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  AlertTriangle,
  Archive,
  ChevronRight,
  ExternalLink,
  Lock,
  RotateCcw,
} from "lucide-react";
import { AutoRefreshIndicator } from "@/components/AutoRefreshIndicator";
import { BackupRestoreSteps } from "@/components/deployment/BackupRestoreSteps";
import { DeploymentTimeline } from "@/components/deployment/DeploymentTimeline";
import type { StepListItem } from "@/components/deployment/StepList";
import { TaskResultBadge } from "@/components/deployment/TaskResultBadge";
import { PinnedImageOverridesNotice } from "@/components/deployment/PinnedImageOverridesNotice";
import { DriverDirectoryChangeNotice } from "@/components/deployment/DriverDirectoryChangeNotice";
import { IfRole } from "@/auth/IfRole";
import { PodsTab } from "./PodsTab";
import {
  driverDirectoriesOf,
  formatDriverVersionLabel,
  withDriverDirectory,
} from "@/lib/driverVersion";
import { taskResultDisplay } from "@/lib/task-display";
import { useDocumentTitle } from "@/hooks/use-document-title";

const DEPLOYMENT_TABS = [
  { id: "overview", label: "Overview" },
  { id: "settings", label: "Settings" },
  { id: "backups", label: "Backups" },
  { id: "pods", label: "Pods" },
  { id: "timeline", label: "Timeline" },
];

export default function DeploymentDetailPage() {
  const { environmentId, deploymentId } = useParams({
    from: "/environments/$environmentId/deployments/$deploymentId",
  });
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [autoRefreshEnabled, setAutoRefreshEnabled] = useState(true);
  const [activeTab, setActiveTab] = useState("overview");

  const { data, isLoading, error, refetch, dataUpdatedAt } =
    useGetDeploymentQuery(
      { deploymentId },
      { refetchInterval: autoRefreshEnabled ? 10_000 : false },
    );

  const deployment = data?.deployment;
  useDocumentTitle(deployment?.name ?? "Deployment");

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
  const [upgradeError, setUpgradeError] = useState<Error | null>(null);
  // Driver-version pin for the upgrade dialog. The "latest" sentinel keeps
  // the backend's default latest-wins resolution (driverVersionId omitted);
  // a UUID pins the binding to that specific driver version.
  const [selectedDriverVersionId, setSelectedDriverVersionId] =
    useState("latest");

  // Versions of the deployment's driver, fetched lazily when the upgrade
  // dialog opens so the picker can offer an explicit driver-version pin.
  const upgradeDriverId =
    deployment?.applicationDriverVersion?.applicationDriver?.id;
  const { data: upgradeDriverData } = useGetDriverQuery(
    { applicationDriverId: upgradeDriverId ?? "" },
    { enabled: upgradeOpen && !!upgradeDriverId },
  );
  const upgradeDriverVersions = [
    ...(upgradeDriverData?.applicationDriver?.versions ?? []),
  ].sort(
    (a, b) => new Date(b.createdOn).getTime() - new Date(a.createdOn).getTime(),
  );
  const upgradeDriverDirectories = driverDirectoriesOf(
    upgradeDriverVersions,
    deployment?.applicationDriverVersionId,
  );

  // Deployment-deletion state (spec 008).
  const deleteDeploymentMutation = useDeleteDeploymentMutation();
  const [deleteDeploymentOpen, setDeleteDeploymentOpen] = useState(false);
  const [deleteDeploymentConfirm, setDeleteDeploymentConfirm] = useState("");
  const [deleteDeploymentError, setDeleteDeploymentError] = useState<
    string | null
  >(null);

  // Lists every instance's backups, so the history survives a new instance.
  const {
    data: backupsData,
    isLoading: backupsFetching,
    error: backupsError,
    refetch: refetchBackups,
    dataUpdatedAt: backupsUpdatedAt,
  } = useListBackupsQuery(
    { deploymentId },
    { refetchInterval: autoRefreshEnabled ? 10_000 : false },
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
        driverVersionId:
          selectedDriverVersionId === "latest"
            ? undefined
            : selectedDriverVersionId,
      });
      queryClient.invalidateQueries({ queryKey: ["GetDeployment"] });
      setUpgradeOpen(false);
      setNewVersion("");
      setSelectedDriverVersionId("latest");
    } catch (err) {
      console.error("[update-version] mutation failed", err);
      setUpgradeError(err instanceof Error ? err : new Error("Unknown error"));
    }
  }

  async function handleDeleteDeployment() {
    setDeleteDeploymentError(null);
    try {
      await deleteDeploymentMutation.mutateAsync({ deploymentId });
      // Invalidate any cached views so the row re-fetches with the new
      // (Deleting...) status badge before vanishing once tombstoned.
      queryClient.invalidateQueries({ queryKey: ["GetEnvironment"] });
      queryClient.invalidateQueries({ queryKey: ["ListEnvironments"] });
      setDeleteDeploymentOpen(false);
      setDeleteDeploymentConfirm("");
      navigate({
        to: "/environments/$environmentId",
        params: { environmentId },
        replace: true,
      });
    } catch (err) {
      console.error("[delete-deployment] mutation failed", err);
      setDeleteDeploymentError(
        err instanceof Error ? err.message : "Unknown error",
      );
    }
  }

  if (isLoading && !data)
    return <LoadingState message="Loading deployment..." />;
  if (error)
    return <ErrorState message={error.message} onRetry={() => refetch()} />;
  if (!deployment) return <ErrorState message="Deployment not found" />;

  const deployColors = getStatusColor(deployment.status);
  // While the styrmin restore flow is in flight, the deployment status is
  // 'restoring'. Block conflicting actions client-side; the API also rejects
  // them with ALREADY_IN_PROGRESS, but greying the buttons matches the
  // intent and avoids racing pop-ups.
  const isRestoring = deployment.status === "restoring";
  const isDeleting = deployment.status === "deleting";
  const isDeleted =
    deployment.status === "deleted" || deployment.deletedAt !== null;
  const isTerminal = isDeleting || isDeleted;
  const terminalTitle = isDeleting
    ? "This deployment is being deleted"
    : isDeleted
      ? "This deployment is deleted"
      : undefined;
  // Warn before restoring a backup of an earlier instance or another version.
  const selectedBackupNeedsWarning =
    !!selectedBackup &&
    (selectedBackup.instance.id !== instanceId ||
      selectedBackup.instance.applicationVersion !==
        deployment.applicationVersion);
  const driverName =
    deployment.applicationDriverVersion?.applicationDriver?.name ?? null;
  const driverVersionLabel = deployment.applicationDriverVersion
    ? formatDriverVersionLabel(deployment.applicationDriverVersion)
    : null;

  return (
    <div
      className="flex flex-col gap-6 p-8 px-10"
      data-testid="deployment-detail"
      data-deployment-id={deployment.id}
      data-instance-id={instanceId ?? ""}
      data-application-version={deployment.applicationVersion ?? ""}
      data-driver-name={driverName ?? ""}
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
                {driverName ?? deployment.applicationDriverVersionId}
                {driverVersionLabel && (
                  <>
                    {" "}
                    <span className="font-mono text-muted-foreground">
                      v{driverVersionLabel}
                    </span>
                  </>
                )}
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
          <IfRole minimum="READ_WRITE">
            <Button
              variant="outline"
              size="sm"
              disabled={!instanceId || isRestoring || isTerminal}
              onClick={() => setUpgradeOpen(true)}
              title={terminalTitle}
            >
              Upgrade
            </Button>
          </IfRole>
          <IfRole minimum="READ_WRITE">
            <Button
              variant="destructive"
              size="sm"
              disabled={isRestoring || isTerminal}
              onClick={() => setDeleteDeploymentOpen(true)}
              title={
                isTerminal
                  ? terminalTitle
                  : isRestoring
                    ? "Deletion is refused while a restore is in progress"
                    : undefined
              }
              data-testid="delete-deployment-button"
            >
              Delete
            </Button>
          </IfRole>
        </div>
      </div>

      {isDeleted && deployment.deletedAt && (
        <Alert variant="destructive" data-testid="deleted-banner">
          <AlertDescription>
            Deleted at{" "}
            <span className="font-mono">
              {new Date(deployment.deletedAt).toLocaleString()}
            </span>
            . This deployment is read-only — actions are disabled.
          </AlertDescription>
        </Alert>
      )}
      {isDeleting && (
        <Alert data-testid="deleting-banner">
          <AlertDescription>
            Deleting… The cluster is tearing down resources. This deployment
            cannot be modified.
          </AlertDescription>
        </Alert>
      )}

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
                    <div
                      key={entry.task.id}
                      className="flex gap-3"
                      data-testid="recent-timeline-entry"
                      data-task-id={entry.task.id}
                      data-task-result={entry.task.result}
                    >
                      <div
                        className="flex flex-col items-center"
                        style={{ width: 20 }}
                      >
                        <div
                          aria-hidden="true"
                          className={`mt-1 h-2.5 w-2.5 flex-shrink-0 rounded-full ${
                            taskResultDisplay(entry.task.result).dot
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
                          <TaskResultBadge result={entry.task.result} />
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

      {/* Configuration Tab (spec 011-unified-deployment-config — US1) */}
      <TabPanel active={activeTab === "settings"}>
        <ConfigurationTab deployment={deployment} />
      </TabPanel>

      {/* Backups Tab */}
      <TabPanel active={activeTab === "backups"}>
        <div className="flex flex-col gap-4">
          <div className="flex items-center justify-between">
            <span className="text-[13px] font-semibold text-foreground">
              Backup History
            </span>
            <IfRole minimum="READ_WRITE">
              <Button
                size="sm"
                disabled={
                  !instanceId ||
                  createBackupMutation.isPending ||
                  isRestoring ||
                  isTerminal
                }
                onClick={handleBackup}
                title={terminalTitle}
              >
                <Archive className="h-4 w-4" />
                {createBackupMutation.isPending
                  ? "Creating..."
                  : "Create Backup"}
              </Button>
            </IfRole>
          </div>

          {backupsFetching && !backupsData ? (
            <p className="text-sm text-muted-foreground">Loading backups...</p>
          ) : backupsError && !backupsData ? (
            <ErrorState
              title="Could not load the backup history"
              message={backupsError.message}
              onRetry={() => refetchBackups()}
            />
          ) : !backupsData?.backups || backupsData.backups.length === 0 ? (
            <div className="flex flex-col gap-1" data-testid="backups-empty">
              <p className="text-sm text-muted-foreground">
                {isDeleted ? "No backups" : "No backups yet"}
              </p>
              <p className="text-xs text-muted-foreground">
                {isDeleted
                  ? "No backup was taken of this deployment before it was deleted."
                  : 'This list shows the backups of this deployment only. If an earlier deployment with the same name was deleted, its backups stay with it: on the environment page, turn on "Show deleted" and open that deployment.'}
              </p>
            </div>
          ) : (
            <>
              {/* Table header. Fixed columns fit beside the sidebar at 1280px. */}
              <div className="flex items-center gap-3 border-l-[3px] border-transparent px-4 py-2">
                <span className="min-w-0 flex-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                  Name
                </span>
                <span className="w-[100px] shrink-0 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                  Status
                </span>
                <span className="w-[120px] shrink-0 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                  Application version
                </span>
                <span className="w-[130px] shrink-0 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                  Created
                </span>
                <span className="w-[70px] shrink-0 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                  Size
                </span>
                <span className="w-[110px] shrink-0 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                  Expires
                </span>
                <span className="w-[110px] shrink-0 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
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
                  deploymentTerminal={isTerminal}
                  terminalTitle={terminalTitle}
                  activeInstanceId={instanceId}
                  listedAt={backupsUpdatedAt}
                />
              ))}
            </>
          )}
        </div>
      </TabPanel>

      {/* Pods Tab */}
      <TabPanel active={activeTab === "pods"}>
        <PodsTab
          deploymentId={deploymentId}
          isActive={activeTab === "pods"}
          declaredComponents={deployment?.components ?? []}
          deploymentStatus={deployment?.status ?? "unknown"}
          onOpenTimeline={() => setActiveTab("timeline")}
        />
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
          {selectedBackup && (
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
              <dt className="text-muted-foreground">
                Backup application version
              </dt>
              <dd
                className="break-all font-mono"
                data-testid="restore-backup-version"
              >
                {selectedBackup.instance.applicationVersion}
              </dd>
              <dt className="text-muted-foreground">
                Current application version
              </dt>
              <dd
                className="break-all font-mono"
                data-testid="restore-current-version"
              >
                {deployment.applicationVersion}
              </dd>
            </dl>
          )}
          {selectedBackup && selectedBackupNeedsWarning && (
            <Alert data-testid="restore-earlier-instance-warning">
              <AlertTriangle className="h-4 w-4" />
              <AlertTitle>
                {selectedBackup.instance.id !== instanceId
                  ? "This backup was taken of an earlier instance"
                  : "This backup was taken at another application version"}
              </AlertTitle>
              <AlertDescription>
                The backup was taken at application version{" "}
                {selectedBackup.instance.applicationVersion}. The deployment
                runs version {deployment.applicationVersion} now. The restore
                puts back the StyrminDeployment and HelmRelease that the backup
                holds, with that application version and config. Styrmin keeps
                the current instance as the deployment&apos;s active instance,
                so this page keeps showing version{" "}
                {deployment.applicationVersion}.
              </AlertDescription>
            </Alert>
          )}
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
            <IfRole minimum="READ_WRITE">
              <Button
                onClick={handleRestore}
                disabled={!selectedBackupId || createRestoreMutation.isPending}
              >
                {createRestoreMutation.isPending ? "Restoring..." : "Restore"}
              </Button>
            </IfRole>
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
            <IfRole minimum="READ_WRITE">
              <Button variant="destructive" onClick={handleDelete}>
                Delete
              </Button>
            </IfRole>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Upgrade dialog */}
      <Dialog
        open={upgradeOpen}
        onOpenChange={(open) => {
          setUpgradeOpen(open);
          if (!open) {
            setSelectedDriverVersionId("latest");
            setUpgradeError(null);
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Upgrade Deployment</DialogTitle>
            <DialogDescription>
              Current version:{" "}
              <code className="font-mono">{deployment.applicationVersion}</code>
            </DialogDescription>
          </DialogHeader>
          {upgradeError && (
            <UpgradeErrorAlert
              error={upgradeError}
              componentNames={deployment.components.map((c) => c.name)}
              onOpenSettings={() => {
                setUpgradeOpen(false);
                setUpgradeError(null);
                setActiveTab("settings");
              }}
            />
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
          <div className="space-y-2">
            <Label htmlFor="upgrade-driver-version">Driver Version</Label>
            <Select
              value={selectedDriverVersionId}
              onValueChange={setSelectedDriverVersionId}
            >
              <SelectTrigger
                id="upgrade-driver-version"
                data-testid="upgrade-driver-version-select"
              >
                <SelectValue placeholder="Latest (auto)" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="latest">Latest (auto)</SelectItem>
                {upgradeDriverVersions.map((v) => (
                  <SelectItem key={v.id} value={v.id}>
                    {withDriverDirectory(formatDriverVersionLabel(v), v)}
                    {v.id === deployment.applicationDriverVersionId
                      ? " (current)"
                      : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              Latest (auto) binds the newest loaded driver version supporting
              the new application version; pick one to pin it explicitly.
            </p>
          </div>
          {selectedDriverVersionId === "latest" && upgradeDriverDirectories && (
            <DriverDirectoryChangeNotice
              current={upgradeDriverDirectories.current}
              others={upgradeDriverDirectories.others}
            />
          )}
          <PinnedImageOverridesNotice
            overrides={deployment.componentImageOverrides}
          />
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setUpgradeOpen(false);
                setSelectedDriverVersionId("latest");
                setUpgradeError(null);
              }}
            >
              Cancel
            </Button>
            <IfRole minimum="READ_WRITE">
              <Button
                onClick={handleUpgrade}
                disabled={!newVersion.trim() || updateVersionMutation.isPending}
              >
                {updateVersionMutation.isPending ? "Upgrading..." : "Upgrade"}
              </Button>
            </IfRole>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete deployment dialog (spec 008) — type-to-confirm. */}
      <Dialog
        open={deleteDeploymentOpen}
        onOpenChange={(open) => {
          setDeleteDeploymentOpen(open);
          if (!open) {
            setDeleteDeploymentConfirm("");
            setDeleteDeploymentError(null);
          }
        }}
      >
        <DialogContent data-testid="delete-deployment-dialog">
          <DialogHeader>
            <DialogTitle>Delete deployment</DialogTitle>
            <DialogDescription>
              This will tear down all workload resources for{" "}
              <code className="font-mono">{deployment.name}</code> and remove
              its namespace. Backups are retained against this deployment. The
              deleted deployment will appear in the deleted view for the
              configured forensic-retention window.
            </DialogDescription>
          </DialogHeader>
          {deleteDeploymentError && (
            <Alert variant="destructive">
              <AlertDescription>{deleteDeploymentError}</AlertDescription>
            </Alert>
          )}
          <div className="space-y-2">
            <Label htmlFor="delete-deployment-confirm">
              Type the deployment name to confirm:{" "}
              <code className="font-mono">{deployment.name}</code>
            </Label>
            <Input
              id="delete-deployment-confirm"
              value={deleteDeploymentConfirm}
              onChange={(e) => setDeleteDeploymentConfirm(e.target.value)}
              placeholder={deployment.name}
              autoComplete="off"
              data-testid="delete-deployment-confirm-input"
            />
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setDeleteDeploymentOpen(false);
                setDeleteDeploymentConfirm("");
                setDeleteDeploymentError(null);
              }}
            >
              Cancel
            </Button>
            <IfRole minimum="READ_WRITE">
              <Button
                variant="destructive"
                onClick={handleDeleteDeployment}
                disabled={
                  deleteDeploymentConfirm !== deployment.name ||
                  deleteDeploymentMutation.isPending
                }
                data-testid="delete-deployment-confirm-button"
              >
                {deleteDeploymentMutation.isPending ? "Deleting…" : "Delete"}
              </Button>
            </IfRole>
          </DialogFooter>
        </DialogContent>
      </Dialog>
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
  deploymentTerminal,
  terminalTitle,
  activeInstanceId,
  listedAt,
}: {
  backup: {
    id: string;
    name: string;
    status: string;
    createdOn: string;
    sizeBytes?: number | null;
    errorMessage?: string | null;
    /** Retention TTL applied when the backup was taken, e.g. `"2160h"`. */
    ttl?: string | null;
    /** Expiration Velero reported for the backup. */
    expiresAt?: string | null;
    /** The instance the backup was taken of, possibly not the active one. */
    instance: { id: string; applicationVersion: string };
    /** One step per component. */
    steps: StepListItem[];
  };
  index: number;
  onRestore: (backupId: string) => void;
  onDelete: (backupId: string) => void;
  autoRefreshEnabled: boolean;
  /**
   * True when the parent deployment is DELETING or DELETED. Disables
   * restore + delete-backup actions on the row even though the backup
   * row itself is still available (per spec 008 US12: action buttons
   * disabled while the deployment is being deleted or already deleted).
   */
  deploymentTerminal: boolean;
  /** Why the actions are disabled on a deleting or deleted deployment. */
  terminalTitle?: string;
  /** The deployment's active instance, to mark the backups taken of it. */
  activeInstanceId?: string;
  /** When the list was fetched, in ms since the epoch; expiry is judged against it. */
  listedAt: number;
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
  const isCurrentInstance = backup.instance.id === activeInstanceId;

  // The applied retention TTL explains *why* the expiry date is what it is.
  // It rides a native `title` for pointer users, but is also rendered as
  // assistive-only text so it reaches the accessibility tree without any
  // hover interaction (spec 016 critique P2).
  const retentionHint = backup.ttl ? `Retention TTL ${backup.ttl}` : undefined;

  // `new Date(...)` never throws — an unparseable value yields an Invalid Date
  // whose `toLocaleDateString()` is the literal string "Invalid Date". Fall
  // back to the same em-dash placeholder used for a missing expiry so a
  // corrupt stored timestamp reads as "unknown" rather than as an error.
  const expiresAt = ((): Date | null => {
    if (!backup.expiresAt) return null;
    const parsed = new Date(backup.expiresAt);
    return isNaN(parsed.getTime()) ? null : parsed;
  })();
  const expiresAtLabel = expiresAt ? expiresAt.toLocaleDateString() : "—";
  // Velero deletes a backup once its expiry date has passed.
  const isExpired = expiresAt !== null && expiresAt.getTime() <= listedAt;

  const isRestoreDisabled =
    backup.status !== "completed" ||
    hasActiveRestore ||
    deploymentTerminal ||
    isExpired;
  const restoreTitle = deploymentTerminal
    ? terminalTitle
    : isExpired
      ? "The expiry date of this backup has passed: Velero deletes a backup when it expires"
      : undefined;

  const bc = getStatusColor(backup.status);

  return (
    <div
      data-testid="backup-row"
      data-backup-id={backup.id}
      data-backup-name={backup.name}
      data-backup-status={backup.status}
      data-backup-application-version={backup.instance.applicationVersion}
    >
      <div
        className={`flex items-center gap-3 rounded-lg border-l-[3px] px-4 py-3 ${bc.border} ${
          index % 2 === 0 ? "bg-surface" : ""
        }`}
      >
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <div className={`h-2 w-2 flex-shrink-0 rounded-full ${bc.dot}`} />
          <span className="min-w-0 break-all text-[13px] font-medium text-foreground">
            {backup.name}
          </span>
        </div>
        <div className="w-[100px] shrink-0" data-testid="backup-status">
          <StatusBadge status={backup.status} />
        </div>
        <div className="w-[120px] shrink-0 text-[13px] text-muted-foreground">
          <span className="sr-only">Application version </span>
          <span
            className="break-all font-mono"
            data-testid="backup-application-version"
          >
            {backup.instance.applicationVersion}
          </span>
          {isCurrentInstance && (
            <span
              className="block text-[11px]"
              data-testid="backup-current-instance"
            >
              current instance
            </span>
          )}
        </div>
        <span
          className="w-[130px] shrink-0 text-[13px] text-muted-foreground"
          data-testid="backup-created"
        >
          {new Date(backup.createdOn).toLocaleString(undefined, {
            dateStyle: "short",
            timeStyle: "short",
          })}
        </span>
        <span className="w-[70px] shrink-0 text-[13px] text-muted-foreground">
          {backup.sizeBytes != null ? formatBytes(backup.sizeBytes) : "—"}
        </span>
        <span
          className="w-[110px] shrink-0 text-[13px] text-muted-foreground"
          data-testid="backup-expires"
          title={retentionHint}
        >
          {expiresAtLabel}
          {isExpired && (
            <span
              className="block text-[11px] font-medium text-destructive"
              data-testid="backup-expired"
            >
              Expired
            </span>
          )}
          {retentionHint && <span className="sr-only"> ({retentionHint})</span>}
        </span>
        <div className="flex w-[110px] shrink-0 items-center gap-2">
          <IfRole minimum="READ_WRITE">
            <button
              disabled={isRestoreDisabled}
              onClick={() => onRestore(backup.id)}
              className="text-xs font-medium text-primary hover:underline disabled:text-muted-foreground disabled:no-underline"
              title={restoreTitle}
            >
              Restore
            </button>
            <span className="text-muted-foreground/30">|</span>
            <button
              disabled={deploymentTerminal}
              onClick={() => onDelete(backup.id)}
              className="text-xs font-medium text-destructive hover:underline disabled:text-muted-foreground disabled:no-underline"
              title={deploymentTerminal ? terminalTitle : undefined}
            >
              Delete
            </button>
          </IfRole>
        </div>
      </div>

      <div className="px-4 py-2 pl-8">
        <BackupRestoreSteps
          parent="backup"
          parentId={backup.id}
          status={backup.status}
          steps={backup.steps}
        />
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
      className="flex flex-col gap-2 border-t border-border/50 px-4 py-2.5 pl-10"
      data-testid="restore-row"
      data-restore-id={restore.id}
      data-restore-status={restore.status}
      data-target-namespace={restore.targetNamespace}
    >
      <div className="flex items-center gap-3">
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
      <div className="pl-6">
        <BackupRestoreSteps
          parent="restore"
          parentId={restore.id}
          status={restore.status}
          steps={restore.steps}
        />
      </div>
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
