# Environment Backups and Clones Tabs

<!-- Extracted from specs/001-env-backup-restore on 2026-10-13 -->
<!-- Extracted from specs/010-environment-clone on 2026-10-13 -->

## Overview

The environment detail page (`frontend/src/pages/environments/EnvironmentDetailPage.tsx`)
has a Backups tab and a Clones tab. On the Backups tab, users create an environment
backup, restore one, and delete one. On the Clones tab, administrators clone the
environment and follow each clone's outcome.

The server calculates every status shown on these tabs on each read; none is stored.
The tabs only display the statuses, and they move from one status to the next by
fetching the lists again. The backend side is described in
[backup-restore.md](../backend/backup-restore.md#environment-level-backup--restore).

## Backups tab

`EnvironmentBackupsTab` lists the environment's backups, one `EnvironmentBackupRow` per
backup.

Creating a backup:

- The "Create Backup" button is shown to users with the `READ_WRITE` role or higher
  (`IfRole minimum="READ_WRITE"`).
- A refused request, for example `ALREADY_IN_PROGRESS`, is shown as an error message
  above the list.
- On success the tab invalidates `ListEnvironmentBackups` and `ListBackups`. The second
  key is the deployment page's backup list, which now has one more constituent backup.

Polling:

- `ListEnvironmentBackups` is fetched again every 10 seconds while the page's
  auto-refresh is on.
- The page unmounts the panel of an inactive tab, so the polling stops when the user
  leaves the tab.

What each row shows:

- The Applications column summarises the constituents, for example
  `2/3 complete · 1 failed`. A backup without constituents shows "Config only".
- The expanded row lists every captured deployment once:
  - its backup's status;
  - `not backed up — <error>` when the backup could not be created;
  - "constituent backup was deleted" when the constituent backup was deleted on its own
    after the environment backup was taken. An expired constituent backup still has its
    row and reads as completed, so it never shows this text.
- The expanded row also lists the restores of this backup (`ListEnvironmentRestores`).
  The list is fetched only while the row is expanded, and again every 10 seconds while
  auto-refresh is on.

Actions on a row, each behind a confirmation dialog:

| Action | Minimum role | Enabled when | Query keys invalidated on success |
|--------|--------------|--------------|-----------------------------------|
| Restore | `ADMIN` | The status is `COMPLETED` or `PARTIAL`; the server refuses any other status with `OPERATION_DENIED` | `ListEnvironmentRestores`, `GetEnvironment` (the restore reverts the environment's config), `ListRestores` |
| Delete | `READ_WRITE` | Always, including while the backup is in progress | `ListEnvironmentBackups`, `ListBackups`, `ListRestores` (the deletion removes the constituent backups and their restores) |

## Clones tab

`EnvironmentClonesSection` lists the clones whose source is this environment.
`CloneEnvironmentDialog` starts a new clone.

Starting a clone:

- The "Clone Environment" button and its dialog are shown only to administrators
  (`IfRole minimum="ADMIN"`).
- On success the dialog invalidates `ListEnvironmentClones`, `ListEnvironmentBackups`
  (a clone starts with a new environment backup of the source) and `ListEnvironments`.

Polling (`cloneListRefetchInterval`):

- `ListEnvironmentClones` is fetched only while the Clones tab is active.
- It is fetched again every 10 seconds only while auto-refresh is on and at least one
  listed clone is not finished. `COMPLETED`, `PARTIAL` and `FAILED` are finished.
  Starting a clone invalidates the list, which starts the polling again.
- An expanded row fetches `GetEnvironmentClone`, and fetches it again every 10 seconds
  while auto-refresh is on and that clone is not finished.

How a row shows the created environment:

- A link to the environment, when `createdEnvironment` is set.
- "Discarded", when the environment was deleted. The row detects this from a
  `cloneErrors` entry that starts with `created_environment_deleted:`, because a null
  `createdEnvironment` also means "not created yet".
- "not created yet", otherwise.

`cloneErrors` entries arrive as `"<step>: <error>"` strings without the `fatal` flag, so
the label does not depend on it. A finished clone whose environment was deleted keeps its
status and still shows "Discarded". The E2E API driver detects a discard with its own
copy of the same prefix. `backend/tests/unit/test_clone_discard_step_contract.py` fails
when either copy no longer matches the backend step name.

## Data attributes for tests

| Element | Attributes |
|---------|------------|
| Backups tab | `data-testid="environment-backups-tab"`, `data-environment-id` |
| Backup row | `data-testid="environment-backup-row"`, `data-environment-backup-id`, `data-environment-backup-name`, `data-environment-backup-status` |
| Backup row buttons | `data-testid="create-environment-backup-button"`, `"environment-backup-restore-button"`, `"environment-backup-delete-button"` |
| Clone row | `data-testid="environment-clone-row"`, `data-environment-clone-id`, `data-environment-clone-name`, `data-environment-clone-status`, `data-environment-clone-discarded`, `data-created-environment-id`, `data-environment-backup-id`, `data-result-total` |
| Clone button | `data-testid="clone-environment-button"` |

## Tests

Vitest tests live in `frontend/src/__tests__/environments/`:

- `EnvironmentBackupsTab.test.tsx`, `EnvironmentBackupRestore.test.tsx` and
  `EnvironmentBackupLifecycle.test.tsx` for the Backups tab;
- `EnvironmentCloneDialog.test.tsx` and `EnvironmentClonesSection.test.tsx` for the
  Clones tab.

## Key Files

| File | Purpose |
|------|---------|
| [EnvironmentDetailPage.tsx](../../../frontend/src/pages/environments/EnvironmentDetailPage.tsx) | Environment detail page; mounts both tabs and owns the auto-refresh flag |
| [EnvironmentBackupsTab.tsx](../../../frontend/src/components/environment/EnvironmentBackupsTab.tsx) | Backups tab: create button, list polling |
| [EnvironmentBackupRow.tsx](../../../frontend/src/components/environment/EnvironmentBackupRow.tsx) | One environment backup: constituent summary, restore history, restore and delete |
| [EnvironmentClonesSection.tsx](../../../frontend/src/components/environment/EnvironmentClonesSection.tsx) | Clones tab: list polling, clone rows, "Discarded" detection |
| [CloneEnvironmentDialog.tsx](../../../frontend/src/components/environment/CloneEnvironmentDialog.tsx) | Clone form, shown to administrators only |
| [test_clone_discard_step_contract.py](../../../backend/tests/unit/test_clone_discard_step_contract.py) | Keeps the copies of the discard prefix equal to the backend step name |
