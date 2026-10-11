# Implementation Report: Keep a Deployment's Backup History When It Gets a New Instance (#304)

- Status: DONE. All 45 tasks are complete, and every new or modified test has a recorded local pass.
- Spec directory: `specs/011-deployment-backup-history`
- Base commit: `1681b1ac`
- Head commit: `11d5be71` before this report's own commit
- Wall-clock time: about 1 hour 15 minutes (2026-10-08, about 22:42 to 23:57 UTC)

## Chunk-by-chunk ledger

| # | Chunk (tasks.md phase) | Tasks | Done / partial / blocked | Commits |
|---|------------------------|-------|--------------------------|---------|
| 1 | Phase 1: Setup (T001–T002) | 2 | 2 / 0 / 0 | `7c7f388a` |
| 2 | Phase 2: Repository and service (T003–T007) | 5 | 5 / 0 / 0 | `fee38037` |
| 3 | Phase 2: GraphQL (T008–T012) | 5 | 5 / 0 / 0 | `06878b0e` |
| 4 | Phase 2: SDK (T013–T015) | 3 | 3 / 0 / 0 | `72461a3f` |
| 5 | Phase 3 (US1): integration test for the four operations (T016) | 1 | 1 / 0 / 0 | `7c1c25a2` |
| 6 | Phase 3 (US1): frontend Backups tab (T019, T020, T021, T017) | 4 | 4 / 0 / 0 | `c47ff312` |
| 7 | Phase 3 (US1): CLI `backups list` (T022, T023, T018) | 3 | 3 / 0 / 0 | `32a2b3fa` |
| 8 | Phase 3 (US1): E2E (T024–T029) | 6 | 6 / 0 / 0 | `5dfe8e85`, `e939d1f7` |
| 9 | Phase 4 (US2): CLI `restore --last` (T030–T032) | 3 | 3 / 0 / 0 | `be5d99c2` |
| 10 | Phase 5 (US3): SDK tests and docstring (T033–T034) | 2 | 2 / 0 / 0 | `77202287` |
| 11 | Phase 6 (US4): deleted deployment (T035–T036) | 2 | 2 / 0 / 0 | `a2adeb20` |
| 12 | Phase 7: documentation, changelog and full gate (T037–T045) | 9 | 9 / 0 / 0 | `034a317a`, `9de93063` |
| — | Review fixes | — | — | `11d5be71` |

What each chunk reported upward:

- Chunk 1
  - The T002 command, which runs six files in one pytest session, never runs a test. `backend/tests/conftest.py` and `python_sdk/tests/conftest.py` both import as `tests.conftest`, so the session stops at collection. Each file ran in its own session, as CI runs them.
  - `uv run invoke generate` and vitest need Node 22. The chunk installed a portable Node 22 in the session scratchpad. It also re-ran `pnpm install --frozen-lockfile` under Node 22, because Node 18 skips the native package `@rolldown/binding-linux-x64-gnu`; the lockfile did not change.
  - `pnpm test -- deployment-detail` ignores the filter and runs the whole suite. `pnpm test deployment-detail` applies it.
  - All baseline tests passed (see [baseline.md](baseline.md)).
- Chunk 2: No production caller of `get_backups` needed an edit, because the resolver already passed every argument by keyword.
- Chunk 3
  - `frontend/src/generated/graphql.ts` was regenerated in this chunk, because lint failed until it was.
  - The `VALIDATION_ERROR` test also checks the service's exact message and `path == ["backups"]`. graphql-core's own request-validation errors use the same code, so the code alone would not prove which error was returned.
- Chunk 4
  - The SDK class is `BackupResource`, not `BackupsResource` as tasks.md says.
  - The regenerated model requires `instance`, so two existing SDK test fixtures gained it.
  - Two CLI telemetry tests fail when the tests run as root (see "Review findings").
- Chunk 5
  - The first instance comes from the `deploy` mutation, because a hand-seeded instance has an empty context and cannot be the active instance.
  - The chunk confirmed that all four operations create a new instance. In every case, listing by the new active instance returns `[]`, which is the bug in #304.
  - The environment config change catches redeploy errors per deployment, so in that case the active-instance assertion is the only check that would catch a failed redeploy.
- Chunk 6
  - A deployment with no active instance now shows "Loading backups..." and then its history. Before this change it showed "No backups yet".
  - The E2E page object reads only `data-backup-*` attributes, so the new column cannot break its selectors.
- Chunk 7
  - `backups list --id` reaches a deleted deployment, because `deployment(deploymentId:)` returns deleted deployments. The name lookup does not find them.
  - The shared help text in `cli/src/styrminctl/types.py` said "(resolves its active instance)". That is now wrong for `list`; chunk 12 corrected it.
