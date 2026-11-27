# Research: Rename Backups and Add a Description

Source spec: [spec.md](spec.md). Each decision lists what was chosen, why, and the options that were not chosen.

## R1. How a backup finds its Velero `Backup` object

**Decision**: Add the function `velero_backup_name(backup)` to `backend/styrmin_backend/services/backup/metadata.py`. It returns `metadata_["velero_backup_name"]` when that key is set, and `styrmin-<backup id>` otherwise. The backup flow (`workflows/templates/backup.py:565`) and the restore flow (`:971`) call it instead of reading `backup.name`. New backups never set the key. An Alembic data migration sets the key only on existing rows whose `name` is not `styrmin-<id>`, to the value of `name`. That value is the name of the Velero object that an earlier version created for the row.

**Rationale**:

- ADR-073 requires that Styrmin names the Kubernetes objects of a record after the record's id and finds them by that id. With this function every new Velero `Backup` object is `styrmin-<id>`, and a rename has no effect on it.
- A backup created with a custom name before this feature already has a Velero object with that custom name. A Velero `Restore` names its backup by object name (`spec.backupName`), and a Velero object cannot be renamed, so Styrmin has to keep that name for those rows. ADR-073 allows this for objects that "an earlier version named differently".
- The value is stored only for old rows, is written once by the migration, and is never written by a request. A rename cannot change it.
- `Backup.metadata_` already holds the backup's typed pipeline keys (`BackupMetadata`), so no new column is needed.

**Alternatives considered**:

- Find old objects by an id label. Rejected: old Velero `Backup` objects have no backup-id label (`builders/backup.py:60` sets only `styrmin.io/instance` and `styrmin.io/driver`).
- Add a `velero_name` column for every row. Rejected: ADR-073 option 2, which the ADR rejected. A stored value for every row is the pattern that left objects behind in #488.
- Keep using `backup.name` and forbid renaming backups that have a custom name. Rejected: this does not satisfy FR-003 for those backups.

## R2. Label on new Velero `Backup` objects

**Decision**: `build_velero_backup` adds the label `styrmin.io/backup-id: <backup id>` to every new Velero `Backup` object.

**Rationale**: ADR-073 requires that each object carries a label with the id of its record. No code reads the label in this feature, and it costs one line.

**Alternatives considered**: Skip the label. Rejected: it would leave the new objects short of the rule that AGENTS.md states for every object Styrmin creates.

## R3. Name uniqueness per application instance

**Decision**: Drop the PostgreSQL constraint `backup_name_key` (unique `name` across all backups). Create the unique index `ix_backup_instance_id_name` on `(instance_id, name)`. Follow the pattern of migration `c9d0e1f2a3b4_deployment_name_scoped_uniqueness.py`, which finds the unnamed constraint by inspection and uses `batch_alter_table` on SQLite. Before each write, the service checks for a conflict through a new repository method `get_by_instance_and_name` and raises `BackupNameAlreadyExistsError` (`ALREADY_EXISTS`, metadata `existing_backup_id`). The index stops concurrent writes that pass the check at the same moment.

**Rationale**: The issue asks for names that are unique per instance. Each Velero name is now built from the backup's id (R1), so two backups with the same name no longer share a Velero object. Existing data cannot violate the new index, because every name is unique across all backups today.

**Alternatives considered**:

- Keep names unique across all backups. Rejected: this contradicts the issue and stops an operator from using the same name, such as `before-upgrade`, on two deployments.
- Catch `IntegrityError` only. Rejected: the backup services check for conflicts before they write, as the rest of the backup code does, and catching only the database error would not give the id of the existing backup.

## R4. Description field and how to clear it

**Decision**: Add the nullable text column `backup.description`. In `updateBackup`, an argument that is not sent (`None`) leaves its field unchanged. An empty or whitespace-only `description` clears the field (stored as `NULL`). An empty name fails with `ValidationError`.

**Rationale**: This follows the `update_backup_schedule` pattern, in which `None` means "leave unchanged", and needs no `strawberry.UNSET` handling, which the codebase does not use anywhere. The empty string is the natural "clear" value for a text box.

**Alternatives considered**: Use `strawberry.UNSET` to tell "not sent" apart from `null`. Rejected: this would introduce a new pattern with no added value over the empty string.

## R5. Validation limits

