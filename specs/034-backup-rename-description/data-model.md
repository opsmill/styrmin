# Data Model: Rename Backups and Add a Description

## Backup (table `backup`)

Changed fields only. All other fields stay as they are in `backend/styrmin_backend/db/models.py`.

| Field | Type | Change | Rules |
|-------|------|--------|-------|
| `name` | `str`, not null | No longer unique across all backups. Unique per `instance_id`. | 1–255 characters after leading and trailing whitespace is removed. Default `styrmin-<id>`. |
| `description` | `str \| None`, text, nullable | New | At most 2,000 characters. Empty or whitespace-only input is stored as `NULL`. |
| `metadata_["velero_backup_name"]` | `str`, optional key in the existing JSON column | New key in `BackupMetadata` | Written only by the migration, for rows that existed before this feature and have a custom name. Never written by a request. |

### Constraints and indexes

| Before | After |
|--------|-------|
| `backup_name_key`: `UNIQUE (name)` (unnamed in the initial schema, so PostgreSQL named it `backup_name_key`) | Dropped |
| — | `ix_backup_instance_id_name`: `UNIQUE (instance_id, name)` |

The model declares the new index in `__table_args__`, so that `metadata.create_all()` builds the same schema for fresh databases and test fixtures.

### Derived value: the Velero object name

`velero_backup_name(backup)`, in `services/backup/metadata.py`:

```text
metadata_.velero_backup_name  if set   (a row that an earlier version created with a custom name)
"styrmin-" + str(backup.id)   otherwise (every new row, and old rows with the default name)
```

This is the only place that builds the name of a backup's Velero `Backup` object.

### State transitions

None change. Updates to `name` and `description` are allowed in every `BackupStatus`.

## Alembic revision

One revision whose parent is the current head (`859c9d31dc11`, check with `alembic heads` before you write it):

1. Add the column `backup.description` (`sa.Text`, nullable).
2. Backfill: for each row where `name != 'styrmin-' || id`, set `metadata.velero_backup_name = name`. Write it as a short Python loop over `SELECT id, name, metadata`, which works on both PostgreSQL and SQLite, so that it does not depend on the JSON functions of one database.
3. Drop the unique constraint on `backup.name`. Find it by inspection, as `c9d0e1f2a3b4_deployment_name_scoped_uniqueness.py` does. On SQLite, use `batch_alter_table` with a naming convention.
4. Create the unique index `ix_backup_instance_id_name` on `(instance_id, name)`.

Downgrade:

1. Drop the index.
2. Refuse to run if any two rows share a name, because the old constraint would reject them.
3. Re-create `UNIQUE (name)`.
4. Remove the `velero_backup_name` key.
5. Drop `description`.

## Velero Backup object (Kubernetes, not stored by Styrmin)

| Attribute | Before | After |
|-----------|--------|-------|
| `metadata.name` | `backup.name` at flow run time | `velero_backup_name(backup)` |
| label `styrmin.io/backup-id` | absent | `<backup id>` on new objects |

## Not changed

- `Restore.name` and the name of the Velero `Restore` object (`restore.name`). Restores cannot be renamed.
- `EnvironmentBackup.name`.
- `BackupSchedule`. See research R10.