- Chunk 8
  - The fallback in research R9 was not needed: the restore stayed stable after the config edit in both variants.
  - Other sessions on this host were building images at the same time. The runs set `STYRMIN_IMAGE_VER=local-f8kjf-backup-history`, so that their builds could not replace this branch's images.
  - The test adds the marker env var to the `server` component's existing env vars instead of replacing them (they were empty). It reverts them in `finally` only if the edit was attempted.
- Chunk 9
  - The restore still goes to the deployment's active instance. The backup can belong to an older instance.
  - `--last` takes the first row of the server's newest-first list. That is the most recently created completed backup, not the most recently completed one, which is how `--last` behaved before this change.
  - `--last --target-deployment` still fails when the deployment has no active instance, because a restore needs one.
- Chunk 10
  - A `VALIDATION_ERROR` raises the SDK's existing `OperationFailedError`.
  - A `sed -i` mistake emptied `tasks.md`. The chunk restored it from git, and the orchestrator confirmed that every earlier tick was still there.
- Chunk 11
  - A deployment name can be reused only after the first deployment is deleted. The unique index `uq_deployment_env_name_active` counts only deployments that are not deleted.
  - Restore and delete are disabled on a deleted deployment's Backups tab. The intro to spec US4 says an operator opens a deleted deployment "to review it or restore from it", so the spec text does not match the product.
- Chunk 12
  - The `[DEPLOYMENT]` and `--id` help text in `types.py` now reads "Name of the deployment." and "UUID of the deployment.", which is true for both `create` and `list`.
  - `--deployment` exists as the keyword form of the positional `DEPLOYMENT` argument, so the reference page no longer presents it as an instance option.
  - The docs site build was not run, because `docs/node_modules` is not installed.
  - Quickstart §3 needs the dev stack and is optional, so it was not run.

## Tasks not completed

None. All 45 tasks in [tasks.md](tasks.md) are `[X]`.

## Local-pass evidence

Every row passed on 2026-10-08 (UTC). Backend unit and functional tests ran against in-memory SQLite, and the SDK and CLI tests ran against mocked transports and SDKs. Frontend rows ran on Node v22.23.3.

Backend: repository (T004).

| Test id | Type | Run command | Passed at | Environment context | Verbatim pass line |
|---------|------|-------------|-----------|---------------------|--------------------|
| `backend/tests/unit/repository/backup/test_backup_repository.py::test_get_by_deployment_id_returns_every_instance_newest_first` | unit | `uv run pytest backend/tests/unit/repository/backup/test_backup_repository.py -k get_by_deployment_id -rA -q` | 2026-10-08T22:51:34+00:00 | n/a | `PASSED backend/tests/unit/repository/backup/test_backup_repository.py::test_get_by_deployment_id_returns_every_instance_newest_first` |
| `…::test_get_by_deployment_id_excludes_other_deployment` | unit | same | 2026-10-08T22:51:34+00:00 | n/a | `PASSED backend/tests/unit/repository/backup/test_backup_repository.py::test_get_by_deployment_id_excludes_other_deployment` |
| `…::test_get_by_deployment_id_with_status_filter` | unit | same | 2026-10-08T22:51:34+00:00 | n/a | `PASSED backend/tests/unit/repository/backup/test_backup_repository.py::test_get_by_deployment_id_with_status_filter` |
| `…::test_get_by_deployment_id_unknown_deployment_returns_empty` | unit | same | 2026-10-08T22:51:34+00:00 | n/a | `PASSED backend/tests/unit/repository/backup/test_backup_repository.py::test_get_by_deployment_id_unknown_deployment_returns_empty` |
| `…::test_get_by_deployment_id_includes_constituent_backup` | unit | same | 2026-10-08T22:51:34+00:00 | n/a | `PASSED backend/tests/unit/repository/backup/test_backup_repository.py::test_get_by_deployment_id_includes_constituent_backup` |

Backend: service (T007). The first two are existing tests whose calls changed.

