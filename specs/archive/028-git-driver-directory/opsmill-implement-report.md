# Implementation report: spec 028, load an application driver from a driver directory of a git repository

- Status: DONE. All 54 tasks are `[X]`, and every new or changed test has local-pass evidence.
- Spec directory: `specs/028-git-driver-directory`
- Issue: #517
- Base commit: `44aface80b2236d36d4338b723b5d1a682ef7aed`
- Head commit before this report: `1242c43c`
- Wall-clock time: 2026-10-17T18:12:52+00:00 to about 19:55 (about 1 hour 42 minutes)
- Final backend check on the head tree: `uv run pytest backend/tests/unit backend/tests/functional -q -p no:cacheprovider` at 2026-10-17T19:53:37+00:00 gave `4939 passed, 3 skipped, 35 warnings in 123.69s (0:02:03)`.

## Chunk ledger

| # | Chunk (phase in tasks.md) | Tasks | ✅ / ⚠️ / ❌ | Commits |
|---|---------------------------|-------|-------------|---------|
| 1 | Phase 1: Setup (T001) | 1 | 1 / 0 / 0 | `1e4cd9d5` |
| 2 | Phase 2: Foundational (T002–T009) | 8 | 8 / 0 / 0 | `dffaed5c` |
| 3 | Phase 3 US1: Action deployments (T010–T019) | 10 | 10 / 0 / 0 | `ac1b1c48` |
| 4 | Phase 3 US1: SDK and CLI (T020–T023) | 4 | 4 / 0 / 0 | `fd328ac5` |
| 5 | Phase 3 US1: E2E (T024–T027) | 4 | 4 / 0 / 0 | `6595abcb`, `fd4341e9` |
| 6 | Phase 4 US2: Drawer, Overview tab and drivers list (T028–T035) | 8 | 8 / 0 / 0 | `3eb3045e` |
| 7 | Phase 5 US3: Unsafe driver directories and error messages (T036–T038) | 3 | 3 / 0 / 0 | `1ebe6643` |
| 8 | Phase 6 US4: Loads from the repository root (T039–T040) | 2 | 2 / 0 / 0 | `63464769` |
| 9 | Phase 7: Documentation (T041–T049) | 9 | 9 / 0 / 0 | `e29dde69` |
| 10 | Phase 8: Lint and full suites (T050–T051) | 2 | 2 / 0 / 0 | `197d368e` |
| 11 | Phase 8: E2E `[api-chromium]` (T052) | 1 | 1 / 0 / 0 | `c93a92ea` |
| 12 | Phase 8: E2E `[ui-chromium]` and quickstart (T053–T054) | 2 | 2 / 0 / 0 | `7a68e96e` |
| — | Review fixes (Phase 6 of this workflow) | — | — | `1242c43c` |

Decisions and surprises the chunks reported:

- Chunk 1: the T001 and T051 commands put `backend/tests`, `python_sdk/tests` and `cli/tests` in one pytest session. That fails with `ImportPathMismatchError` because all three folders are packages named `tests`. Every later chunk ran them as three sessions, as CI does.
- Chunk 2:
  - `resolve_inside` returns `None` for a path outside the clone, as the task says. Plan §1 says it raises.
  - T009 needed one more operation file, `get_driver_version_source_path.graphql`.
  - `uv run invoke generate` fails at its frontend step on this host (`ELIFECYCLE`). Every chunk ran `pnpm --ignore-workspace run codegen` directly instead.
- Chunk 3:
  - The T019 test calls `load_flow_from_entrypoint(..., use_placeholder_flow=False)`, as Prefect's flow engine does. It also replaces Prefect's template resolvers, so `run_steps` does not start a temporary Prefect server.
  - `contracts/action-deployments.md` gives `5f3c2a1` as the digest of `drivers/infrahub`. The real digest is `c8dc0c0`. The documentation uses the real value; the contract still has the wrong one.
- Chunk 4: "git-sourced" in T022 is tested as "`source_repository` is set".
- Chunk 5:
  - The E2E git server image needed `git init --bare /git/driver-collection.git` in `backend/tests/e2e/fixtures/git-server/Dockerfile`.
  - `dev/knowledge/backend/e2e-testing.md` was updated for the new repository.
  - The fixture still builds the shared tag `git-daemon:latest`. If a session on another branch rebuilds it at the same time, the new repository can be missing from it.
