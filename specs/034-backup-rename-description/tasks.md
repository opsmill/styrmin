---
description: "Task list for 034-backup-rename-description"
---

# Tasks: Rename Backups and Add a Description

**Input**: Design documents from `specs/034-backup-rename-description/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)

**Tests**: Required by the constitution (§V). The work needs:

- unit tests for the service, the repository, the migration and the flows;
- GraphQL propagation tests for every schema change;
- the extended E2E test `test_backup_and_restore_lifecycle`, run until it passes in both variants with local evidence recorded.

**Organization**: Phase 2 (Foundational) moves the Velero object name off `backup.name`. Every story depends on it, because no rename is safe until this change is in place.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1 = rename and describe (P1), US2 = name and describe at creation (P2), US3 = old custom-named backups keep working (P1)

---

## Phase 1: Setup

- [ ] T001 Confirm the current Alembic head. The repository has no `alembic.ini`, so run `uv run python -c 'from alembic import command; from styrmin_backend.cli.db import _get_alembic_config; command.heads(_get_alembic_config())'`, as described in `dev/guides/database-migrations.md` ("Multi-head resolution"). Expected: `859c9d31dc11`. Use the head you find as `down_revision` in T003.

---

## Phase 2: Foundational (blocks every story)

**Purpose**: Add the description column, make names unique per instance, and name every new Velero `Backup` object after the backup's id (research R1–R4).

- [ ] T002 In `backend/styrmin_backend/db/models.py`, class `Backup`:
  - change `name: str = Field(unique=True)` to `name: str`;
  - add `description: str | None = Field(default=None, sa_type=Text)`;
  - add `__table_args__ = (Index("ix_backup_instance_id_name", "instance_id", "name", unique=True),)`.

  Constraints, quoted from data-model.md: the name is "unique per `instance_id`"; the description is "`str | None`, text, nullable".
- [ ] T003 Create the Alembic revision `backend/styrmin_backend/db/migrations/versions/<rev>_backup_description_and_instance_scoped_name.py`, with `down_revision` set to the head from T001. Copy the structure of `c9d0e1f2a3b4_deployment_name_scoped_uniqueness.py`. Upgrade steps:
  1. add the column `backup.description` (`sa.Text`, nullable);
  2. backfill: in a Python loop over `SELECT id, name, metadata FROM backup`, for each row where `name != f"styrmin-{id}"`, set `metadata["velero_backup_name"] = name`, and log the number of rows updated;
  3. drop the unique constraint on `backup.name`, found by `sa.inspect(bind).get_unique_constraints("backup")`. It is `backup_name_key` on PostgreSQL. On SQLite, use `batch_alter_table` with a naming convention;
  4. create the unique index `ix_backup_instance_id_name` on `(instance_id, name)`.

  Downgrade steps:
  1. drop the index;
  2. refuse with a clear error if any two rows share a name;
  3. re-create `UNIQUE (name)`;
  4. remove the `velero_backup_name` key;
  5. drop the column.

  The docstring must state the downgrade limit from the plan's Risks section: backups created or renamed after the upgrade with a custom name cannot be restored by the older code.
- [ ] T004 [P] Write the migration test `backend/tests/unit/db/test_backup_rename_migration.py`, modelled on `test_backup_history_index_migration.py`. Test cases:
  - a row with a custom name gets `metadata.velero_backup_name`;
  - a row with the default name `styrmin-<id>` does not;
  - two backups of one instance cannot share a name;
  - two backups of different instances can;
  - the downgrade restores global uniqueness and refuses when names are duplicated.
- [ ] T005 [P] In `backend/styrmin_backend/services/backup/metadata.py`:
  - add the key `velero_backup_name: str` to `BackupMetadata`, documented as "written only by migration <rev> for rows created with a custom name before #39; never written by a request";
  - add `def velero_backup_name(backup: Backup) -> str`, which returns `read_backup_metadata(backup.metadata_).get("velero_backup_name") or f"styrmin-{backup.id}"`.

  Add unit tests for both branches in `backend/tests/unit/services/backup/test_backup_metadata.py` (create the file, or extend the existing metadata test module).
- [ ] T006 [P] In `backend/styrmin_backend/agent/service/kubernetes/resources/builders/backup.py`, give `build_velero_backup` a `backup_id: str` argument and add the label `"styrmin.io/backup-id": backup_id`. Update the builder's unit tests to check the label.
- [ ] T007 In `backend/styrmin_backend/workflows/templates/backup.py`:
  - replace `velero_backup_name = backup.name` at about line 565 (backup flow) and at about line 971 (restore flow) with `velero_backup_name(backup)`;
  - pass `backup_id=str(backup.id)` to `build_velero_backup`;
  - update the comment at about line 968.

  In the same task, update every unit test that uses a backup name as the Velero name (critique E6):
  - `backend/tests/unit/workflows/test_velero_backup_flow.py`;
  - `test_restore_steps.py`;
  - `test_backup_component_steps.py`;
  - `test_backup_workflow_ttl.py`;
  - `test_restore_workflow_failure_handler.py`.

  Add a test in which `backup.name` differs from `styrmin-<id>`: the backup flow must build a Velero `Backup` named `styrmin-<id>`, and the restore flow must pass `backupName=styrmin-<id>` (critique E1).
- [ ] T008 In `backend/tests/e2e/test_backup_restore.py`, change the Velero helper calls that pass `backup.name` to pass `f"styrmin-{backup.id}"`, at about lines 982, 987, 1005, 2002 and 2040. Line 2040 asserts that the step error contains the Velero name. Do this in the same commit as T007, so the E2E tests never fail between tasks.
- [ ] T009 [P] Update the comments that say `Backup.name` is unique across all backups:
  - `backend/styrmin_backend/services/backup/service.py` at about lines 174–177;
  - `backend/styrmin_backend/services/backup/environment.py` at about line 494.

  The id is still generated before the write, so the default name `styrmin-<id>` is final at insert time.
- [ ] T010 Run `uv run invoke format lint` and `uv run pytest backend/tests/unit -k "backup or restore or migration" -q`. All must pass.

**Checkpoint**: New Velero objects are named after the id. Old custom-named rows keep their Velero name. Names are unique per instance.

---

## Phase 3: User Story 1 - Rename a backup and edit its description (P1) 🎯 MVP

**Goal**: Operators can change a backup's name and description from every surface (FR-003, FR-004, FR-006, FR-007, FR-010, FR-011, FR-012).

**Independent Test**: Rename a backup and set its description through the UI, the API, the SDK and the CLI. The new values are returned and a restore still succeeds.

### Service, repository and errors

- [ ] T011 [P] [US1] In `backend/styrmin_backend/services/exceptions.py`, add `BackupNameAlreadyExistsError(ServiceError)` with `error_code = "ALREADY_EXISTS"`, the default message "A backup with that name already exists for this instance", `__init__(self, existing_backup_id: str, message: str = "")`, and `error_metadata` that returns `{"existing_backup_id": ...}`. Copy the shape of `BackupScheduleAlreadyExistsError`.
- [ ] T012 [P] [US1] In `backend/styrmin_backend/repository/backup.py`, add `get_by_instance_and_name(instance_id: UUID, name: str) -> Backup | None` to the abstract `BackupRepository` and to `SQLModelBackupRepository`. Test it in `backend/tests/unit/repository/backup/test_backup_repository.py`.
- [ ] T013 [US1] In `backend/styrmin_backend/services/backup/service.py`, add two private helpers:
  - `_clean_backup_name(name: str) -> str`: strip whitespace, then raise `ValidationError` unless "1 to 255 characters after leading and trailing whitespace is removed";
  - `_clean_backup_description(description: str) -> str | None`: raise `ValidationError` if the description is longer than "at most 2,000 characters"; return `None` for empty or whitespace-only input.

  Add `async def update_backup(backup_id: UUID, uow: UnitOfWork, name: str | None = None, description: str | None = None) -> Backup`. It must:
  - raise `BackupNotFoundError` when the backup does not exist;
  - apply only the arguments that are not `None`;
  - when the new name differs from the current one, call `get_by_instance_and_name` and raise `BackupNameAlreadyExistsError` if another backup of the instance has the name;
  - commit, refresh, log, and never touch Kubernetes (FR-007);
  - allow every status (FR-010).
- [ ] T014 [US1] Add unit tests in `backend/tests/unit/services/backup/test_backup_service.py` for `update_backup`:
  - renames;
  - description set, then cleared with `""`;
  - only one field sent;
  - same name again does nothing;
  - empty or whitespace name → `ValidationError`;
  - 256-character name → `ValidationError`;
  - 2,001-character description → `ValidationError`;
  - duplicate name in the same instance → `BackupNameAlreadyExistsError` with `existing_backup_id`;
  - same name in a different instance is allowed;
  - an in-progress backup can be renamed;
  - unknown id → `BackupNotFoundError`.

### GraphQL

- [ ] T015 [US1] In `backend/styrmin_backend/api/definitions/backup/backup.py`, add `description: str | None = None` to the strawberry `Backup` type, with the docstring from contracts/graphql.md, and set it in `from_instance`.
- [ ] T016 [US1] In `backend/styrmin_backend/api/schema/mutation.py`, add the `update_backup(self, backup_id: UUID, info: strawberry.Info, name: str | None = None, description: str | None = None) -> BackupType | None` mutation with `@strawberry.mutation(extensions=[_requires(Role.READ_WRITE)])` and the docstring from contracts/graphql.md. It calls `update_backup` from the service, imported under an alias next to `create_backup as create_backup_service`.
- [ ] T017 [US1] Regenerate the schema with `uv run styrmin export graphql-schema schema.graphql`. Check that the `schema.graphql` diff contains only the changes in contracts/graphql.md.
- [ ] T018 [US1] Add the propagation test `backend/tests/functional/graphql/test_backup_update_propagation.py` with the operation file `backend/tests/functional/graphql/operations/update_backup.graphql` (`mutation UpdateBackup`), following `dev/guides/graphql-propagation-tests.md` and `test_backup_schedule.py`. The test must:
  - call `updateBackup` and read the row back from the database to assert `name` and `description`;
  - query a seeded `Backup.description` and assert it is returned;
  - assert `extensions.code` for `ALREADY_EXISTS`, `VALIDATION_ERROR` and `NOT_FOUND`;
  - assert that the read-only role is rejected.

### SDK and CLI

- [ ] T019 [P] [US1] Add `python_sdk/src/styrmin_sdk/graphql/update_backup.graphql` (`mutation UpdateBackup($backupId: UUID!, $name: String, $description: String)`, selecting the same fields as `create_backup.graphql` plus `description`). Add `description` to `get_backup.graphql` and `list_backups.graphql`. Run `uv run invoke validate-graphql` and `uv run invoke generate`.
- [ ] T020 [US1] In `python_sdk/src/styrmin_sdk/resources/backups.py`, add `update_backup(self, backup_id: UUID | str, name: str | None = None, description: str | None = None)`. It sends only the arguments that are set, so `description=""` is sent. Follow `resources/schedules.py`. Test it in `python_sdk/tests/test_backups.py`.
- [ ] T021 [US1] In `cli/src/styrminctl/commands/backups.py`:
  - add the command `update <backup-id> [--name NAME] [--description TEXT]`, which exits with a usage error when neither option is given;
  - show the description in `get`, and as a Description column, cut short to fit, in `list`.

  Test both in `cli/tests/test_backups.py`.

### Frontend

- [ ] T022 [P] [US1] Add `frontend/src/graphql/update_backup.graphql` (`mutation UpdateBackup`) and add `description` to `frontend/src/graphql/list_backups.graphql`. Run `cd frontend && pnpm codegen`.
- [ ] T023 [US1] Create `frontend/src/pages/deployments/BackupDetailsDialog.tsx`: a dialog with optional Name and Description fields, built with `@tanstack/react-form` in the same way as `frontend/src/pages/clusters/EditClusterDialog.tsx`. The dialog has a `mode: "create" | "edit"` prop and initial values. Client-side validation mirrors the server rules: name at most 255 characters, and not whitespace-only when non-empty in edit mode; description at most 2,000 characters. Server errors are shown in the dialog. In create mode the submit button has focus, so Enter submits the empty form (critique P4).
- [ ] T024 [US1] In `frontend/src/pages/deployments/DeploymentDetailPage.tsx`, change `BackupRow` (about line 1126):
  - show `description` under the name, in muted text, limited to two lines (`line-clamp-2`), with the full text in `title`, rendered as text only (critique P5, E4);
  - add an **Edit** action next to Restore and Delete that opens `BackupDetailsDialog` in edit mode and calls the `updateBackup` mutation;
  - invalidate the backups query on success;
  - keep the existing `data-testid="backup-row"`, `data-backup-id` and `data-backup-name` attributes;
  - add `data-testid="backup-edit"` to the action and `data-backup-description` to the row.
- [ ] T025 [US1] Add `frontend/src/__tests__/deployment-detail/BackupDetailsDialog.test.tsx`. Test cases:
  - edit mode pre-fills the values and submits only the changed fields;
  - a whitespace-only name is rejected;
  - a server `ALREADY_EXISTS` error is shown;
  - the row shows the description.

### E2E (dual-entrypoint)

- [ ] T026 [US1] Add `update_backup(self, *, backup_id: str, name: str | None = None, description: str | None = None) -> BackupRef` to the scenario driver protocol `backend/tests/e2e/drivers/protocol.py`, and add `description: str | None` to `BackupRef`.
  - API driver (`backend/tests/e2e/drivers/api_driver.py`): call `client.backups.update_backup`.
  - UI driver (`backend/tests/e2e/drivers/ui_driver.py`) and page object (`backend/tests/e2e/pages/deployment_detail.py`): click `backup-edit` on the row, fill the dialog, save, then wait until the row's `data-backup-name` shows the new value.
- [ ] T027 [US1] Extend `test_backup_and_restore_lifecycle` in `backend/tests/e2e/test_backup_restore.py`. After the backup completes and before the restore:
  - call `scenario_driver.update_backup(...)` to rename the backup and set its description;
  - assert that the returned and re-read backup has the new values;
  - assert, with kubectl or kr8s, that the Velero `Backup` object is named `styrmin-<backup id>` and has the label `styrmin.io/backup-id=<backup id>`.

  The existing restore steps then prove that a restore after the rename succeeds (SC-002).

**Checkpoint**: Backups can be renamed and described on all four surfaces, and a restore after a rename works.

---

## Phase 4: User Story 2 - Name and describe a backup at creation (P2)

**Goal**: FR-001, FR-002 and FR-006 at creation.

**Independent Test**: Create a backup with a name and a description from the UI, the SDK and the CLI. Both values are stored. A duplicate name in the same instance is rejected.

- [ ] T028 [US2] In `backend/styrmin_backend/services/backup/service.py`, change `create_backup` to take `description: str | None = None`. It must:
  - clean the name with `_clean_backup_name` when a name is given and is not whitespace-only (a whitespace-only name falls back to the default `styrmin-<id>`);
  - clean the description with `_clean_backup_description`;
  - before the insert, check `get_by_instance_and_name` and raise `BackupNameAlreadyExistsError`.

  The environment fan-out in `services/backup/environment.py` keeps passing no name. Add unit tests in `test_backup_service.py`:
  - create with a description;
  - default name with no description;
  - duplicate name in one instance is rejected;
  - the same name on two instances is allowed.
- [ ] T029 [US2] In `backend/styrmin_backend/api/schema/mutation.py`, give `create_backup` a `description: str | None = None` argument and pass it to the service. Regenerate `schema.graphql`. In the same propagation test file as T018, add a create test with an operation file `backend/tests/functional/graphql/operations/create_backup_with_description.graphql`. It asserts that `description` reaches the database and that the duplicate name returns `ALREADY_EXISTS`.
- [ ] T030 [P] [US2] Add `$description: String` and `description` to `python_sdk/src/styrmin_sdk/graphql/create_backup.graphql`, then regenerate. Give `BackupResource.create_backup` a `description` argument. Give `styrminctl backups create` a `--description` option. Test it in `python_sdk/tests/test_backups.py` and `cli/tests/test_backups.py`.
- [ ] T031 [US2] Add `$name`, `$description` and `description` to `frontend/src/graphql/create_backup.graphql` and run codegen. In `DeploymentDetailPage.tsx`, make the **Create Backup** button (about lines 628–651, `handleBackup` about line 185) open `BackupDetailsDialog` in create mode, and send only the fields that are not empty. Add a create-mode test to `BackupDetailsDialog.test.tsx`.
- [ ] T032 [US2] E2E support:
  - `create_backup(self, *, instance_id: str, name: str | None = None, description: str | None = None)` in `protocol.py`, `api_driver.py` and `ui_driver.py`;
  - the page object `create_backup()` in `pages/deployment_detail.py` clicks **Create Backup**, fills the dialog when values are given, and submits.

  This page object is shared by every UI-variant test that creates a backup (critique E7). In `test_backup_and_restore_lifecycle`, create the backup with a name and a description, and assert both on the returned `BackupRef`.

**Checkpoint**: Backups can be created with a name and a description on every surface.

---

## Phase 5: User Story 3 - Existing custom-named backups keep working (P1)

**Goal**: FR-009 for rows created before this feature. The mechanism is in Phase 2. This phase proves it.

**Independent Test**: A row that represents a backup created with a custom name before the upgrade can still be restored and renamed, and its restore names the original Velero object.

- [ ] T033 [US3] In `backend/tests/unit/workflows/test_restore_steps.py` (or the restore-flow test module that T007 touched), add a test. Seed a backup with `name="pre-migration"` and `metadata_={"velero_backup_name": "pre-migration"}`, rename it to `golden` with `update_backup`, and run the restore flow with Kubernetes faked. The Velero `Restore` must have `backupName="pre-migration"`. Add the matching check for a default-named row: `styrmin-<id>` is used.
- [ ] T034 [US3] Check that `update_backup` never writes `metadata_["velero_backup_name"]`. Add a unit assertion in `test_backup_service.py` that the key is unchanged after a rename.

**Checkpoint**: Old backups are covered by the migration test (T004) and by the flow and service tests (T033, T034).

---

## Phase 6: Documentation, changelog and verification

- [ ] T035 [P] In `docs/docs/concepts-and-architecture/backups-and-restores.md`, add a section "Name and describe a backup". It must cover:
  - setting a name and a description at creation;
  - renaming and editing in the UI (Edit action), the CLI (`styrminctl backups update`), the SDK and GraphQL (`updateBackup`);
  - names are unique per application instance;
  - the default name is `styrmin-<backup id>`;
  - a rename does not change the Velero `Backup` object, which is always named `styrmin-<backup id>` (and keeps its original name for backups created with a custom name before this version).
- [ ] T036 [P] In `docs/docs/reference/styrminctl.md`, add a `backups` section that documents `create` (including `--name` and `--description`) and `update`, in the format of the existing `env-backups` section (about line 269).
- [ ] T037 [P] In `CONTEXT.md`, add a **Backup** entry next to "Backup storage location". It must say:
  - a per-instance snapshot;
  - the name is a label only Styrmin shows, unique per application instance, default `styrmin-<backup id>`, and can be renamed;
  - the description is optional;
  - the Velero `Backup` object is named after the backup's id and is found by it (ADR-073), and backups created with a custom name before #39 keep their original Velero name.
- [ ] T038 [P] Add the changelog fragment `changelog/39.added.md` with `uv run towncrier create -c "..." 39.added.md`. It states that backups can be given a description, renamed and re-described after creation, that names are unique per deployment instance, and that Velero objects are now always named after the backup's id.
- [ ] T039 Run the checks from quickstart.md:
  - `uv run invoke format lint`;
  - `uv run invoke validate-graphql`;
  - `uv run invoke test`;
  - `cd frontend && pnpm lint && pnpm test`;
  - `uv run pytest python_sdk/tests cli/tests -q`.

  Check that a fresh run of `uv run invoke generate` leaves no changes.
- [ ] T040 Run the E2E test in both variants, following AGENTS.md:
  ```bash
  sleep infinity | uv run pytest "backend/tests/e2e/test_backup_restore.py::test_backup_and_restore_lifecycle" -v -s --pdb 2>&1 | tee /tmp/pdb.log
  ```
  Then run one other UI-variant test that uses the shared `create_backup` page object, for example `test_restore_lifecycle_transitions`. Record the evidence in `specs/034-backup-rename-description/e2e-evidence.md`, as required by constitution §V:
  - the node id;
  - the command;
  - the ISO 8601 timestamp;
  - the vcluster id and kubeconfig path;
  - the verbatim `PASSED` line.
- [ ] T041 Record in the implementation report the follow-up for the deferred scheduled-backup name template (research R10). Do not file the issue automatically; the user decides.

---

## Dependencies & Execution Order

- **Phase 1 → Phase 2**: T001 before T003.
- **Phase 2** blocks every story.
  - T002 comes before T003 and T004.
  - T005 and T006 come before T007.
  - T007 and T008 go in one commit.
- **US1 (Phase 3)**:
  - T011 and T012 come before T013, which comes before T014.
  - T015 and T016 come before T017, which comes before T018.
  - T017 comes before T019, which comes before T020 and T021.
  - T017 comes before T022, which comes before T023, T024 and T025.
  - T020 and T024 come before T026, which comes before T027.
- **US2 (Phase 4)** depends on the helpers in T013, the dialog in T023 and the driver changes in T026.
  - T028 comes before T029, which comes before T030 and T031, which come before T032.
- **US3 (Phase 5)** depends on Phase 2 and T013.
- **Phase 6** comes after all stories. T040 is last, apart from T041.

## Parallel Opportunities

- Phase 2: T004, T005 and T006 (different files) once T002 is done. T009 at any time.
- US1: T011 and T012 together. T019 and T022 together once T017 is done.
- Phase 6: T035, T036, T037 and T038 together.

## Implementation Strategy

1. Phase 2 first. It is the change that makes any rename safe, and it keeps the existing suite green.
2. US1 is the MVP: rename and description across all surfaces, proved by the extended E2E test.
3. US2 adds the inputs at creation by reusing US1's helpers and dialog.
4. US3 adds explicit tests for old rows.
5. Documentation, then the full checks and the E2E run in both variants with evidence.
