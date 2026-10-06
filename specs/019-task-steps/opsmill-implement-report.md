# Implementation report: steps and failure causes for tasks, backups and restores

## 1. Run summary

- Feature: 019-task-steps, [spec.md](spec.md), [plan.md](plan.md), [tasks.md](tasks.md)
- Spec directory: `/root/emdash/worktrees/styrmin-55123dec/fac-feat-background-task-visibility-i4lwl/specs/019-task-steps`
- Base commit: `675e057a`
- Head commit before this report: `83fe442f`
- Wall-clock time: 2026-10-06T12:01:32Z to about 20:50Z (about 8 hours 50 minutes)
- Run status: DONE. All 111 tasks are checked, every new or changed test has a recorded passing run, and the three review findings rated high or medium that were fixed have passing tests.
- Totals: 26 implementation chunks plus 2 review-fix runs, 111 tasks done, 0 partial, 0 blocked, 28 commits before this report.

Abbreviation used in the evidence table: `$SP` is the session scratchpad `/tmp/claude-0/-root-emdash-worktrees-styrmin-55123dec-fac-feat-background-task-visibility-i4lwl/0a805e37-240f-451b-a90e-85491204ebbd/scratchpad`.

## 2. Chunk ledger

Each chunk ran in a new subagent with no shared conversation. "Done" counts tasks the subagent reported as done and that are checked in tasks.md.

| Chunk | Tasks | Done / partial / blocked | Commit | Decisions and surprises the subagent reported |
|---|---|---|---|---|
| 1. Phase 1 Setup | T001–T003 | 3 / 0 / 0 | `5de99e80` | Alembic head was `d1e2f3a4b5c6`. `cd frontend && pnpm install` resolved to the outer `/root/emdash` pnpm workspace and removed 312 packages from `/root/emdash/node_modules` (no tracked files changed). Later chunks used `pnpm --ignore-workspace` with Node 22. |
| 2. Phase 2, storage and domain | T004–T010 | 7 / 0 / 0 | `e409867b` | Revision `e2f3a4b5c6d7`. Enums are stored as upper-case names, as the existing enums are; data-model.md says lower-case. The one-parent check uses `CASE` so it also works on SQLite. `Task.create` now stores its `status` argument. Steps tests use a PostgreSQL test container. |
| 3. Phase 2, recorder and GraphQL | T011–T016 | 6 / 0 / 0 | `83f92f56` | A pending step cannot go straight to succeeded. `outputTruncated` is `Boolean! = false`. New `@isActionsServiceAccount` directive. |
| 4. Phase 2, flow reporter and job variables | T017–T021 | 5 / 0 / 0 | `dcafad62` | `uv run invoke generate` and `lint` work only with Node 22 first on `PATH`. |
| 5. US1, task types | T026–T028 | 3 / 0 / 0 | `abad0a55` | No enum, migration or schema change was needed. The `update_instance` branch of `_ensure_ingress_controller` cannot be reached today. |
| 6. US1, flow steps | T024, T030–T033 | 5 / 0 / 0 | `491b7a0b` | Step keys are defined once in `backend/styrmin_backend/domain/steps.py`. Found an existing `KeyError: 'name'` on failed Jobs (fixed in chunk 11). |
| 7. US1, operator-phase steps | T022, T023, T025, T029, T034–T037 | 8 / 0 / 0 | `353cb271` | The phase history runs in a savepoint of the status-report transaction. The update handler body moved unchanged into `_roll_out_spec_update`. |
| 8. US1, GraphQL read model | T038–T041 | 4 / 0 / 0 | `117e2c11` | The timeline loads the steps of all its tasks in one query. |
| 9. US1, web step list | T042–T045 | 4 / 0 / 0 | `acf5b2f4` | Data attributes for the E2E UI driver are listed in the commit. |
| 10. US1, E2E | T046–T048 | 3 / 0 / 0 | `97178139` | The SDK timeline operation was extended for the API driver. The "every task has a result" check was deferred to T076 because `Task.result` did not exist yet. |
| 11. US2, command output | T049, T052–T055 | 5 / 0 / 0 | `d8caa0e4` | `read_job_output_tail` raises `JobOutputUnreadableError` instead of returning `None`; the subagent changed the contract and the T049 text. `run_job` now raises `JobFailedError` instead of `RuntimeError`. Fixed the existing `KeyError: 'name'`. |
| 12. US2, operator HelmRelease generation | T050, T056, T057 | 3 / 0 / 0 | `e25b0355` | Reason and message come from FluxCD `Released=False` when `Ready=False`, because after a rollback `Ready` hides the cause; research D5 said "copy Ready". `tests/unit/operator/test_crd_drift.py` is never collected (its folder name clashes with the Python `operator` module). |
| 13. US2, failures, attempts and rollbacks | T051, T058, T059 | 3 / 0 / 0 | `029f0259` | An operator retry is detected from `HelmReleaseReady` returning to Unknown/Progressing. The attempt count can be one too high across two 60-second checks. |
| 14. US2, web failure causes | T060–T061 | 2 / 0 / 0 | `1e2d0d2b` | Added wording the contract does not give: "Hide output", "Loading output…", "The output could not be loaded: …", "No output was recorded for this step." |
| 15. US2, E2E | T062–T064 | 3 / 0 / 0 | `86eac69e` | Versions `0.9.0+raise` and `0.9.0+command`, because `0.9.0-raise` is not a valid PEP 440 version (T062 text changed). Pod reasons now skip finished pods. Set `STYRMIN_OPERATOR_DEPLOYMENT_READY_TIMEOUT=270` in the E2E values. Observed that FluxCD reports a rolled-back override change Ready (fixed by review fix H1). |
| 16. US3, results and superseding | T065–T068 | 4 / 0 / 0 | `7e67a4b9` | A family member with no steps counts by its `Task.status` (one line added to data-model.md). |
| 17. US3, links and result fields | T069–T073 | 5 / 0 / 0 | `1ae646e1` | The timeline makes 4 queries for 1 or 20 tasks. |
| 18. US3, web results and links | T074–T075 | 2 / 0 / 0 | `c69b0257` | Added wording: "Started tasks" and "This task is not in this deployment's timeline." |
| 19. US3, E2E | T076–T077 | 2 / 0 / 0 | `b809b5db` | The upgrade hook starts 2 tasks, not 3, because `upgrade_deployment_version` to the version already set starts no task (plan.md changed). Fixed a result bug: a task with a failed HelmRelease step stayed `RUNNING`; the subagent changed spec.md FR-006, data-model.md, research D8 and CONTEXT.md to state the rule. |
| 20. US4, live view | T078–T083 | 6 / 0 / 0 | `2b8bcb59` | The timeline makes 5 queries. New steps appeared 0.7 to 4.8 seconds after they started. `operator:services` gets 60 extra seconds in the latency check. |
| 21. US5, SDK and CLI | T084–T088 | 5 / 0 / 0 | `a4b55f12` | The HelmRelease E2E test now sets the image through SDK `apply(wait=True)`. |
| 22. US6, Velero flows | T089–T095 | 7 / 0 / 0 | `0c8b9af3` | `FailedValidation` is now terminal, so a failed restore ends in seconds. Found that the Restore record's error message was empty (fixed by review fix M1). |
| 23. US6, API, web and SDK | T096–T099 | 4 / 0 / 0 | `35063b5c` | Backup and restore lists load steps in one query. |
| 24. US6, E2E | T100–T101 | 2 / 0 / 0 | `0d872c45` | Velero's error: "Velero restore failed validation: Error retrieving backup: can't find backup styrmin/&lt;name&gt;: …". |
| 25. Polish, documentation | T102–T107 | 6 / 0 / 0 | `db752313` | ADR number 0060. Five changelog fragments for issue 2. The docs site builds. |
| Review fix 1 (H3, M1) | none | not applicable | `f16a092b` | No code path sets `FAILED` on a task that should read `SUPERSEDED`. |
| Review fix 2 (H1) | none | not applicable | `828a219c` | Evidence from helm-controller v1.1.0 in `$SP/evidence/`. |
| 26. Polish, gates | T108–T111 | 4 / 0 / 0 | `83fe442f` | The first `shard_general` API run failed during `docker compose build` because three services built the same new image tag at once; creating the tag first fixed it. |