- Chunk 6: the frontend tests ran in `node:22-slim` on a copy of `frontend/` without `node_modules`.
- Chunk 7:
  - The "leads outside the repository" message names the first part of the path that is a symlink leading outside.
  - A load from the repository root without `driver.styrmin.yml` now fails in the provider, so the `test_provider_commit_sha.py` test repository got a root `driver.styrmin.yml`.
  - `porcelain.add` follows a symlink to `/etc`, so the tests stage files with `repo.get_worktree().stage()`.
- Chunk 8: T040 extends the chunk 3 test instead of adding a duplicate.
- Chunk 9:
  - The changelog fragment is in the past tense, as `dev/guidelines/changelog.md` asks. It also names the new refusal of root loads whose driver files are symlinks to paths outside the repository.
  - ADR-076 was free on all 142 refs. On 2026-10-18 develop took ADR-0076, so the rebase renumbered this ADR to ADR-079.
  - `CONTEXT.md` had one drift, now fixed: only git loads register actions.
  - The "Key Files" table in `hooks-and-actions.md` has 15 links that were already broken before this change.
- Chunks 11 and 12: the logs went to the session scratchpad, not to `/tmp/e2e-028-*.log`. The `shard_general` API run took 8 minutes 11 seconds and the UI run 6 minutes 40 seconds.

## Tasks not completed

None. All 54 tasks in `tasks.md` are `[X]`.

## Local-pass evidence

Environment context is "local host, Python 3.14, SQLite in memory" for backend rows unless the row says otherwise. The final backend run at 2026-10-17T19:53:37+00:00 (`4939 passed, 3 skipped`) passed every backend row below on the head tree. Each row gives the run that the chunk recorded. Paths are relative to the repository root.

Command keys:

- `[U2]`: `uv run pytest backend/tests/unit/services/driver backend/tests/unit/workflows/test_git_source_commit_pinning.py backend/tests/unit/workflows/test_user_action_registration.py backend/tests/unit/services/reconciliation/test_remediation.py backend/tests/functional/graphql/test_application_driver_version_propagation.py -v -p no:cacheprovider`
- `[U3]`: `uv run pytest backend/tests/unit/workflows/test_git_source_commit_pinning.py backend/tests/unit/workflows/test_user_action_registration.py backend/tests/unit/workflows/test_action_driver_directory.py backend/tests/unit/services/reconciliation/test_remediation.py -v -p no:cacheprovider`
- `[U7a]`: `uv run pytest backend/tests/unit/services/driver -v -p no:cacheprovider`
- `[U7b]`: `uv run pytest backend/tests/functional -v -p no:cacheprovider`
- `[U8]`: `uv run pytest backend/tests/unit/workflows backend/tests/functional/graphql/test_application_driver_version_propagation.py -v -p no:cacheprovider`
- `[UR]`: `uv run pytest backend/tests/unit/services/driver backend/tests/functional/graphql/test_application_driver_version_propagation.py -v -p no:cacheprovider`
- `[FE]`: `pnpm exec vitest run --reporter=verbose src/__tests__/drivers/LoadDriverDrawer.test.tsx src/__tests__/driver-detail/DriverDetailPage.test.tsx src/__tests__/drivers/driverList.test.ts`
- `[E5]`: `export STYRMIN_IMAGE_VER=e2e028-1792262388 && docker compose build server`, then `uv run pytest backend/tests/e2e/test_driver_version_reselection.py -m "ci and shard_general" -k api-chromium -v -s --pdb`, with stdin held open by `sleep infinity`
- `[E11]`: `export STYRMIN_IMAGE_VER=e2e028-1792264606; docker compose build server`, then `uv run pytest backend/tests/e2e -m "ci and shard_general" -k api-chromium -v -s --pdb`, with stdin from `exec 3< <(sleep infinity)`
- `[E12]`: `export STYRMIN_IMAGE_VER=e2e028-1792265291; docker compose build server`, then `uv run pytest backend/tests/e2e -m "ci and shard_general" -k ui-chromium -v -s --pdb <&3`