| Test id | Type | Run command | Passed at | Environment context | Verbatim pass line |
|---------|------|-------------|-----------|---------------------|--------------------|
| `backend/tests/unit/services/backup/test_backup_service.py::TestGetBackups::test_get_backups_by_instance[asyncio]` | unit | `uv run pytest backend/tests/unit/services/backup/test_backup_service.py -k TestGetBackups -rA -q` | 2026-10-08T22:51:37+00:00 | n/a | `PASSED backend/tests/unit/services/backup/test_backup_service.py::TestGetBackups::test_get_backups_by_instance[asyncio]` |
| `…::TestGetBackups::test_get_backups_with_status_filter[asyncio]` | unit | same | 2026-10-08T22:51:37+00:00 | n/a | `PASSED backend/tests/unit/services/backup/test_backup_service.py::TestGetBackups::test_get_backups_with_status_filter[asyncio]` |
| `…::TestGetBackups::test_get_backups_by_deployment_returns_every_instance[asyncio]` | unit | same | 2026-10-08T22:51:37+00:00 | n/a | `PASSED backend/tests/unit/services/backup/test_backup_service.py::TestGetBackups::test_get_backups_by_deployment_returns_every_instance[asyncio]` |
| `…::TestGetBackups::test_get_backups_by_deployment_with_status_filter[asyncio]` | unit | same | 2026-10-08T22:51:37+00:00 | n/a | `PASSED backend/tests/unit/services/backup/test_backup_service.py::TestGetBackups::test_get_backups_by_deployment_with_status_filter[asyncio]` |
| `…::TestGetBackups::test_get_backups_by_instance_returns_only_that_instance[asyncio]` | unit | same | 2026-10-08T22:51:37+00:00 | n/a | `PASSED backend/tests/unit/services/backup/test_backup_service.py::TestGetBackups::test_get_backups_by_instance_returns_only_that_instance[asyncio]` |
| `…::TestGetBackups::test_get_backups_with_both_identifiers_raises[asyncio]` | unit | same | 2026-10-08T22:51:37+00:00 | n/a | `PASSED backend/tests/unit/services/backup/test_backup_service.py::TestGetBackups::test_get_backups_with_both_identifiers_raises[asyncio]` |
| `…::TestGetBackups::test_get_backups_with_no_identifier_raises[asyncio]` | unit | same | 2026-10-08T22:51:37+00:00 | n/a | `PASSED backend/tests/unit/services/backup/test_backup_service.py::TestGetBackups::test_get_backups_with_no_identifier_raises[asyncio]` |

Backend: GraphQL propagation and integration tests (T011, T016, T035).

| Test id | Type | Run command | Passed at | Environment context | Verbatim pass line |
|---------|------|-------------|-----------|---------------------|--------------------|
| `backend/tests/functional/graphql/test_backup_history_propagation.py::test_backups_by_deployment_id_lists_every_instance_newest_first` | integration | `uv run pytest backend/tests/functional/graphql/test_backup_history_propagation.py -v` | 2026-10-08T22:58:32+00:00 | n/a | `backend/tests/functional/graphql/test_backup_history_propagation.py::test_backups_by_deployment_id_lists_every_instance_newest_first PASSED [ 16%]` |
| `…::test_backups_by_deployment_id_filters_by_status` | integration | same | 2026-10-08T22:58:32+00:00 | n/a | `backend/tests/functional/graphql/test_backup_history_propagation.py::test_backups_by_deployment_id_filters_by_status PASSED [ 33%]` |
| `…::test_backups_by_unknown_deployment_id_returns_empty_list` | integration | same | 2026-10-08T22:58:32+00:00 | n/a | `backend/tests/functional/graphql/test_backup_history_propagation.py::test_backups_by_unknown_deployment_id_returns_empty_list PASSED [ 50%]` |
| `…::test_backups_by_inactive_instance_id_returns_only_its_backups` | integration | same | 2026-10-08T22:58:32+00:00 | n/a | `backend/tests/functional/graphql/test_backup_history_propagation.py::test_backups_by_inactive_instance_id_returns_only_its_backups PASSED [ 66%]` |
| `…::test_backups_with_both_or_neither_id_is_a_validation_error[both]` | integration | same | 2026-10-08T22:58:32+00:00 | n/a | `backend/tests/functional/graphql/test_backup_history_propagation.py::test_backups_with_both_or_neither_id_is_a_validation_error[both] PASSED [ 83%]` |
| `…::test_backups_with_both_or_neither_id_is_a_validation_error[neither]` | integration | same | 2026-10-08T22:58:32+00:00 | n/a | `backend/tests/functional/graphql/test_backup_history_propagation.py::test_backups_with_both_or_neither_id_is_a_validation_error[neither] PASSED [100%]` |
| `…::test_backup_stays_in_history_after_operation_creates_new_instance[upgrade]` | integration | `uv run pytest backend/tests/functional/graphql/test_backup_history_propagation.py backend/tests/functional/graphql/test_driver_version_reselection_propagation.py -v` | 2026-10-08T23:05:41+00:00 | mocked Prefect manager | `backend/tests/functional/graphql/test_backup_history_propagation.py::test_backup_stays_in_history_after_operation_creates_new_instance[upgrade] PASSED [ 35%]` |
| `…::test_backup_stays_in_history_after_operation_creates_new_instance[config-edit]` | integration | same | 2026-10-08T23:05:41+00:00 | mocked Prefect manager | `backend/tests/functional/graphql/test_backup_history_propagation.py::test_backup_stays_in_history_after_operation_creates_new_instance[config-edit] PASSED [ 40%]` |
| `…::test_backup_stays_in_history_after_operation_creates_new_instance[refresh]` | integration | same | 2026-10-08T23:05:41+00:00 | mocked Prefect manager | `backend/tests/functional/graphql/test_backup_history_propagation.py::test_backup_stays_in_history_after_operation_creates_new_instance[refresh] PASSED [ 45%]` |
| `…::test_backup_stays_in_history_after_operation_creates_new_instance[environment-config-change]` | integration | same | 2026-10-08T23:05:41+00:00 | mocked Prefect manager | `backend/tests/functional/graphql/test_backup_history_propagation.py::test_backup_stays_in_history_after_operation_creates_new_instance[environment-config-change] PASSED [ 50%]` |
| `…::test_deleted_deployment_still_lists_its_backup_history` | integration | `uv run pytest backend/tests/functional/graphql/test_backup_history_propagation.py -v` | 2026-10-08T23:45:36+00:00 | n/a | `backend/tests/functional/graphql/test_backup_history_propagation.py::test_deleted_deployment_still_lists_its_backup_history PASSED [ 91%]` |
| `…::test_new_deployment_reusing_a_deleted_name_starts_with_empty_history` | integration | same | 2026-10-08T23:45:36+00:00 | n/a | `backend/tests/functional/graphql/test_backup_history_propagation.py::test_new_deployment_reusing_a_deleted_name_starts_with_empty_history PASSED [100%]` |