## 3. Tasks not completed

None. All 111 tasks in tasks.md are checked.

## 4. Local-pass evidence

Every row below is a run observed to pass. Unit and frontend rows group the tests of one file or one run; the subagent reported each test id in that run as `PASSED`. E2E rows show the last run with `--pdb` after the last change to the test, and the final shard run (without `--pdb`, so a failure would not stop the shard), which ran after every code change.

### Unit, functional and frontend tests

| Test id | Type | Run command | Passed at (ISO 8601) | Environment context | Verbatim pass line |
|---|---|---|---|---|---|
| `backend/tests/unit/db/test_steps_migration.py`, `backend/tests/unit/steps/test_step_repository.py`, `test_task_repository_steps.py` | unit | `timeout 600 uv run pytest backend/tests/unit/db/test_steps_migration.py backend/tests/unit/steps -v -rs` | 2026-10-06T12:19:01Z | SQLite and a `postgres:16-alpine` test container | `31 passed, 1 skipped in 4.67s` |
| `backend/tests/unit/steps/test_recorder.py`, `test_reads.py`, `test_step_graphql.py`, `backend/tests/unit/api/test_actions_service_account_permission.py` | unit | `uv run pytest backend/tests/unit/steps backend/tests/unit/api -v -p no:randomly` | 2026-10-06T12:37:16Z | SQLite and PostgreSQL 16 test container | `214 passed, 1 skipped in 13.69s` |
| `backend/tests/unit/agent/test_step_reporter.py` | unit | `uv run pytest backend/tests/unit/agent/test_step_reporter.py -v` | 2026-10-06T12:48:29Z | n/a | `15 passed in 0.07s` |
| `backend/tests/unit/agent/tasks/test_run_deployment_or_fail.py`, `test_apply_state_flow.py` | unit | `uv run pytest backend/tests/unit/agent/tasks/test_run_deployment_or_fail.py backend/tests/unit/agent/tasks/test_apply_state_flow.py -v` | 2026-10-06T12:48:35Z | n/a | `11 passed in 3.12s` |
| `backend/tests/functional/graphql/test_step_propagation.py` | functional | `uv run pytest backend/tests/functional/graphql/test_step_propagation.py -v` | 2026-10-06T12:48:40Z | SQLite in memory | `20 passed in 1.50s` |
| `backend/tests/unit/services/test_task_types.py` and the 3 changed `apply_state` stub tests | unit | `uv run pytest backend/tests/unit/services/test_task_types.py backend/tests/unit/services/test_update_deployment_noop.py backend/tests/unit/services/test_update_deployment_service_rename.py backend/tests/unit/services/test_deploy_skip_initial_reconcile.py -v -p no:cacheprovider` | 2026-10-06T12:56:20Z | fake repositories | `21 passed in 0.21s` |
| `test_remediation_flow_steps.py`, `test_apply_state_flow.py`, `test_run_job_flows.py`, `test_internal_flow_steps.py`, `test_task_callback_steps.py` | unit | `uv run pytest <these 5 files> -v` | 2026-10-06T13:11:27Z | SQLite, PostgreSQL test container, Prefect test server | `54 passed in 11.01s` |
| `backend/tests/unit/steps/test_operator_history.py` | unit | `uv run pytest backend/tests/unit/steps/test_operator_history.py -v` | 2026-10-06T13:28:44Z | SQLite and PostgreSQL test container | `54 passed in 6.06s` |
| `backend/tests/unit/services/test_delete_deployment_steps.py` | unit | `uv run pytest backend/tests/unit/services/test_delete_deployment_steps.py -v` | 2026-10-06T13:28:53Z | SQLite and PostgreSQL test container | `6 passed in 2.07s` |
| `backend/tests/unit/test_styrmin_deployment_handlers_status.py` | unit | `uv run pytest backend/tests/unit/test_styrmin_deployment_handlers_status.py -v` | 2026-10-06T13:28:57Z | n/a | `20 passed in 0.17s` |
| `backend/tests/unit/agent/test_status_reporter.py::TestCollectCrdStatus` | unit | `uv run pytest "backend/tests/unit/agent/test_status_reporter.py::TestCollectCrdStatus" -v` | 2026-10-06T13:28:59Z | n/a | `7 passed in 0.09s` |
| `test_job_logs.py`, `test_execute_commands_output.py`, `test_kubernetes_job_failure.py`, `test_run_job_flows.py`, `test_recorder.py` | unit | `uv run pytest backend/tests/unit/agent/test_job_logs.py backend/tests/unit/agent/test_execute_commands_output.py backend/tests/unit/agent/test_kubernetes_job_failure.py backend/tests/unit/agent/tasks/test_run_job_flows.py backend/tests/unit/steps/test_recorder.py -v -p no:randomly` | 2026-10-06T14:08:27Z | fake Kubernetes API served by aiohttp | `126 passed in 11.26s` |
| `test_styrmin_deployment_helmrelease_generation.py`, `test_styrmin_deployment_timer.py` | unit | `uv run pytest backend/tests/unit/test_styrmin_deployment_helmrelease_generation.py backend/tests/unit/test_styrmin_deployment_timer.py -v` | 2026-10-06T14:36:33Z | n/a | `53 passed in 0.23s` |
| `tests/unit/operator/test_crd_drift.py` (a copy, because the repository never collects it) | unit | `uv run pytest <copy in $SP> -q` | 2026-10-06T14:2xZ (minute not recorded) | n/a | `3 passed in 0.21s` |
| `test_operator_history_failures.py`, `test_step_failure_propagation.py` | unit, functional | `uv run pytest backend/tests/unit/steps/test_operator_history_failures.py backend/tests/functional/graphql/test_step_failure_propagation.py -v` | 2026-10-06T14:59:01Z | SQLite and PostgreSQL test container | `90 passed, 1 warning in 9.22s` |
| `test_results.py`, `test_supersede.py` | unit | `uv run pytest backend/tests/unit/steps/test_results.py backend/tests/unit/steps/test_supersede.py -v` | 2026-10-06T16:05:13Z | SQLite and PostgreSQL test container | `54 passed in 4.19s` |
| `test_action_primitives_started_by.py`, `test_deployment_timeline_steps.py`, `test_step_graphql.py`, `test_update_deployment_noop.py`, `test_task_result_propagation.py`, `test_action_primitives_auth.py` | unit, functional | `uv run pytest <these 6 files> -v -p no:randomly` | 2026-10-06T16:23:06Z | SQLite and PostgreSQL test container | `42 passed in 4.27s` |
| `test_reads.py`, `test_deployment_timeline_steps.py`, `test_task_steps_propagation.py` (no-report cases) | unit, functional | `uv run pytest <these 3 files> -q` | 2026-10-06T17:23:34Z | SQLite and PostgreSQL test container | `56 passed in 5.21s` |
| `test_velero_client_poll.py` | unit | `uv run pytest backend/tests/unit/agent/test_velero_client_poll.py -v` | 2026-10-06T18:13:12Z | n/a | `18 passed in 0.03s` |
| `test_backup_workflow_ttl.py`, `test_restore_workflow_failure_handler.py` | unit | `uv run pytest <both files> -v` | 2026-10-06T18:13:18Z | n/a | `24 passed in 0.20s` |
| `test_backup_restore_steps_propagation.py`, `test_step_repository.py` | functional, unit | `uv run pytest backend/tests/functional/graphql/test_backup_restore_steps_propagation.py backend/tests/unit/steps/test_step_repository.py -v` | 2026-10-06T18:26:48Z | PostgreSQL test container | `27 passed, 1 skipped in 3.68s` |
| `test_results.py`, `test_task_result_propagation.py`, `test_deployment_timeline_steps.py`, `test_restore_steps.py`, `test_backup_component_steps.py`, `test_restore_workflow_failure_handler.py`, `test_backup_workflow_ttl.py` (after review fix 1) | unit, functional | `uv run pytest <these 7 files> -v` | 2026-10-06T19:13:27Z | n/a | `130 passed in 4.68s` |
| `test_styrmin_deployment_helmrelease_generation.py`, `test_operator_history_failures.py` and all other backend tests (after review fix 2) | unit, functional | `uv run pytest backend/tests/unit backend/tests/functional -n 8 -q` | 2026-10-06T20:07:40Z | n/a | `3749 passed, 3 skipped, 22 warnings in 25.66s` |
| `backend/tests/unit/test_e2e_driver_conformance.py` (all changed and new driver tests) | unit | `uv run pytest backend/tests/unit/test_e2e_driver_conformance.py -v` | 2026-10-06T18:51:48Z | n/a | `24 passed in 0.17s` |
| Final backend merge gate | unit, functional | `PATH=/root/.local/node22/bin:$PATH uv run invoke test` | 2026-10-06T20:15:48Z | n/a | `3767 passed, 3 skipped` |
| `python_sdk/tests/test_tasks.py`, `test_deployments.py`, `test_backups.py` and the rest of the SDK suite | unit | `uv run pytest -v python_sdk/tests` | 2026-10-06T20:12:56Z | n/a | `246 passed in 0.30s` |
| `cli/tests/test_tasks.py`, `cli/tests/test_deployments.py` and the rest of the CLI suite | unit | `uv run pytest -v cli/tests` | 2026-10-06T20:13:19Z | n/a | `2 failed, 350 passed`. The 2 failures are the telemetry tests that also fail on `675e057a` when run as root (see section 5). |
| `StepList.test.tsx`, `DeploymentTimelineSteps.test.tsx` | frontend | `cd frontend && PATH=/root/.local/node22/bin:$PATH pnpm --ignore-workspace exec vitest run src/__tests__/deployment-detail/StepList.test.tsx src/__tests__/deployment-detail/DeploymentTimelineSteps.test.tsx --reporter=verbose` | 2026-10-06T13:44:16Z | Node 22, Vitest 4.1, jsdom | `Tests  24 passed (24)` |
| `StepListFailures.test.tsx` | frontend | `cd frontend && PATH=/root/.local/node22/bin:$PATH pnpm --ignore-workspace exec vitest run src/__tests__/deployment-detail/StepListFailures.test.tsx --reporter=verbose` | 2026-10-06T15:05:35Z | Node 22, jsdom | `Tests  7 passed (7)` |
| `TaskResult.test.tsx`, `DeploymentTimelineSteps.test.tsx` | frontend | `pnpm --ignore-workspace exec vitest run <both files> --reporter=verbose` | 2026-10-06T16:29:29Z (about) | Node 22, jsdom | `Tests 20 passed (20)` |
| `StepListLive.test.tsx`, `TaskResult.test.tsx` | frontend | `pnpm --ignore-workspace exec vitest run <both files>` | 2026-10-06T17:23:40Z | Node 22, jsdom | `Tests 20 passed (20)` |
| `BackupRestoreSteps.test.tsx`, `StepList.test.tsx` (`showTimes`), `BackupExpiry.test.tsx` | frontend | `PATH=/root/.local/node22/bin:$PATH pnpm --ignore-workspace exec vitest run <3 files> --reporter=verbose` | 2026-10-06T18:27:00Z | Node 22, jsdom | `Tests  28 passed (28)` |
| Final frontend suite | frontend | `cd frontend && PATH=/root/.local/node22/bin:$PATH pnpm --ignore-workspace test` | 2026-10-06T20:12:08Z | Node 22, jsdom | `Tests 830 passed (830)` |