| Test id | Type | Run command | Passed at (ISO 8601) | Environment context | Verbatim pass line |
|---------|------|-------------|----------------------|---------------------|--------------------|
| `backend/tests/unit/services/driver/test_driver_directory.py::test_normalise_accepts_every_written_form` (9 cases) | unit | `[U2]` | 2026-10-17T18:20:07+00:00 | local | `...::test_normalise_accepts_every_written_form[./drivers/infrahub/-drivers/infrahub] PASSED` (and 8 more) |
| `...test_driver_directory.py::test_normalise_refuses_with_the_rule` (5 cases) | unit | `[U2]` | 2026-10-17T18:20:07+00:00 | local | `...::test_normalise_refuses_with_the_rule[../x-'../x'-it contains a '..' segment] PASSED` (and 4 more) |
| `...test_driver_directory.py::test_resolve_inside_accepts_the_root_and_a_folder` | unit | `[U2]` | 2026-10-17T18:20:07+00:00 | local | `...::test_resolve_inside_accepts_the_root_and_a_folder PASSED` |
| `...test_driver_directory.py::test_resolve_inside_follows_a_symlink_that_stays_inside` | unit | `[U2]` | 2026-10-17T18:20:07+00:00 | local | `...::test_resolve_inside_follows_a_symlink_that_stays_inside PASSED` |
| `...test_driver_directory.py::test_resolve_inside_refuses_paths_that_leave_the_root` (4 cases) | unit | `[U2]` | 2026-10-17T18:20:07+00:00 | local | `...::test_resolve_inside_refuses_paths_that_leave_the_root[drivers/evil] PASSED` (and 3 more) |
| `...test_driver_directory.py::test_redact_repository_url_removes_user_info` (8 cases, 3 added in the review fix) | unit | `[UR]` | 2026-10-17T19:50:04+00:00 | local | `...::test_redact_repository_url_removes_user_info[https://user:token@[bad/x.git-https://[bad/x.git] PASSED` (and 7 more) |
| Doctests of `backend/styrmin_backend/services/driver/driver_directory.py` | unit (doctest) | `uv run pytest --doctest-modules backend/styrmin_backend/services/driver/driver_directory.py -v -p no:cacheprovider` | 2026-10-17T19:50:12+00:00 | local | `5 passed` |
| Doctests of `driver_directory.py` and `labels.py` | unit (doctest) | `uv run pytest --doctest-modules backend/styrmin_backend/services/driver/driver_directory.py backend/styrmin_backend/services/driver/labels.py -q` | 2026-10-17T19:15:15+00:00 | local | `6 passed in 0.05s` |
| `backend/tests/unit/services/driver/test_loaders_git_commit_sha.py::test_git_load_from_driver_directory_stores_source_path` | unit | `[U2]` | 2026-10-17T18:20:07+00:00 | local | `...::test_git_load_from_driver_directory_stores_source_path PASSED` |
| `...test_loaders_git_commit_sha.py::test_git_load_same_commit_and_driver_directory_returns_same_row` | unit | `[U2]` | 2026-10-17T18:20:07+00:00 | local | `...::test_git_load_same_commit_and_driver_directory_returns_same_row PASSED` |
| `...test_loaders_git_commit_sha.py::test_git_load_from_root_and_driver_directory_are_separate_rows` | unit | `[U2]` | 2026-10-17T18:20:07+00:00 | local | `...::test_git_load_from_root_and_driver_directory_are_separate_rows PASSED` |
| `...test_loaders_git_commit_sha.py`: the 4 existing tests that use the changed fake provider | unit | `[U2]` | 2026-10-17T18:20:07+00:00 | local | `...::test_git_load_records_resolved_commit_sha PASSED` (and 3 more) |
| `...test_loaders_git_commit_sha.py::test_git_load_registers_actions_with_the_driver_directory` (2 cases, review fix) | unit | `[UR]` | 2026-10-17T19:50:04+00:00 | local | `...::test_git_load_registers_actions_with_the_driver_directory[driver-directory] PASSED`, `...[root] PASSED` |
| `backend/tests/functional/graphql/test_application_driver_version_propagation.py::test_driver_directory_propagates_from_git_load_to_db` | functional (propagation) | `[U2]` | 2026-10-17T18:20:07+00:00 | local | `...::test_driver_directory_propagates_from_git_load_to_db PASSED` |
| `...test_application_driver_version_propagation.py::test_driver_directory_projects_through_application_driver_query` | functional (propagation) | `[U2]` | 2026-10-17T18:20:07+00:00 | local | `...::test_driver_directory_projects_through_application_driver_query PASSED` |
| `...test_application_driver_version_propagation.py::test_refused_driver_directory_returns_validation_error_and_stores_nothing` | functional | `[U7b]` | 2026-10-17T18:57:32+00:00 | local | `...::test_refused_driver_directory_returns_validation_error_and_stores_nothing PASSED` |
| `...test_application_driver_version_propagation.py::test_missing_driver_directory_error_names_directory_and_commit` | functional | `[U7b]` | 2026-10-17T18:57:32+00:00 | local | `...::test_missing_driver_directory_error_names_directory_and_commit PASSED` |
| `...test_application_driver_version_propagation.py::test_root_load_stores_null_and_reloads_return_the_same_version` | functional | `[U8]` | 2026-10-17T19:00:56+00:00 | local | `...::test_root_load_stores_null_and_reloads_return_the_same_version PASSED [ 98%]` |
| `backend/tests/unit/workflows/test_git_source_commit_pinning.py::test_set_directory_step_follows_the_clone_directory` (2 cases, changed) | unit | `[U3]` | 2026-10-17T18:28:20+00:00 | local | `...::test_set_directory_step_follows_the_clone_directory[555d1558a741f3b4c9d0e1f2a3b4c5d6e7f80912-lab-driver-a-555d155/backend] PASSED` (and 1 more) |
| `...test_git_source_commit_pinning.py::test_builder_with_driver_directory_adds_set_working_directory` | unit | `[U3]` | 2026-10-17T18:28:20+00:00 | local | `...::test_builder_with_driver_directory_adds_set_working_directory PASSED` |
| `...test_git_source_commit_pinning.py::test_builder_without_driver_directory_keeps_one_pull_step` | unit | `[U3]` | 2026-10-17T18:28:20+00:00 | local | `...::test_builder_without_driver_directory_keeps_one_pull_step PASSED` |
| `backend/tests/unit/workflows/test_user_action_registration.py::test_registration_with_driver_directory_is_tagged_and_named` | unit | `[U3]` | 2026-10-17T18:28:20+00:00 | local | `...::test_registration_with_driver_directory_is_tagged_and_named PASSED` |
| `...test_user_action_registration.py::test_registration_with_driver_directory_and_no_fingerprint` | unit | `[U3]` | 2026-10-17T18:28:20+00:00 | local | `...::test_registration_with_driver_directory_and_no_fingerprint PASSED` |
| `...test_user_action_registration.py::test_two_driver_directories_at_one_commit_register_distinct_deployments` | unit | `[U3]` | 2026-10-17T18:28:20+00:00 | local | `...::test_two_driver_directories_at_one_commit_register_distinct_deployments PASSED` |
| `...test_user_action_registration.py::test_registration_without_driver_directory_has_no_directory_tag` (extended in chunk 8) | unit | `[U8]` | 2026-10-17T19:00:56+00:00 | local | `...::test_registration_without_driver_directory_has_no_directory_tag PASSED [ 77%]` |
| `...test_user_action_registration.py::test_lookup_with_driver_directory_filters_on_its_tag` | unit | `[U3]` | 2026-10-17T18:28:20+00:00 | local | `...::test_lookup_with_driver_directory_filters_on_its_tag PASSED` |
| `...test_user_action_registration.py::test_lookup_without_driver_directory_skips_driver_directory_deployments` | unit | `[U3]` | 2026-10-17T18:28:20+00:00 | local | `...::test_lookup_without_driver_directory_skips_driver_directory_deployments PASSED` |
| `...test_user_action_registration.py::test_lookup_without_driver_directory_returns_none_when_only_tagged_match` | unit | `[U3]` | 2026-10-17T18:28:20+00:00 | local | `...::test_lookup_without_driver_directory_returns_none_when_only_tagged_match PASSED` |
| `...test_user_action_registration.py::test_lookup_prefers_the_newest_matching_deployment` (changed: `tags=[]` added to its mocks) | unit | `[U3]` | 2026-10-17T18:28:20+00:00 | local | `...::test_lookup_prefers_the_newest_matching_deployment PASSED` |
| `backend/tests/unit/workflows/test_action_driver_directory.py::test_action_imports_a_module_of_its_driver_directory` | unit | `[U3]` | 2026-10-17T18:28:20+00:00 | local | `...::test_action_imports_a_module_of_its_driver_directory PASSED` |
| `...test_action_driver_directory.py::test_action_cannot_import_a_module_outside_its_driver_directory` | unit | `[U3]` | 2026-10-17T18:28:20+00:00 | local | `...::test_action_cannot_import_a_module_outside_its_driver_directory PASSED` |
| `backend/tests/unit/services/reconciliation/test_remediation.py::test_every_user_action_lookup_receives_the_driver_directory` (3 cases; the 3 existing fakes changed too) | unit | `[U3]` | 2026-10-17T18:28:20+00:00 | local | `...::test_every_user_action_lookup_receives_the_driver_directory[git-driver-directory] PASSED` (and 2 more) |
| `backend/tests/unit/services/driver/test_provider.py::test_driver_directory_symlinked_outside_is_refused` | unit | `[U7a]` | 2026-10-17T18:56:11+00:00 | local | `...::test_driver_directory_symlinked_outside_is_refused PASSED` |
| `...test_provider.py::test_driver_file_symlinked_outside_is_refused` (6 cases; replaces 2 chunk 7 tests) | unit | `[UR]` | 2026-10-17T19:50:04+00:00 | local | `...::test_driver_file_symlinked_outside_is_refused[actions.py-driver-directory] PASSED` (and 5 more) |
| `...test_provider.py::test_driver_directory_symlinked_inside_is_accepted` | unit | `[U7a]` | 2026-10-17T18:56:11+00:00 | local | `...::test_driver_directory_symlinked_inside_is_accepted PASSED` |
| `...test_provider.py::test_missing_or_file_driver_directory_does_not_exist` (2 cases) | unit | `[U7a]` | 2026-10-17T18:56:11+00:00 | local | `...::test_missing_or_file_driver_directory_does_not_exist[drivers/missing] PASSED` (and 1 more) |
| `...test_provider.py::test_driver_directory_without_driver_specification_is_reported` | unit | `[U7a]` | 2026-10-17T18:56:11+00:00 | local | `...::test_driver_directory_without_driver_specification_is_reported PASSED` |
| `...test_provider.py::test_root_without_driver_specification_is_reported` | unit | `[U7a]` | 2026-10-17T18:56:11+00:00 | local | `...::test_root_without_driver_specification_is_reported PASSED` |
| `...test_provider.py::test_refused_driver_directory_raises_before_the_clone` | unit | `[U7a]` | 2026-10-17T18:56:11+00:00 | local | `...::test_refused_driver_directory_raises_before_the_clone PASSED` |
| `...test_provider.py::test_clone_failure_message_has_no_user_info` | unit | `[U7a]` | 2026-10-17T18:56:11+00:00 | local | `...::test_clone_failure_message_has_no_user_info PASSED` |
| `...test_provider.py::test_malformed_repository_url_fails_with_a_driver_loading_error` (2 cases, review fix) | unit | `[UR]` | 2026-10-17T19:50:04+00:00 | local | `...::test_malformed_repository_url_fails_with_a_driver_loading_error[https://[bad/x.git] PASSED` (and 1 more) |
| `backend/tests/unit/services/driver/test_provider_commit_sha.py`: 4 tests (test repository changed) | unit | `[U7a]` | 2026-10-17T18:56:11+00:00 | local | `...::test_provider_resolves_head_commit_sha PASSED` (and 3 more) |
| `python_sdk/tests/test_drivers.py::test_load_version_sends_driver_directory` | unit | `uv run pytest python_sdk/tests/test_drivers.py -v -p no:cacheprovider` | 2026-10-17T18:34:33+00:00 | local | `PASSED [ 80%]` |
| `python_sdk/tests/test_drivers.py::test_load_version_without_driver_directory_omits_the_variable` | unit | same | 2026-10-17T18:34:33+00:00 | local | `PASSED [100%]` |
| `cli/tests/test_drivers.py::test_drivers_load_version` (changed) | unit | `uv run pytest cli/tests/test_drivers.py -v -p no:cacheprovider` | 2026-10-17T18:34:34+00:00 | local | `PASSED [ 30%]` |
| `cli/tests/test_drivers.py::test_drivers_load_version_with_driver_directory` | unit | same | 2026-10-17T18:34:34+00:00 | local | `PASSED [ 40%]` |
| `cli/tests/test_drivers.py::test_drivers_load_version_help_lists_driver_directory` | unit | same | 2026-10-17T18:34:34+00:00 | local | `PASSED [ 50%]` |
| `cli/tests/test_drivers.py::test_drivers_load_version_renders_label_and_full_commit_sha` (changed) | unit | same | 2026-10-17T18:34:34+00:00 | local | `PASSED [ 90%]` |
| `LoadDriverDrawer.test.tsx > LoadDriverDrawer > sends the driver directory when one is entered` | unit (frontend) | `[FE]` | 2026-10-17T18:48:28+00:00 | `docker.io/node:22-slim`, copy of `frontend/` in the scratchpad | `✓ src/__tests__/drivers/LoadDriverDrawer.test.tsx > LoadDriverDrawer > sends the driver directory when one is entered 151ms` |
| `... > sends no driver directory when the field is empty` | unit (frontend) | `[FE]` | 2026-10-17T18:48:28+00:00 | as above | `✓ ... > sends no driver directory when the field is empty 116ms` |
| `... > sends no driver directory when the field is spaces only` | unit (frontend) | `[FE]` | 2026-10-17T18:48:28+00:00 | as above | `✓ ... > sends no driver directory when the field is spaces only 132ms` |
| `... > shows the load error and keeps the entered values when the load fails` | unit (frontend) | `[FE]` | 2026-10-17T18:48:28+00:00 | as above | `✓ ... > shows the load error and keeps the entered values when the load fails 159ms` |
| `DriverDetailPage.test.tsx > DriverDetailPage > shows the driver directory row in the Overview tab for a git version loaded from one` | unit (frontend) | `[FE]` | 2026-10-17T18:48:28+00:00 | as above | `✓ src/__tests__/driver-detail/DriverDetailPage.test.tsx > DriverDetailPage > shows the driver directory row in the Overview tab for a git version loaded from one 12ms` |
| `... > shows no driver directory row for a git version without a driver directory` | unit (frontend) | `[FE]` | 2026-10-17T18:48:28+00:00 | as above | `✓ ... > shows no driver directory row for a git version without a driver directory 6ms` |
| `... > shows no driver directory row for a local version` | unit (frontend) | `[FE]` | 2026-10-17T18:48:28+00:00 | as above | `✓ ... > shows no driver directory row for a local version 7ms` |
| `driverList.test.ts > versionSource > appends the driver directory of a git source as repo @ branch · dir` | unit (frontend) | `[FE]` | 2026-10-17T18:48:28+00:00 | as above | `✓ src/__tests__/drivers/driverList.test.ts > versionSource > appends the driver directory of a git source as \`repo @ branch · dir\` 0ms` |
| `... > appends the driver directory of a git source without a branch as repo · dir` | unit (frontend) | `[FE]` | 2026-10-17T18:48:28+00:00 | as above | `✓ ... > appends the driver directory of a git source without a branch as \`repo · dir\` 0ms` |
| `backend/tests/e2e/test_driver_version_reselection.py::test_driver_version_reselection[api-chromium]` (single test, early run) | e2e | `[E5]` | 2026-10-17T18:43:40Z (started 18:40:00Z) | vCluster `pytest-fffb29b8-ba8c-4d5e-a83d-4346251da1e9`, kubeconfig `/tmp/pytest-of-root/pytest-1948/vcluster0/kubeconfig` | `PASSED`; `1 passed, 1 skipped, 2 deselected, 1 warning in 218.29s (0:03:38)` |
| `shard_general [api-chromium]`, all 17 selected tests, including `test_driver_version_reselection[api-chromium]` and every test using the changed `styrmin_resources` and `git_server` fixtures | e2e | `[E11]` | 2026-10-17T19:25:20+00:00 (started 19:17:06) | vCluster `pytest-ed6d5d60-2d48-483a-8518-0d75e9f14e3e`, kubeconfig `/tmp/pytest-of-root/pytest-1960/vcluster0/kubeconfig` | `==== 17 passed, 10 skipped, 174 deselected, 1 warning in 491.21s (0:08:11) =====` |
| `shard_general [ui-chromium]`, all 21 selected tests, including `test_ui_smoke.py::test_driver_detail_inspects_versions_via_tabs[ui-chromium]` (changed) and `test_driver_version_reselection[ui-chromium]` | e2e | `[E12]` | 2026-10-17T19:35:03+00:00 (started 19:28:20) | vCluster `pytest-11eb92e1-41a4-4b3c-bc3b-b1de7c432c53`, kubeconfig `/tmp/pytest-of-root/pytest-1961/vcluster0/kubeconfig` | `===== 21 passed, 6 skipped, 174 deselected, 1 warning in 400.59s (0:06:40) =====` |