SDK (chunk 4 fixture changes, T033). The first two are existing tests whose mocked responses changed.

| Test id | Type | Run command | Passed at | Environment context | Verbatim pass line |
|---------|------|-------------|-----------|---------------------|--------------------|
| `python_sdk/tests/test_backups.py::TestBackupResource::test_list_backups` | unit | `uv run pytest python_sdk/tests/test_backups.py -rA -q` | 2026-10-08T23:00:27+00:00 | n/a | `PASSED python_sdk/tests/test_backups.py::TestBackupResource::test_list_backups` |
| `python_sdk/tests/test_backups.py::TestBackupAndRestoreSteps::test_list_backups_parses_the_steps_of_each_backup` | unit | same | 2026-10-08T23:00:27+00:00 | n/a | `PASSED python_sdk/tests/test_backups.py::TestBackupAndRestoreSteps::test_list_backups_parses_the_steps_of_each_backup` |
| `…::TestListBackupsByDeploymentOrInstance::test_by_deployment_sends_only_the_deployment_id` | unit | `uv run pytest python_sdk/tests -rA -q` | 2026-10-08T23:40:53+00:00 | n/a | `PASSED python_sdk/tests/test_backups.py::TestListBackupsByDeploymentOrInstance::test_by_deployment_sends_only_the_deployment_id` |
| `…::test_by_instance_sends_only_the_instance_id[positional]` | unit | same | 2026-10-08T23:40:53+00:00 | n/a | `PASSED python_sdk/tests/test_backups.py::TestListBackupsByDeploymentOrInstance::test_by_instance_sends_only_the_instance_id[positional]` |
| `…::test_by_instance_sends_only_the_instance_id[keyword]` | unit | same | 2026-10-08T23:40:53+00:00 | n/a | `PASSED python_sdk/tests/test_backups.py::TestListBackupsByDeploymentOrInstance::test_by_instance_sends_only_the_instance_id[keyword]` |
| `…::test_status_is_coerced_and_sent_with_either_id[str-by-deployment]` | unit | same | 2026-10-08T23:40:53+00:00 | n/a | `PASSED python_sdk/tests/test_backups.py::TestListBackupsByDeploymentOrInstance::test_status_is_coerced_and_sent_with_either_id[str-by-deployment]` |
| `…::test_status_is_coerced_and_sent_with_either_id[str-by-instance]` | unit | same | 2026-10-08T23:40:53+00:00 | n/a | `PASSED python_sdk/tests/test_backups.py::TestListBackupsByDeploymentOrInstance::test_status_is_coerced_and_sent_with_either_id[str-by-instance]` |
| `…::test_status_is_coerced_and_sent_with_either_id[enum-by-deployment]` | unit | same | 2026-10-08T23:40:53+00:00 | n/a | `PASSED python_sdk/tests/test_backups.py::TestListBackupsByDeploymentOrInstance::test_status_is_coerced_and_sent_with_either_id[enum-by-deployment]` |
| `…::test_status_is_coerced_and_sent_with_either_id[enum-by-instance]` | unit | same | 2026-10-08T23:40:53+00:00 | n/a | `PASSED python_sdk/tests/test_backups.py::TestListBackupsByDeploymentOrInstance::test_status_is_coerced_and_sent_with_either_id[enum-by-instance]` |
| `…::test_parses_the_instance_each_backup_was_taken_of` | unit | same | 2026-10-08T23:40:53+00:00 | n/a | `PASSED python_sdk/tests/test_backups.py::TestListBackupsByDeploymentOrInstance::test_parses_the_instance_each_backup_was_taken_of` |
| `…::test_validation_error_raises_operation_failed[both]` | unit | same | 2026-10-08T23:40:53+00:00 | n/a | `PASSED python_sdk/tests/test_backups.py::TestListBackupsByDeploymentOrInstance::test_validation_error_raises_operation_failed[both]` |
| `…::test_validation_error_raises_operation_failed[neither]` | unit | same | 2026-10-08T23:40:53+00:00 | n/a | `PASSED python_sdk/tests/test_backups.py::TestListBackupsByDeploymentOrInstance::test_validation_error_raises_operation_failed[neither]` |