### E2E tests

| Test id | Type | Run command | Passed at (ISO 8601) | Environment context | Verbatim pass line |
|---|---|---|---|---|---|
| `backend/tests/e2e/test_deployment_timeline.py::test_deployment_timeline_has_entries[api-chromium]` | e2e | `sleep infinity \| uv run pytest "<node>" -v -s --pdb 2>&1 \| tee <log>` | 2026-10-06T16:58:15Z | `pytest-8bc1e7aa-6e4b-4b76-9dca-fda6509c798d`, `/tmp/pytest-of-root/pytest-645/vcluster0/kubeconfig` | `1 passed, 1 warning in 119.62s (0:01:59)` |
| same node, final shard run | e2e | `STYRMIN_IMAGE_VER=local-019-general-api-2 uv run pytest -v -rA --durations=0 -m "ci and shard_general" -k "api-chromium" --basetemp=$SP/shards/general-api-2/bt backend/tests/e2e` | 2026-10-06T20:18:24Z | `pytest-83cc742e-ef46-436e-9ee0-42d0425fd25b`, `$SP/shards/general-api-2/bt/vcluster0/kubeconfig` | `backend/tests/e2e/test_deployment_timeline.py::test_deployment_timeline_has_entries[api-chromium] PASSED [ 38%]` |
| `backend/tests/e2e/test_deployment_timeline.py::test_deployment_timeline_has_entries[ui-chromium]` | e2e | `sleep infinity \| uv run pytest "<node>" -v -s --pdb 2>&1 \| tee <log>` | 2026-10-06T17:00:44Z | `pytest-91a7829c-3b36-4e47-aeb5-4e89be9599f5`, `/tmp/pytest-of-root/pytest-646/vcluster0/kubeconfig` | `1 passed, 1 warning in 135.52s (0:02:15)` |
| same node, final shard run | e2e | `STYRMIN_IMAGE_VER=local-019-general-ui-2 uv run pytest -v -rA --durations=0 -m "ci and shard_general" -k "ui-chromium" --basetemp=$SP/shards/general-ui-2/bt backend/tests/e2e` | 2026-10-06T20:32:16Z | `pytest-da891ace-369c-42de-b8c4-4265895e3062`, `$SP/shards/general-ui-2/bt/vcluster0/kubeconfig` | `backend/tests/e2e/test_deployment_timeline.py::test_deployment_timeline_has_entries[ui-chromium] PASSED [ 38%]` |
| `backend/tests/e2e/test_deploy_app.py::test_upgrade_simple_app[api-chromium]` | e2e | `sleep infinity \| uv run pytest "<node>" -v -s --pdb --basetemp=$SP/upg1/bt` | 2026-10-06T19:44:26Z | `pytest-cbcd7d41-e58f-4b13-a926-0bcc289cf5bf`, `$SP/upg1/bt/vcluster0/kubeconfig` | `1 passed, 1 warning in 209.46s (0:03:29)` |
| same node, final shard run | e2e | shard `general-api-2` command above | 2026-10-06T20:18:23Z | `pytest-83cc742e-ef46-436e-9ee0-42d0425fd25b` | `backend/tests/e2e/test_deploy_app.py::test_upgrade_simple_app[api-chromium] PASSED [ 26%]` |
| `backend/tests/e2e/test_deploy_app.py::test_upgrade_simple_app[ui-chromium]` | e2e | `sleep infinity \| uv run pytest "<node>" -v -s --pdb 2>&1 \| tee upgrade-live-ui-1.log` | 2026-10-06T17:25:33Z | `pytest-5ef8ee7e-8079-4391-96df-f3541c3fed0e`, `/tmp/pytest-of-root/pytest-649/vcluster0/kubeconfig` | `1 passed, 1 warning in 216.07s (0:03:36)` |
| same node, final shard run | e2e | shard `general-ui-2` command above | 2026-10-06T20:32:16Z | `pytest-da891ace-369c-42de-b8c4-4265895e3062` | `backend/tests/e2e/test_deploy_app.py::test_upgrade_simple_app[ui-chromium] PASSED [ 26%]` |
| `backend/tests/e2e/test_task_steps.py::test_hook_action_error_shows_failed_step[api-chromium]`, `test_command_output_on_failed_step[api-chromium]`, `test_prerequisite_failure_shows_attempts[api-chromium]`, `test_helmrelease_failure_shows_fluxcd_reason[api-chromium]` | e2e | `sleep infinity \| uv run pytest backend/tests/e2e/test_task_steps.py -k api-chromium -v -s --pdb --basetemp=$SP/api4/bt` | 2026-10-06T20:04:10Z | `pytest-4497f438-6ca5-40a9-ad18-83e4077b4215`, `$SP/api4/bt/vcluster0/kubeconfig` | `…test_helmrelease_failure_shows_fluxcd_reason[api-chromium] PASSED`; `4 passed, 4 deselected, 1 warning in 697.23s (0:11:37)` |
| the same 4 nodes, final shard run | e2e | shard `general-api-2` command above | 2026-10-06T20:21:48Z, 20:22:16Z, 20:23:08Z, 20:30:49Z | `pytest-83cc742e-ef46-436e-9ee0-42d0425fd25b` | `PASSED [ 69%]`, `PASSED [ 73%]`, `PASSED [ 76%]`, `PASSED [ 80%]` |
| `backend/tests/e2e/test_task_steps.py::test_helmrelease_failure_shows_fluxcd_reason[ui-chromium]` | e2e | `sleep infinity \| uv run pytest "<node>" -v -s --pdb --basetemp=$SP/ui2/bt` | 2026-10-06T20:05:51Z | `pytest-9a5b03f2-f9e0-402e-a0e8-9913533187af`, `$SP/ui2/bt/vcluster0/kubeconfig` | `1 passed, 1 warning in 556.82s (0:09:16)` |
| same node, final shard run | e2e | shard `general-ui-2` command above | 2026-10-06T20:41:17Z | `pytest-da891ace-369c-42de-b8c4-4265895e3062` | `backend/tests/e2e/test_task_steps.py::test_helmrelease_failure_shows_fluxcd_reason[ui-chromium] PASSED [ 80%]` |
| `backend/tests/e2e/test_backup_restore.py::test_backup_and_restore_lifecycle[api-chromium]` | e2e | `sleep infinity \| uv run pytest "…lifecycle[api-chromium]" "…fails_velero_step[api-chromium]" -v -s --pdb > backup-api-1.log 2>&1` | 2026-10-06T18:41:54Z | `pytest-8d3ae917-5027-427a-bfa1-8337f85eb414`, `/tmp/pytest-of-root/pytest-670/vcluster0/kubeconfig` | `2 passed, 1 warning in 327.26s` |
| same node, final shard run | e2e | `STYRMIN_IMAGE_VER=local-019-backup-api-1 uv run pytest -v -rA --durations=0 -m "ci and shard_backup" -k "api-chromium" --basetemp=$SP/shards/backup-api-1/bt backend/tests/e2e` | 2026-10-06T20:19:35Z | `pytest-63a3ceb7-202f-4898-86c0-be7ecf097fef`, `$SP/shards/backup-api-1/bt/vcluster0/kubeconfig` | `backend/tests/e2e/test_backup_restore.py::test_backup_and_restore_lifecycle[api-chromium] PASSED [ 20%]` |
| `backend/tests/e2e/test_backup_restore.py::test_backup_and_restore_lifecycle[ui-chromium]` | e2e | `sleep infinity \| uv run pytest "…lifecycle[ui-chromium]" -v -s --pdb > backup-ui-2.log 2>&1` | 2026-10-06T18:48:03Z | `pytest-92786c72-40d0-41c6-b62c-91fa8da8b8d3`, `/tmp/pytest-of-root/pytest-672/vcluster0/kubeconfig` | `1 passed, 1 warning in 249.29s` |
| same node, final shard run | e2e | `STYRMIN_IMAGE_VER=local-019-backup-ui-1 uv run pytest -v -rA --durations=0 -m "ci and shard_backup" -k "ui-chromium" --basetemp=$SP/shards/backup-ui-1/bt backend/tests/e2e` | 2026-10-06T20:27:42Z | `pytest-a0801c73-0a61-45cb-9274-201272a0d3ab`, `$SP/shards/backup-ui-1/bt/vcluster0/kubeconfig` | `backend/tests/e2e/test_backup_restore.py::test_backup_and_restore_lifecycle[ui-chromium] PASSED [ 20%]` |
| `backend/tests/e2e/test_backup_restore.py::test_restore_of_removed_velero_backup_fails_velero_step[api-chromium]` | e2e | `sleep infinity \| uv run pytest "<node>" -v -s --pdb 2>&1 \| tee restore-fail-m1-1.log` | 2026-10-06T19:14:17Z | `pytest-bc3c74ea-9d97-4480-8e7d-e7845220e438`, `/tmp/pytest-of-root/pytest-674/vcluster0/kubeconfig` | `1 passed, 1 warning in 186.55s (0:03:06)` |
| same node, final shard run | e2e | shard `backup-api-1` command above | 2026-10-06T20:22:05Z | `pytest-63a3ceb7-202f-4898-86c0-be7ecf097fef` | `backend/tests/e2e/test_backup_restore.py::test_restore_of_removed_velero_backup_fails_velero_step[api-chromium] PASSED [ 80%]` |
| `backend/tests/e2e/test_deployment_image_override.py`, 3 nodes `[api-chromium]` (not changed by the feature; run to check review fix H1) | e2e | `sleep infinity \| uv run pytest backend/tests/e2e/test_deployment_image_override.py -k api-chromium -v -s --pdb --basetemp=$SP/img3/bt` | 2026-10-06T19:55:28Z | `pytest-8556f64e-498d-4011-8848-e24364a41459` | `3 passed, 3 deselected, 1 warning in 366.10s (0:06:06)` |
| `backend/tests/e2e/test_deployment_image_override.py`, `[ui-chromium]` nodes (same reason) | e2e | `sleep infinity \| uv run pytest backend/tests/e2e/test_deployment_image_override.py -k ui-chromium -v -s --pdb --basetemp=$SP/img2/bt` | 2026-10-06T19:54:39Z | `pytest-76f10303-0024-483f-896a-4a3177b4b130` | `2 passed, 1 skipped, 3 deselected, 1 warning in 348.91s (0:05:48)` |

