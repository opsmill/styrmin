import { useState } from "react";
import { useParams } from "react-router";
import {
  useGetDeploymentQuery,
  useCreateBackupMutation,
  useDeleteBackupMutation,
  useListBackupsQuery,
  useCreateRestoreMutation,
  useListRestoresQuery,
  useUpdateDeploymentVersionMutation,
  type ListRestoresQuery,
} from "@/generated/graphql";
import { PageLayout } from "@/components/PageLayout";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { StatusBadge } from "@/components/StatusBadge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Archive,
  ArrowUpCircle,
  ChevronRight,
  EllipsisVertical,
  RotateCcw,
  Trash2,
} from "lucide-react";
import { useAutoRefresh } from "@/hooks/useAutoRefresh";
import { AutoRefreshIndicator } from "@/components/AutoRefreshIndicator";

export default function DeploymentDetailPage() {
  const { environmentId, deploymentId } = useParams();
  const [{ data, fetching, error }, reexecute] = useGetDeploymentQuery({
    variables: { deploymentId: deploymentId! },
    pause: !deploymentId,
  });

  const deployment = data?.deployment;

  const instanceId = deployment?.applicationInstance?.id;

  // Backup mutation
  const [backupResult, createBackup] = useCreateBackupMutation();
  const [backupError, setBackupError] = useState<string | null>(null);

  // Restore mutation and state
  const [restoreResult, createRestore] = useCreateRestoreMutation();
  const [restoreOpen, setRestoreOpen] = useState(false);
  const [selectedBackupId, setSelectedBackupId] = useState<string | null>(null);
  const [restoreError, setRestoreError] = useState<string | null>(null);

  // Delete backup state
  const [, deleteBackup] = useDeleteBackupMutation();
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteBackupId, setDeleteBackupId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  // Upgrade mutation
  const [upgradeResult, updateVersion] = useUpdateDeploymentVersionMutation();
  const [upgradeOpen, setUpgradeOpen] = useState(false);
  const [newVersion, setNewVersion] = useState("");
  const [upgradeError, setUpgradeError] = useState<string | null>(null);

  // Backups list
  const [{ data: backupsData, fetching: backupsFetching }, reexecuteBackups] =
    useListBackupsQuery({
      variables: { instanceId: instanceId! },
      pause: !instanceId,
    });

  const autoRefresh = useAutoRefresh({
    onRefresh: () => {
      reexecute({ requestPolicy: "network-only" });
      if (instanceId) {
        reexecuteBackups({ requestPolicy: "network-only" });
      }
    },
  });

  const selectedBackup = backupsData?.backups?.find(
    (b) => b.id === selectedBackupId,
  );
  const deleteBackupName = backupsData?.backups?.find(
    (b) => b.id === deleteBackupId,
  )?.name;
  const targetNamespace = deploymentId ? `styrmin-${deploymentId}` : "";

  async function handleBackup() {
    setBackupError(null);
    const result = await createBackup({ instanceId: instanceId! });
    if (result.error) {
      setBackupError(result.error.message);
    } else {
      reexecuteBackups({ requestPolicy: "network-only" });
    }
  }

  async function handleRestore() {
    if (!selectedBackupId) return;
    setRestoreError(null);
    const result = await createRestore({
      backupId: selectedBackupId,
      targetNamespace,
    });
    if (result.error) {
      setRestoreError(result.error.message);
    } else {
      setRestoreOpen(false);
      setSelectedBackupId(null);
    }
  }

  async function handleDelete() {
    if (!deleteBackupId) return;
    setDeleteError(null);
    const result = await deleteBackup({ backupId: deleteBackupId });
    if (result.error) {
      setDeleteError(result.error.message);
    } else {
      setDeleteOpen(false);
      setDeleteBackupId(null);
      reexecuteBackups({ requestPolicy: "network-only" });
    }
  }

  async function handleUpgrade() {
    setUpgradeError(null);
    const result = await updateVersion({
      deploymentId: deploymentId!,
      version: newVersion,
    });
    if (result.error) {
      setUpgradeError(result.error.message);
    } else {
      setUpgradeOpen(false);
      setNewVersion("");
      reexecute({ requestPolicy: "network-only" });
    }
  }

  if (fetching && !data)
    return <LoadingState message="Loading deployment..." />;

  if (error) {
    return (
      <ErrorState
        message={error.message}
        onRetry={() => reexecute({ requestPolicy: "network-only" })}
      />
    );
  }

  if (!deployment) {
    return <ErrorState message="Deployment not found" />;
  }

  return (
    <PageLayout
      title={deployment.name}
      breadcrumbs={[
        {
          label: "Environment",
          href: `/environments/${environmentId}`,
        },
        { label: deployment.name },
      ]}
      actions={
        <>
          <AutoRefreshIndicator
            enabled={autoRefresh.enabled}
            onToggle={autoRefresh.setEnabled}
            lastRefreshedAt={autoRefresh.lastRefreshedAt}
            onRefreshNow={autoRefresh.refreshNow}
          />
          <Button
            variant="outline"
            size="sm"
            disabled={!instanceId || backupResult.fetching}
            onClick={handleBackup}
          >
            <Archive className="h-4 w-4" />
            {backupResult.fetching ? "Backing up…" : "Backup"}
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={!instanceId}
            onClick={() => setUpgradeOpen(true)}
          >
            <ArrowUpCircle className="h-4 w-4" />
            Upgrade
          </Button>
        </>
      }
    >
      <div className="space-y-6 max-w-3xl">
        {backupError && (
          <Alert variant="destructive">
            <AlertDescription>{backupError}</AlertDescription>
          </Alert>
        )}

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              <span>Overview</span>
              <StatusBadge status={deployment.status} />
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <DetailRow
              label="Version"
              value={deployment.applicationVersion}
              mono
            />
            <DetailRow
              label="Driver Version ID"
              value={deployment.applicationDriverVersionId}
              mono
            />
            <DetailRow
              label="Environment ID"
              value={deployment.environmentId}
              mono
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Application Instance</CardTitle>
          </CardHeader>
          <CardContent>
            {deployment.applicationInstance ? (
              <div className="space-y-3">
                <DetailRow
                  label="Name"
                  value={deployment.applicationInstance.name}
                />
                <div className="flex items-center gap-2">
                  <span className="text-sm text-muted-foreground w-40">
                    Status
                  </span>
                  <StatusBadge status={deployment.applicationInstance.status} />
                </div>
                <DetailRow
                  label="Version"
                  value={deployment.applicationInstance.applicationVersion}
                  mono
                />
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                No active instance
              </p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Components ({deployment.components.length})</CardTitle>
          </CardHeader>
          <CardContent>
            {deployment.components.length === 0 ? (
              <p className="text-sm text-muted-foreground">No components</p>
            ) : (
              <div className="space-y-2">
                {deployment.components.map((component) => (
                  <div
                    key={component.id}
                    className="flex items-center justify-between py-2"
                  >
                    <span className="text-sm font-medium">
                      {component.name}
                    </span>
                    <Badge
                      variant={component.enabled ? "success" : "secondary"}
                    >
                      {component.enabled ? "Enabled" : "Disabled"}
                    </Badge>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {deployment.config && Object.keys(deployment.config).length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle>Configuration</CardTitle>
            </CardHeader>
            <CardContent>
              <pre className="text-xs bg-muted p-4 rounded-md overflow-auto max-h-64">
                {JSON.stringify(deployment.config, null, 2)}
              </pre>
            </CardContent>
          </Card>
        )}

        {deployment.parameters &&
          Object.keys(deployment.parameters).length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Parameters</CardTitle>
              </CardHeader>
              <CardContent>
                <pre className="text-xs bg-muted p-4 rounded-md overflow-auto max-h-64">
                  {JSON.stringify(deployment.parameters, null, 2)}
                </pre>
              </CardContent>
            </Card>
          )}

        {deployment.applicationInstance && (
          <Card>
            <CardHeader>
              <CardTitle>Backups</CardTitle>
            </CardHeader>
            <CardContent>
              {backupsFetching && !backupsData ? (
                <p className="text-sm text-muted-foreground">
                  Loading backups…
                </p>
              ) : !backupsData?.backups || backupsData.backups.length === 0 ? (
                <p className="text-sm text-muted-foreground">No backups yet</p>
              ) : (
                <div className="space-y-3">
                  {backupsData.backups.map((backup) => (
                    <BackupRow
                      key={backup.id}
                      backup={backup}
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
                      autoRefreshEnabled={autoRefresh.enabled}
                    />
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        )}
      </div>

      {/* Restore confirmation dialog */}
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
              disabled={!selectedBackupId || restoreResult.fetching}
            >
              {restoreResult.fetching ? "Restoring…" : "Restore"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete confirmation dialog */}
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
              disabled={!newVersion.trim() || upgradeResult.fetching}
            >
              {upgradeResult.fetching ? "Upgrading…" : "Upgrade"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PageLayout>
  );
}

// ---------------------------------------------------------------------------
// BackupRow — each backup manages its own restore list query + actions menu
// ---------------------------------------------------------------------------

type RestoreItem = ListRestoresQuery["restores"][number];

function BackupRow({
  backup,
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
  onRestore: (backupId: string) => void;
  onDelete: (backupId: string) => void;
  autoRefreshEnabled: boolean;
}) {
  const [{ data: restoresData }, reexecuteRestores] = useListRestoresQuery({
    variables: { backupId: backup.id },
    pause: backup.status !== "completed",
  });

  // Auto-refresh restores when enabled
  useAutoRefresh({
    onRefresh: () => reexecuteRestores({ requestPolicy: "network-only" }),
    enabled:
      autoRefreshEnabled &&
      backup.status === "completed" &&
      (restoresData?.restores?.some(
        (r) => r.status === "pending" || r.status === "in_progress",
      ) ??
        false),
  });

  const restores = restoresData?.restores ?? [];
  const hasActiveRestore = restores.some(
    (r) => r.status === "pending" || r.status === "in_progress",
  );
  const isRestoreDisabled = backup.status !== "completed" || hasActiveRestore;

  return (
    <div className="py-2 border-b last:border-b-0">
      <div className="flex items-center justify-between">
        <div className="space-y-1">
          <span className="text-sm font-medium">{backup.name}</span>
          <div className="text-xs text-muted-foreground">
            {new Date(backup.createdOn).toLocaleString()}
            {backup.sizeBytes != null && (
              <span className="ml-2">{formatBytes(backup.sizeBytes)}</span>
            )}
          </div>
          {backup.errorMessage && (
            <p className="text-xs text-destructive">{backup.errorMessage}</p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="sm" className="h-8 w-8 p-0">
                <EllipsisVertical className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem
                disabled={isRestoreDisabled}
                onClick={() => onRestore(backup.id)}
              >
                <RotateCcw className="h-4 w-4" />
                Restore
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                className="text-destructive focus:text-destructive"
                onClick={() => onDelete(backup.id)}
              >
                <Trash2 className="h-4 w-4" />
                Delete
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <StatusBadge status={backup.status} />
        </div>
      </div>

      {/* Restore history */}
      {restores.length > 0 && (
        <div className="mt-3 ml-4">
          <p className="text-xs font-medium text-muted-foreground mb-2">
            <RotateCcw className="h-3 w-3 inline mr-1" />
            Restores ({restores.length})
          </p>
          <div className="space-y-2">
            {restores.map((restore) => (
              <RestoreRow key={restore.id} restore={restore} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// RestoreRow — a single restore with expandable component statuses
// ---------------------------------------------------------------------------

function RestoreRow({ restore }: { restore: RestoreItem }) {
  const components = restore.componentStatuses ?? [];

  return (
    <div className="rounded-md border-l-2 border-l-blue-400 border border-l-2 bg-muted/20 p-2 pl-3">
      <div className="flex items-center justify-between">
        <div className="space-y-0.5">
          <span className="text-xs font-medium">{restore.name}</span>
          <div className="text-xs text-muted-foreground">
            {new Date(restore.createdOn).toLocaleString()}
            {restore.completedAt && (
              <span>
                {" → "}
                {new Date(restore.completedAt).toLocaleString()}
              </span>
            )}
          </div>
          <div className="text-xs text-muted-foreground font-mono">
            {restore.targetNamespace}
          </div>
          {restore.errorMessage && (
            <p className="text-xs text-destructive mt-1">
              {restore.errorMessage}
            </p>
          )}
        </div>
        <StatusBadge status={restore.status} />
      </div>

      {/* Component-level statuses */}
      {components.length > 0 && (
        <Collapsible className="mt-2">
          <CollapsibleTrigger className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors group">
            <ChevronRight className="h-3 w-3 transition-transform group-data-[state=open]:rotate-90" />
            Components ({components.length})
          </CollapsibleTrigger>
          <CollapsibleContent className="mt-1 ml-4 space-y-1">
            {components.map((comp) => (
              <div
                key={comp.componentName}
                className="flex items-center justify-between py-1"
              >
                <span className="text-xs font-medium">
                  {comp.componentName}
                </span>
                <div className="flex items-center gap-2">
                  {comp.errorMessage && (
                    <span className="text-xs text-destructive max-w-48 truncate">
                      {comp.errorMessage}
                    </span>
                  )}
                  <StatusBadge status={comp.status} />
                </div>
              </div>
            ))}
          </CollapsibleContent>
        </Collapsible>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Utility components
// ---------------------------------------------------------------------------

function DetailRow({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-sm text-muted-foreground w-40">{label}</span>
      <span className={`text-sm ${mono ? "font-mono" : ""}`}>{value}</span>
    </div>
  );
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}
