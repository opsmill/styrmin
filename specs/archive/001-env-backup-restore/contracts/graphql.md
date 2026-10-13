# GraphQL Contract: Environment-Level Backup and Restore

**Feature**: `specs/001-env-backup-restore` | **Date**: 2026-08-06

New surface under `backend/styrmin_backend/api/schema/`. Every field, argument, and mutation below requires a propagation test (`dev/guides/graphql-propagation-tests.md`). After implementing: `uv run styrmin export graphql-schema schema.graphql` then `uv run invoke generate`.

## Types

```graphql
"""A coordinated snapshot of an environment: captured config, per-deployment
declared state, and one constituent backup per eligible application instance."""
type EnvironmentBackup {
  id: UUID!
  name: String!
  createdOn: DateTime!
  """Derived from constituents — never stored (PENDING, IN_PROGRESS, COMPLETED, PARTIAL, FAILED)."""
  status: EnvironmentBackupStatus!
  environment: Environment!
  """Environment config captured at backup time."""
  environmentConfig: JSON
  """Per-deployment declared state captured at backup time (clone readiness)."""
  deploymentSnapshots: [DeploymentSnapshot!]!
  """One entry per eligible deployment: the constituent backup or the creation error."""
  constituents: [EnvironmentBackupConstituent!]!
  restores: [EnvironmentRestore!]!
}

enum EnvironmentBackupStatus { PENDING IN_PROGRESS COMPLETED PARTIAL FAILED }

type DeploymentSnapshot {
  deploymentId: UUID!
  deploymentName: String!
  instanceId: UUID!
  driverName: String!
  driverVersion: String!
  driverFingerprint: String
  applicationVersion: String!
  config: JSON
  parameters: JSON
}

"""Union-shaped per-constituent outcome: exactly one of backup / error is set."""
type EnvironmentBackupConstituent {
  deploymentId: UUID!
  deploymentName: String!
  backup: Backup          # null when creation failed
  error: String           # null when a backup row exists
}

type EnvironmentRestore {
  id: UUID!
  createdOn: DateTime!
  """Derived from constituent restores + skips — never stored."""
  status: EnvironmentRestoreStatus!
  environmentBackup: EnvironmentBackup!
  """Constituent restores dispatched by this operation."""
  restores: [Restore!]!
  """Constituents not restored, each with deployment name and reason (zero silent skips)."""
  skippedConstituents: [SkippedConstituent!]!
}

enum EnvironmentRestoreStatus { PENDING IN_PROGRESS COMPLETED PARTIAL FAILED }

type SkippedConstituent {
  deploymentId: UUID!
  deploymentName: String!
  reason: String!
}
```

## Mutations

| Mutation | Args | Returns | Role | Errors (`extensions.code`) |
|---|---|---|---|---|
| `createEnvironmentBackup` | `environmentId: UUID!`, `name: String` | `EnvironmentBackup` | `READ_WRITE` | `NOT_FOUND` (environment), `ALREADY_IN_PROGRESS` (env-level op in flight) |
| `restoreEnvironmentBackup` | `environmentBackupId: UUID!` | `EnvironmentRestore` | `ADMIN` (reverts environment config — parity with `updateEnvironment`) | `NOT_FOUND`, `ALREADY_IN_PROGRESS`, `OPERATION_DENIED` (not restorable: derived status not in {COMPLETED, PARTIAL}) |
| `deleteEnvironmentBackup` | `environmentBackupId: UUID!` | `Boolean` | `READ_WRITE` | `NOT_FOUND` |

Behavioral notes:
- `createEnvironmentBackup` returns synchronously after all constituent backups are created + dispatched (fire-and-forget flows); the returned object's `status` is typically `PENDING`/`IN_PROGRESS`. Empty environment → zero constituents, `status: COMPLETED` immediately.
- A per-instance conflict during fan-out becomes a `constituents[].error` entry — it never fails the mutation.
- `restoreEnvironmentBackup` classifies skips at creation time; `skippedConstituents` is complete in the mutation response. Skip reasons include "deployment busy with another restore" when a constituent's deployment is already mid-restore.
- `deleteEnvironmentBackup` cascade-deletes constituent backups (and their restores) and the parent's `EnvironmentRestore` records. It succeeds **regardless of derived status** — deleting an in-progress environment backup is the documented escape hatch (spec FR-010).
- `deleteEnvironment` (existing mutation) cascades through the environment's environment backups first (spec FR-015).

## Queries

| Query | Args | Returns | Role |
|---|---|---|---|
| `environmentBackup` | `environmentBackupId: UUID!` | `EnvironmentBackup` | `READ_ONLY` |
| `environmentBackups` | `environmentId: UUID!` | `[EnvironmentBackup!]!` (newest first) | `READ_ONLY` |
| `environmentRestore` | `environmentRestoreId: UUID!` | `EnvironmentRestore` | `READ_ONLY` |
| `environmentRestores` | `environmentBackupId: UUID!` | `[EnvironmentRestore!]!` (newest first) | `READ_ONLY` |

## Client operation files

SDK (`python_sdk/src/styrmin_sdk/graphql/`): `create_environment_backup.graphql`, `get_environment_backup.graphql`, `list_environment_backups.graphql`, `delete_environment_backup.graphql`, `restore_environment_backup.graphql`, `get_environment_restore.graphql`, `list_environment_restores.graphql`.

Frontend (`frontend/src/graphql/`): `create_environment_backup.graphql`, `list_environment_backups.graphql`, `restore_environment_backup.graphql`, `delete_environment_backup.graphql`, `list_environment_restores.graphql`.

One named operation per file; validate with `uv run invoke validate-graphql`.

## SDK facade (`client.environment_backups.*`, ADR-0037 shape)

`create(environment_id, name=None)`, `get(environment_backup_id)`, `list(environment_id)`, `delete(environment_backup_id)`, `restore(environment_backup_id)`, `get_restore(environment_restore_id)`, `list_restores(environment_backup_id)`, `wait_for_backup(environment_backup_id, max_wait=600, interval=5)`, `wait_for_restore(environment_restore_id, max_wait=900, interval=5)` — polling until derived status is terminal (`COMPLETED`, `PARTIAL`, `FAILED`).

## CLI (`styrminctl env-backups …`)

| Command | Key options |
|---|---|
| `create <environment> [--cluster …] [--id …] [--name …] [--wait --max-wait --interval]` | Dual-identifier environment resolution (ADR-0031) |
| `list <environment> …` | Table: name, status, constituents (ok/failed/total), created |
| `get <environment-backup-id>` | Key/value detail incl. per-constituent outcomes |
| `delete <environment-backup-id>` | |
| `restore <environment-backup-id> [--wait …]` | Prints skipped constituents with reasons |
| `restore-get <environment-restore-id>` / `restore-list <environment-backup-id>` | |
