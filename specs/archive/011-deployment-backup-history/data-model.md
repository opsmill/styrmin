# Data Model: Keep a Deployment's Backup History When It Gets a New Instance

**Feature**: [spec.md](spec.md) | **Research**: [research.md](research.md)

No table, column, index or constraint changes. No Alembic revision. This file describes the existing records the history is read from, and the new read path.

## Existing records

```text
Deployment (deployment)
  id: UUID  (stable across every operation; ADR-008 keeps it after deletion)
  active_application_instance_id: UUID | None  → applicationinstance.id
        │
        │ 1 ── * (ApplicationInstance.deployment_id, non-null)
        ▼
ApplicationInstance (applicationinstance)
  id: UUID  (new value on each upgrade, config edit, refresh,
             and environment config change)
  deployment_id: UUID  → deployment.id
  application_version: str
        │
        │ 1 ── * (Backup.instance_id, non-null)
        ▼
Backup (backup)
  id: UUID
  instance_id: UUID  → applicationinstance.id
  status: BackupStatus (pending | in_progress | completed | failed)
  created_on: datetime
  environment_backup_id: UUID | None  (constituent of an environment backup)
```

No code path deletes an `ApplicationInstance` row (research R1), so a backup always reaches its deployment through its instance.

## Backup history (derived, not stored)

**Definition**: the backup history of deployment `D` is every `Backup` whose instance has `deployment_id = D`, ordered by `created_on` descending, optionally filtered by `status`.

**Read path** (new repository method `BackupRepository.get_by_deployment_id(deployment_id, status=None)`):

```text
SELECT backup.*
FROM backup
JOIN applicationinstance ON backup.instance_id = applicationinstance.id
WHERE applicationinstance.deployment_id = :deployment_id
  [AND backup.status = :status]
ORDER BY backup.created_on DESC
```

**Rules**:

| Rule | Source |
|------|--------|
| Includes backups of every instance the deployment ever had | FR-001 |
| Includes constituent backups of environment backups | spec edge cases |
| Excludes backups of instances of any other deployment, including a counterpart deployment created by an environment clone and a new deployment that reuses a deleted deployment's name | FR-007 |
| Stays readable after the deployment is deleted | FR-006, ADR-008 |
| An id that matches no deployment gives an empty history, not an error | research R4 |
| The application version shown for a backup is `applicationinstance.application_version` of its instance | FR-002 |

## Read-only projections added to client operations

These add fields to what clients select. They do not change the GraphQL `Backup` type.

| Client operation | Added selection | Consumer |
|------------------|-----------------|----------|
| SDK `ListBackups` (`python_sdk/src/styrmin_sdk/graphql/list_backups.graphql`) | `instance { id applicationVersion }` | `styrminctl backups list` version column; SDK users |
| Frontend `ListBackups` (`frontend/src/graphql/list_backups.graphql`) | `instance { id applicationVersion }` | Backups tab version column |

## Validation rule on the list call

| Arguments passed | Result |
|------------------|--------|
| `deploymentId` only | the deployment's backup history |
| `instanceId` only | that instance's backups, unchanged from today |
| both | `AmbiguousIdentifierError` → `VALIDATION_ERROR` |
| neither | `AmbiguousIdentifierError` → `VALIDATION_ERROR` |

`status` applies to either argument.