Whole shards (T110), once per variant, after every code change:

| Shard and variant | Start and end (UTC) | vCluster id | Result |
|---|---|---|---|
| `shard_general`, `api-chromium` | 20:13:44Z to 20:30:57Z | `pytest-83cc742e-ef46-436e-9ee0-42d0425fd25b` | `20 passed, 6 skipped, 142 deselected, 1 warning in 1029.36s (0:17:09)` |
| `shard_general`, `ui-chromium` | 20:27:46Z to 20:41:25Z | `pytest-da891ace-369c-42de-b8c4-4265895e3062` | `18 passed, 8 skipped, 142 deselected, 1 warning in 816.34s (0:13:36)` |
| `shard_backup`, `api-chromium` | 20:15:40Z to 20:24:10Z | `pytest-63a3ceb7-202f-4898-86c0-be7ecf097fef` | `5 passed, 163 deselected, 1 warning in 507.62s (0:08:27)` |
| `shard_backup`, `ui-chromium` | 20:23:48Z to 20:30:57Z | `pytest-a0801c73-0a61-45cb-9274-201272a0d3ab` | `3 passed, 2 skipped, 163 deselected, 1 warning in 426.88s (0:07:06)` |

Every skip in the shards comes from an `api_only` or `ui_only` marker. The full rows and the shard script are in [e2e-evidence.md](e2e-evidence.md).

