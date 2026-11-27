# Implementation Plan: Rename Backups and Add a Description

**Branch**: `034-backup-rename-description` | **Date**: 2026-11-27 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/034-backup-rename-description/spec.md` ([issue #39](https://github.com/opsmill/styrmin/issues/39))

## Summary

Operators can name and describe a backup when they create it, and can rename it and edit its description later, from the web UI, the GraphQL API, the SDK and the CLI. The name becomes a label that only Styrmin shows, unique per application instance.

To make a rename safe, the plan does three things (see research R1–R3):

- Every new Velero `Backup` object is named after the backup's id (`styrmin-<id>`) and carries the label `styrmin.io/backup-id`.
- One function, `velero_backup_name(backup)`, gives the backup and restore flows the name of the Velero object. For a row that an earlier version created with a custom name, it returns that custom name, which a one-time migration stores in `metadata_`.
- The global unique constraint on `backup.name` becomes a unique index on `(instance_id, name)`.

The name template for scheduled backups is deferred, because no code creates backups from schedules today (research R10).

## Technical Context

**Language/Version**: Python 3.14+ (backend, SDK, CLI); TypeScript 5.9.3 and React 19 (frontend)

**Primary Dependencies**: Strawberry GraphQL, SQLModel and SQLAlchemy (async), Alembic, Prefect (existing flows only), Cyclopts, ariadne-codegen; frontend: TanStack Query v5, `@tanstack/react-form`, Radix UI and Tailwind. No new dependencies.

**Storage**: PostgreSQL. One Alembic revision: the new column `backup.description`, a data backfill of `metadata.velero_backup_name` for old rows with a custom name, and the global unique constraint on `name` replaced by the unique index `(instance_id, name)`.

**Testing**: pytest (unit, functional GraphQL propagation, migration), Vitest and React Testing Library, and the E2E test `test_backup_and_restore_lifecycle` (vCluster, both variants)

**Target Platform**: Linux server and Kubernetes (Velero)

**Project Type**: Web service, SPA, SDK and CLI

**Performance Goals**: No change. The uniqueness check is one indexed lookup per write.

**Constraints**:

- ADR-073: the name of a Velero object never depends on a field that a user can change.
- Backups that exist before the upgrade must stay restorable.

**Scale/Scope**: One table and one mutation, on four surfaces (web UI, GraphQL API, SDK, CLI).

## Constitution Check

| Principle | Status | How the plan meets it |
|-----------|--------|-----------------------|
| I. Declarative reconciliation | Pass | Not affected. A rename touches no cluster state (FR-007). |
| II. Driver-based deployment | Pass | Not affected. |
| III. Layered architecture | Pass | Path: `updateBackup` mutation → `services/backup/service.update_backup` → `BackupRepository.get_by_instance_and_name` → database. The flows call `velero_backup_name` from the service package. |
| IV. Typed errors | Pass | New `BackupNameAlreadyExistsError` (`ALREADY_EXISTS`, with `existing_backup_id`). The existing `ValidationError` and `BackupNotFoundError` are reused. No union return types. |
| V. Test-first, E2E, propagation | Pass | Extends the existing E2E `test_backup_and_restore_lifecycle` (reuses its stack). Adds a propagation test for `updateBackup`, for `createBackup(description)` and for `Backup.description`. Adds a migration test and unit tests for the service, the flows and `velero_backup_name`. |
| VI. Format and lint | Pass | `uv run invoke format lint`, and the frontend lint. |
| VII. Documentation | Pass | Updates `docs/docs/concepts-and-architecture/backups-and-restores.md`. Adds a `backups` section to `docs/docs/reference/styrminctl.md` covering `create --description` and `update`. Adds a **Backup** entry to `CONTEXT.md` (name per instance, description, Velero object named after the id). Adds a changelog fragment. |
| Governance gates (database and GraphQL schema) | Acknowledged | Issue #39 asks for both changes in its acceptance criteria (research R11). |

No violations, so the Complexity Tracking table is empty.

## Project Structure

### Documentation (this feature)

```text
specs/034-backup-rename-description/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── graphql.md
│   └── cli-sdk.md
└── tasks.md            # produced by /speckit-tasks
```

### Source code (files this feature touches)

```text
backend/styrmin_backend/
├── db/models.py                                   # Backup.description, name unique per instance (__table_args__)
├── db/migrations/versions/<rev>_backup_description_and_instance_scoped_name.py
├── repository/backup.py                           # get_by_instance_and_name
├── services/exceptions.py                         # BackupNameAlreadyExistsError
├── services/backup/metadata.py                    # BackupMetadata.velero_backup_name + velero_backup_name()
├── services/backup/service.py                     # create_backup(description), update_backup(), name validation; fix comment at :174
├── services/backup/environment.py                 # fix comment at :494 (name no longer globally unique)
├── workflows/templates/backup.py                  # :565 and :971 use velero_backup_name()
├── agent/service/kubernetes/resources/builders/backup.py  # styrmin.io/backup-id label
├── api/definitions/backup/backup.py               # Backup.description
└── api/schema/mutation.py                         # createBackup(description), updateBackup