CLI (T018, T030). The rows from 23:14:31 are copied from the subagent's report, which shortened the run of spaces that pytest printed before `[ nn%]` to one space.

| Test id | Type | Run command | Passed at | Environment context | Verbatim pass line |
|---------|------|-------------|-----------|---------------------|--------------------|
| `cli/tests/test_backups.py::test_backups_list_by_deployment_name` | unit | `uv run pytest cli/tests/test_backups.py -v -p no:cacheprovider` | 2026-10-08T23:14:31+00:00 | `COLUMNS=200` set inside the test | `cli/tests/test_backups.py::test_backups_list_by_deployment_name PASSED [ 28%]` |
| `cli/tests/test_backups.py::test_backups_list_by_deployment_id_without_active_instance` | unit | same | 2026-10-08T23:14:31+00:00 | n/a | `cli/tests/test_backups.py::test_backups_list_by_deployment_id_without_active_instance PASSED [ 31%]` |
| `cli/tests/test_backups.py::test_backups_list_shows_application_version_column` | unit | same | 2026-10-08T23:14:31+00:00 | `COLUMNS=200` set inside the test | `cli/tests/test_backups.py::test_backups_list_shows_application_version_column PASSED [ 34%]` |
| `cli/tests/test_backups.py::test_backups_list_shows_expiry_column` | unit | same | 2026-10-08T23:14:31+00:00 | n/a | `cli/tests/test_backups.py::test_backups_list_shows_expiry_column PASSED [ 37%]` |
| `cli/tests/test_backups.py::test_backups_list_renders_dash_without_expiry` | unit | same | 2026-10-08T23:14:31+00:00 | n/a | `cli/tests/test_backups.py::test_backups_list_renders_dash_without_expiry PASSED [ 40%]` |
| `cli/tests/test_backups.py::test_backups_list_by_instance_id_escape_hatch` | unit | same | 2026-10-08T23:14:31+00:00 | n/a | `cli/tests/test_backups.py::test_backups_list_by_instance_id_escape_hatch PASSED [ 43%]` |
| `cli/tests/test_backups.py::test_backups_restore_last_by_deployment` | unit | `uv run pytest cli/tests/test_backups.py -rA` | 2026-10-08T23:37:44+00:00 | n/a | `PASSED cli/tests/test_backups.py::test_backups_restore_last_by_deployment` |
| `cli/tests/test_backups.py::test_backups_restore_last_by_instance_id` | unit | same | 2026-10-08T23:37:44+00:00 | n/a | `PASSED cli/tests/test_backups.py::test_backups_restore_last_by_instance_id` |
| `cli/tests/test_backups.py::test_backups_restore_last_no_completed_backups_exits_nonzero[by-deployment-name]` | unit | same | 2026-10-08T23:37:44+00:00 | n/a | `PASSED cli/tests/test_backups.py::test_backups_restore_last_no_completed_backups_exits_nonzero[by-deployment-name]` |
| `…::test_backups_restore_last_no_completed_backups_exits_nonzero[by-deployment-id]` | unit | same | 2026-10-08T23:37:44+00:00 | n/a | `PASSED cli/tests/test_backups.py::test_backups_restore_last_no_completed_backups_exits_nonzero[by-deployment-id]` |
| `…::test_backups_restore_last_no_completed_backups_exits_nonzero[by-instance-id]` | unit | same | 2026-10-08T23:37:44+00:00 | n/a | `PASSED cli/tests/test_backups.py::test_backups_restore_last_no_completed_backups_exits_nonzero[by-instance-id]` |