## 5. Review findings

The review was done by hand in the orchestrator's context, without the `speckit-review-run` skill and without subagents (see section 6). The fixes were made by subagents. Severity: High, Medium, Low, Info.

| Severity | File | Finding | Status |
|---|---|---|---|
| High (H1) | `backend/styrmin_backend/operator/handlers/styrmin_deployment.py` | After FluxCD rolled back an update that changes only post-render overrides (image or environment overrides), FluxCD reported the release Ready again, so the operator reported Ready, the failed HelmRelease step succeeded, the task read `SUCCEEDED` and the deployment showed Running although the override never ran. | Fixed in `828a219c`. The operator now fails the rollout when FluxCD counted a failed release for the current generation and the newest release in its history directly follows a failed one. |
| High (H3) | `backend/styrmin_backend/services/steps/results.py` | The task result ignored `Task.status` once a task had steps. A flow that failed before its first USER-flow step read `SUCCEEDED`, and a running task read `SUCCEEDED` between the plan step and the next step. | Fixed in `f16a092b`. `Task.status` `PENDING` or `RUNNING` adds `RUNNING`, `FAILED` adds `FAILED`. |
| Medium (M1) | `backend/styrmin_backend/workflows/templates/backup.py` | A restore or backup that Velero rejected in validation ended with an empty error message on the Restore or Backup record. | Fixed in `f16a092b`. The record gets Velero's reason, or the step's text. |
| Medium (H2) | `backend/styrmin_backend/services/deployment_status.py`, `services/steps/operator_history.py` | `reportDeploymentStatuses` stays on the unauthenticated allow-list (existing TODO #396) and now also changes operator-phase steps. `recordStep` is limited to `styrmin-actions`, but this path is not, so a caller without a token can change the step record of any task whose instance belongs to the deployment it names. | Deferred. Needs the service-account work of #396. Documented in ADR-060 and the docs. |
| Medium (M2) | `python_sdk/src/styrmin_sdk/resources/deployments.py` | The SDK waits at most 300 seconds, which equals the operator's default readiness timeout, so in production `apply --wait` usually reports a wait timeout instead of the failed HelmRelease step. The E2E test uses 420 seconds. | Deferred. Needs a decision on the default wait. |
| Medium (M3) | `backend/tests/e2e/fixtures/styrmin-values.yaml` | The E2E values set `STYRMIN_OPERATOR_DEPLOYMENT_READY_TIMEOUT=270` for the whole suite. With 300 seconds the operator times out at the same moment FluxCD's 5-minute timeout rolls back the release and removes the failing pods, so pod reasons were caught only by chance. The production default of 300 seconds has the same race. | Deferred. Needs a decision on the production default. |
| Low (L1) | `backend/styrmin_backend/services/steps/recorder.py` | The check that stops a repeated `SUCCEEDED` event from superseding again reads the step before it is locked, so two concurrent `SUCCEEDED` events for one step could both run the supersede step. | Deferred. |
| Low (L2) | `backend/tests/e2e/test_deploy_app.py` | The 15-second latency check logs a warning and skips itself when an earlier test already upgraded the shared deployment. | Deferred. |
| Low (L3) | `backend/styrmin_backend/services/steps/results.py` | `_OPEN_STATUSES` is not used. | Deferred. |
| Low (L9) | `backend/styrmin_backend/agent/steps/reporter.py` | Step errors use Prefect's `format_exception`, which includes the tracebacks of chained exceptions. Step errors are visible to every signed-in user. | Deferred. |
| Info (L4) | `tests/unit/operator/test_crd_drift.py` | Never collected, because its folder name clashes with the Python `operator` module. Existed before this feature. | Not changed. |
| Info (L5) | `python_sdk/tests`, `cli/tests` | Running both folders in one pytest command stops at collection with `ImportPathMismatchError`. CI runs them separately. | Not changed. |
| Info (L6) | `cli/tests` | `test_unwritable_dir_falls_back_to_ephemeral_id` and `test_commands_succeed_under_unwritable_dir` fail when run as root. They also fail on `675e057a`. | Not changed. |
| Info (L7) | `backend/styrmin_backend/api/schema/mutation.py` | Any driver action that holds the action token can record steps for any task, backup or restore; the token is not limited to one parent. The design accepts this. | Not changed. |
| Info (L8) | `backend/styrmin_backend/services/deployment.py` | `deleteDeployment` raises `CustomResourceNotFound` when the deployment's CR no longer exists, for example after a failed restore. Probably existed before this feature. | Not changed. |
| Info (L10) | task callback | A crashed or cancelled Prefect flow sends no accepted callback, so its task stays `RUNNING` without end. Existed before this feature; documented in ADR-060. | Not changed. |

## 6. Autonomous decisions

- Review method: the `speckit-review-run` skill was not used. A saved instruction from the user forbids code-review skills and subagents during code reviews, so the orchestrator reviewed the diff by hand. The review covered the recorder, the operator phase history, the operator's HelmRelease check, the status-report path, the GraphQL authorization, the orchestration flows, the backup and restore workflows and the task result calculation. The frontend components and the test files were covered only by their tests and were not read line by line.
- Order of the last steps: the review fixes ran before chunk 26 (T108–T111), so the format and lint checks, the merge gate and both whole shards tested the fixed code.
- Chunk splits: Phase 2 was split into 3 chunks, Phase 3 into 6, Phase 4 into 5, Phase 5 into 4, Phase 8 into 3 and Phase 9 into 2, along files and test types.
- Specification changes made by subagents during implementation, which the user should confirm:
  - spec.md FR-006, data-model.md, research D8 and CONTEXT.md: a pending step that waits behind a failed step does not count as running; `Task.status` counts in the task result (review fix H3).
  - plan.md and quickstart.md: the upgrade hook of simple-app starts 2 tasks, not 3.
  - contracts/flow-step-reporter.md and T049: `read_job_output_tail` raises `JobOutputUnreadableError` instead of returning `None`.
  - T062: test versions `0.9.0+raise` and `0.9.0+command`.
  - research D5 and contracts/operator-status.md: `HelmReleaseReady` takes its reason from FluxCD `Released=False`; the rollback rule of review fix H1.
- E2E timeout: `STYRMIN_OPERATOR_DEPLOYMENT_READY_TIMEOUT=270` in the E2E values (finding M3).
- E2E evidence paths: the later E2E runs used `--basetemp` under the session scratchpad instead of `/tmp/pytest-of-root/`, so their kubeconfig paths differ from the form in the evidence rule.
- Side effect outside the worktree: chunk 1 removed 312 packages from `/root/emdash/node_modules`. Running `pnpm install` in `/root/emdash` with Node 24 restores them. This run did not change `/root/emdash`.
- Stale processes: the orchestrator stopped 2 log-polling loops that chunk 12 left running.

## 7. Suggested next steps

1. Decide findings M2 (SDK default wait of 300 seconds) and M3 (operator readiness timeout and the 270-second E2E value).
2. Confirm the specification changes listed in section 6.
3. Restore `/root/emdash/node_modules` with `pnpm install` in `/root/emdash` and Node 24.
4. Open a pull request with the `pr` skill. Call out the high-risk areas listed in tasks.md: the database revision, the operator and the status reporter, the Prefect flow dispatch and action tokens, and the authorization of `recordStep`. Also call out finding H2 (#396).
5. Plan the deferred low findings L1, L2, L3 and L9, and the information items L8 and L10, as follow-up issues.
6. Run `speckit-opsmill-extract` to move the knowledge of this feature into the project documentation.
