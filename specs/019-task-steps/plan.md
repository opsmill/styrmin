# Implementation Plan: Steps and Failure Causes for Tasks, Backups and Restores

**Branch**: `fac/feat-background-task-visibility-i4lwl` | **Date**: 2026-10-06 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/019-task-steps/spec.md`, PRD [opsmill/styrmin#2 (comment)](https://github.com/opsmill/styrmin/issues/2#issuecomment-6012882649)

## Summary

Users who open a deployment view one status and one message per task, and cannot find out which part of an operation failed or why. This plan records an ordered list of **steps** for every task, and in a second phase for restores and backups of one deployment, and calculates a **task result** from those steps on every read.

The approach, from [research.md](research.md):

- A new `step` table, written only through a step recorder service (D1, D2).
- Three kinds of writers:
  - server code and INTERNAL flows call the recorder directly;
  - USER flows and driver actions call a new `recordStep` mutation with the action token (D3, D11, D13);
  - the operator's CR status reaches the server through the existing status reports, and an operator phase history turns each report into step changes (D4, D6).
- The operator must judge the HelmRelease on its current generation and copy FluxCD's reason and rollbacks into the CR status (D5). Today it reports updates `Ready` without waiting for FluxCD, which is why a task can show success while its HelmRelease fails.
- Command output is read from the failed Job's pod before anything can remove it (D10).
- The task result is calculated over the task's family, so the tasks that one upgrade hook started count as the upgrade's work (D8).
- Tasks that a reconcile runs are stored with the type their caller means instead of `noop`, so users can find "the upgrade" (D19, FR-019).
- The frontend, the SDK and `styrminctl` read the new fields (D15, D16). The timeline uses a precomputed read model so it stays at a fixed number of queries (D14).

## Technical Context

**Language/Version**: Python 3.14+ (backend, agent, operator, SDK, CLI); TypeScript 5.9.3 with React 19 (frontend)

**Primary Dependencies**: Strawberry GraphQL, SQLModel and SQLAlchemy (async), Pydantic v2, Prefect, kopf, kubernetes-asyncio, httpx, Cyclopts; TanStack Query v5 and Tailwind (frontend). No new dependency.

**Storage**: PostgreSQL. One Alembic revision: new `step` table; `task.instance_id` and `task.started_by_step_id` columns ([data-model.md](data-model.md)).

**Testing**: pytest (unit, propagation, E2E on vCluster), Vitest with React Testing Library, SDK and CLI pytest suites.

**Target Platform**: Kubernetes. The server and the task worker run from the `styrmin` chart; the agent (Prefect worker for `user-work-pool`, kopf operator, status reporter) runs from the `agent` chart.

**Project Type**: Web service with an in-cluster agent, an SDK and a CLI.

**Performance Goals**: A step change appears on the deployment page within 15 seconds of being recorded (FR-005: 5-second reports plus the 10-second page refresh). The timeline query runs a fixed number of database queries whatever the number of tasks and steps: the timeline service loads the steps, started tasks and deployment status in three queries and hands them to the GraphQL objects as private fields (research D14). The phase history returns without locking rows for tasks whose operator-phase steps are final.

**Constraints**:

- `Task.status` keeps its meaning (FR-015).
- No unauthenticated mutation is added (FR-014).
- The input of `reportDeploymentStatuses` does not change.
- A failed step write never fails the work it describes.
- Command output is limited to the last 200 lines and 64 KiB (FR-003).

**Scale/Scope**: About 8 to 12 steps per rollout task; deployments have up to about 50 tasks (ADR-028). Output exists only on failed command steps.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Status | How the plan meets it |
|---|---|---|
| §I Declarative state reconciliation | Pass | Steps record work and never drive reconciliation (FR-018). The operator changes in D5 make the CR status describe the current HelmRelease generation; the reconciliation diff and remediation do not change. |
| §II Driver-based deployment | Pass | Each run of a hook mode becomes a step without driver changes. The action primitives gain output capture and the started-by link inside Styrmin's own code. The driver-author documentation says that action commands must not print secrets. |
| §III Layered architecture | Pass | `recordStep`, the extended mutations and the report path go GraphQL → service (`services/steps/`) → repository (`repository/steps.py`) → database. The task result is calculated in the service layer. INTERNAL flows call services with `get_unit_of_work`, as they do today. |
| §IV Type safety and typed errors | Pass | `StepNotFoundError` and `InvalidStepRecordError` subclass `ServiceError`; unknown parents reuse `TaskNotFoundError`, `BackupNotFoundError` and `RestoreNotFoundError`. Domain, database and GraphQL models stay separate. |
| §V Test-first, E2E required | Pass | Unit tests for the recorder, the result calculation, the phase history, the reporter, job output and the operator handlers; propagation tests for every GraphQL change; E2E scenarios in [quickstart.md](quickstart.md), extending existing tests first. |
| §V Propagation tests | Pass | Listed in [contracts/graphql.md](contracts/graphql.md). |
| §VI Format and lint | Pass | `uv run invoke format lint`, `pnpm lint` before each commit. |
| §VII Documentation accuracy | Pass | Documentation tasks listed under "Documentation" below. |
| Governance gates | Crossed, recorded | See "Governance gates crossed". The PRD records them as discussed. |

Re-check after Phase 1: no new violation. The operator change (D5) and the action token for backup and restore flows (D13) widen two gates that the PRD already crossed; both are called out below.

## Project Structure

### Documentation (this feature)

```text
specs/019-task-steps/
├── spec.md
├── plan.md                         # this file
├── research.md                     # D1–D18
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── graphql.md
│   ├── operator-status.md
│   ├── flow-step-reporter.md
│   └── client-surfaces.md
├── checklists/requirements.md
└── tasks.md                        # /speckit-tasks
```

### Source Code (repository root)

```text
backend/styrmin_backend/
├── db/models.py                              # Step table; Task.instance_id, Task.started_by_step_id
├── db/migrations/versions/<rev>_add_steps.py # one revision
├── domain/models.py                          # Step, StepError, StepStatus, StepKind, TaskResult; Task fields
├── repository/steps.py                       # new
├── repository/tasks.py                       # new columns; find_started_by_steps
├── services/steps/                           # new package
│   ├── recorder.py                           # open/succeed/fail/output/supersede/ensure operator steps/close open
│   ├── results.py                            # compute_task_result, bulk results
│   ├── operator_history.py                   # apply_operator_report
│   ├── reads.py                              # step reads, no_report_since
│   └── exceptions.py                         # StepNotFoundError, InvalidStepRecordError
├── services/reconciliation/__init__.py       # Task.instance_id, started_by_step_id, task_type argument
├── services/primitives.py                    # stop/start: started_by_step_id, task types
├── services/deployment.py                    # task types per caller; update_deployment_version started_by; delete request step
├── services/deployment_status.py             # call apply_operator_report
├── services/deployment_timeline.py           # read model: steps, started tasks, family results, last report
├── services/tasks.py                         # callback closes open flow steps
├── services/unit_of_work.py                  # steps repository
├── api/definitions/step/model.py             # new: Step, StepError, enums, RecordStepInput
├── api/definitions/task/model.py             # steps, result, startedBy, startedTasks
├── api/definitions/backup/{backup,restore}.py# steps
├── api/schema/{query,mutation}.py            # step, recordStep, startedByStepId
├── api/auth/permissions.py                   # IsActionsServiceAccount
├── agent/steps/                              # new: reporter.py, record_step.graphql, queries.py
├── agent/service/kubernetes/job_logs.py      # new: read_job_output_tail
├── agent/service/kubernetes/primitives.py    # run_job, run_kubernetes_job read output on failure
├── agent/service/kubernetes/velero/client.py # list_pod_volume_backups, on_poll, FailedValidation terminal
├── agent/status/reporter.py                  # instanceId from status
├── agent/tasks/orchestration.py              # plan step, env, remediation flow steps, run_job wrapper, run_job_command
├── agent/tasks/utils.py                      # action_job_variables, run_driver_action_or_fail(step_id)
├── actions/primitives.py, actions/*.graphql  # output capture; startedByStepId
├── operator/handlers/styrmin_deployment.py   # D5
├── operator/reconciler.py                    # HelmRelease observation (generation-aware)
├── operator/crd/schema.py                    # HelmReleaseRemediated, status fields
├── workflows/catalogue.py, workflows/models.py # RUN_JOB INTERNAL, RUN_JOB_COMMAND USER
└── workflows/templates/backup.py             # tokens, steps, crash handling

backend/tests/
├── unit/steps/                               # recorder, results, operator history, reads
├── unit/api/                                 # propagation tests
├── unit/agent/                               # reporter, job output, primitives, flows
├── unit/operator/                            # handler changes
└── e2e/test_task_steps.py (new), test_deploy_app.py, test_backup_restore.py (extended)
    e2e/fixtures/drivers/failing-actions/     # test driver for SC-001 types 1 and 2

helm/agent/templates/roles.yaml               # get, list podvolumebackups
helm/agent/crds/styrmin.io_styrmindeployments.yaml # document status.instanceId, status.rolloutStartedAt

frontend/src/
├── graphql/get_deployment_timeline.graphql, get_step_output.graphql, list_backups.graphql, list_restores.graphql
├── components/deployment/StepList.tsx, TaskResultBadge.tsx (new), DeploymentTimeline.tsx
├── pages/deployments/DeploymentDetailPage.tsx
└── __tests__/…

python_sdk/src/styrmin_sdk/
├── graphql/get_task.graphql, get_deployment_timeline.graphql, get_backup.graphql, get_restore.graphql, list_backups.graphql, list_restores.graphql
├── resources/tasks.py (failed_step), resources/deployments.py (_wait_for_terminal)
└── graphql/_generated/ (regenerated)

cli/src/styrminctl/commands/tasks.py          # step table
schema.graphql                                # regenerated
```

**Structure Decision**: The existing web-service layout. New backend code goes into a `services/steps/` package and an `agent/steps/` package so the recorder and the reporter each have one home.

## Implementation phases

Each phase leaves the system working. Phases 1 to 6 deliver P1; phase 7 delivers P2.

1. **Storage and recorder.** Migration (with a reversible downgrade), models, repository, recorder, family result calculation, reads, errors. Unit tests for the recorder and the result calculation; a migration test.
2. **GraphQL.** `Step` type and enums, `Task` and `Backup`/`Restore` fields, `Query.step`, `recordStep` (restricted to `styrmin-actions`), `startedByStepId`; services wired (`apply_state` sets `instance_id` and takes the task type, each caller passes its type, the three mutations set `started_by_step_id`, `deleteDeployment` records its request step, the callback closes open steps). Timeline read model with a query-count test. Schema and SDK regeneration. Propagation tests.
3. **Flow steps.** Reporter and job variables; `apply_state` plan step and crash handling; remediation flow steps; `run_job` wrapper and `run_job_command`; job output in `execute_commands` and `run_job_command`; started-by link in the action primitives. Unit tests.
4. **Operator and phase history.** Operator changes (D5) and `status.instanceId`; reporter `instanceId`; phase history. Unit tests, including the existing operator handler tests.
5. **Frontend.** Queries, `StepList`, `TaskResultBadge`, timeline changes. Component tests.
6. **SDK and CLI.** Queries, `failed_step`, `_wait_for_terminal`, `tasks get`. Tests. Then the P1 E2E scenarios.
7. **Restores and backups (P2).** Tokens and steps in the backup and restore flows, PodVolumeBackup mapping, RBAC, crash handling, `FailedValidation` as a terminal Velero phase, backup and restore rows in the frontend, SDK queries. Unit and E2E tests.
8. **Documentation and changelog** (see below), then the full local merge gate.

## E2E coverage

Following "reuse before you boot" ([`dev/guides/e2e-deployment-sharing.md`](../../dev/guides/e2e-deployment-sharing.md)):

- **Extend** `test_upgrade_simple_app` (`shard_general`, both variants): after the upgrade, assert:
  - the upgrade task has the type `upgrade_instance` and its steps in order: plan, CR write and upgrade hook, and the operator phases in their own order. The operator phases start when the CR write ends, so the prerequisites step is listed before the upgrade hook;
  - the upgrade hook step lists the tasks it started, and each links back. These are `stop_components` and `start_components`: the action's `upgrade_deployment_version` asks for the version that the upgrade already set, which is a no-op that starts no task (observed in the T076 run);
  - the upgrade's result is `SUCCEEDED`, the last started task (`start_components`) is `SUCCEEDED`, and each earlier started task is `SUCCEEDED` or `SUPERSEDED` by one of its siblings (they interrupt each other's rollouts, research D8).
- **Extend** `test_deployment_timeline_has_entries`: every task of the shared deployment has a result, and the create task has the type `create_instance` and the plan, CR-write and operator-phase steps.
- **New** `test_task_steps.py` (`shard_general`), with one module-scoped deployment of a test driver `failing-actions` (served by the existing git-server fixture; it reuses the simple-app chart). No existing deployment can host these scenarios: failing the shared simple-app deployment would break every later test in the shard. Its upgrade action reads the target version to choose a failure:
  - `test_hook_action_error_shows_failed_step` (`api_only`): the action raises; the hook step is failed with the error; the result is `FAILED`.
  - `test_command_output_on_failed_step` (`api_only`): the action's command exits non-zero after printing known lines; the hook step has the end of the output.
  - `test_prerequisite_failure_shows_attempts` (`api_only`): delete one of the operator's network policies in the deployment namespace, add a `ResourceQuota` whose `count/networkpolicies.networking.k8s.io` equals the remaining count, then update the deployment; the prerequisites step fails with the quota message and more than one attempt. The test removes the quota afterwards.
  - `test_helmrelease_failure_shows_fluxcd_reason` (both variants, runs last in the module): an image override with a tag that does not exist; within a 420-second budget (the operator's 270-second readiness timeout plus margin) the HelmRelease step is failed with FluxCD's reason and `ImagePullBackOff`; a `READ_ONLY` user reads the same data (SC-004); `apply --wait` through the SDK reports the step.
- **Extend** `test_backup_restore.py` (`shard_backup`): a completed restore lists its three steps in order with durations; a backup lists one step per component; for a failed restore, the test removes the Velero backup with a `DeleteBackupRequest`, waits until the `Backup` object is gone (so Velero's backup sync cannot bring it back), then restores it, and asserts that "Run the Velero restore" failed with Velero's validation error.

Markers follow [`dev/knowledge/backend/e2e-testing.md`](../../dev/knowledge/backend/e2e-testing.md): the SC-001 scenarios other than the HelmRelease one are `api_only`, because component tests cover how each failure appears on the page.

## Risks

| Risk | Effect | Mitigation |
|---|---|---|
| D5 changes when deployments become `RUNNING` after an update or upgrade | Updates take as long as FluxCD's rollout; failed upgrades now end `FAILED`; E2E tests that wait for `RUNNING` wait longer | Existing waits use 300-second budgets; run the whole `shard_general` and `shard_backup` locally before handoff; `fix` changelog fragment and docs explain the change |
| The readiness timeout (270 seconds) now applies to updates | A rollout slower than 270 seconds shows `FAILED`, then `RUNNING` if it completes | Below FluxCD's own 5-minute timeout, so the failed step lists the pods before FluxCD's rollback removes them; documented; `deployment_ready_timeout` stays configurable |
| Two writers change the same step | Lost or out-of-order transitions | Row locks; final states; failed-to-running only for operator-phase steps |
| A remediation flow dies without closing its step | A task stays `RUNNING` | `apply_state`, the `run_job` wrapper, the backup and restore flows and the callback close open flow-kind steps |
| Forged reports through the unauthenticated `reportDeploymentStatuses` | Forged operator-phase steps | Same exposure as `Deployment.status` today; tracked by [#396](https://github.com/opsmill/styrmin/issues/396) |
| FluxCD attempts faster than the operator's 60-second check | Attempts undercounted | Documented limit (research D6) |
| FluxCD rolls back after each failed attempt, then retries | Treating a rollback as final would leave the CR `Failed` after a successful retry | Only `Stalled=True`, and FluxCD's `Ready=True` for its own rollback of the generation, are final; the readiness timeout is the safety net (research D5) |
| Timeline payload and query count grow | Slower page refresh | No output in the timeline query; precomputed read model with a query-count test; output loaded per step |
| New task types for reconcile tasks | Consumers that expected `noop` see `create_instance`, `update_instance`, `upgrade_instance` and the component types | The values already exist in the enum and in the frontend labels; E2E `VALID_TASK_TYPES` already accepts them; changelog fragment |

High-risk areas touched (AGENTS.md): database, operator, agent status reporter, Prefect flow dispatch, authentication (new `READ_WRITE` mutation and new action-token users). The PR description calls each out.

## Governance gates crossed

- **Database schema**: `step` table; `task.instance_id`; `task.started_by_step_id`.
- **GraphQL schema**: new types, enums, `Query.step`, `recordStep`, `startedByStepId` on three mutations.
- **Authentication and authorization**: `recordStep` requires `READ_WRITE`, accepts only the `styrmin-actions` user, and is called with the action token; `run_job` gets an action token (PRD); backup and restore flows get an action token (research D13, beyond the PRD's implementation note).
- **Operator behaviour**: the CR status gains `instanceId`, `rolloutStartedAt` and `HelmReleaseRemediated`, and updates wait for FluxCD (research D5).
- **Helm chart RBAC**: the agent can `get` and `list` `podvolumebackups`.
- No new dependency. No CI/CD workflow change: the new E2E file uses the existing `shard_general` marker.

## Documentation

| Page | Change |
|---|---|
| `docs/docs/concepts-and-architecture/status-reporting.md` | Steps, task results, the 15-second update, "no report from the agent" |
| `docs/docs/concepts-and-architecture/operator-and-crds.md`, `docs/docs/reference/styrmindeployment.md` | `status.instanceId`, `status.rolloutStartedAt`, `HelmReleaseRemediated`, the current-generation rule, the timeout from the rollout start |
| `docs/docs/concepts-and-architecture/hooks-and-actions.md`, `docs/docs/reference/driver-api.md` | Each hook mode is a step; failed command output is stored and visible to every signed-in user, so commands must not print secrets; SDK calls are not linked as started tasks |
| `docs/docs/concepts-and-architecture/backups-and-restores.md` | Restore and backup steps |
| `docs/docs/reference/styrminctl.md` | `tasks get` step table; `apply --wait` failed line |
| `docs/docs/concepts-and-architecture/glossary.md` | Step, Task result |
| `dev/knowledge/backend/orchestration-flows.md`, `hooks-and-actions.md`, `data-models.md`, `api.md`, `backup-restore.md`; `dev/knowledge/agent/operator.md`, `overview.md`; `dev/knowledge/frontend/data-fetching.md` (if the output query pattern is new) | The path from flows and the operator to steps; the new tables; the operator changes |
| `dev/adr/0060-steps-and-derived-task-result.md` (new) | Steps as records written through one recorder, the derived task result, the three writers, the operator's current-generation rule |
| `CONTEXT.md` | Step and Task result (drafted in the specify phase); `instanceId` meaning on the CR status |
| `changelog/2.added.md`, `changelog/2.fixed.md`, `changelog/2.changed.md` | The feature; updates no longer reported ready before FluxCD applies them; reconcile tasks get their real type instead of `noop` |
| `dev/guides/users-and-groups.md` | `styrmin-actions` sessions are also created by `run_job`, backups and restores |

## Complexity Tracking

No constitution violation needs justification.