Frontend (T017, T021, T036). The orchestrator re-ran both files after the last code change to record a pass line for each test. Vitest's color codes and durations are removed from the pass lines.

| Test id | Type | Run command | Passed at | Environment context | Verbatim pass line |
|---------|------|-------------|-----------|---------------------|--------------------|
| `BackupExpiry.test.tsx > DeploymentDetailPage backups tab backup history (#304) > lists the backups by the deployment id from the route` | unit | `cd frontend && pnpm --ignore-workspace test deployment-detail/BackupExpiry deployment-detail/BackupRestoreSteps --reporter=verbose` | 2026-10-08T23:56:28+00:00 | Node v22.23.3 | `✓ src/__tests__/deployment-detail/BackupExpiry.test.tsx > DeploymentDetailPage backups tab backup history (#304) > lists the backups by the deployment id from the route` |
| `… backup history (#304) > lists the backup history when the deployment has no active instance` | unit | same | 2026-10-08T23:56:28+00:00 | Node v22.23.3 | `✓ src/__tests__/deployment-detail/BackupExpiry.test.tsx > DeploymentDetailPage backups tab backup history (#304) > lists the backup history when the deployment has no active instance` |
| `… backup history (#304) > shows the application version of each backup after the Status column` | unit | same | 2026-10-08T23:56:28+00:00 | Node v22.23.3 | `✓ src/__tests__/deployment-detail/BackupExpiry.test.tsx > DeploymentDetailPage backups tab backup history (#304) > shows the application version of each backup after the Status column` |
| `… backup history (#304) > lists a deleted deployment's backup history with restore and delete disabled` | unit | same | 2026-10-08T23:56:28+00:00 | Node v22.23.3 | `✓ src/__tests__/deployment-detail/BackupExpiry.test.tsx > DeploymentDetailPage backups tab backup history (#304) > lists a deleted deployment's backup history with restore and delete disabled` |
| `BackupExpiry.test.tsx > … expiry column > labels the expiry column in the backups table header` (fixture changed) | unit | same | 2026-10-08T23:56:28+00:00 | Node v22.23.3 | `✓ src/__tests__/deployment-detail/BackupExpiry.test.tsx > DeploymentDetailPage backups tab expiry column > labels the expiry column in the backups table header` |
| `… expiry column > renders the localized expiry date for a backup that has one` (fixture changed) | unit | same | 2026-10-08T23:56:28+00:00 | Node v22.23.3 | `✓ src/__tests__/deployment-detail/BackupExpiry.test.tsx > DeploymentDetailPage backups tab expiry column > renders the localized expiry date for a backup that has one` |
| `… expiry column > exposes the applied TTL without requiring hover (title + assistive text)` (fixture changed) | unit | same | 2026-10-08T23:56:28+00:00 | Node v22.23.3 | `✓ src/__tests__/deployment-detail/BackupExpiry.test.tsx > DeploymentDetailPage backups tab expiry column > exposes the applied TTL without requiring hover (title + assistive text)` |
| `… expiry column > renders an em-dash when no expiry was recorded` (fixture changed) | unit | same | 2026-10-08T23:56:28+00:00 | Node v22.23.3 | `✓ src/__tests__/deployment-detail/BackupExpiry.test.tsx > DeploymentDetailPage backups tab expiry column > renders an em-dash when no expiry was recorded` |
| `… expiry column > renders an em-dash rather than 'Invalid Date' for an unparseable expiry` (fixture changed) | unit | same | 2026-10-08T23:56:28+00:00 | Node v22.23.3 | `✓ src/__tests__/deployment-detail/BackupExpiry.test.tsx > DeploymentDetailPage backups tab expiry column > renders an em-dash rather than 'Invalid Date' for an unparseable expiry` |
| `… expiry column > keeps the TTL hint when a failed backup never got an expiry` (fixture changed) | unit | same | 2026-10-08T23:56:28+00:00 | Node v22.23.3 | `✓ src/__tests__/deployment-detail/BackupExpiry.test.tsx > DeploymentDetailPage backups tab expiry column > keeps the TTL hint when a failed backup never got an expiry` |
| `… expiry column > keeps the expiry date when only the TTL is missing` (fixture changed) | unit | same | 2026-10-08T23:56:28+00:00 | Node v22.23.3 | `✓ src/__tests__/deployment-detail/BackupExpiry.test.tsx > DeploymentDetailPage backups tab expiry column > keeps the expiry date when only the TTL is missing` |
| `BackupRestoreSteps.test.tsx > … > shows each component of a failed backup with its start time, end time and result` (fixture changed) | unit | same | 2026-10-08T23:56:28+00:00 | Node v22.23.3 | `✓ src/__tests__/deployment-detail/BackupRestoreSteps.test.tsx > DeploymentDetailPage backup and restore steps > shows each component of a failed backup with its start time, end time and result` |
| `… > starts a completed backup's steps collapsed and expands them on click` (fixture changed) | unit | same | 2026-10-08T23:56:28+00:00 | Node v22.23.3 | `✓ src/__tests__/deployment-detail/BackupRestoreSteps.test.tsx > DeploymentDetailPage backup and restore steps > starts a completed backup's steps collapsed and expands them on click` |
| `… > names the failed restore step and its error, with each step's duration in order` (fixture changed) | unit | same | 2026-10-08T23:56:28+00:00 | Node v22.23.3 | `✓ src/__tests__/deployment-detail/BackupRestoreSteps.test.tsx > DeploymentDetailPage backup and restore steps > names the failed restore step and its error, with each step's duration in order` |
| `… > shows a notice for a backup and a restore that ran before steps were recorded` (fixture changed) | unit | same | 2026-10-08T23:56:28+00:00 | Node v22.23.3 | `✓ src/__tests__/deployment-detail/BackupRestoreSteps.test.tsx > DeploymentDetailPage backup and restore steps > shows a notice for a backup and a restore that ran before steps were recorded` |
| `… > shows an in-progress backup without steps as waiting for its first step` (fixture changed) | unit | same | 2026-10-08T23:56:28+00:00 | Node v22.23.3 | `✓ src/__tests__/deployment-detail/BackupRestoreSteps.test.tsx > DeploymentDetailPage backup and restore steps > shows an in-progress backup without steps as waiting for its first step` |

