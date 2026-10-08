# Contract: Backups tab on the deployment page

**Feature**: [../spec.md](../spec.md) | **Requirements**: FR-002, FR-005, FR-006

File: `frontend/src/pages/deployments/DeploymentDetailPage.tsx`.

## Data source

- Before: `useListBackupsQuery({ instanceId: deployment.applicationInstance.id }, { enabled: !!instanceId, ... })`.
- After: `useListBackupsQuery({ deploymentId }, { refetchInterval: ... })`, where `deploymentId` comes from the route parameters. The query no longer waits for an active instance, so a deployment with no active instance, or a deleted deployment, still lists its history.
- The 10-second auto-refresh and the `["ListBackups"]` query-key invalidations from the environment backup components keep working unchanged.

## Table

A **Version** column is added after **Status**. Each row shows `backup.instance.applicationVersion`.

```text
Name | Status | Version | Created | Size | Expires | Actions
```

## Row attributes (E2E hooks)

Each `[data-testid=backup-row]` keeps `data-backup-id`, `data-backup-name` and `data-backup-status`, and gains:

```text
data-backup-application-version="<applicationVersion>"
```

## Unchanged

- "Create Backup" still backs up the active instance and stays disabled when there is none.
- Restore and delete actions, their dialogs and their disabled states (restoring, deleting, deleted) do not change.
- An in-place restore from a row of an earlier instance goes through the same `createRestore(backupId, targetNamespace)` call. The backend resolves the deployment from the backup's instance.
