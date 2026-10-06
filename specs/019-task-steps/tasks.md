---

description: "Task list for steps and failure causes for tasks, backups and restores"
---

# Tasks: Steps and Failure Causes for Tasks, Backups and Restores

**Input**: Design documents from `specs/019-task-steps/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)

**Tests**: Required. Constitution §V requires unit tests, a GraphQL propagation test for every schema change, and an E2E test observed to pass locally, with evidence recorded in `specs/019-task-steps/e2e-evidence.md`.

**Organization**: Tasks are grouped by user story so each story can be built and tested on its own after the foundational phase.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: The user story the task belongs to (US1 to US6 in [spec.md](spec.md))
- Paths are relative to the repository root. Research decisions are cited as D1 to D19 ([research.md](research.md)).

## E2E evidence rule (applies to every "Run … and record evidence" task)

Run each E2E node with `--pdb` (in a non-interactive shell: `sleep infinity | uv run pytest <node> -v -s --pdb 2>&1 | tee /tmp/pdb.log`). For each new or changed node, append to `specs/019-task-steps/e2e-evidence.md`: (a) the pytest node id, (b) the exact command, (c) the ISO 8601 time of the passing run, (d) the vCluster fixture id and kubeconfig path under `/tmp/pytest-of-*/pytest-*/`, (e) the verbatim `PASSED …` line. A node that has only been skipped, or never run against a cluster, is not done.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Packages and baseline for the feature

- [X] T001 Confirm the environment: run `uv sync`, `cd frontend && pnpm install`, `uv run invoke pre-commit-install`; record the current Alembic head revision id (from `backend/styrmin_backend/db/migrations/versions/`) as the `down_revision` for T005
- [X] T002 [P] Create empty packages: `backend/styrmin_backend/services/steps/__init__.py`, `backend/styrmin_backend/agent/steps/__init__.py`, `backend/styrmin_backend/api/definitions/step/__init__.py`, `backend/tests/unit/steps/__init__.py`
- [X] T003 [P] Create `specs/019-task-steps/e2e-evidence.md` with a header and an empty table (columns: node id, command, passing time, vCluster id and kubeconfig, PASSED line)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Storage, recorder, `recordStep` and the flow step reporter, which every story uses

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T004 Add to `backend/styrmin_backend/db/models.py`: enums `StepStatus` (pending, running, succeeded, failed, superseded) and `StepKind` (plan, hook, resource_write, operator_phase, command, restore, backup_component); table `Step` with every column of [data-model.md](data-model.md) "New table `step`", the `ck_step_one_parent` check, and three partial unique indexes on (parent, `key`); on `Task`, `instance_id` (FK `applicationinstance.id`, `ON DELETE SET NULL`, indexed) and `started_by_step_id` (FK `step.id`, `ON DELETE SET NULL`, `use_alter=True`, indexed)
- [X] T005 Write the Alembic revision `backend/styrmin_backend/db/migrations/versions/<rev>_add_steps.py` with `down_revision` from T001: create both enum types, the `step` table, constraints and indexes, and the two `task` columns; the downgrade drops `task.started_by_step_id`, `task.instance_id` and their foreign keys first, then the `step` table and the enum types (follow `dev/guides/database-migrations.md`; check autogenerate shows no remaining diff)
- [X] T006 Add a migration round-trip test in `backend/tests/unit/db/test_steps_migration.py`: upgrade to head, downgrade one step, upgrade again against the test Postgres container, asserting the `step` table and both `task` columns exist only after upgrade (reuse the Alembic config helper from `backend/styrmin_backend/cli/db.py` as `backend/tests/unit/cli/test_db.py` does)
- [X] T007 [P] Add domain models to `backend/styrmin_backend/domain/models.py`: `StepStatus`, `StepKind`, `TaskResult`, `StepError` (`attempt`, `message`, `occurred_at`), `Step` (table fields plus `task_id | backup_id | restore_id`); add `instance_id` and `started_by_step_id` to `Task` and let `Task.create` accept them and `status`
- [X] T008 [P] Add `StepNotFoundError` (`NOT_FOUND`, "Step not found") and `InvalidStepRecordError` (`VALIDATION_ERROR`) subclassing `ServiceError` in `backend/styrmin_backend/services/steps/exceptions.py`
- [X] T009 Create `backend/styrmin_backend/repository/steps.py` (`SQLModelStepRepository`): `get(id)`, `find_by_key(parent, key, for_update=False)`, `insert_if_absent(step)` with `INSERT … ON CONFLICT DO NOTHING` on the partial unique index, `list_by_task_ids(ids)`, `list_by_backup(id)`, `list_by_restore(id)`, `list_open_operator_steps_for_deployment(deployment_id, exclude_task_id)` (join `task`), `save(step)`; order lists by `started_at` nulls last, then `created_on`; register `steps` in `backend/styrmin_backend/services/unit_of_work.py`
- [X] T010 Extend `backend/styrmin_backend/repository/tasks.py`: map `instance_id` and `started_by_step_id` in `_to_model`/`_to_entity`; add `find_by_instance(instance_id)`, `find_latest_by_type(deployment_id, type)`, `find_started_by_steps(step_ids)`
- [X] T011 Implement the recorder core in `backend/styrmin_backend/services/steps/recorder.py`: `open_step(parent, key, name, kind, at)`, `succeed_step(step, at)`, `fail_step(step, error, at, output=None)` appending to `errors`, `record_output(step, output, truncated)` keeping the last 200 lines and 64 KiB and setting `output_truncated`, `fail_open_flow_steps(parent, message, at)`, and `record_event(input, uow)` (the `recordStep` entry point: validates `stepId` versus parent and key, raises `StepNotFoundError`, `TaskNotFoundError`, `BackupNotFoundError`, `RestoreNotFoundError`, `InvalidStepRecordError`); enforce the state rules of [data-model.md](data-model.md) "State transitions of a step" with `SELECT … FOR UPDATE`; ignore and log forbidden transitions; never set `ended_at` before `started_at`
- [X] T012 Write recorder unit tests in `backend/tests/unit/steps/test_recorder.py` against the real repository: each event, idempotent `STARTED`, forbidden transitions ignored, output truncation by lines and bytes, `fail_open_flow_steps` only touches flow kinds, validation errors for each bad input of [data-model.md](data-model.md) "Validation rules"
- [X] T013 [P] Implement `backend/styrmin_backend/services/steps/reads.py`: `get_step(step_id)`, `list_steps(parent)`, and `no_report_since(step, last_polled_at, now)` per D9 (running `operator_phase` step, last report or step start older than 60 seconds)
- [X] T014 Create `backend/styrmin_backend/api/definitions/step/model.py`: Strawberry enums `StepStatus`, `StepKind`, `StepEvent`, `TaskResult`; types `StepError` and `Step` with every field of [contracts/graphql.md](contracts/graphql.md) "New types" (`durationSeconds`, `error`, `hasOutput` derived) and `strawberry.Private` view fields (`superseded_by_view`, `started_tasks_view`, `no_report_since_view`) whose resolvers fall back to queries when unset; input `RecordStepInput`
- [X] T015 Add `IsActionsServiceAccount` to `backend/styrmin_backend/api/auth/permissions.py` (accepts only the user named `ACTIONS_SERVICE_ACCOUNT_USERNAME` from `backend/styrmin_backend/services/auth/bootstrap.py`, else `FORBIDDEN`) and unit tests in `backend/tests/unit/api/test_actions_service_account_permission.py`
- [X] T016 Add `Query.step(stepId)` in `backend/styrmin_backend/api/schema/query.py` and `Mutation.recordStep(input)` with `PermissionExtension([RequiresRole(Role.READ_WRITE), IsActionsServiceAccount()])` in `backend/styrmin_backend/api/schema/mutation.py`; update `backend/tests/unit/api/test_mutation_authz_coverage.py` if it lists mutations
- [X] T017 Implement the flow step reporter in `backend/styrmin_backend/agent/steps/reporter.py` with `backend/styrmin_backend/agent/steps/record_step.graphql` and a `load_query` helper in `backend/styrmin_backend/agent/steps/queries.py`: `StepReporter.from_env()` (no-op without `STYRMIN_TOKEN` or a parent variable), `step(key, name, kind)` async context manager, `record_output(step_id, output, truncated)`, `fail_step(key, error, output=None)`; send `occurredAt`; log and swallow network and GraphQL errors ([contracts/flow-step-reporter.md](contracts/flow-step-reporter.md))
- [X] T018 Replace `api_token_job_variables` with `action_job_variables(token, *, task_id=None, backup_id=None, restore_id=None, step_id=None)` in `backend/styrmin_backend/agent/tasks/utils.py`; give `run_driver_action_or_fail` a `step_id` argument that forwards `STYRMIN_TOKEN` and `STYRMIN_TASK_ID` from the current environment and adds `STYRMIN_STEP_ID`; let `Remediation.apply(api_token, task_id)` in `backend/styrmin_backend/services/reconciliation/remediation.py` pass `STYRMIN_TASK_ID`; update every caller
- [X] T019 [P] Write unit tests for the reporter and job variables in `backend/tests/unit/agent/test_step_reporter.py` and extend `backend/tests/unit/agent/tasks/test_run_deployment_or_fail.py` (variables forwarded and added; no-op mode; errors swallowed; `step()` records `FAILED` and re-raises)
- [X] T020 Regenerate `schema.graphql` (`uv run styrmin export graphql-schema schema.graphql`), run `uv run invoke generate` and `uv run invoke validate-graphql`
- [X] T021 Write propagation tests in `backend/tests/functional/graphql/test_step_propagation.py` with operations `backend/tests/functional/graphql/operations/record_step.graphql` and `get_step.graphql`: `recordStep` for each event and each parent type reaches the database and returns the `Step`; rejected without a token, as `READ_ONLY`, and as a `READ_WRITE` or `ADMIN` person; `Query.step` returns every field of a seeded step to a `READ_ONLY` user

**Checkpoint**: Steps can be stored, recorded through the API by the actions account, and read.

---

## Phase 3: User Story 1 - View the ordered steps of a deployment task (Priority: P1) 🎯 MVP

**Goal**: Every task type in the timeline shows its ordered steps with status and duration, and its real type.

**Independent Test**: Upgrade simple-app; the upgrade entry (type `upgrade_instance`) lists plan, CR write, upgrade hook and the four operator phases in start order, each completed step with a duration; a task from before the feature shows "No steps recorded for this task."

### Tests for User Story 1

- [ ] T022 [P] [US1] Write `backend/tests/unit/steps/test_operator_history.py`: operator-phase steps created on `resource:styrmindeployment` success (first running, others pending), none for an internal deployment; forward mapping for each phase of [contracts/operator-status.md](contracts/operator-status.md) "Moving rollout steps forward", skipped phases, end times from condition transition times; reports for an unknown instance, a pre-feature task and a legacy CR change nothing; early return when all steps are final; `Deleting`/`Deleted` routed to the newest `delete_deployment` task
- [ ] T023 [P] [US1] Extend `backend/tests/unit/agent/test_status_reporter.py`: `instanceId` taken from `status.instanceId`, falling back to `spec.instanceId`
- [ ] T024 [P] [US1] Write `backend/tests/unit/agent/tasks/test_remediation_flow_steps.py`: `create_instance_crd`, `update_instance_crd` and `upgrade_instance_crd` open the steps of [contracts/flow-step-reporter.md](contracts/flow-step-reporter.md) in order, with and without hooks and aliases; each hook's step id reaches `run_driver_action_or_fail(step_id=…)`; a failing hook records `FAILED`
- [ ] T025 [P] [US1] Write `backend/tests/unit/test_styrmin_deployment_handlers_status.py`: create, update and resume handlers write `status.instanceId`, also when the handler raises `kopf.TemporaryError`
- [ ] T026 [P] [US1] Write `backend/tests/unit/services/test_task_types.py`: each caller in D19 creates its task with the documented type, `apply_state` sets `Task.instance_id` to the new instance

### Implementation for User Story 1

- [ ] T027 [US1] Give the `apply_state` service function a `task_type` argument (default `noop`) and set `Task.instance_id` to the new instance in `backend/styrmin_backend/services/reconciliation/__init__.py`
- [ ] T028 [US1] Pass task types per D19 from `deploy_application`, `update_deployment`, `refresh_deployment`, `update_deployment_version`, `redeploy_for_environment_update` and `_ensure_ingress_controller` in `backend/styrmin_backend/services/deployment.py`, and from `stop_components`/`start_components` in `backend/styrmin_backend/services/primitives.py`
- [ ] T029 [US1] Add `ensure_operator_steps(task, at)` to `backend/styrmin_backend/services/steps/recorder.py` and call it when a `resource:styrmindeployment` step succeeds (skip internal deployments: read `deployment.internal`)
- [ ] T030 [US1] In the `apply_state` flow in `backend/styrmin_backend/agent/tasks/orchestration.py`: record `plan` ("Plan the changes") through the recorder directly, retrying on `TaskNotFoundError` for up to 10 seconds (D2); pass `task_id` to `remediation.apply`; on a failed or crashed remediation flow, call `fail_open_flow_steps` for the task before raising
- [ ] T031 [US1] Wrap the work of `create_instance_crd`, `update_instance_crd` and `upgrade_instance_crd` in `backend/styrmin_backend/agent/tasks/orchestration.py` with reporter steps (keys and names of [data-model.md](data-model.md) "Step keys and names"); pass each hook step's id to `run_driver_action_or_fail(step_id=…)`
- [ ] T032 [US1] Split `run_job` per D11: INTERNAL flow `run_job` (keeps callbacks and `task_id`, opens `action_api_token()`, runs `run_job_command` with `run_deployment_or_fail` and `action_job_variables(token, task_id=…)`, closes open flow steps on failure) and USER flow `run_job_command` (builds today's Job manifest, records the `command` step) in `backend/styrmin_backend/agent/tasks/orchestration.py`; add `PrefectAction.RUN_JOB_COMMAND` in `backend/styrmin_backend/workflows/models.py`; register `RUN_JOB` as INTERNAL and `RUN_JOB_COMMAND` as USER in `backend/styrmin_backend/workflows/catalogue.py`; tests in `backend/tests/unit/agent/tasks/test_run_job_flows.py`
- [ ] T033 [US1] In `update_task_state` in `backend/styrmin_backend/services/tasks.py`, call `fail_open_flow_steps` with the state message when the state is `FAILED`; tests in `backend/tests/unit/services/test_task_callback_steps.py`
- [ ] T034 [US1] In `delete_deployment` in `backend/styrmin_backend/services/deployment.py`, record `resource:delete-request` ("Request the deletion") as succeeded after the CR patch, and create the pending `operator:teardown` step; test in `backend/tests/unit/services/test_delete_deployment_steps.py`
- [ ] T035 [US1] Write `status.instanceId` from the create, update and resume handlers in `backend/styrmin_backend/operator/handlers/styrmin_deployment.py`; add `instance_id` and `rollout_started_at` to `StyrminDeploymentStatus` in `backend/styrmin_backend/operator/crd/schema.py`; document both status fields in `helm/agent/crds/styrmin.io_styrmindeployments.yaml`
- [ ] T036 [US1] Send `status.instanceId`, falling back to `spec.instanceId`, from `_collect_crd_status` in `backend/styrmin_backend/agent/status/reporter.py`
- [ ] T037 [US1] Implement `apply_operator_report(report, now, uow)` forward mapping, delete routing and early return in `backend/styrmin_backend/services/steps/operator_history.py`; call it from `report_deployment_statuses` in `backend/styrmin_backend/services/deployment_status.py` after the snapshot upsert
- [ ] T038 [US1] Add `Task.steps` (private `steps_view`, query fallback) and `Task.startedByStepId` to `backend/styrmin_backend/api/definitions/task/model.py`
- [ ] T039 [US1] Build the timeline read model in `backend/styrmin_backend/services/deployment_timeline.py` (steps of all tasks in one query) and hand it to `DeploymentTimelineEntry`/`Task` in `backend/styrmin_backend/api/definitions/deployment_timeline/model.py`; add a query-count test in `backend/tests/unit/services/test_deployment_timeline_steps.py` (20 tasks × 10 steps, count does not grow with tasks)
- [ ] T040 [US1] Write propagation tests in `backend/tests/functional/graphql/test_task_steps_propagation.py`: `Task.steps` and every `Step` field of seeded rows reach a `READ_ONLY` caller through `task` and `deploymentTimeline`; `Task.type` for tasks created through each mutation in D19
- [ ] T041 [US1] Regenerate `schema.graphql` and generated types (T020 commands)
- [ ] T042 [US1] Extend `frontend/src/graphql/get_deployment_timeline.graphql` with the step fields of [contracts/client-surfaces.md](contracts/client-surfaces.md) (no `output`) and run `pnpm codegen` in `frontend/`
- [ ] T043 [P] [US1] Create `frontend/src/components/deployment/StepList.tsx`: ordered rows with status icon and text label, name, duration or "running for <elapsed>", attempts above 1; `data-step-key` and `data-step-status` attributes
- [ ] T044 [US1] Update `frontend/src/components/deployment/DeploymentTimeline.tsx`: every entry expands to show `StepList` then the context diff; "No steps recorded for this task." for finished tasks without steps; "Waiting for the first step." for unfinished ones; label `delete_deployment` as "Delete"
- [ ] T045 [P] [US1] Write `frontend/src/__tests__/deployment-detail/StepList.test.tsx` and `frontend/src/__tests__/deployment-detail/DeploymentTimelineSteps.test.tsx` (each status, duration, elapsed time, empty-steps and waiting notices, Delete label)
- [ ] T046 [US1] Extend the E2E scenario drivers so timeline entries carry `result`, `steps` (key, name, kind, status, started/ended, attempts, errors, detail, has output), `started_by` and `started_tasks`: `backend/tests/e2e/drivers/protocol.py`, `backend/tests/e2e/drivers/api_driver.py` (SDK), `backend/tests/e2e/drivers/ui_driver.py` (DOM data attributes); keep `backend/tests/unit/test_e2e_driver_conformance.py` passing
- [ ] T047 [US1] Extend `test_deployment_timeline_has_entries` in `backend/tests/e2e/test_deployment_timeline.py`: every task has a result; the create task has type `create_instance` and the `plan`, `resource:styrmindeployment` and four `operator:*` steps, all succeeded
- [ ] T048 [US1] Run `backend/tests/e2e/test_deployment_timeline.py::test_deployment_timeline_has_entries` (both variants) and record evidence in `specs/019-task-steps/e2e-evidence.md`

**Checkpoint**: The timeline shows typed tasks with ordered steps.

---

## Phase 4: User Story 2 - View the cause of a failed step (Priority: P1)

**Goal**: A failed step shows each attempt's error, FluxCD's reason, rollbacks, pod reasons and the end of a failed command's output.

**Independent Test**: The four SC-001 failure types each show the failed step and its cause on the deployment page.

### Tests for User Story 2

- [ ] T049 [P] [US2] Write `backend/tests/unit/agent/test_job_logs.py` for `read_job_output_tail`: newest pod chosen by either label; 201 lines and 65,537 bytes set `truncated`; no pod and API errors return `None`
- [ ] T050 [P] [US2] Extend `backend/tests/unit/test_styrmin_deployment_timer.py` and add `backend/tests/unit/test_styrmin_deployment_helmrelease_generation.py`: `HelmReleaseReady` reset on create and update, not on resume; `rolloutStartedAt` on create and update, on resume only when missing; FluxCD `Ready=True` counted only for the current generation; FluxCD reason copied; `HelmReleaseRemediated` copied without a phase change; `Stalled=True` sets `Failed`/`Error`; a retry that succeeds after a rollback reaches `Ready`; timeout from `rolloutStartedAt`; no status patch when nothing changed
- [ ] T051 [P] [US2] Write `backend/tests/unit/steps/test_operator_history_failures.py`: `Failed`/`Error` fails the first unfinished step with the CR message; a new attempt when the operator works on the step again; a failed HelmRelease step succeeds when a later phase is reported; `*Failed` FluxCD reasons with a new message or time add attempts; `HelmReleaseRemediated` sets `rolled_back_at`/`rollback_message` and ends the attempt; pod reasons from stored pod statuses appended (at most 5 pods); `detail` holds FluxCD's reason
- [ ] T052 [P] [US2] Write `backend/tests/unit/agent/test_execute_commands_output.py`: on Job failure, `execute_commands` records the output on `STYRMIN_STEP_ID` before it raises; "The output could not be read: …" when no pod exists

### Implementation for User Story 2

- [ ] T053 [US2] Implement `read_job_output_tail(namespace, job_name, container)` in `backend/styrmin_backend/agent/service/kubernetes/job_logs.py` ([contracts/flow-step-reporter.md](contracts/flow-step-reporter.md) "Job output")
- [ ] T054 [US2] Read the output before raising in `run_job` (container `user-job`) and `run_kubernetes_job` (container `prefect-job`) in `backend/styrmin_backend/agent/service/kubernetes/primitives.py`; attach it to the raised error (a `JobFailedError` carrying `output` and `truncated`)
- [ ] T055 [US2] Record the output on `STYRMIN_STEP_ID` with the reporter in `execute_commands` in `backend/styrmin_backend/actions/primitives.py`; record it on the `command` step in `run_job_command` in `backend/styrmin_backend/agent/tasks/orchestration.py`
- [ ] T056 [US2] Add a generation-aware HelmRelease observation (`Ready` of the current generation, its reason/message/transition time, `Remediated`, `Stalled`) read once per tick in `backend/styrmin_backend/operator/reconciler.py`, reusing the rule of `_helmrelease_guard_failure`
- [ ] T057 [US2] Apply D5 in `backend/styrmin_backend/operator/handlers/styrmin_deployment.py`: reset `HelmReleaseReady` to `Unknown`/`Progressing` and set `rolloutStartedAt` in create and update; resume sets `rolloutStartedAt` only when missing; the timer copies FluxCD's state into `HelmReleaseReady` and `HelmReleaseRemediated`, sets `Failed`/`Error` on `Stalled=True`, measures the readiness timeout from `rolloutStartedAt`, and writes conditions only when they change; add `HELM_RELEASE_REMEDIATED` to `ConditionType` in `backend/styrmin_backend/operator/crd/schema.py`; keep `backend/tests/unit/test_deployment_deletion_operator.py` passing
- [ ] T058 [US2] Implement failures, attempts, reopening, later-phase success, FluxCD `detail`, failure-reason attempts, rollbacks and pod reasons in `backend/styrmin_backend/services/steps/operator_history.py` ([contracts/operator-status.md](contracts/operator-status.md) "HelmRelease details", "Pod reasons on failure")
- [ ] T059 [US2] Write propagation tests in `backend/tests/functional/graphql/test_step_failure_propagation.py`: `errors`, `error`, `detail`, `rolledBackAt`, `rollbackMessage`, `hasOutput`, `output`, `outputTruncated` from seeded rows to a `READ_ONLY` caller; `recordStep` `FAILED` with output and `OUTPUT` events stored
- [ ] T060 [US2] Add `frontend/src/graphql/get_step_output.graphql`, run `pnpm codegen`, and extend `frontend/src/components/deployment/StepList.tsx`: errors per attempt, FluxCD `detail`, "FluxCD rolled back the release at <time>: <message>", "Show output" loading `GetStepOutput` into a scrollable monospace block with "Earlier output was cut"
- [ ] T061 [P] [US2] Write `frontend/src/__tests__/deployment-detail/StepListFailures.test.tsx`: one case per SC-001 failure type (failed hook with error; failed hook with output; failed HelmRelease with FluxCD detail and pod reasons; failed prerequisites with attempts) and the rollback line
- [ ] T062 [US2] Add the test driver `backend/tests/e2e/fixtures/drivers/failing-actions/` (`driver.styrmin.yml` reusing the simple-app chart, `values.j2.yml`, `actions.py` whose `upgrade` action raises for target version `0.9.0-raise` and runs `sh -c 'echo step-output-1; echo step-output-2; exit 3'` through `execute_commands` for `0.9.0-command`); serve it from the git-server fixture in `backend/tests/e2e/conftest.py`; add a module-scoped deployment fixture in `backend/tests/e2e/test_task_steps.py`
- [ ] T063 [US2] Write `backend/tests/e2e/test_task_steps.py` (`shard_general`, `ci`): `test_hook_action_error_shows_failed_step` (`api_only`), `test_command_output_on_failed_step` (`api_only`, asserts `step-output-2` in the output), `test_prerequisite_failure_shows_attempts` (`api_only`; delete one operator network policy, add a `ResourceQuota` on `count/networkpolicies.networking.k8s.io` equal to the remaining count, update the deployment, assert the failed prerequisites step with the quota message and more than one attempt, remove the quota), `test_helmrelease_failure_shows_fluxcd_reason` (both variants, runs last, 420-second budget; image override with a missing tag; failed HelmRelease step with FluxCD's reason and `ImagePullBackOff`; a `READ_ONLY` user reads the same steps, errors and output; SDK `apply(wait=True)` failure reason names the step)
- [ ] T064 [US2] Run every node of `backend/tests/e2e/test_task_steps.py` and record evidence in `specs/019-task-steps/e2e-evidence.md`

**Checkpoint**: Each SC-001 failure type names its step and cause (4 of 4).

---

## Phase 5: User Story 3 - View a task result that includes the operator's work (Priority: P1)

**Goal**: Each task shows a calculated result; superseded and hook-started tasks link to each other.

**Independent Test**: After a simple-app upgrade, the upgrade is `SUCCEEDED`, lists three started tasks that link back, and the earlier started tasks are `SUCCEEDED` or `SUPERSEDED` by a sibling; a second update during the first's operator phases makes the first `SUPERSEDED`.

### Tests for User Story 3

- [ ] T065 [P] [US3] Write `backend/tests/unit/steps/test_results.py`: each of the four results; family with a sibling-superseded started task (`SUCCEEDED`); family step superseded by an outside task (`SUPERSEDED`); failed started task (`FAILED`); running started task (`RUNNING`); `RUNNING` before `FAILED`; no steps falls back to `Task.status`; cycle guard
- [ ] T066 [P] [US3] Write `backend/tests/unit/steps/test_supersede.py`: success of `resource:styrmindeployment` or `resource:delete-request` supersedes pending and running operator-phase steps of the deployment's other tasks with `superseded_by_task_id`; superseded steps are final

### Implementation for User Story 3

- [ ] T067 [US3] Implement `compute_task_result` and a bulk `family_results(tasks, steps_by_task, started_by_step)` in `backend/styrmin_backend/services/steps/results.py` per [data-model.md](data-model.md) "Task result calculation"
- [ ] T068 [US3] Implement `supersede_operator_steps(deployment_id, by_task_id, at)` in `backend/styrmin_backend/services/steps/recorder.py` and call it on success of `resource:styrmindeployment` and `resource:delete-request`
- [ ] T069 [US3] Add the optional `startedByStepId` argument to `stopComponents`, `startComponents` and `updateDeploymentVersion` in `backend/styrmin_backend/api/schema/mutation.py`; pass it through `stop_components`/`start_components` in `backend/styrmin_backend/services/primitives.py`, `update_deployment_version` in `backend/styrmin_backend/services/deployment.py` and the `apply_state` service function, which validates the step (`StepNotFoundError`) and sets `Task.started_by_step_id`
- [ ] T070 [US3] Send `STYRMIN_STEP_ID` as `startedByStepId` from `stop_components`, `start_components` and `upgrade_deployment_version` in `backend/styrmin_backend/actions/primitives.py`, updating `backend/styrmin_backend/actions/stop_components.graphql`, `start_components.graphql` and `update_deployment_version.graphql`; extend `backend/tests/unit/test_driver_example_upgrade_actions.py` or add `backend/tests/unit/agent/test_action_primitives_started_by.py`
- [ ] T071 [US3] Add `Task.result`, `Task.startedBy`, `Task.startedTasks`, `Step.supersededBy` and `Step.startedTasks` with private views and query fallbacks in `backend/styrmin_backend/api/definitions/task/model.py` and `backend/styrmin_backend/api/definitions/step/model.py`; extend the timeline read model in `backend/styrmin_backend/services/deployment_timeline.py` with started tasks (one query) and family results; keep the query-count test of T039 passing
- [ ] T072 [US3] Write propagation tests in `backend/tests/functional/graphql/test_task_result_propagation.py`: `startedByStepId` on each of the three mutations reaches `task.started_by_step_id` and `Task.startedBy`, `Task.startedTasks`, `Step.startedTasks`; unknown step rejected; `Task.result` for each of the four values including the sibling and outside-task families; `Step.supersededBy`
- [ ] T073 [US3] Regenerate `schema.graphql` and generated types (T020 commands)
- [ ] T074 [US3] Create `frontend/src/components/deployment/TaskResultBadge.tsx`; use it in `DeploymentTimeline.tsx` instead of `StatusBadge(task.status)` with `data-task-result`; show "Started by <type>" links, "Superseded by <type>" links on steps and started tasks with results under hook steps; use it in the Overview "Recent Timeline" in `frontend/src/pages/deployments/DeploymentDetailPage.tsx`; extend the timeline query and run `pnpm codegen`
- [ ] T075 [P] [US3] Write `frontend/src/__tests__/deployment-detail/TaskResult.test.tsx`: badge for each result; started-by and superseded links; started tasks list; Overview uses the result
- [ ] T076 [US3] Extend `test_upgrade_simple_app` in `backend/tests/e2e/test_deploy_app.py` per [plan.md](plan.md) "E2E coverage": type `upgrade_instance`, step order, three started tasks with links both ways, upgrade `SUCCEEDED`, `start_components` `SUCCEEDED`, earlier started tasks `SUCCEEDED` or `SUPERSEDED` by a sibling
- [ ] T077 [US3] Run `backend/tests/e2e/test_deploy_app.py::test_upgrade_simple_app` (both variants) and record evidence in `specs/019-task-steps/e2e-evidence.md`

**Checkpoint**: Results include the operator's work; upgrades read as one family.

---

## Phase 6: User Story 4 - Follow a running task without reloading (Priority: P1)

**Goal**: Step changes appear within 15 seconds; a lost agent is visible.

**Independent Test**: During an upgrade, each step change is visible within 15 seconds of being recorded; with no agent report for over 60 seconds, the running operator step shows "No report from the agent since <time>".

- [ ] T078 [P] [US4] Write `backend/tests/unit/steps/test_reads.py` for `no_report_since`: running operator step with an old report, recent report, no report (step start used), non-operator and finished steps
- [ ] T079 [US4] Resolve `Step.noReportSince` from the read model (deployment `DeploymentStatus.last_polled_at`, loaded once per timeline) and from a query for single reads in `backend/styrmin_backend/api/definitions/step/model.py` and `backend/styrmin_backend/services/deployment_timeline.py`
- [ ] T080 [US4] Add the `noReportSince` case to `backend/tests/functional/graphql/test_task_steps_propagation.py` (seeded `last_polled_at` 2 minutes ago → field set; 10 seconds ago → null)
- [ ] T081 [US4] Show "No report from the agent since <time>" in `frontend/src/components/deployment/StepList.tsx`; start `RUNNING` and `FAILED` entries expanded in `DeploymentTimeline.tsx`; keep `refetchInterval: 10_000` in `DeploymentDetailPage.tsx`
- [ ] T082 [P] [US4] Write `frontend/src/__tests__/deployment-detail/StepListLive.test.tsx`: no-report notice, default expansion, elapsed time updates on re-render
- [ ] T083 [US4] In `test_upgrade_simple_app` (`backend/tests/e2e/test_deploy_app.py`, API variant), poll the timeline every 2 seconds after submitting the upgrade and assert that each step is first observed at most 15 seconds after its recorded `startedAt` (allow 2 seconds of clock difference); run it and record evidence in `specs/019-task-steps/e2e-evidence.md`

**Checkpoint**: Users can follow a running task and tell a lost agent from a slow phase.

---

## Phase 7: User Story 5 - Read steps and failure causes from the SDK and `styrminctl` (Priority: P1)

**Goal**: SDK users and platform engineers get steps, results and the failed step without a browser.

**Independent Test**: `sdk.tasks.get` returns steps and result; `styrminctl tasks get` prints the step table; the `apply --wait` failed line names the step.

- [ ] T084 [P] [US5] Extend `python_sdk/src/styrmin_sdk/graphql/get_task.graphql` and `get_deployment_timeline.graphql` per [contracts/client-surfaces.md](contracts/client-surfaces.md); run `uv run invoke generate`
- [ ] T085 [US5] Add `failed_step(task_id) -> FailedStep | None` (searches the task's steps, then its started tasks) to `python_sdk/src/styrmin_sdk/resources/tasks.py`; tests in `python_sdk/tests/test_tasks.py`
- [ ] T086 [US5] Set `failure_reason` to `step "<name>" failed: <error>` in `_wait_for_terminal` in `python_sdk/src/styrmin_sdk/resources/deployments.py` when `failed_step` finds one; tests in `python_sdk/tests/test_deployments.py`
- [ ] T087 [US5] Print the result column, the "Steps" table (step, status, duration, attempts, error) or "No steps recorded for this task.", and the "Started tasks" table in `get` in `cli/src/styrminctl/commands/tasks.py`; tests in `cli/tests/test_tasks.py`
- [ ] T088 [US5] Add a test for the `failed` line with a step reason in `cli/tests/test_deployments.py`

**Checkpoint**: CI logs and scripts explain failures.

---

## Phase 8: User Story 6 - View the steps of a restore or backup of one deployment (Priority: P2)

**Goal**: Restores show three steps; backups show one step per component.

**Independent Test**: A restore lists "Delete the namespace", "Run the Velero restore", "Run the recovery" with durations; a restore of a missing Velero backup fails "Run the Velero restore" with Velero's error; a backup lists one step per component.

### Tests for User Story 6

- [ ] T089 [P] [US6] Write `backend/tests/unit/agent/test_velero_client_poll.py`: `FailedValidation` terminal in `poll_backup_status` and `poll_restore_status`; `on_poll` called after each poll; `list_pod_volume_backups` filters by `velero.io/backup-name`
- [ ] T090 [P] [US6] Write `backend/tests/unit/workflows/test_backup_component_steps.py`: `PodVolumeBackup` lists mapped to component steps (start, end, result, error), a component without items gets the backup's result and times
- [ ] T091 [P] [US6] Write `backend/tests/unit/workflows/test_restore_steps.py`: the three restore steps opened in order and failed on namespace timeout, Velero failure and recovery failure; the INTERNAL flow fails open steps when the USER flow fails or crashes; token and `STYRMIN_RESTORE_ID` passed as job variables

### Implementation for User Story 6

- [ ] T092 [US6] Add `list_pod_volume_backups(namespace, backup_name)`, an `on_poll` callback on `poll_backup_status`, and `FailedValidation` as terminal in both poll functions in `backend/styrmin_backend/agent/service/kubernetes/velero/client.py`
- [ ] T093 [US6] Grant `get` and `list` on `podvolumebackups` in `velero.io` in `helm/agent/templates/roles.yaml`; run `helm lint` for the agent chart
- [ ] T094 [US6] In `backend/styrmin_backend/workflows/templates/backup.py`: `execute_restore_workflow` opens `action_api_token()` and passes `action_job_variables(token, restore_id=…)` to the Velero restore flow, and fails open restore steps when it fails or crashes; `execute_velero_restore_flow` records `restore:namespace`, `restore:velero` (error from Velero's failure reason or validation errors) and `restore:recovery`
- [ ] T095 [US6] In `backend/styrmin_backend/workflows/templates/backup.py`: `execute_backup_workflow` opens `action_api_token()` and passes `action_job_variables(token, backup_id=…)`, and fails open backup steps on failure; `execute_velero_backup_flow` records `backup:component:<name>` steps from `PodVolumeBackup` objects on each poll (pods mapped by the `styrmin/component` label) and closes components without items at the end
- [ ] T096 [US6] Add `Backup.steps` and `Restore.steps` in `backend/styrmin_backend/api/definitions/backup/backup.py` and `backend/styrmin_backend/api/definitions/backup/restore.py`; regenerate `schema.graphql` and generated types
- [ ] T097 [US6] Write propagation tests in `backend/tests/functional/graphql/test_backup_restore_steps_propagation.py`: seeded backup and restore steps reach `Backup.steps`/`Restore.steps` for a `READ_ONLY` caller; steps deleted with their backup
- [ ] T098 [US6] Extend `frontend/src/graphql/list_backups.graphql` and `list_restores.graphql` with steps, run `pnpm codegen`, and render `StepList` in `BackupRow` and `RestoreRow` in `frontend/src/pages/deployments/DeploymentDetailPage.tsx`; tests in `frontend/src/__tests__/deployment-detail/BackupRestoreSteps.test.tsx`
- [ ] T099 [US6] Extend `python_sdk/src/styrmin_sdk/graphql/get_backup.graphql`, `get_restore.graphql`, `list_backups.graphql` and `list_restores.graphql` with steps; run `uv run invoke generate`; parsing tests in `python_sdk/tests/test_backups.py`
- [ ] T100 [US6] Extend `backend/tests/e2e/test_backup_restore.py` (`shard_backup`): a completed restore lists its three steps in order with durations; a backup lists one step per component; a failed restore (remove the Velero backup with a `DeleteBackupRequest`, wait until the `Backup` object is gone, restore) fails "Run the Velero restore" with Velero's validation error
- [ ] T101 [US6] Run the changed nodes of `backend/tests/e2e/test_backup_restore.py` and record evidence in `specs/019-task-steps/e2e-evidence.md`

**Checkpoint**: Restores and backups of one deployment show their steps.

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Documentation (Constitution §VII), changelog, full gates

- [ ] T102 [P] Write `dev/adr/0060-steps-and-derived-task-result.md`: steps written through one recorder by three writers, the family task result never stored, `status.instanceId`, the operator's current-generation rule, the action token for `run_job`, backups and restores, `recordStep` limited to `styrmin-actions` (sources: research D1–D19)
- [ ] T103 [P] Update `dev/knowledge/backend/orchestration-flows.md` (plan step, job variables, `run_job` wrapper, remediation steps), `dev/knowledge/backend/hooks-and-actions.md` (hook steps, output capture, `startedByStepId`), `dev/knowledge/backend/data-models.md` (`step`, task columns), `dev/knowledge/backend/api.md` (new types and mutation), `dev/knowledge/backend/backup-restore.md` (backup and restore steps, `FailedValidation`)
- [ ] T104 [P] Update `dev/knowledge/agent/operator.md` (current-generation rule, `status.instanceId`, `rolloutStartedAt`, `HelmReleaseRemediated`, `Stalled`; replace the statement that HelmRelease failures are not reflected in the CR status with the new behaviour) and `dev/knowledge/agent/overview.md` (status reporter sends `status.instanceId`; phase history); update `dev/knowledge/architecture.md` if it describes the report path
- [ ] T105 [P] Update `docs/docs/concepts-and-architecture/status-reporting.md`, `operator-and-crds.md`, `hooks-and-actions.md`, `backups-and-restores.md`, `glossary.md`, and `docs/docs/reference/styrmindeployment.md`, `driver-api.md` (failed command output is visible to every signed-in user, so commands must not print secrets; SDK calls from actions are not linked as started tasks), `styrminctl.md` (`tasks get` steps, `apply --wait` failed line)
- [ ] T106 [P] Update `CONTEXT.md`: Action token now also created by `run_job`, backups and restores; `status.instanceId` meaning; re-check the Step and Task result entries against the final design (family result, `SUPERSEDED` rule); update `dev/guides/users-and-groups.md` about the extra `styrmin-actions` sessions
- [ ] T107 Create changelog fragments with towncrier: `uv run towncrier create -c "…" 2.added.md` (steps, task results, command output, SDK and CLI), `2.fixed.md` (updates and upgrades are no longer reported ready before FluxCD applies the new release; failed upgrades end `FAILED`), `2.changed.md` (reconcile tasks get their real type instead of `noop`; `run_job` runs through an internal flow)
- [ ] T108 Run `uv run invoke format lint`, `cd frontend && pnpm lint && pnpm build`, and fix every finding
- [ ] T109 Run the local merge gate: `uv run invoke test`, `cd frontend && pnpm test`, `uv run pytest python_sdk/tests cli/tests`
- [ ] T110 Run the whole `shard_general` and `shard_backup` E2E shards locally (the operator change in D5 affects every rollout), fix regressions, and record evidence for every changed node in `specs/019-task-steps/e2e-evidence.md`
- [ ] T111 Walk through `specs/019-task-steps/quickstart.md` sections 1 to 3 and update it to match what was built

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (Phase 1)**: none.
- **Foundational (Phase 2)**: after Setup. Blocks every story.
- **US1 (Phase 3)**: after Foundational. The MVP.
- **US2 (Phase 4)**: after US1 (needs operator-phase steps, the phase history and `StepList`).
- **US3 (Phase 5)**: after US1 (needs operator-phase steps and the timeline read model). Can run beside US2; T068 and T058 both edit the recorder and the phase history, so sequence those two.
- **US4 (Phase 6)**: after US1. Can run beside US2 and US3.
- **US5 (Phase 7)**: after US1; the `failed_step` reason is most useful after US2 and US3 fields exist.
- **US6 (Phase 8)**: after Foundational and T043 (`StepList`). Independent of US2 to US5.
- **Polish (Phase 9)**: after the stories in scope.

### Within each story

- Tests first; they must fail before the implementation.
- Models and repository → services → GraphQL → regeneration → frontend, SDK, CLI → E2E → evidence.

### Parallel opportunities

- Phase 1: T002 and T003.
- Phase 2: T007, T008 and T013 after T004; T019 after T017 and T018.
- US1: T022–T026 together; T043 beside the backend tasks.
- US2: T049–T052 together; T053 beside T056.
- US3: T065 and T066 together; T075 beside the backend tasks.
- US6: T089–T091 together; T093 beside T092.
- Polish: T102–T106 together.

## Parallel Example: User Story 1

```bash
# Tests together:
Task: "T022 operator history unit tests in backend/tests/unit/steps/test_operator_history.py"
Task: "T023 status reporter instanceId tests in backend/tests/unit/agent/test_status_reporter.py"
Task: "T024 remediation flow step tests in backend/tests/unit/agent/tasks/test_remediation_flow_steps.py"
Task: "T025 handler status.instanceId tests in backend/tests/unit/test_styrmin_deployment_handlers_status.py"
Task: "T026 task type tests in backend/tests/unit/services/test_task_types.py"

# Frontend beside the backend:
Task: "T043 StepList in frontend/src/components/deployment/StepList.tsx"
```

## Implementation Strategy

### MVP (User Story 1)

1. Phases 1 and 2.
2. Phase 3 (US1). Validate with T047–T048: typed tasks with ordered steps.

### Incremental delivery

1. US1 → typed tasks and ordered steps.
2. US2 → failure causes (SC-001).
3. US3 → task results and links (SC-003).
4. US4 → live updates and lost-agent notice (SC-002).
5. US5 → SDK and CLI (FR-012).
6. US6 → restores and backups (P2, SC-005).
7. Polish → documentation, changelog, full gates and shard runs.

### High-risk tasks (call out in the PR)

T004–T006 (database), T035–T037 and T056–T058 (operator and status reporter), T030–T032 and T094–T095 (Prefect flow dispatch and action tokens), T015–T016 and T069 (authorization and schema).
