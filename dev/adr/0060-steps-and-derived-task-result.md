# ADR-060: Steps Written Through One Recorder, and a Task Result Derived From Them

**Status**: Accepted
**Date**: 2026-10-06
**Source**: [issue #2](https://github.com/opsmill/styrmin/issues/2) and specs/archive/019-task-steps/
(research.md D1–D19, data-model.md, contracts/). Each decision in research.md names the evidence
it is based on.
**Related**: [ADR-059](0059-driver-action-api-tokens.md) (the action token that flows and actions
use to record steps), [ADR-028](0028-deployment-history-derived-from-existing-data.md) (the
deployment timeline that shows the steps), [ADR-019](0019-crd-phase-and-task-callback-coexist.md)
(`Task.status` follows the Prefect flow run), [ADR-005](0005-ordered-phase-deployment-sub-handlers.md)
(the operator's ordered phases), [ADR-055](0055-environment-backup-parent-records.md) (a status
derived on every read and never stored), [ADR-017](0017-authorization-model.md) (the allow-list),
[ADR-001](0001-alembic-database-migrations.md) (the revision this ships).
Open follow-up for the unauthenticated status report:
[issue #396](https://github.com/opsmill/styrmin/issues/396).

## Context

Users could not find out why a task failed, or what it was doing, without Prefect, `kubectl` or
server logs. Five facts of the code caused this:

1. **The work of a reconcile runs in four places.** `apply_state` runs on `styrmin-work-pool` with
   database access. It starts the remediation flow as a Kubernetes Job on `user-work-pool`, which
   has no database access. The remediation flow starts each driver action as another Job. The
   operator rolls the StyrminDeployment out once a flow writes it, and keeps working after every
   flow has ended.
2. **`Task.status` follows only the Prefect flow run** (ADR-019). Every task that a reconcile ran
   had the type `noop`, so the timeline labelled creates, updates and upgrades "No-op".
3. **Nothing linked a task to the instance it rolled out.** The status reporter sent
   `spec.instanceId`. Right after a flow wrote a new spec, the CR still carried the previous
   rollout's status, so a report could pair the new instance with the old `Ready` phase.
4. **The operator marked an update ready without waiting for FluxCD.** The update handler kept
   `HelmReleaseReady=True` from the previous rollout, so the timer moved the CR to `Ready` on its
   next tick. A HelmRelease that failed a few minutes later was not reflected in the CR status. The
   readiness timeout counted from the CR's creation time, so it did not apply to updates of an
   older CR.
5. **Command output was never read.** `execute_commands` and `run_job` waited on a Kubernetes Job
   and raised a generic error when it failed. `run_job` ran as a USER flow without an action
   token.

Backups and restores had the same problem. The three restore steps (delete the namespace, run the
Velero restore, run the recovery) run in the USER flow `execute_velero_restore_flow`. Velero runs
one backup for the whole namespace and creates one `PodVolumeBackup` per backed-up pod volume.

## Decision

### Storage

1. **One `step` table.** Each row belongs to exactly one task, backup or restore, through three
   nullable foreign keys with `ON DELETE CASCADE` and the check `ck_step_one_parent`. A partial
   unique index on (parent, `key`) for each parent type makes "open this step" idempotent. A step
   has a key, a name, a kind, a status (`pending`, `running`, `succeeded`, `failed`,
   `superseded`), start and end times, an attempt count, the error of each failed attempt,
   FluxCD's detail, the newest rollback, the end of a command's output, and the task that
   superseded it. Steps are kept as long as their parent.
2. **`task.instance_id`** records the instance that the task rolls out, and
   **`task.started_by_step_id`** the hook step that started the task. Both are `ON DELETE SET
   NULL`. Alembic revision `e2f3a4b5c6d7` adds the table and the two columns.

### One recorder, three ways to call it

3. **The step recorder (`services/steps/recorder.py`) is the only code that creates or changes
   steps.** It enforces the state rules: `succeeded` and `superseded` are final, `failed` is final
   except for operator-phase steps, and a transition that the rules forbid is logged and ignored,
   because a late write is not an error.
4. **Server code and INTERNAL flows call the recorder directly.** The `apply_state` flow records
   "Plan the changes" (`plan`), retrying for up to 10 seconds while the task row is not committed
   yet. `deleteDeployment` records "Request the deletion" as succeeded and a pending teardown step.
   The task callback fails the open flow steps of a task whose flow run failed. The INTERNAL
   `apply_state`, `run_job`, backup and restore flows fail the open steps of a USER flow that
   failed or crashed, because that flow cannot end them.
5. **USER flows and driver actions call `recordStep` with the action token** (ADR-059). The flow
   step reporter (`agent/steps/reporter.py`) reads `STYRMIN_TOKEN` and exactly one of
   `STYRMIN_TASK_ID`, `STYRMIN_BACKUP_ID` and `STYRMIN_RESTORE_ID` from the Job's environment, and
   a driver action's Job also gets `STYRMIN_STEP_ID`, the hook step that runs it. The process that
   starts a Job adds these variables to the flow run's `env` job variable with
   `action_job_variables`. The remediation flows record their hook steps and the
   "Write the StyrminDeployment resource" step this way.
6. **Operator reports change operator-phase steps.** The operator writes the CR status, the status
   reporter sends it, and `report_deployment_statuses` passes each report to the operator phase
   history (`services/steps/operator_history.py`). The phase history runs in a savepoint of the
   report's transaction, so its failure does not lose the status snapshot.
7. **A failed step write never fails the work.** The reporter and the direct writers log a warning
   and continue. Without a token or a parent, the reporter records nothing.
8. **`recordStep` requires the `READ_WRITE` role and the built-in `styrmin-actions` user**
   (`IsActionsServiceAccount`). Every other caller, an admin included, gets `FORBIDDEN`, so no
   person can change the record of what happened. `Query.step` and the step fields of `Task`,
   `Backup` and `Restore` are readable by every signed-in user.

### Linking operator reports to their task

9. **`status.instanceId` names the instance that the operator acted on.** The create, update and
   resume handlers copy `spec.instanceId` into it, also when the handler raises. The status
   reporter sends `status.instanceId`, and `spec.instanceId` for a CR that no handler has touched
   since the upgrade. The phase history finds the task by `task.instance_id`. Reports in the
   `Deleting` and `Deleted` phases go to the newest `delete_deployment` task of the deployment.
   The `reportDeploymentStatuses` input does not change, and the existing stale-instance guard on
   `Deployment.status` now compares the instance the operator acted on.

### The operator judges the HelmRelease on its current generation

10. **Each rollout starts from a clean HelmRelease state.** The create and update handlers set
    `HelmReleaseReady` to `Unknown` with reason `Progressing`, remove `HelmReleaseRemediated`, and
    set `status.rolloutStartedAt`. A kopf retry of these handlers runs them again, so it resets
    both. The resume handler sets `rolloutStartedAt` only when it is missing, so an operator
    restart does not extend the readiness timeout.
11. **Only the current generation counts.** A FluxCD condition counts when its
    `observedGeneration`, or else `status.lastAttemptedGeneration`, equals the HelmRelease's
    `metadata.generation`. This is the rule of the component-container guard (ADR-058).
12. **The timer copies FluxCD's state.** While the current generation is not Ready, it copies
    FluxCD's `Ready` status and transition time into `HelmReleaseReady`, with the reason and
    message of `Released=False` when `Ready` is `False`, because after a rollback `Ready` describes
    the rollback and `Released` describes the failed release. FluxCD's `Ready=True` sets
    `HelmReleaseReady` to `True` with reason `FluxReady`. FluxCD's `Remediated=True` is copied into
    the new condition `HelmReleaseRemediated`. The timer writes conditions only when they change.
13. **FluxCD's `Stalled=True` fails the rollout.** FluxCD has used all its retries, so the timer
    sets the phase `Failed`, `displayState: Error`, the message
    `"<Stalled message>: <failure message>"`, and `Ready=False` with the `Stalled` reason (for
    example `RetriesExceeded`). `Remediated=True` alone is not final, because FluxCD tries again
    after each rollback (`remediation.retries: 3`). FluxCD's `Ready=True` for its own rollback
    also fails the rollout: after rolling back a change of post-renderers alone, helm-controller
    v1.1.0 compares only the chart and the values, reports the rolled-back release as
    `UpgradeSucceeded` and removes `Remediated`. The timer counts `Ready=True` as that rollback
    when FluxCD counted a failed install or upgrade for the current generation and the newest
    `status.history` entry is `deployed` with the version right after a `failed` entry. It then
    sets the phase `Failed`, `displayState: Error`, the message
    `"FluxCD rolled the release back after release v<N> failed: <failure message>"`, and
    `Ready=False` with reason `RolledBack`. A retry that succeeds adds a newer release, so it
    still reaches `Ready`.
14. **The readiness timeout counts from `status.rolloutStartedAt`**, and from `creationTimestamp`
    for a CR that an older operator wrote. It stays the safety net when FluxCD never reports
    `Stalled`. Its default is 270 seconds, below FluxCD's 5-minute HelmRelease timeout: FluxCD's
    rollback at that timeout removes the failing pods, so a later timeout would fail the
    HelmRelease step without the pods' reasons. `apply --wait` waits 600 seconds by default
    (`--max-wait`, SDK `max_wait`), which leaves time for the flow and its hooks before the
    rollout starts.
15. **Internal deployments keep their exception.** A ready pod still counts as ready, and wins over
    `Stalled`, because their HelmRelease can stay `Progressing` when a LoadBalancer gets no
    external IP.

### Operator-phase steps

16. **Creation.** When "Write the StyrminDeployment resource" succeeds, the recorder creates the
    four operator-phase steps of the task: "Create network policies and secrets" (running),
    "Install or upgrade the HelmRelease", "Create services and middlewares" and "Wait for the
    deployment to be ready" (pending). Internal deployments get none, because the status reporter
    does not report them.
17. **Mapping.** Each reported phase (`CreatingPrerequisites`, `CreatingHelmRelease`,
    `CreatingServices`, `Ready`) succeeds the earlier steps and starts the step of that phase. End
    times come from the matching CR condition's transition time when it is `True`, and from the
    report time otherwise.
18. **Failures.** Phase `Failed` or `displayState: Error` fails the first unfinished step with the
    CR message. For the HelmRelease step and "Wait for the deployment to be ready", the error also
    lists up to five pods that have not finished and whose containers wait or ended with a reason
    such as `ImagePullBackOff`, read from the stored pod statuses.
19. **Attempts.** A failed operator-phase step starts a new attempt when a later report shows the
    operator working on it again, including a `Failed` CR whose `HelmReleaseReady` went back to
    `Unknown`/`Progressing` after the newest error. It succeeds with a new attempt when a later
    phase is reported. On the HelmRelease step, each new
    FluxCD reason that ends in `Failed` adds an error, `detail` holds FluxCD's current reason and
    message, and `HelmReleaseRemediated` sets `rolled_back_at` and `rollback_message`.
20. **Superseding.** When "Write the StyrminDeployment resource" or "Request the deletion" of a task
    succeeds, the recorder sets every pending or running operator-phase step of the deployment's
    other tasks to `superseded`, with a link to the new task. The operator abandons the earlier
    rollout as soon as the spec changes.

### The task result is derived, never stored

21. **The task result is calculated on every read** (`services/steps/results.py`), like the status
    of an environment backup (ADR-055). It covers the task's family: the task and the tasks its
    hook steps started, at any depth. The rules apply in this order:
    - `RUNNING` when the `Task.status` of a family member is `pending` or `running`, or a step of
      the family runs, or is pending and its task has no failed step;
    - `FAILED` when the `Task.status` of a family member is `failed`, or a step of the family
      failed;
    - `SUPERSEDED` when a step of the family was superseded by a task outside the family;
    - `SUCCEEDED` otherwise.

    `Task.status` counts in addition to the steps, because a flow can fail, or still run, between
    two steps: `apply_state` can fail after "Plan the changes" succeeded and before the remediation
    flow records a step, and Prefect starts the remediation flow some seconds after the plan step
    ended. A member whose flow succeeded counts by its steps only, so the operator-phase steps keep
    the task `RUNNING` after its flow ended. A family member without steps, such as a task from
    before this change, counts by its `Task.status` only. `Task.status` keeps its meaning, because
    driver actions wait on it.
22. **Why the family.** The tasks that one upgrade hook starts interrupt the rollouts before them:
    in the simple-app upgrade, the `stop_components` task writes the CR while the operator still
    rolls out the upgrade, and the `start_components` task writes it again while the operator
    rolls out the stop. With the family, the upgrade succeeds when the last rollout succeeds, an
    interrupted started task still shows `SUPERSEDED` on its own entry, and only a task outside
    the family makes the upgrade `SUPERSEDED`. The action's `upgrade_deployment_version` call asks
    for the version that the upgrade already set, so it starts no task (ADR-054).

### Links, output and task types

23. **Hook-started tasks link to their hook step.** `stopComponents`, `startComponents` and
    `updateDeploymentVersion` take an optional `startedByStepId`, which the action primitives fill
    from `STYRMIN_STEP_ID`. `Task.startedBy` and `Task.startedTasks` follow the link.
24. **Command output.** When a Job fails, the process that waits on it reads the end of the Job
    pod's log before it raises `JobFailedError` with the output: `execute_commands` records it on
    its hook step, and the `run_job` command flow on its "Run the job's command" step. The server
    keeps the last 200 lines and at most 64 KiB, and marks output that was cut.
25. **`run_job` gets an action token.** The `RUN_JOB` catalogue entry is now the INTERNAL flow
    `run_job`, which keeps the callbacks, opens an action token and runs the new USER flow
    `run_job_command` (`PrefectAction.RUN_JOB_COMMAND`), which builds the Job and records the
    `command` step. This is the `apply_state` pattern of ADR-059.
26. **Tasks get the type of their operation.** `apply_state` takes a `task_type`: `createDeployment`
    creates a `create_instance` task; updates, refreshes and environment configuration
    redeploys create `update_instance`; `updateDeploymentVersion` creates `upgrade_instance`;
    `stopComponents` and `startComponents` create `stop_components` and `start_components`. The
    ingress controller's reconcile creates `create_instance` for its first instance and
    `update_instance` after that. Existing rows keep `noop`.

### Backups and restores

27. **Each backup and restore gets an action token.** The INTERNAL flows `execute_backup_workflow`
    and `execute_restore_workflow` open one and pass it to the USER flow with `STYRMIN_BACKUP_ID`
    or `STYRMIN_RESTORE_ID`. When the token cannot be created, the backup or restore runs without
    steps.
28. **Restore steps.** `execute_velero_restore_flow` records `restore:namespace`,
    `restore:velero` and, only after a completed Velero restore, `restore:recovery`.
29. **Backup steps.** `execute_velero_backup_flow` records one `backup:component:<name>` step per
    component. On each poll it lists the backup's `PodVolumeBackup` objects and maps each pod to its
    component through the `styrmin/component` label. A component without pod volumes gets the
    Velero backup's times and result. The agent's RBAC gains `get` and `list` on
    `podvolumebackups.velero.io`.
30. **Velero's `FailedValidation` phase is terminal** in `poll_backup_status` and
    `poll_restore_status`. A restore of a Velero backup that no longer exists now fails within
    seconds instead of waiting for the restore timeout, and its step error starts with
    "Velero restore failed validation:".

### Reads

31. **The timeline is built from a read model.** The timeline service loads the steps of all the
    deployment's tasks, the tasks those steps started and their steps, and the deployment's
    `DeploymentStatus` in a fixed number of queries, then calculates every task result in memory.
    The GraphQL objects carry their part in `strawberry.Private` fields and query only for single
    reads. The timeline does not request `output`; `Step.hasOutput` tells the page to load it with
    `Query.step`.
32. **`Step.noReportSince` is derived on read.** It is set while a running operator-phase step has
    had no agent report for more than 60 seconds, from `DeploymentStatus.last_polled_at`.

## Alternatives considered

- **A JSON list of steps on `Task`, `Backup` and `Restore`.** Concurrent writers would overwrite
  each other's changes, and the list would be stored three times. Rejected.
- **One `parent_id` column with a `parent_type` column.** No foreign key, so no cascade and no
  integrity check. Rejected.
- **Storing the task result.** Three writers change the steps of one family at different times,
  so each of them would have to recalculate the stored value of every task in the family.
  Rejected in favour of the ADR-055 pattern.
- **Keeping steps in Prefect** (task runs, flow-run states or artifacts). Users cannot reach the
  Prefect server, most of the work happens in the operator outside Prefect, and Prefect's
  retention would decide how long steps are kept. Rejected.
- **Correlating operator reports with tasks by time, as ADR-028 does for versions.** Approximate,
  and the times come from two clocks. Sending the CR's `metadata.generation` in a new report field
  was also rejected, because it changes the report input. Rejected.
- **Leaving the operator as it was.** An upgrade whose HelmRelease fails would still be reported
  `Ready`, so its HelmRelease step and its task would succeed. Rejected.
- **A kopf handler on HelmRelease status changes that writes the CR conditions.** Two handlers
  would write `status.conditions`, and a merge patch replaces the whole list. Rejected.
- **Recording the restore steps from the INTERNAL flow after the USER flow ends.** A stuck step
  would stay hidden for up to the restore timeout, and a crash would lose the step it
  interrupted. Rejected.
- **Creating the `run_job` token in the `runJob` mutation and deleting it in the callback.** A lost
  callback would leave a valid token for 24 hours, and token handling would live in two places.
  Rejected.
- **Linking hook-started tasks through the action token's session, or an HTTP header.** The
  session cannot tell which hook step started the task, and a header would be invisible in the
  schema and not covered by propagation tests. Rejected.
- **Deriving the task type from the remediation flow or from the steps.** The hook-started
  `stop_components` task would show "Update", and the type would change while the task runs.
  Rejected.

## Consequences

- Each task, backup and restore shows its steps, and each task a result that includes the
  operator's work, in the web page, the API, the SDK (`tasks.get`, `tasks.step_output`, `tasks.failed_step`) and
  `styrminctl tasks get`. `styrminctl deployments apply --wait` names the failed step.
- Updates and upgrades now reach `Ready` only after FluxCD reports the new generation Ready, and a
  failed update or upgrade ends `FAILED` instead of `RUNNING`.
- Every signed-in user, `READ_ONLY` included, can read the output of a failed command. Action
  commands must not print secrets.
- `reportDeploymentStatuses` stays on the unauthenticated allow-list (ADR-017, issue #396) and now
  also moves operator-phase steps. A caller who can reach the API could already set
  `Deployment.status` through it; now it can also change the operator-phase steps of a task.
- Besides each reconcile, every `run_job` task, backup and restore creates and deletes one
  `styrmin-actions` session.
- A driver action that calls the API through the SDK instead of the action primitives creates tasks
  that are not linked to its hook step.
- The operator reads FluxCD every 60 seconds, so FluxCD attempts that fail faster than that count
  as one attempt.
- A kopf retry of the create or update handler resets `rolloutStartedAt`, which extends the
  readiness timeout of that rollout.
- A rollout that becomes ready between 270 seconds and FluxCD's 5-minute timeout shows `FAILED`,
  then `RUNNING`.
- Hooks that run for more than about 5 minutes before the rollout starts can end
  `apply --wait` with a wait timeout before the HelmRelease step fails, unless the caller raises
  `--max-wait`.
- Tasks, backups and restores from before this change have no steps; a task without steps gets
  its result from `Task.status`.
- The `callback` mutation rejects Prefect's `Crashed` and `Cancelled` states as unknown, and a
  flow run that the zombie automation marks `Crashed` sends no callback. The `Task.status` of such
  a task stays `running`, so its task result stays `RUNNING`.
- The rollback rule of decision 13 reads FluxCD's release history and failure counters, which
  depend on helm-controller's behaviour (v1.1.0 in `helm/agent`). It assumes that FluxCD rolls
  back each failed upgrade before it tries again, which `remediation.retries: 3` guarantees.