The verbatim `PASSED` and `SKIPPED` line of every node in the two shard runs is in [e2e-evidence.md](e2e-evidence.md). The 10 tests skipped in the API run are marked `ui_only`, and the 6 skipped in the UI run are marked `api_only`.

Full suites on the final tree (chunk 10, plus the final backend run):

- Backend unit and functional, 19:53:37: `4939 passed, 3 skipped`.
- `python_sdk/tests`: `299 passed`.
- `cli/tests`: `2 failed, 397 passed`. The 2 failures are the root-only telemetry tests (`test_unwritable_dir_falls_back_to_ephemeral_id`, `test_commands_succeed_under_unwritable_dir`). They fail on every branch on this host and pass in CI.
- Frontend: Vitest `1054 passed`, `pnpm lint` 0 errors, `tsc -b` exits 0.

The E2E runs used the tree at `c93a92ea` and `7a68e96e`, before the review fix `1242c43c`. That fix changes only `redact_repository_url` for URLs that `urlsplit` cannot parse, plus tests and one sentence in `dev/knowledge/`. The E2E git server URLs are parseable `git://` URLs, so the fix does not change the code paths the E2E tests ran.

## Review findings

Six review aspects ran on `44aface8..7a68e96e`: code, comments, tests, errors, types and simplify. No aspect reported a Critical or High finding. The orchestrator raised one Medium finding to High because this branch introduced it.