E2E (T028, T029). The full record is in [e2e-evidence.md](e2e-evidence.md).

| Test id | Type | Run command | Passed at | Environment context | Verbatim pass line |
|---------|------|-------------|-----------|---------------------|--------------------|
| `backend/tests/e2e/test_backup_restore.py::test_backup_and_restore_lifecycle[api-chromium]` | e2e | `PATH=<scratchpad>/node22/bin:$PATH npm_config_ignore_workspace=true STYRMIN_IMAGE_VER=local-f8kjf-backup-history uv run pytest "backend/tests/e2e/test_backup_restore.py::test_backup_and_restore_lifecycle" -k "api-chromium" -v -s --pdb < <(exec sleep 987654)` | 2026-10-08T23:27:46Z | vcluster `pytest-0546f061-48ab-4fad-98f3-938cee81978c`, kubeconfig `/tmp/pytest-of-root/pytest-1037/vcluster0/kubeconfig` | `PASSED23:27:46 info Removing vCluster container vcluster.cp.pytest-0546f061-48ab-4fad-98f3-938cee81978c...` (summary `1 passed, 1 deselected, 1 warning in 256.28s (0:04:16)`) |
| `backend/tests/e2e/test_backup_restore.py::test_backup_and_restore_lifecycle[ui-chromium]` | e2e | same, with `-k "ui-chromium"` | 2026-10-08T23:33:46Z | vcluster `pytest-249aa49a-e677-4b16-b7e5-d928d753bbc5`, kubeconfig `/tmp/pytest-of-root/pytest-1038/vcluster0/kubeconfig` | `PASSED23:33:46 info Removing vCluster container vcluster.cp.pytest-249aa49a-e677-4b16-b7e5-d928d753bbc5...` (summary `1 passed, 1 deselected, 1 warning in 314.70s (0:05:14)`) |

Full-suite runs (T044, chunk 12):

- Backend: `uv run invoke test`, started 2026-10-08T23:51:29Z: `2 failed, 3927 passed, 3 skipped, 22 warnings in 121.86s (0:02:01)`. Both failures are in `tests/unit/db/test_steps_migration.py` and existed before this change (see "Review findings").
- SDK: `uv run pytest python_sdk/tests -q -p no:cacheprovider`, 2026-10-08T23:51:32Z: `263 passed in 0.34s`.
- CLI: `uv run pytest cli/tests -q -p no:cacheprovider`, 2026-10-08T23:51:33Z: `2 failed, 356 passed in 22.14s`. Both failures are telemetry tests that also fail on `1681b1ac` (see "Review findings").
- Frontend: `pnpm --ignore-workspace test`, 2026-10-08T23:52:15Z: `Test Files 84 passed (84)`, `Tests 841 passed (841)`.
- `uv run invoke validate-graphql`: 261 of 261 operations passed. `uv run invoke generate` left no diff.