backend/tests/
├── unit/db/test_backup_rename_migration.py        # new
├── unit/services/backup/test_backup_service.py    # create/update, validation, uniqueness
├── unit/services/backup/test_backup_metadata.py   # velero_backup_name both branches (or existing metadata test file)
├── unit/workflows/…                               # flows pass velero_backup_name(); fixture names updated
├── functional/graphql/test_backup_update_propagation.py  # new
├── functional/graphql/operations/update_backup.graphql   # new
└── e2e/
    ├── test_backup_restore.py                     # extend test_backup_and_restore_lifecycle; Velero helper args → styrmin-<id>
    ├── drivers/{protocol,api_driver,ui_driver}.py # create_backup(name, description), update_backup()
    └── pages/deployment_detail.py                 # create dialog + Edit action

python_sdk/src/styrmin_sdk/
├── resources/backups.py                           # create_backup(description), update_backup
└── graphql/{update_backup,create_backup,get_backup,list_backups}.graphql

cli/src/styrminctl/commands/backups.py             # create --description, update command, show description

frontend/src/
├── graphql/{update_backup,create_backup,list_backups}.graphql
├── pages/deployments/BackupDetailsDialog.tsx      # new (create + edit)
├── pages/deployments/DeploymentDetailPage.tsx     # Create button opens dialog; BackupRow shows description + Edit
└── __tests__/deployment-detail/BackupDetailsDialog.test.tsx   # new

schema.graphql, python_sdk/…/_generated/, frontend/src/generated/graphql.ts   # regenerated
docs/docs/concepts-and-architecture/backups-and-restores.md
docs/docs/reference/styrminctl.md
CONTEXT.md
changelog/39.added.md
```

**Structure Decision**: The existing web application layout (backend, frontend, python_sdk and cli). No new packages or modules. The only new component is the frontend dialog.

## Phase overview

1. **Foundation** (all stories depend on it): model, migration, `velero_backup_name`, Velero label, and the flows switched to the id-based name. This is the step that makes renaming safe (User Story 3).
2. **Service and API**: name validation, the uniqueness check, `create_backup(description)`, `update_backup`, the error class, the GraphQL type and mutations, the schema and code regeneration, and the propagation tests (User Stories 1 and 2).
3. **SDK and CLI**.
4. **Frontend**: the dialog, the row description and the Edit action.
5. **E2E**: driver methods, page object, the extended lifecycle test, and a local pass in both variants.
6. **Documentation**: `docs/`, `CONTEXT.md` and the changelog fragment.

## Risks

- **The E2E test reads the Velero name from `backup.name` today.** Update every call site listed in research R9 in the same change, or the backup E2E tests fail.
- **The constraint name on SQLite.** Test fixtures build the schema with `create_all()`, so the migration test has to drop the unnamed constraint with `batch_alter_table` and a naming convention, as `c9d0e1f2a3b4` does.
- **Downgrade.** The older code uses `backup.name` as the Velero name. After a downgrade, backups that were created after the upgrade with a custom name, or renamed after it, cannot be restored, because their Velero object is `styrmin-<id>`. The downgrade cannot repair this. The migration's docstring and its downgrade function state this limit.
- **Two writes of the same name at the same moment.** The second write fails on the unique index and returns `INTERNAL_ERROR` instead of `ALREADY_EXISTS`. No data is damaged. Upgrade path: catch `IntegrityError` at commit (critique E3).
- **A backup that is running during the upgrade.** The migration backfills its `velero_backup_name` before the flow next reads the row. The backup flow reads the name once, when it starts, so a backup that started before the upgrade keeps the name it already used.

## Complexity Tracking

None.
