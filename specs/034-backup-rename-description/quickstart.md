# Quickstart: Validate backup rename and description

How to check that the feature works. The field rules and errors are in [data-model.md](data-model.md) and [contracts/](contracts/).

## Prerequisites

- `uv sync` and `cd frontend && pnpm install`
- `vcluster` and Docker on `PATH` (needed only for the E2E tests)

## 1. Schema, code generation and lint

```bash
uv run styrmin export graphql-schema schema.graphql
uv run invoke generate
uv run invoke validate-graphql
uv run invoke format lint
cd frontend && pnpm codegen && pnpm lint && pnpm exec tsc --noEmit
```

Expected result: `schema.graphql` shows `Backup.description` and `updateBackup`, and the regeneration leaves no other changes.

## 2. Migration

```bash
uv run pytest backend/tests/unit/db -k backup_rename -v
```

Expected result:

- After the upgrade, a row with a custom name has `metadata.velero_backup_name` and a row with the default name does not.
- Two backups of one instance cannot share a name, and two backups of different instances can.
- The downgrade restores the old constraint.

## 3. Unit and propagation tests

```bash
uv run pytest backend/tests/unit/services/backup backend/tests/unit/workflows backend/tests/functional/graphql -k "backup" -v
uv run pytest python_sdk/tests/test_backups.py cli/tests/test_backups.py -v
cd frontend && pnpm test -- deployment-detail
```

Expected result: all tests pass. The propagation test checks that `updateBackup` writes `name` and `description` to the database, and that `Backup.description` is returned when you query it.

## 4. E2E (both variants)

```bash
sleep infinity | uv run pytest "backend/tests/e2e/test_backup_restore.py::test_backup_and_restore_lifecycle" -v -s --pdb 2>&1 | tee /tmp/pdb.log
```

Expected result: both `[api-chromium]` and `[ui-chromium]` pass, and the test checks the following:

- the backup is created with the name and description it was given;
- the rename is shown in the API and in the UI;
- the Velero `Backup` object is `styrmin-<backup id>` and carries the label `styrmin.io/backup-id`;
- the restore after the rename completes.

## 5. Manual check in the UI (optional)

1. Run `uv run invoke dev` and open a deployment.
2. Open the **Backups** tab and click **Create Backup**. Enter a name and a description.
3. Click **Edit** on the row and change both values. The row shows the new values.
4. Click **Restore** on the row. The dialog shows the new name.