## Review findings

The orchestrator reviewed the diff from `1681b1ac` to `HEAD` by hand. The review found no high-severity issue.

| Severity | File | Finding | Outcome |
|----------|------|---------|---------|
| Medium | `docs/docs/concepts-and-architecture/backups-and-restores.md` | The new passage said a restore of a backup taken at another application version "starts with no check and no confirmation". The Backups tab asks for confirmation in the Restore Backup dialog. | Fixed in `11d5be71`. The passage now says Styrmin does not compare the two versions and shows no warning. |
| Low | `cli/README.md` | The list of operations that keep earlier backups in the list did not name a refresh. The other pages name all four operations. | Fixed in `11d5be71`. |
| Low | `backend/styrmin_backend/repository/backup.py` | `get_by_deployment_id` filters on `applicationinstance.deployment_id`, which has no index. Every upgrade, config edit, refresh and environment config change adds an instance, so the scanned table grows over time. | Deferred. The spec excludes database changes, so an index needs a follow-up issue with an Alembic revision. |
| Low | `specs/011-deployment-backup-history/spec.md` | The intro to US4 says an operator opens a deleted deployment "to review it or restore from it", but restore is disabled on a deleted deployment's Backups tab. The tests and docs describe the actual behavior. | Deferred. Correct the spec text with `speckit-reconcile-run`. |
| Info | `cli/src/styrminctl/commands/backups.py` | `restore --last` chooses the most recently created completed backup, not the most recently completed one. This is how it behaved before this change. | No change. |
| Pre-existing | `backend/tests/unit/db/test_steps_migration.py` | Two tests fail with `Multiple head revisions ... c2ff6dba5ffd, f3a4b5c6d7e8`. Both migrations branch from `e2f3a4b5c6d7` and both are present at the merge base `a2a627d3` on `develop`. This branch changes no file under `backend/styrmin_backend/db/`. | Not caused by this change. It needs a merge revision on `develop`. |
| Pre-existing | `cli/tests/telemetry/test_store.py::test_unwritable_dir_falls_back_to_ephemeral_id`, `cli/tests/telemetry/test_telemetry_command.py::test_commands_succeed_under_unwritable_dir` | Both fail when run as root, because root can write to a directory marked read-only. Both also fail on `1681b1ac`. | Not caused by this change. |

## Autonomous decisions

- The orchestrator ran the 45 tasks as 12 chunks:
  - Phase 2 (13 tasks) was split into three chunks: repository and service, GraphQL, and SDK.
  - Phase 3 (14 tasks) was split into four chunks: integration test, frontend, CLI, and E2E.
  - Each other phase was one chunk.
- The orchestrator did the review by hand instead of invoking `speckit-review-run`. A stored user instruction forbids code-review skills and subagents for reviews. The orchestrator also fixed a medium-severity finding, although this workflow only requires high-severity fixes. The fix was a one-sentence documentation correction.
- The T002 baseline command as written cannot run any test, so the baseline ran each test file in its own pytest session.
- Chunk 6 reported its 12 changed fixture tests as a group. The orchestrator re-ran both test files to record a pass line for each test.
- Chunk 12 changed the shared `[DEPLOYMENT]` and `--id` help text in `cli/src/styrminctl/types.py`. No task named this change, but the old text was wrong for `backups list`.
- Chunk 8 isolated its E2E images with `STYRMIN_IMAGE_VER=local-f8kjf-backup-history`, because other sessions on the host were building images at the same time.
- The orchestrator accepted four failing tests as unrelated: the two migration tests and the two telemetry tests. Each was checked against the base commit or the merge base.
- No E2E row is deferred: both variants ran locally.

## Suggested next steps

1. Open a pull request for `fac/fix-backup-history-disappears-f8kjf`. Note in its description that the two `test_steps_migration.py` failures come from `develop`.
2. Fix the two migration heads on `develop` (`c2ff6dba5ffd`, `f3a4b5c6d7e8`) with a merge revision, in a separate change.
3. Run `speckit-reconcile-run` to align the US4 intro in spec.md with the product: restore is disabled on a deleted deployment.
4. Consider a follow-up issue for an index on `applicationinstance.deployment_id`.
5. Build the docs site in CI or locally, because this run did not build it (`docs/node_modules` was not installed).