| Severity | Aspect | File | Summary | Outcome |
|----------|--------|------|---------|---------|
| High (raised from Medium) | errors | `backend/styrmin_backend/services/driver/provider.py:92`, `driver_directory.py:142` | `redact_repository_url` ran before the clone `try`. `urlsplit` raises `ValueError` on `https://[bad/x.git`, so the load failed with `INTERNAL_ERROR` instead of `VALIDATION_ERROR`, a change from the base commit. | Fixed in `1242c43c` |
| Medium | tests | `backend/tests/unit/services/driver/test_provider.py` | No test refused an `actions.py` that is a symlink to a file outside the clone (FR-008). | Fixed in `1242c43c`: one test covers the 3 driver files for a root load and a driver directory load |
| Medium | tests | `backend/styrmin_backend/services/applications.py:243` | No unit test checked that a git load passes the driver directory to `register_user_action` (FR-010). | Fixed in `1242c43c` |
| Medium | comments | `dev/knowledge/backend/hooks-and-actions.md:186` | The page said `git_clone` clones into `/source`. Prefect 3.8.6 clones into a temporary `prefect-flow-run-*` folder. | Fixed in `1242c43c`. `research.md:36` has the same claim and was not edited. |
| Medium | types | `backend/styrmin_backend/services/driver/models/structure/source.py:21` | Only the provider constructor keeps `GitSource.driver_directory` normalised. The model has no validator and can be changed after it is created. | Deferred |
| Medium | types | `backend/styrmin_backend/workflows/manager.py:136` | `get_user_action_deployment_id(driver_directory=None)` treats a missing argument as a root load. A future caller that leaves it out gets `None`, and the hooks are skipped without an error. | Deferred |
| Medium | errors | `backend/styrmin_backend/services/driver/loaders.py:85-95` | Pre-existing. `actions.py` is optional even when the driver specification declares actions. A driver directory without `actions.py` loads, and its actions fail only when they run. | Deferred |
| Medium | errors | `backend/styrmin_backend/services/driver/parsers.py:31` | Pre-existing. A YAML syntax error in a git load shows the temporary clone path and does not name the repository, branch, commit or driver directory. | Deferred |
| Low | code | `driver_directory.py:66-75`, `services/user.py:42` | `{{ … }}` in a driver directory reaches the Prefect `set_working_directory` step without escaping, and Prefect fills in templates there. An admin who enters such a value could make the action run from a different folder, or put a filled-in value in a log. Refusing `{{`, `}}` and control characters would close this. | Deferred: changes the refusal rule of FR-006 |
| Low | code | `backend/styrmin_backend/workflows/manager.py:168-184` | The filter that drops `directory/` deployments runs after `read_deployments`, which returns at most 200 rows. Uncertain: the reviewer found no realistic case for rows that have a fingerprint. | Deferred |
| Low | types | `DriverDetailPage.tsx:278`, `driverList.ts:29`, `cli/.../drivers.py:38`, `labels.py:88` | Each surface decides in its own way whether `sourcePath` is a driver directory. | Deferred |
| Low | types | `backend/styrmin_backend/workflows/models.py:208-211` | `GitSourceWorkflowDefinition.get_function`, used only by the test executor, ignores `set_directory` and `commit_sha`. | Deferred |
| Low | types | `driver_directory.py:34` | Control characters other than NUL, and spaces inside a segment, are accepted. | Deferred |
| Low | comments | `provider.py:149,155-158,178` | When a driver file is the symlink, the message names the driver directory. A root load reads "Driver directory 'the repository root'". | Deferred |
| Low | comments | `CONTEXT.md:110`, `labels.py:79-81` | `CONTEXT.md` says `source_path` is "empty" for a root load, but the code stores `None`. It also defines the driver directory of a local load as the server path, which the docstring of `labels.py` contradicts. | Deferred |
| Low | comments | `services/applications.py:410-411` | The `Raises:` section lists only the refusal before the clone. | Deferred |
| Low | comments | `docs/docs/drivers/loading-drivers.md:169` | The page says messages show no username. scp-style URLs keep `git@`. | Deferred |
| Low | errors | `parsers.py:48`, `provider.py:104-117`, `manager.py:174-183` | These are pre-existing or edited by this branch: a `values.j2.yml` folder gives `INTERNAL_ERROR`; dulwich `NotGitRepository()` leaves an empty message after the colon; a lookup that returns `None` is not logged. | Deferred |
| Low | tests | `test_driver_version_reselection.py:183`; E2E | No assertion that the setup actions of a driver directory version ran, or that `original_binding` equals the session driver version. `_first_link_outside` has no test for a symlink in a parent folder. | Deferred |
| Advisory | simplify | `provider.py:105-186`; test fixtures; `cli/.../drivers.py:37-39` | Compute the root or driver directory phrasing once in `provider.py`. Share one git repository helper across three test fixtures. Remove a redundant check in the CLI. | Deferred |

