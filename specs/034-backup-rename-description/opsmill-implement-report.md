# Implementation Report: Rename Backups and Add a Description

- **Feature**: rename backups and add a description ([opsmill/styrmin#39](https://github.com/opsmill/styrmin/issues/39))
- **Spec directory**: `specs/034-backup-rename-description`
- **Branch**: `034-backup-rename-description`
- **Base commit**: `4200d107` (last prep commit)
- **Head commit**: `ba3cc1f3` before this report
- **Status**: DONE. All 41 tasks are complete, every new or changed test has a local pass, and the review ran in `command` mode.
- **Wall-clock time**: about 1 hour 50 minutes, from the first chunk at about 15:08Z to the review fixes at 16:36Z, plus the report.

## 1. Chunk ledger

| # | Chunk (tasks.md phase) | Tasks | ✅ / ⚠️ / ❌ | Commit(s) | Notes passed up by the subagent |
|---|---|---|---|---|---|
| 1 | Phase 1: Setup | T001 | 1 / 0 / 0 | `546ef0a4` | The Alembic head is `859c9d31dc11`, as expected. |
| 2 | Phase 2: Foundational | T002–T010 | 9 / 0 / 0 | `d7b7cfc0` | Migration `a2a102e37495`. The task list missed two call sites in `test_infrahub_backup_restore.py` (lines 154 and 265) that passed `backup.name` as the Velero name; both were fixed. The comment in `environment.py:494` was left as it was, because it describes `EnvironmentBackup.name`, which is still unique across all environment backups. `velero_backup_name` was added to the pinned keys in `test_backup_metadata_contract.py`. |
| 3 | Phase 3 (US1): service, GraphQL | T011–T018 | 8 / 0 / 0 | `62c3a91a` | The GraphQL descriptions are set with `description=`, because Strawberry does not copy docstrings into the schema. The description is stripped of surrounding whitespace before it is stored. A second operation file, `get_backup_description.graphql`, reads a seeded description. |
| 4 | Phase 3 (US1): SDK, CLI | T019–T021 | 3 / 0 / 0 | `732acfe3` | `backups update` with no option prints an error and exits with code 1, as `restore` does, instead of a Cyclopts usage error. The `list` Description column is cut to 40 characters. |
| 5 | Phase 3 (US1): frontend | T022–T025 | 4 / 0 / 0 | `782b3a22` | An empty name is rejected in edit mode, as a whitespace-only one is. The Actions column is now 150 px wide. Test ids are listed in chunk 6. |
| 6 | Phase 3 (US1): E2E | T026–T027 | 2 / 0 / 0 | `6e472c3e` | The rename step runs before the configuration edit and the restore. The E2E run was deferred to chunk 10 (see §6). |
| 7 | Phase 4 (US2): create with name and description | T028–T032 | 5 / 0 / 0 | `dfda2dc2` | The page-level error banner for **Create Backup** was removed; creation errors now appear in the dialog. Three UI tests use the shared page object `create_backup()`: `test_backup_and_restore_lifecycle`, `test_mariadb_mongodb_backup_and_restore_lifecycle` and `test_restore_lifecycle_transitions`. |
| 8 | Phase 5 (US3): legacy backups | T033–T034 | 2 / 0 / 0 | `f4528e16` | The restore test renames a real `Backup` row with `update_backup`, then runs the restore flow on that row. The `backup=` argument is on a helper in the test module (`test_restore_steps.py:663`), not on production code; the engineering review confirmed this. |
| 9 | Phase 6: documentation | T035–T038 | 4 / 0 / 0 | `fc519371` | Also corrected step 6 of "What happens when you start a backup" in `backups-and-restores.md` and the `Backup.name` comment in `dev/knowledge/backend/backup-restore.md`. CONTEXT.md had no Backup entry, so one was added. |
| 10 | Phase 6: verification | T039–T041 | 3 / 0 / 0 | `17aaa36b`, `bd8f7c7e` | Prettier reformatted `frontend/src/graphql/create_backup.graphql`. The first E2E attempts failed for local-environment reasons (see §6). One retry was sent, and it passed. |
| – | Review fixes | – | – | `ba3cc1f3` | See §5. |

Total: 41 tasks, 41 ✅, 0 ⚠️, 0 ❌.

## 2. Tasks not completed

None. Every task in `tasks.md` is `[X]`.

## 3. Follow-up for the deferred scheduled-backup name template (T041)

Issue #39 asks that scheduled backups support a name template, such as `daily-<date>`. This feature does not deliver it (research R10). `BackupSchedule` records are stored, but no code creates a backup from a schedule: no code writes `Backup.schedule_id` or uses `BackupSchedule.prefect_deployment_id`. A template would have no effect.

The product review rated this as the one critical item: a pull request that says "Closes #39" would close the issue with this criterion undelivered. Suggested follow-up issue, which has not been filed:

- **Title**: Name template for backups created from a schedule.
- **Body**: when scheduled backups create `Backup` records, apply a per-schedule name template (for example a prefix plus the date) so that each backup gets a readable, per-instance-unique name. The template depends on schedule execution, which does not exist yet. Split out of #39.

Before merging, either file this issue and reference #39 as "Part of #39", or get the issue author's agreement on #39 to close it without this criterion.

## 4. Local-pass evidence

| Test id | Type | Run command | Passed at (ISO 8601) | Environment context | Verbatim pass line |
|---|---|---|---|---|---|
| `backend/tests/unit/db/test_backup_rename_migration.py` (11 tests: 5 cases on PostgreSQL and SQLite, plus the model index check) | unit | `uv run pytest <chunk 2 files> backend/tests/unit/db/test_migration_heads.py backend/tests/unit/db/test_models.py -q` | 2026-11-27T15:15:58Z | macOS, PostgreSQL test container and SQLite | `139 passed in 7.87s` |
| `test_backup_metadata_contract.py::test_velero_backup_name_*` (2 new, 7 in file) | unit | same run as above | 2026-11-27T15:15:58Z | macOS | `139 passed in 7.87s` |
| `backend/tests/unit/agent/test_backup_builders.py` (label check, 18 in file) | unit | same run as above | 2026-11-27T15:15:58Z | macOS | `139 passed in 7.87s` |
| `test_backup_component_steps.py::test_backup_workflow_names_the_velero_backup_after_the_id` | unit | same run as above | 2026-11-27T15:15:58Z | macOS | `139 passed in 7.87s` |
| `test_restore_steps.py::test_restore_workflow_restores_the_velero_backup_named_after_the_id` | unit | `uv run pytest backend/tests/unit/workflows/test_restore_steps.py backend/tests/unit/services/backup/test_backup_service.py -k "legacy_backup_by_its_stored_name or named_after_the_id or never_writes_the_velero_backup_name" -v` | 2026-11-27T15:46:14Z | macOS, no cluster | `4 passed, 89 deselected in 0.25s` |
| `test_restore_steps.py::test_restore_workflow_restores_a_legacy_backup_by_its_stored_name` (extended in chunk 8) | unit | same as above | 2026-11-27T15:46:14Z | macOS, no cluster | `4 passed, 89 deselected in 0.25s` |
| `test_backup_workflow_ttl.py`, `test_restore_workflow_failure_handler.py` (mocks changed) | unit | `uv run pytest backend/tests/unit -k "backup or restore or migration" -q -p no:randomly` | 2026-11-27T15:15:08Z | macOS, PostgreSQL test container | `1058 passed, 4221 deselected, 2 warnings in 40.16s` |
| `test_backup_service.py::TestUpdateBackup` (13 tests) | unit | `uv run pytest backend/tests/unit/services/backup/test_backup_service.py::TestUpdateBackup backend/tests/unit/repository/backup/test_backup_repository.py::test_get_by_instance_and_name backend/tests/functional/graphql/test_backup_update_propagation.py -v` | 2026-11-27T15:19:42Z | macOS, in-memory SQLite | `23 passed in 0.88s` |
| `test_backup_repository.py::test_get_by_instance_and_name` | unit | same as above | 2026-11-27T15:19:42Z | macOS, in-memory SQLite | `23 passed in 0.88s` |
| `test_backup_update_propagation.py` (9 update tests) | functional (GraphQL propagation) | same as above | 2026-11-27T15:19:42Z | macOS, in-memory SQLite | `23 passed in 0.88s` |
| `test_backup_service.py::TestCreateBackup` (5 new tests) | unit | `uv run pytest backend/tests/unit/services/backup/test_backup_service.py -q` | 2026-11-27T15:37:49Z | macOS | `59 passed in 0.09s` |
| `test_backup_update_propagation.py::test_create_backup_persists_description`, `::test_create_backup_duplicate_name_returns_already_exists` | functional (GraphQL propagation) | `uv run pytest backend/tests/functional/graphql/test_backup_update_propagation.py -q` | 2026-11-27T15:37:51Z | macOS | `11 passed in 1.28s` |
| `test_backup_service.py::TestUpdateBackup::test_rename_never_writes_the_velero_backup_name[asyncio-legacy\|asyncio-default]` | unit | chunk 8 command above | 2026-11-27T15:46:14Z | macOS | `4 passed, 89 deselected in 0.25s` |
| `test_backup_rename_migration.py::test_downgrade_restores_the_velero_name_of_a_renamed_legacy_backup[postgresql\|sqlite]`, `::test_downgrade_refuses_a_duplicate_produced_by_the_velero_name_rewrite[postgresql\|sqlite]` (review fix) | unit | `uv run pytest backend/tests/unit/db/test_backup_rename_migration.py -v` | 2026-11-27T16:36:09Z | macOS, Python 3.14.7, pytest 9.0.2 | `15 passed in 14.46s` |
| `python_sdk/tests/test_backups.py` (update tests, plus get and list changed) | unit (SDK) | `uv run pytest python_sdk/tests/test_backups.py -q` | 2026-11-27T15:26:13Z | macOS, Python 3.14.7 | `35 passed in 0.06s` |
| `python_sdk/tests/test_backups.py` (create tests) | unit (SDK) | `uv run pytest python_sdk/tests/test_backups.py -q` | 2026-11-27T15:37:55Z | macOS | `37 passed in 0.07s` |
| `cli/tests/test_backups.py` (update, get, list, help) | unit (CLI) | `uv run pytest cli/tests/test_backups.py -q` | 2026-11-27T15:26:14Z | macOS, Python 3.14.7 | `65 passed in 0.47s` |
| `cli/tests/test_backups.py` (create `--description`) | unit (CLI) | `uv run pytest cli/tests/test_backups.py -q` | 2026-11-27T15:37:56Z | macOS | `66 passed in 0.48s` |
| `BackupDetailsDialog.test.tsx` (6 edit-mode and row tests) | unit (frontend) | `cd frontend && pnpm exec vitest run src/__tests__/deployment-detail/BackupDetailsDialog.test.tsx` | 2026-11-27T15:30:05Z | Node 22.18.0, jsdom | `Tests  6 passed (6)` |
| `BackupDetailsDialog.test.tsx` (2 create-mode tests) | unit (frontend) | `cd frontend && pnpm exec vitest run src/__tests__/deployment-detail/` | 2026-11-27T15:42:12Z | Node 22, jsdom | `Test Files  12 passed (12)` (the file alone: `Tests  8 passed (8)`) |
| `BackupDetailsDialog > keeps Edit enabled while the deployment is being deleted` (review fix) | unit (frontend) | `cd frontend && pnpm exec vitest run src/__tests__/deployment-detail/BackupDetailsDialog.test.tsx` | 2026-11-27T16:35:36Z | Node 22, jsdom | `Tests  9 passed (9)` |
| `backend/tests/e2e/test_backup_restore.py::test_backup_and_restore_lifecycle[api-chromium]` | e2e | `export COMPOSE_PARALLEL_LIMIT=1; sleep infinity \| uv run pytest "backend/tests/e2e/test_backup_restore.py::test_backup_and_restore_lifecycle" -v -s --pdb` | 2026-11-27T16:17:53Z (the run's log had no timestamps; this is the teardown line seconds after the pass) | vcluster `pytest-793eafe7-bba2-47e8-a102-d1b73b37ed28`; kubeconfig recorded in `e2e-evidence.md` | `PASSED` |
| `backend/tests/e2e/test_backup_restore.py::test_backup_and_restore_lifecycle[ui-chromium]` | e2e | `export COMPOSE_PARALLEL_LIMIT=1; sleep infinity \| uv run pytest "backend/tests/e2e/test_backup_restore.py::test_backup_and_restore_lifecycle[ui-chromium]" "backend/tests/e2e/test_backup_restore.py::test_restore_lifecycle_transitions[ui-chromium]" -v -s --pdb` | 2026-11-27T16:28:58Z | vcluster `pytest-531bdced-c0ca-4eb3-89a1-eff07146c331`; kubeconfig recorded in `e2e-evidence.md` | `16:28:58 PASSED` |
| `backend/tests/e2e/test_backup_restore.py::test_restore_lifecycle_transitions[ui-chromium]` (uses the shared `create_backup` page object) | e2e | same session as above | 2026-11-27T16:30:51Z | same vcluster as above | `16:30:51 backend/tests/e2e/test_backup_restore.py::test_restore_lifecycle_transitions[ui-chromium] PASSED` |

**Full suites (T039)**:

| Command | Result |
|---|---|
| `uv run invoke format lint` | Passes. Only yamllint warnings that predate this branch. |
| `uv run invoke validate-graphql` | 289 of 289 files valid. |
| `uv run invoke test` | 6242 passed, 8 skipped and 1 failed. The failure is `backend/tests/unit/services/telemetry/test_sender.py::test_send_report_returns_false_when_the_connection_is_refused`: a refused connection takes about 7.8 s on this machine against a 2 s limit. This branch does not change the telemetry code (the diff `4200d107..HEAD` has no file under `services/telemetry`), and the test fails the same way when run alone. |
| `cd frontend && pnpm lint && pnpm test` | 0 lint errors (35 warnings in older files); 1308 tests passed in 109 files. |
| `uv run pytest python_sdk/tests -q` | `639 passed, 1 xfailed` |
| `uv run pytest cli/tests -q` | `429 passed` |
| `uv run invoke generate` | Leaves no changes. |

**Not run**:

- `test_infrahub_backup_restore.py`, whose Velero helper calls were changed in chunk 2. The change replaces `backup.name` with `styrmin-<backup id>` at two call sites, the same change the lifecycle test proves. The product review asked for a recorded run.
- The E2E runs predate the review-fix commit `ba3cc1f3`. That commit only removes the disabled state of the Edit button when a deployment is being deleted, and the UI E2E path never sees that state. It also changes the migration downgrade, which no E2E test runs.

## 5. Review findings

Review mode: command (/code-review)

The project's `code-review` skill ran three independent reviewers over `4200d107..ba3cc1f3^` (product, user and engineering). Their severities are mapped as follows: Critical is high, Important is medium and Suggestion is low. When two reviewers flagged the same item, the higher severity is used.

| Severity | Lens | File | Finding | Outcome |
|---|---|---|---|---|
| high | PM | `tasks.md:254`, `research.md:102` | The scheduled-backup name template from #39 is deferred and has no follow-up issue, so "Closes #39" would drop the criterion. | **Deferred to the user.** Filing an issue publishes to GitHub; §3 contains the draft. |
| medium | ENG | `a2a102e37495_…py` (downgrade) | The downgrade removed `velero_backup_name` without writing it back into `name`, so a renamed legacy backup could not be restored after a downgrade. | **Fixed** in `ba3cc1f3`. The downgrade now writes the stored Velero name into `name` and checks for duplicates after that rewrite, before any schema change. Two new tests cover it. |
| medium | ENG | `DeploymentDetailPage.tsx:1334` | Edit was disabled for deployments being deleted, which contradicts FR-010 ("allow updates in every status"). | **Fixed** in `ba3cc1f3`, with a test. |
| medium | PM | `changelog/39.added.md` | Two changes in behaviour were listed only under "added": the Velero name of new custom-named backups, and name uniqueness. | **Fixed** in `ba3cc1f3`: new `changelog/39.changed.md`. |
| medium | ENG | `services/backup/service.py:172-177, 247-279` | Two writes of the same name at the same moment return `INTERNAL_ERROR` instead of `ALREADY_EXISTS`. | Deferred. Accepted in critique E3 and plan Risks. The fix is to catch `IntegrityError` at commit. |
| medium | UX + PM | `DeploymentDetailPage.tsx:776-791` | The Restore Backup dialog does not show the description, although that is where the operator chooses a backup. | Deferred. |
| medium | UX | `DeploymentDetailPage.tsx:1262` | The full description is only in a `title` tooltip or in the Edit dialog. Keyboard, touch and read-only users cannot read past two lines. | Deferred. |
| medium | UX | `BackupNameAlreadyExistsError`, `BackupDetailsDialog.tsx:166` | The duplicate-name message uses "instance" and does not say what to do. | Deferred. |
| medium | UX | `BackupDetailsDialog.tsx:116-118` | The Name placeholder does not show the default name `styrmin-<backup id>`. | Deferred. |
| medium | PM | `e2e-evidence.md` | `test_infrahub_backup_restore.py` changed but has no recorded run. | Deferred (see §4, Not run). |
| low | ENG | `BackupDetailsDialog.tsx:37` | The client checks the length of the untrimmed value and counts UTF-16 code units, so it can disagree with the server near 255 characters. | Deferred. |
| low | ENG | `mutation.py:1015-1021` | `description: null` leaves the field unchanged and `""` clears it, which is easy to get wrong. The return type is nullable but the mutation never returns null. | Deferred. Follows the `update_backup_schedule` pattern (research R4). |
| low | ENG | `service.py:223` | Names accept newlines and control characters, which break the CLI table and the UI row. | Deferred. |
| low | ENG | `service.py:160` | On create, a whitespace-only name falls back to the default; on update it is an error. This is intended but undocumented in the GraphQL description. | Deferred. |
| low | ENG | commit messages | `implement T0xx: …` subjects do not use the conventional-commit prefixes used on `develop`. | Deferred: use a conventional title when squash-merging. |
| low | UX | `BackupDetailsDialog.tsx:204-209` | In create mode the focus is on the submit button, so a keyboard user must move back to type a name. | Deferred. Intended (critique P4). |
| low | UX | `BackupDetailsDialog.tsx:138-165` | No character counter for the 2,000-character description. | Deferred. |
| low | UX | `BackupDetailsDialog.tsx:126-130` | Field errors are not linked to their inputs with `aria-describedby`. | Deferred. |
| low | UX | `DeploymentDetailPage.tsx:1333` | Every row's Edit button has the same accessible name. Restore and Delete have the same problem today. | Deferred. |
| low | UX | `cli/.../backups.py:205` | The `NOT_FOUND` error could suggest `styrminctl backups list`. | Deferred. |
| low | PM | `e2e-evidence.md:37,68` | The file contains machine-specific paths. | Deferred. The constitution §V asks for the kubeconfig path. |
| low | PM | `EnvironmentBackupRow.tsx` | Environment backups have no name or description. | Deferred. Out of scope for #39. |
| low | PM | – | No success metric is defined. A query for the share of backups with a non-default name or a description would need no tracking code. | Deferred. |

### Deferred findings fixed after the first report

The user asked to continue after reading the first version of this report, so most deferred findings were fixed in two more commits. No E2E test ran for these commits on the local machine, because it does not have enough memory; CI runs them on the draft pull request.

- `d6f19907` (backend, SDK, CLI):
  - Two writes of the same name at the same moment now return `ALREADY_EXISTS`. The service catches `IntegrityError`, rolls back, and looks the name up again.
  - Names refuse control characters. Descriptions refuse control characters other than line feed, carriage return and tab.
  - The duplicate-name message now reads `A backup named "<name>" already exists for this deployment. Choose a different name.`
  - The `createBackup` `name` description states that an empty name falls back to `styrmin-<backup id>`.
  - The CLI suggests `styrminctl backups list` after a not-found error.
  - Evidence: `1327 passed` (backend services and GraphQL functional tests, 2026-11-27T16:47:34Z), `639 passed, 1 xfailed` (SDK), `433 passed` (CLI, 2026-11-27T16:47:08Z), and `25 passed in 2.55s` for the new race, control-character and propagation tests (2026-11-27T16:49:32Z).
- `13f53acc` (frontend and docs):
  - The Restore Backup dialog shows the description.
  - Every role can expand a long description with a **Show more** button. The button appears when the description has a line break or is longer than 80 characters, so a short description on a wide screen can get a button it does not need.
  - The Name placeholder shows `styrmin-<backup id>`.
  - Client validation trims, counts code points and refuses control characters, as the server does.
  - Field errors are linked to their inputs.
  - Each Edit button's accessible name includes the backup name.
  - A character counter appears from 1,800 characters.
  - A duplicate-name error is titled "Name already in use".
  - Evidence: `Tests  113 passed (113)` (`pnpm exec vitest run src/__tests__/deployment-detail/`, 2026-11-27T16:52:58Z, Node 22.18.0). All E2E test ids are unchanged, and `uv run pytest backend/tests/e2e --collect-only -q` collected 233 tests.

Still deferred:

- **Scheduled-backup name template follow-up (high).** Needs your decision (§3).
- **Nullable `updateBackup` return and `null` versus `""`.** Follows the existing update pattern (research R4).
- **Conventional commit title.** Set it when squash-merging.
- **Machine-specific paths in `e2e-evidence.md`.** Kept, because constitution §V asks for the kubeconfig path.
- **Name and description for environment backups.** Out of scope for #39.
- **Success metric.** None defined.
- **`test_infrahub_backup_restore.py` run.** CI runs it.

## 6. Autonomous decisions

- **Chunking.** Phase 3 (17 tasks) was split into four chunks: service and GraphQL, SDK and CLI, frontend, and E2E. Phase 6 was split into documentation and verification. Phase 1 (one task) was kept as its own chunk, as the skill requires.
- **E2E runs deferred to the last chunk.** Chunks 6 and 7 both change `test_backup_and_restore_lifecycle`, so they only collected and type-checked it. Chunk 10 ran it in both variants, plus `test_restore_lifecycle_transitions[ui-chromium]`. Running the full E2E test after each chunk would have cost about an hour more.
- **Installed `vcluster` 0.38.0 with Homebrew.** AGENTS.md lists it as an E2E prerequisite, and it was not on `PATH`. Homebrew also upgraded `helm` from 4.1.1 to 4.3.2 as a side effect. Run `brew uninstall vcluster` to remove it.
- **E2E environment workarounds (no code changes).**
  - Exported `COMPOSE_PARALLEL_LIMIT=1`. Three compose services build the same image tag, and Docker Desktop rejected the parallel writes.
  - Ran `uv run playwright install chromium`.
  - Ran the API and UI variants in separate sessions to keep memory lower.
  - The first E2E retry was stopped by Claude Code's background-process handling when memory was low. One retry was sent after memory had recovered to 33% free, and it passed.
- **Unrelated telemetry test failure.** It was recorded and not fixed, because the cause is network timing on this machine and the branch does not touch telemetry.
- **Review triage.** I fixed three medium findings (downgrade name restore, Edit enabled per FR-010, changelog `changed` fragment) because each was small and corrects real behaviour. I deferred the others. I deferred the only high finding, the follow-up issue, because it requires publishing to GitHub.
- **Review provider.** The `pr-review-toolkit` plugin was not available. The project's `code-review` skill was used (`command` mode).

## 7. Suggested next steps

1. Decide on the scheduled-backup name template (§3): file the follow-up issue, or agree with the author of #39 to close the issue without it.
2. Review the downgrade change in `a2a102e37495` and the new `changelog/39.changed.md`.
3. Check the E2E results in CI on the draft pull request: the `shard_backup` shard and the Infrahub shard cover `test_backup_and_restore_lifecycle`, `test_restore_lifecycle_transitions` and `test_infrahub_backup_restore.py`, which had not run locally. The local machine cannot run E2E tests.
4. Mark the pull request ready for review when CI passes, then run `/speckit.opsmill.extract` if wanted.
