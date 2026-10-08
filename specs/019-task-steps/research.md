# Research: Steps and Failure Causes for Tasks, Backups and Restores

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Source PRD**: [opsmill/styrmin#2 (comment)](https://github.com/opsmill/styrmin/issues/2#issuecomment-6012882649)

Each decision below was made by Claude during planning. Its label names the evidence it is based on. Decisions that the PRD confirmed in the grilling session say so. File references point at `develop` at commit `4f12e062`.

## Current behaviour that shapes the design

These facts come from the code and decide most of the design.

1. **A reconcile runs in three processes** ([ADR-059](../../dev/adr/0059-driver-action-api-tokens.md)).
   - `apply_state` runs on `styrmin-work-pool` in the task worker pod, which has database access (`backend/styrmin_backend/agent/tasks/orchestration.py:163`).
   - It starts the remediation flow (`create_instance_crd`, `update_instance_crd` or `upgrade_instance_crd`) as a Kubernetes Job on `user-work-pool`. That Job has no database access.
   - The remediation flow starts each driver action as another Job on `user-work-pool` (`agent/tasks/utils.py:31`).
2. **`apply_state` tasks all have the type `noop`** (`services/reconciliation/__init__.py:66`). The timeline labels them "No-op" (`frontend/src/components/deployment/DeploymentTimeline.tsx:21`). Only `run_job` and `delete_deployment` tasks have their own types.
3. **Nothing links a task to the instance it rolled out.** The timeline correlates them by `created_on` ([ADR-028](../../dev/adr/0028-deployment-history-derived-from-existing-data.md)). Every `apply_state` call follows the creation of a new instance (`services/deployment.py:425, 627, 939, 1074, 1192, 1484`, `services/primitives.py:136, 196`), so one instance belongs to exactly one task.
4. **The status reporter sends `spec.instanceId`** (`agent/status/reporter.py:157`). Right after a flow writes a new spec, the CR still carries the previous rollout's status, so a report can pair the new instance with the old `Ready` phase. The upgrade flow works around this by resetting the status after its write (`orchestration.py:740`). The update flow does not.
5. **The operator marks an update ready without waiting for FluxCD.** The update handler keeps the `HelmReleaseReady=True` condition from the previous rollout (`operator/handlers/styrmin_deployment.py:386`). The timer then skips the FluxCD check (`styrmin_deployment.py:561`) and moves to `Ready` on its next tick. [`dev/knowledge/agent/operator.md`](../../dev/knowledge/agent/operator.md) states that HelmRelease failures after `Ready` are not reflected in the CR status. This is the cause of the PRD's statement that "a task can show `SUCCESS` while the HelmRelease fails a few minutes later".
6. **The readiness timeout counts from the CR's creation time** (`styrmin_deployment.py:529`). On any update of a CR older than 300 seconds, the timer sets `displayState: Error` before the same tick moves the CR to `Ready`. Fact 5 hides this today.
7. **The operator's timer runs every 60 seconds** (`config.py:167`), and the status reporter every 5 seconds (`config.py:159`). The deployment page refreshes every 10 seconds (`DeploymentDetailPage.tsx:81`).
8. **`execute_commands` and `run_job` wait on a Kubernetes Job and never read its output** (`agent/service/kubernetes/primitives.py:92, 534`). The Job that `execute_commands` creates is never removed ([#374](https://github.com/opsmill/styrmin/issues/374)).
9. **The three restore steps run in the USER flow** `execute_velero_restore_flow` (`workflows/templates/backup.py:172`), not in the INTERNAL flow. The INTERNAL flow learns the outcome only after the USER flow ends, through a Prefect Variable.
10. **Velero runs one backup for the whole namespace.** Styrmin uses Velero file-system backup (`helm/styrmin/values.yaml:368`), which creates one `PodVolumeBackup` per annotated pod volume. The agent's RBAC does not allow reading `PodVolumeBackup` objects (`helm/agent/templates/roles.yaml:163`). `update_backup_component_status` exists but nothing calls it (`services/backup/service.py:288`).
11. **`reportDeploymentStatuses` and `callback` accept unauthenticated calls** (`api/auth/allowlist.py:26`, tracked by [#396](https://github.com/opsmill/styrmin/issues/396)).

## D1. One `step` table with three parent references

[CLAUDE RECOMMENDED – based on PRD key entity "Step" and the concurrency of writers]

- **Decision**: A new `step` table. Each row references exactly one of `task`, `backup` or `restore` through three nullable foreign keys with `ON DELETE CASCADE`, guarded by a `CHECK` that exactly one is set. A partial unique index on (parent, `key`) per parent type makes "open this step" idempotent.
- **Rationale**: Several writers change steps at the same time (D2), so each step needs its own row and row lock. Real foreign keys give the cascade that FR-016 requires.
- **Alternatives rejected**:
  - A JSON list on `Task`, `Backup` and `Restore`: concurrent writers would overwrite each other's changes, and the list would be stored three times.
  - One `parent_id` column with a `parent_type` column: no foreign key, so no cascade and no integrity check.
  - One table per parent type: three copies of the same code.

## D2. Three writers, one step recorder

[CLAUDE RECOMMENDED – based on PRD "Step recorder ... the only entry point" and facts 1 and 9]

- **Decision**: The step recorder service (`services/steps/recorder.py`) is the only code that creates or changes steps. It is called in three ways:
  - **In the server process or an INTERNAL flow**, directly: `apply_state` (the "Plan the changes" step), `deleteDeployment` (the "Request the deletion" step), the callback mutation, and the INTERNAL backup and restore flows.
  - **From a USER flow or a driver action**, through the new `recordStep` mutation with the action token: the remediation flows, the `run_job` command flow, `execute_commands`, and the Velero backup and restore flows.
  - **From the operator**, indirectly: the operator writes the CR status, the status reporter sends it, and the operator phase history (D6) turns each report into recorder calls.
- **Rationale**: The process that does the work is the one that knows when it starts and ends. A USER flow has no database access, so it uses the API like the action primitives already do (ADR-059).
- **Failure policy**: A failed step write never fails the work. The flow step reporter logs a warning and continues. Recording a step has no effect on the cluster (Constitution §I).
- **Task row not committed yet**: `apply_state` dispatches the flow before its caller commits the task row (`services/reconciliation/__init__.py:84`, `services/primitives.py:144-151`); the callback already tolerates this by returning `success: false`. The "Plan the changes" write therefore retries on `TaskNotFoundError` for up to 10 seconds before it logs and gives up.

## D3. USER flows find their step parent through environment variables

[CLAUDE RECOMMENDED – based on the `STYRMIN_TOKEN` path in ADR-059]

- **Decision**: The process that starts a USER Job adds these variables to the Job's `env` job variable, next to `STYRMIN_TOKEN`:
  - `STYRMIN_TASK_ID`, `STYRMIN_BACKUP_ID` or `STYRMIN_RESTORE_ID`: the parent of the steps the Job records. Exactly one is set.
  - `STYRMIN_STEP_ID`: set only for a driver action's Job. It is the hook step that runs the action.

  `api_token_job_variables` becomes `action_job_variables(token, *, task_id=None, backup_id=None, restore_id=None, step_id=None)`.
- **Rationale**: The token already travels this way, and Prefect merges a flow run's `env` into the work pool's default `env`. No registered flow signature changes.
- **Alternatives rejected**: New flow parameters. They change the parameters that every remediation strategy builds and the schemas of the registered Prefect deployments, for values that only the step reporter reads.

## D4. Operator reports find their task through the instance the operator handled

[CLAUDE RECOMMENDED – based on facts 3 and 4, and PRD "the CRD's `instanceId` links an operator report to the task"]

- **Decision**:
  - `Task` gains `instance_id`, set by the `apply_state` service function to the new instance it schedules.
  - The operator's create, update and resume handlers write `status.instanceId`: the instance whose spec they last handled.
  - The status reporter sends `status.instanceId`, and falls back to `spec.instanceId` for a CR that no operator handler has touched since the upgrade.
  - The operator phase history finds the task by `Task.instance_id`. Reports in the `Deleting` and `Deleted` phases go to the newest `delete_deployment` task of the deployment instead.
- **Rationale**: `status.instanceId` changes only when the operator has acted on the new spec, so a report never pairs a new instance with the previous rollout's phase (fact 4). The same change makes the existing stale-instance guard on `Deployment.status` (`services/deployment_status.py:85`) correct for updates, not only upgrades. The GraphQL input of `reportDeploymentStatuses` does not change, as the PRD recommends.
- **Alternatives rejected**:
  - Correlating by time, as ADR-028 does for versions: approximate, and the times come from two clocks.
  - Comparing condition times with the time of the CR write: depends on clock skew between pods.
  - Sending the CR's `metadata.generation` in a new report field: changes the report input.

## D5. The operator judges the HelmRelease on its current generation

[CLAUDE RECOMMENDED – based on facts 5 and 6, US2 acceptance scenario 1, FR-004 and SC-003]

The P1 acceptance scenario is an upgrade whose HelmRelease does not become Ready. With fact 5, the operator reports that upgrade as `Ready` within a minute, so the HelmRelease step would succeed and the task result would be `SUCCEEDED`. The operator must change.

- **Decision**: The StyrminDeployment handlers change in five ways.
  1. **Reset on each rollout.** The create and update handlers set `HelmReleaseReady` to `Unknown` with reason `Progressing`, and record `status.rolloutStartedAt`. The resume handler continues a rollout: it records `status.rolloutStartedAt` only when it is missing, so an operator restart does not extend the readiness timeout, and it does not reset `HelmReleaseReady`.
  2. **Judge the current generation.** In `CreatingHelmRelease`, the timer reads the HelmRelease once per tick. It counts FluxCD's `Ready=True` only when that condition's `observedGeneration` equals the HelmRelease's `metadata.generation`, the same rule as the component-container guard (`operator/reconciler.py:409`).
  3. **Copy FluxCD's state.** While the current generation is not Ready, the timer copies FluxCD's `Ready` reason, message and transition time into `HelmReleaseReady`. When FluxCD's `Remediated` condition is `True` for the current generation, the timer copies it into a new `HelmReleaseRemediated` condition.
  4. **Stop on FluxCD's final failure.** When FluxCD's `Stalled` condition is `True` for the current generation (FluxCD has used all its retries), the timer sets the phase `Failed` and `displayState: Error` with FluxCD's message. `Remediated=True` alone is not final: with `remediation.retries: 3` (`agent/service/kubernetes/resources/builders/application.py:231`), FluxCD rolls back after each failed attempt and then tries again, and a later attempt can succeed.
  5. **Time out from the rollout start.** The readiness timeout counts from `status.rolloutStartedAt`, and falls back to `creationTimestamp`. It stays the safety net when FluxCD never reports `Stalled`.
- **Consequences**:
  - An update or upgrade reaches `RUNNING` only after FluxCD reports the new release Ready. With `spec.timeout: 5m` and Helm's wait enabled by default ([FluxCD documentation](https://fluxcd.io/flux/components/helm/helmreleases/)), that is after the new pods are ready.
  - A failed update or upgrade ends `FAILED` instead of `RUNNING`. This is a visible change in behaviour and gets a `fix` changelog fragment.
  - The CRD's status schema keeps `x-kubernetes-preserve-unknown-fields: true` (`helm/agent/crds/styrmin.io_styrmindeployments.yaml`), so the new status fields need no CRD change. The CRD file still documents them for new installs.
- **Alternatives rejected**:
  - Leave the operator as it is: the P1 acceptance scenario cannot pass.
  - A kopf handler on HelmRelease status changes that writes the CR's conditions: two handlers would write `status.conditions` on the same CR. A merge patch replaces the whole list, so one handler would overwrite the other's change.
  - A shorter timer interval to show FluxCD's reason sooner: changes the cost of drift detection for every deployment. FR-005 is measured from the moment a change is recorded, and FluxCD's reason concerns failures that take minutes. Out of scope.
- **FluxCD extension points evaluated** (research directive on third-party dependencies): FluxCD already exposes everything needed in the HelmRelease status: the `Ready`, `Released`, `Remediated` and `Stalled` conditions, their `observedGeneration`, and the `installFailures` and `upgradeFailures` counters ([`condition_types.go`](https://github.com/fluxcd/helm-controller/blob/main/api/v2/condition_types.go), [`helmrelease_types.go`](https://github.com/fluxcd/helm-controller/blob/main/api/v2/helmrelease_types.go)). No extension or upstream change is needed.
- **As built (review finding H1)**: a sixth rule. A live run of `test_helmrelease_failure_shows_fluxcd_reason` (helm-controller v1.1.0) showed that, about 11 seconds after FluxCD rolled back an upgrade that only changed post-renderers, FluxCD found the rolled-back release in sync with the current generation: it set `Ready=True` and `Released=True` with reason `UpgradeSucceeded` for the rollback release, removed `Remediated`, and kept `upgradeFailures: 1`. The conditions alone cannot tell this from a retry that succeeded. The timer therefore counts `Ready=True` as FluxCD's rollback when FluxCD counted a failed install or upgrade for the current generation and the newest `status.history` entry is `deployed` with the version right after a `failed` entry, and then sets the phase `Failed`, `displayState: Error` and `Ready=False` with reason `RolledBack`. A retry that succeeds adds a newer release after the rollback and still reaches `Ready`. See [`dev/knowledge/agent/operator.md`](../../dev/knowledge/agent/operator.md#rollback-reported-ready).

## D6. Operator-phase steps and the phase history

[CLAUDE RECOMMENDED – based on PRD FR-001, FR-002, FR-004 and the module "Operator phase history"]

- **Decision**:
  - **Creation**: When a remediation flow reports that its "Write the StyrminDeployment resource" step succeeded, the recorder creates the four operator-phase steps of that task: "Create network policies and secrets" (running), "Install or upgrade the HelmRelease", "Create services and middlewares" and "Wait for the deployment to be ready" (pending). Pending steps keep the task result `RUNNING` in the gap between the end of the flow and the first operator report (FR-006: "not started"). An internal deployment gets no operator-phase steps, because the status reporter does not report internal deployments (`reporter.py:205`).
  - **Mapping**: For each report of the task's instance, until a newer task writes the StyrminDeployment or requests the deletion (D7), the phase history moves the steps forward by phase: `CreatingPrerequisites`, `CreatingHelmRelease`, `CreatingServices`, `Ready`. A report can skip phases between two polls; every earlier step then succeeds. A step's end time is the transition time of its condition when the report carries one, and the report time otherwise.
  - **Failures**: Phase `Failed` or `displayState: Error` fails the running step with the CR message. When the step is the HelmRelease step or "Wait for the deployment to be ready", the error also lists the pods of the deployment whose containers wait or ended with an error reason (for example `ImagePullBackOff`), read from the stored pod statuses. This names the cause of SC-001's third failure type: FluxCD's message after a Helm wait timeout does not say why the pods are not ready.
  - **Attempts**: A failed step becomes running again, with one more attempt, when a later report shows the operator working on it again (the operator retries after 30 seconds). When a report shows a later phase, every earlier failed step gets a new attempt and succeeds: this happens when the readiness timeout failed the HelmRelease step and a later FluxCD attempt then succeeded. On the HelmRelease step, each FluxCD failure reason (`InstallFailed`, `UpgradeFailed` and the other `*Failed` reasons) with a new message or transition time adds the error to the current attempt and starts the next one. The operator reads FluxCD every 60 seconds, so attempts that fail faster than that are counted as one. This limit is documented.
  - **FluxCD's reason and rollbacks**: While the HelmRelease step runs or has failed, its `detail` holds FluxCD's current reason and message. The `HelmReleaseRemediated` condition sets `rolledBackAt` and `rollbackMessage` (FR-004); a newer rollback replaces the older one.
  - **Cost**: The phase history runs for every report, every 5 seconds. It returns before locking any row when the task's operator-phase steps are all final.
  - **Deletes**: A `delete_deployment` task has two steps: "Request the deletion", recorded by the service when it patches the CR, and "Remove the deployment's resources and namespace", which runs during the operator's `Deleting` phase and succeeds at `Deleted`. The operator's teardown runs in one handler call, so it has no finer phases to report.
- **Kopf extension points evaluated**: kopf records handler progress in annotations and can post Kubernetes Events. Kubernetes keeps Events for one hour by default, and the server does not read them. Neither gives a durable phase history, so the server keeps it.

## D7. A rollout supersedes the open operator-phase steps of older tasks

[CLAUDE RECOMMENDED – based on PRD FR-007 and the edge case "A later task interrupts the operator phases"]

- **Decision**: When a "Write the StyrminDeployment resource" step or a "Request the deletion" step succeeds, the recorder sets every pending or running operator-phase step of every older task of the same deployment to `superseded`, with `superseded_by_task_id` set to the new task. A task is older when it was created first; tasks created at the same time are ordered by id. A superseded step is final.
- **Rationale**: The operator abandons the earlier rollout as soon as the spec changes, so the write is the moment of interruption. It does not depend on when the next report arrives.
- **Late success events**: The success of an older task's write can reach the server after a newer task's write ([review thread](https://github.com/opsmill/styrmin/pull/404#discussion_r4206764461)). That success does not supersede the steps of a newer task, so the reports for the newer rollout keep moving its steps. When a newer task of the deployment has already written the StyrminDeployment or requested the deletion, the recorder creates the older task's operator-phase steps and the first such newer task supersedes them at once, so they do not stay pending.
- **Late status reports**: Superseding leaves failed steps `failed`. A report for the older task's instance can still arrive after the newer write, before the operator reads the new spec ([review thread](https://github.com/opsmill/styrmin/pull/404#discussion_r4206764626)). Once a newer task of the deployment has written the StyrminDeployment or requested the deletion, the phase history changes no step of the older task for a report outside the `Deleting` and `Deleted` phases, so a late `Ready` does not succeed a failed step. Before that write, reports for the older instance still move the older task's steps. The phase history does not use the stale-instance guard on `Deployment.status`: that guard skips every report of the older instance as soon as the deployment's active instance changes, before the newer task's flow runs, so a newer task that fails before it writes the CR would leave the older task's steps running for good.

## D8. Task result calculation

[CLAUDE RECOMMENDED – based on PRD FR-006 and the edge cases]

- **Decision**: `compute_task_result` is a pure function in `services/steps/results.py`. It works on the task's **family**: the task and every task its hook steps started, transitively. It applies the PRD's rules in the PRD's order:
  1. `RUNNING` when a step of the family is pending or running.
  2. `FAILED` when a step of the family failed.
  3. `SUPERSEDED` when a step of the family was superseded by a task outside the family.
  4. `SUCCEEDED` otherwise.

  For a task that started no task, the family is the task itself, and the rules read exactly as FR-006.

  A task with no steps gets its result from `Task.status`: `pending` and `running` give `RUNNING`, `success` gives `SUCCEEDED`, `failed` gives `FAILED`. The deployment page shows "no steps recorded for this task" for a finished task with no steps (FR-010), and "waiting for the first step" for an unfinished one.
- **Why the family**: The tasks that one hook starts interrupt each other. In the simple-app upgrade (`driver/examples/simple-app/actions.py`), `stop_components` and `upgrade_deployment_version` each write the CR before the operator finishes the previous rollout, and only `start_components` completes. With rules that look only at the upgrade's own steps and its direct results, the upgrade could never be `SUCCEEDED`, and an outside task interrupting `start_components` would not make the upgrade `SUPERSEDED`. With the family, the upgrade is `SUCCEEDED` when the last rollout succeeds, and each interrupted started task still shows `SUPERSEDED` on its own entry.
- **Order**: `RUNNING` comes before `FAILED`, as in the PRD's list. A task whose post-hook failed after the CR write stays `RUNNING` until the operator finishes, because the work is not over. The failed step is visible in the step list at once.
- **Pending steps behind a failure**: The operator leaves the steps after a failed phase pending. A pending step therefore counts as `RUNNING` only when its task has no failed step; otherwise a failed HelmRelease would keep its task `RUNNING` after the deployment is `FAILED` (US3 acceptance scenario 1, SC-003). A new attempt makes the failed step running, and the task `RUNNING` again. [CLAUDE RECOMMENDED – based on the E2E run of T076]
- **Recursion**: The family is collected with a visited set, so a cycle cannot loop. In practice the depth is 1, because tasks started by `stop_components`, `start_components` and `upgrade_deployment_version` have no hook steps.

## D9. "No report from the agent" is derived on read

[CLAUDE RECOMMENDED – based on PRD FR-009 and the existing `DeploymentStatus.last_polled_at` column]

- **Decision**: `Step.noReportSince` is calculated on each read. For a running operator-phase step, it is the deployment's `DeploymentStatus.last_polled_at` (or the step's start time when no report exists) when that time is more than 60 seconds ago, and null otherwise.
- **Rationale**: The server already records the time of the last report for each deployment. Nothing new is stored, and the message disappears with the next report.

## D10. Command output

[CLAUDE RECOMMENDED – based on spec FR-003 and fact 8]

- **Decision**:
  - The process that waits on the Job reads the output when the Job fails, before it raises: `execute_commands` in the action's Job, and the `run_job` command flow.
  - It reads the newest pod of the Job (label `batch.kubernetes.io/job-name`, falling back to `job-name`) with `read_namespaced_pod_log(tail_lines=201, limit_bytes=65537)`. Getting 201 lines or 65,537 bytes means that earlier output was cut.
  - `execute_commands` records the output on its hook step through `STYRMIN_STEP_ID` with the `OUTPUT` event. The `run_job` command flow records it on its own step.
  - The server keeps at most the last 200 lines and 64 KiB, and sets `output_truncated` when it cuts more.
  - When the output cannot be read, for example because the pod was evicted, the step error says so.
- **Rationale**: Kubernetes' log API returns the end of a log directly. The agent's RBAC already allows `pods/log` (`helm/agent/templates/roles.yaml:111`).

## D11. `run_job` gets an action token from an INTERNAL wrapper flow

[CLAUDE RECOMMENDED – based on PRD FR-014 "in the same way that `apply_state` creates one"]

- **Decision**: The `RUN_JOB` catalogue entry becomes an INTERNAL flow `run_job` that keeps the existing callbacks and `task_id` parameter. It opens `action_api_token()` and runs a new USER flow `run_job_command` with `run_deployment_or_fail`, passing the token and `STYRMIN_TASK_ID` as job variables. `run_job_command` builds the Job manifest that `run_job` builds today and records the step "Run the job's command".
- **Rationale**: This is the `apply_state` pattern: the INTERNAL flow has database access to create and revoke the session, and the USER flow has cluster access.
- **Alternatives rejected**: Creating the token in the `runJob` mutation and revoking it in the callback. A lost callback would leave a valid token for 24 hours, and token handling would live in two places.

## D12. Tasks started by a hook link to the hook step

[CLAUDE RECOMMENDED – based on PRD FR-008 and fact 1]

- **Decision**: `Task` gains `started_by_step_id`. The mutations that the action primitives call, `stopComponents`, `startComponents` and `updateDeploymentVersion`, gain an optional `startedByStepId` argument. The primitives send the value of `STYRMIN_STEP_ID`. `Task.startedBy` resolves through the step to its task, and `Task.startedTasks` lists the tasks whose `started_by_step_id` is one of the task's steps.
- **Rationale**: The hook step is known only inside the remediation flow, which passes it to the action's Job (D3). An explicit argument is typed and covered by propagation tests.
- **Alternatives rejected**:
  - Linking the action token's session to the task: adds a task column to the authentication table, and cannot tell which hook step started the task.
  - An HTTP header: the link would be invisible in the schema and not covered by propagation tests.
- **Limit**: A driver action that calls the API through the SDK instead of the primitives creates tasks without the link. This is documented for driver authors.

## D13. Backup and restore steps

[CLAUDE RECOMMENDED – based on facts 9 and 10. This differs from the PRD's implementation note, see below]

- **Decision**:
  - **Restore**: `execute_velero_restore_flow` records "Delete the namespace", "Run the Velero restore" and "Run the recovery" through the flow step reporter. The INTERNAL flow `execute_restore_workflow` creates an action token with `action_api_token()` and passes it with `STYRMIN_RESTORE_ID`.
  - **Backup**: `execute_velero_backup_flow` records one step per component, "Back up <component>". On each poll it lists the `PodVolumeBackup` objects of the backup, maps each pod to its component through the pod's `styrmin/component` label, and sets the step's start time, end time and result from them. A component with no `PodVolumeBackup` when the backup ends gets the Velero backup's result and times. The agent's RBAC gains `get` and `list` on `podvolumebackups`.
  - **Crash handling**: When the USER flow fails or crashes, the INTERNAL flow fails every step of the backup or restore that is still pending or running, with the flow's state message, through the recorder directly.
  - **Velero's `FailedValidation` phase**: `poll_backup_status` and `poll_restore_status` return only on `Completed`, `PartiallyFailed` and `Failed` (`velero/client.py:253, 272`). A restore of a backup that Velero cannot find ends in `FailedValidation` and would be polled until the 7,200-second timeout. Both functions treat `FailedValidation` as terminal, and the step fails with Velero's `status.validationErrors`.
- **Difference from the PRD**: The PRD's implementation decisions say that backup and restore flows "write their steps through the step recorder directly, because they run as INTERNAL flows with database access". The three restore steps and the per-component backup work run in the USER flow (facts 9 and 10). Recording them only after the USER flow ends would hide a stuck step for up to two hours (the restore timeout) and lose the step that a crash interrupted. FR-014 already requires Prefect flows to write steps with the action token. The INTERNAL flows still write the steps they own directly.
- **Velero extension points evaluated**: Velero has no per-component concept. `PodVolumeBackup` objects carry the pod, the volume, the phase and the start and end times, which is enough to build per-component steps without an upstream change.

## D14. GraphQL surface

[CLAUDE RECOMMENDED – based on the PRD's recommended surface, which leaves final names to the plan]

- **Decision**: See [contracts/graphql.md](contracts/graphql.md). In short:
  - A `Step` type, a `StepError` type, and the enums `StepStatus`, `StepKind`, `StepEvent` and `TaskResult`.
  - `Task.steps`, `Task.result`, `Task.startedBy` and `Task.startedTasks`; `Backup.steps` and `Restore.steps`.
  - `Query.step(stepId)`, used to load one step's output on demand.
  - `Mutation.recordStep(input)`, which requires `READ_WRITE`.
  - The optional `startedByStepId` argument on three existing mutations (D12).
  - No change to `reportDeploymentStatuses` (D4).
- **Read cost**: Styrmin's resolvers query per object (`api/resolvers.py:13`) and there are no data loaders, so per-field resolvers for `Task.steps`, `Task.result`, `Step.supersededBy` and `Step.startedTasks` would run about a thousand queries for a 50-task timeline on every 10-second refresh. Instead:
  - The timeline service builds a read model in three queries: the steps of all the deployment's tasks, the tasks started by those steps (with their steps), and the deployment's `DeploymentStatus`. It calculates every family result and `noReportSince` in memory.
  - The GraphQL `Task` and `Step` objects carry their part of the read model in `strawberry.Private` fields. Their resolvers use it when present and query only for single reads such as `Query.task` and `Query.step`.
  - A unit test counts the queries of a timeline read and fails above a fixed number.
  - The timeline query requests steps without `output`. `Step.hasOutput` tells the page whether to offer the output, which it loads with `Query.step`.
- **Who may call `recordStep`**: `READ_WRITE` and, in addition, only the built-in `styrmin-actions` user (`services/auth/bootstrap.py:31`). Other users get `FORBIDDEN`, so a person cannot change the record of what happened.
- **Strawberry**: Supports enums, input types, permission extensions, private fields and per-field resolvers as used today. No extension is needed.

## D15. Frontend

[CLAUDE RECOMMENDED – based on PRD "Step list (frontend component, new)" and the existing page]

- **Decision**: A `StepList` component shows the steps inside each timeline entry and inside each backup and restore row on the deployment page. Each timeline entry shows the task result instead of `Task.status`. The page keeps its 10-second refresh (`refetchInterval`), which with the 5-second report interval gives FR-005's 15 seconds.
- **TanStack Query**: `refetchInterval` is enough. Server push is out of scope.

## D16. SDK and `styrminctl`

[CLAUDE RECOMMENDED – based on PRD FR-012]

- **Decision**:
  - The SDK's `get_task` and timeline operations request the steps, the result and the links.
  - `styrminctl tasks get` prints the task, then a table of steps with name, status, duration, attempts and error.
  - `StyrminClient.deployments.apply(wait=True)` sets `failure_reason` from the failed step when the deployment fails: it searches the task's steps, then its started tasks, and writes `step "<name>" failed: <error>`. The `failed` line of `styrminctl deployments apply --wait` prints that reason, so both the SDK and the CLI get it.

## D17. Prefect evaluated as the place to keep steps

[CLAUDE RECOMMENDED – based on the research directive on third-party dependencies]

- **Decision**: Steps are stored in Styrmin's database, not in Prefect.
- **Evaluated**: Prefect's task runs, flow-run states and progress artifacts can describe progress.
- **Rejected because**:
  - The problem statement is that users cannot reach the Prefect server. Steps must be readable by every signed-in user through Styrmin's API (FR-011).
  - Most of the work happens in the operator, outside Prefect (fact 5).
  - Prefect's retention would decide how long steps are kept, against FR-016.
- Prefect's flow-run job variables are the extension point used to pass the token and the step parent (D3).

## D18. Security consequences

[CLAUDE RECOMMENDED – based on PRD Assumptions and fact 11]

- Every signed-in user, including `READ_ONLY`, can read command output. The PRD records that the team accepted this. The driver-author documentation says that action commands must not print secrets.
- `recordStep` requires `READ_WRITE`, accepts only the built-in `styrmin-actions` user (D14), and is not on the allow-list (FR-014).
- The phase history writes operator-phase steps from `reportDeploymentStatuses`, which accepts unauthenticated calls. A caller who can reach the API can already set `Deployment.status` through it; after this feature it can also change operator-phase steps. [#396](https://github.com/opsmill/styrmin/issues/396) tracks authentication for that mutation, which is out of scope.
- Backups and restores now create one `styrmin-actions` session each, like reconciles (ADR-059).

## D19. Tasks are stored with the type their caller means

[CLAUDE RECOMMENDED – based on fact 2, User Story 1 and spec FR-019]

- **Decision**: The `apply_state` service function takes a `task_type` argument, and each caller passes the operation it starts:

  | Caller | Task type |
  |---|---|
  | `deploy_application` (`createDeployment`); `_ensure_ingress_controller` when the deployment has no instance yet | `create_instance` |
  | `update_deployment`, `refresh_deployment`, `redeploy_for_environment_update`; `_ensure_ingress_controller` otherwise | `update_instance` |
  | `updateDeploymentVersion` | `upgrade_instance` |
  | `stopComponents`, `startComponents` | `stop_components`, `start_components` |

  The frontend gains the label "Delete" for `delete_deployment`, which it lacks today.
- **Rationale**: Users read the timeline by operation. A version change is an upgrade from the user's point of view even when the driver has no upgrade hook and the flow updates the CR instead; the step list shows which flow ran.
- **Alternatives rejected**:
  - Setting the type inside the `apply_state` flow from the remediation: the hook-started `stop_components` task would show "Update".
  - Deriving the type from the steps on read: the type would change while the task runs.
- `Task.status` is not touched (FR-015). Existing rows keep `noop`.

## Resolved clarifications

| Question | Decision | Where |
|---|---|---|
| How much command output to keep | The last 200 lines, at most 64 KiB | spec FR-003, D10 |
| How long to keep steps | As long as their task, backup or restore | spec FR-016, D1 |
| What "waiting for Ready" means | The step from the end of services to the CR's `Ready` phase | D6 |
| Which steps a delete has | "Request the deletion" and "Remove the deployment's resources and namespace" | D6 |
| Precedence between `RUNNING` and `FAILED` | `RUNNING` first, as in the PRD's list | D8 |