## Autonomous decisions

- Chunking:
  - Phase 3 has 18 tasks, so it was split into three chunks: action deployments, SDK and CLI, and E2E.
  - Phase 8 was split into three chunks: lint and suites, the API E2E run, and the UI E2E run with the quickstart.
  - Phase 1 (1 task) stayed its own chunk.
- Chunk 5 ran `test_driver_version_reselection[api-chromium]` alone before the full shard runs. This gave early evidence that the session fixture change works. The same test ran again in T052 and T053.
- The E2E run of `test_ui_smoke.py::test_driver_detail_inspects_versions_via_tabs[ui-chromium]` (T035) waited for the full UI shard run in T053, which passed. Chunk 6 did not run it.
- The six review aspects ran in parallel, not one at a time. They only read files, so they could not conflict, and this saved time.
- Review triage:
  - The malformed-URL finding was raised to High because this branch introduced it.
  - Three Medium findings were fixed even though the rule requires fixes only for High and above. Two are test gaps on FR-008 and FR-010. The third is a wrong statement in `dev/knowledge/`. All three were small.
  - The `{{ … }}` template finding was deferred because closing it changes the refusal rule in FR-006, research R-005 and the error contract. It needs a decision.
- The design documents were not edited, as this workflow requires:
  - `contracts/action-deployments.md` still shows the wrong digest example `5f3c2a1`; the real digest is `c8dc0c0`.
  - `research.md:36` still has the `/source` claim.
- The changelog fragment does not use the present-tense text given in T049. It follows the past-tense rule in `dev/guidelines/changelog.md` and also names the new refusal of root loads whose driver files are symlinks to paths outside the repository. Whether that refusal also needs its own `517.security.md` fragment is not decided.

## Suggested next steps

1. Decide whether to refuse `{{`, `}}` and control characters in driver directories. This closes the Prefect template finding, but it changes FR-006 and the error contract.
2. Fix the two documentation drifts in the design documents if they should stay accurate: the digest example in `contracts/action-deployments.md` and the clone folder in `research.md:36`.
3. Decide about the two Medium type findings:
   - Add a validator to `GitSource.driver_directory`.
   - Make `driver_directory` a required argument of `get_user_action_deployment_id`.
4. Open a pull request. CI runs the other E2E shards. Each of them now loads the session driver from a driver directory, and none of them has run on this branch yet.
5. Decide whether the root-load symlink refusal needs a separate `changelog/517.security.md` fragment.
6. Run `speckit-opsmill-extract` on `specs/028-git-driver-directory` to move the knowledge into `dev/`.