**Decision**: The service strips leading and trailing whitespace from the name. The stripped name must be 1 to 255 characters. The description must be at most 2,000 characters. A failure raises the existing `ValidationError` (`VALIDATION_ERROR`). `create_backup` and `update_backup` share one helper. `create_backup` keeps the default `styrmin-<id>` when no name is given or when the given name is only whitespace.

**Rationale**: The issue gives no limits. 255 characters covers any name that fits in a table cell, and 2,000 characters covers a paragraph of notes. The existing `ValidationError` fits, so no new error class is needed.

## R6. Renaming during a running backup

**Decision**: Allow updates in every status.

**Rationale**: After R1 no flow reads `backup.name` to find a cluster object, so a rename while a backup runs cannot affect that backup. The flows load the backup row only to read the metadata and the component configs.

## R7. Web UI

**Decision**: Add one component, `BackupDetailsDialog`, with an optional name field and an optional description field, built with `@tanstack/react-form` in the same way as `EditClusterDialog.tsx`. It is used in two places:

- The **Create Backup** button opens it in create mode. Submitting with both fields empty creates a backup with the default name, as the button does today.
- A new **Edit** action in each `BackupRow` opens it in edit mode, filled with the current values, and calls `updateBackup`.

`BackupRow` shows the description under the name, in muted text, limited to two lines, with the full text in a `title` tooltip. The description is rendered as plain text, never as Markdown or HTML. In create mode the submit button has focus, so pressing Enter in the empty dialog creates a backup with the default name, which keeps the old one-click flow close to one keystroke. The restore dialog already shows the backup's current `name`, so it needs no change.

**Rationale**: One dialog covers FR-001 and FR-012. An edit dialog is simpler than inline editing and works the same way for the name and the description.

**Alternatives considered**: Inline editing of the name in the row. Rejected: the description also needs an editor, and two editing patterns in one row are harder to use and to test.

## R8. SDK and CLI

**Decision**:

- SDK: `BackupResource.create_backup(instance_id, name=None, description=None)` and a new `BackupResource.update_backup(backup_id, name=None, description=None)`. Add the new operation file `update_backup.graphql`, and add `description` to the field lists of `create_backup.graphql`, `get_backup.graphql` and `list_backups.graphql`.
- CLI: `styrminctl backups create --description TEXT`, and a new `styrminctl backups update BACKUP_ID [--name NAME] [--description TEXT]`. `get` and `list` show the description.

**Rationale**: FR-001 and FR-003 name every surface. The pattern follows `resources/schedules.py` and the existing `backups.py` CLI module.

## R9. E2E coverage

**Decision**: Extend the existing test `test_backup_and_restore_lifecycle` (`backend/tests/e2e/test_backup_restore.py`, `shard_backup`, runs in both variants). Do not add a new test node.

- The scenario driver's `create_backup` gains `name` and `description` arguments. The scenario creates the backup with a name and a description.
- A new dual-entrypoint method `update_backup(backup_id, name, description)` renames the backup before the restore. The API driver uses the SDK. The UI driver uses the Edit action in the backup row.
- The scenario checks that the Velero `Backup` object is `styrmin-<backup id>`, that it carries the `styrmin.io/backup-id` label, and that the restore after the rename succeeds.
- The Velero helper calls at `test_backup_restore.py` lines 982, 987, 1005, 2002 and 2040 pass `f"styrmin-{backup.id}"` instead of `backup.name`.

**Rationale**: Constitution §V ("Reuse before you boot"). This test already deploys the stack and runs a backup and a restore, so adding the assertions to it boots nothing new.

**Legacy backups** (User Story 3): the cases are covered by unit tests:

- the migration test checks that the backfill writes `velero_backup_name` only for rows with a custom name;
- a test of `velero_backup_name` covers both branches;
- a restore-flow unit test checks that a legacy row passes its stored name to the Velero `Restore`.

An E2E test would have to run a backup on the version before this feature, which the E2E fixtures cannot do.

## R10. Scheduled backup name template (deferred)

**Decision**: Out of scope, as the spec states. `BackupSchedule` records are stored, but no code creates a backup from a schedule. A search of `backend/` finds no writer of `Backup.schedule_id` and no use of `prefect_deployment_id`. The implementation report records a follow-up issue.

**Rationale**: A template field that has no effect cannot be checked by an E2E test, and it would show operators a setting that does nothing.

## R11. Governance gates

The constitution requires discussion before database and GraphQL schema changes. The issue asks for both changes in its acceptance criteria (a `description` column on Backup and an `updateBackup` mutation), so the issue is the record of that discussion. The plan records the gates as acknowledged.
