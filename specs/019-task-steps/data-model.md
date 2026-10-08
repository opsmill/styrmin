# Data Model: Steps and Failure Causes for Tasks, Backups and Restores

**Feature**: [spec.md](spec.md) | **Research**: [research.md](research.md)

One Alembic revision ships every database change below ([ADR-001](../../dev/adr/0001-alembic-database-migrations.md)).

## New table `step`

One unit of work inside a task, a backup or a restore (glossary: [CONTEXT.md](../../CONTEXT.md) "Step").

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | UUID | no | Primary key (`StyrminModel`) |
| `created_on`, `updated_on` | timestamptz | no / yes | `StyrminModel` |
| `task_id` | UUID | yes | FK `task.id`, `ON DELETE CASCADE` |
| `backup_id` | UUID | yes | FK `backup.id`, `ON DELETE CASCADE` |
| `restore_id` | UUID | yes | FK `restore.id`, `ON DELETE CASCADE` |
| `key` | varchar | no | Stable identifier within the parent, see "Step keys" |
| `name` | varchar | no | Name shown to users |
| `kind` | enum `stepkind` | no | See `StepKind` |
| `status` | enum `stepstatus` | no | See `StepStatus` |
| `started_at` | timestamptz | yes | Null while pending |
| `ended_at` | timestamptz | yes | Set when succeeded, failed or superseded |
| `attempt_count` | integer | no | 0 while pending, 1 when first started |
| `errors` | JSON | yes | List of `{"attempt": int, "message": str, "occurred_at": iso8601}` |
| `detail` | varchar | yes | FluxCD's current reason and message, HelmRelease step only |
| `rolled_back_at` | timestamptz | yes | When FluxCD rolled back or uninstalled the release |
| `rollback_message` | varchar | yes | FluxCD's `Remediated` message |
| `output` | text | yes | End of a failed command's output |
| `output_truncated` | boolean | no | Default `false`; `true` when earlier output was cut |
| `superseded_by_task_id` | UUID | yes | FK `task.id`, `ON DELETE SET NULL` |

Constraints and indexes:

- `CHECK (num_nonnulls(task_id, backup_id, restore_id) = 1)`, named `ck_step_one_parent`.
- Unique index on (`task_id`, `key`) where `task_id IS NOT NULL`; the same for `backup_id` and `restore_id`.
- Indexes on `task_id`, `backup_id`, `restore_id` and `superseded_by_task_id` come with the unique indexes or are added explicitly.

## Changed table `task`

| Column | Type | Null | Notes |
|---|---|---|---|
| `instance_id` | UUID | yes | FK `applicationinstance.id`, `ON DELETE SET NULL`. Set by `apply_state` (research D4). Indexed. |
| `started_by_step_id` | UUID | yes | FK `step.id`, `ON DELETE SET NULL`, created with `use_alter` because `step.task_id` points back at `task`. Indexed. |

`Task.status` and `Task.message` keep their meaning (FR-015). Existing rows get nulls.

`Task.type` keeps its values. New tasks that a reconcile runs get the type their caller means instead of `noop` (research D19, spec FR-019); existing rows keep `noop`.

The revision's downgrade drops `task.started_by_step_id` and `task.instance_id` (with their foreign keys) before it drops the `step` table, because the two tables reference each other. A migration test applies the revision and reverts it.

## Unchanged tables

- `backup`, `restore`: their `status` and `component_statuses` keep their meaning (FR-013).
- `deploymentstatus`: still one row per deployment with the latest report. Its `last_polled_at` drives `noReportSince` (research D9).

## Enums

### `StepStatus`

Stored lower-case like the other enums; GraphQL values are upper-case.

| Value | Meaning |
|---|---|
| `pending` | Expected but not started. Only operator-phase steps are created pending. |
| `running` | Started, not ended |
| `succeeded` | Ended without error |
| `failed` | Ended with an error. An operator-phase step can become `running` again on a new attempt. |
| `superseded` | A later task interrupted it. Final. Never counts as failed (FR-007). |

### `StepKind`

| Value | Steps | Written by |
|---|---|---|
| `plan` | "Plan the changes" | `apply_state` (INTERNAL, direct) |
| `hook` | One run of a hook mode | Remediation flow (USER, `recordStep`) |
| `resource_write` | "Write the StyrminDeployment resource", "Create service aliases", "Request the deletion" | Remediation flow; `deleteDeployment` service |
| `operator_phase` | Prerequisites, HelmRelease, services, wait for Ready; delete teardown | Operator phase history |
| `command` | "Run the job's command" | `run_job_command` (USER, `recordStep`) |
| `restore` | "Delete the namespace", "Run the Velero restore", "Run the recovery" | `execute_velero_restore_flow` (USER, `recordStep`) |
| `backup_component` | "Back up <component>" | `execute_velero_backup_flow` (USER, `recordStep`) |

"Flow kinds" are every kind except `operator_phase`. When the process that owns a step dies, the recorder fails that parent's open steps of a flow kind (see "Closing open steps").

### `TaskResult` (calculated, never stored)

`RUNNING`, `FAILED`, `SUCCEEDED`, `SUPERSEDED`. See "Task result calculation".

### `StepEvent` (mutation input only)

`STARTED`, `SUCCEEDED`, `FAILED`, `OUTPUT`.

## Step keys and names

| Parent | Key | Name | Kind | When |
|---|---|---|---|---|
| Task (apply) | `plan` | Plan the changes | plan | Every `apply_state` run |
| Task (create) | `hook:setup:pre` | Run the setup pre-hook | hook | Driver declares it |
| Task (create, update, upgrade) | `resource:styrmindeployment` | Write the StyrminDeployment resource | resource_write | Every remediation |
| Task (create, update, upgrade) | `resource:service-aliases` | Create service aliases | resource_write | Context has aliases |
| Task (create) | `hook:setup:post` | Run the setup post-hook | hook | Driver declares it |
| Task (upgrade) | `hook:upgrade:pre` | Run the upgrade pre-hook | hook | Driver declares it |
| Task (upgrade) | `hook:upgrade:core` | Run the upgrade hook | hook | Every upgrade |
| Task (upgrade) | `hook:upgrade:post` | Run the upgrade post-hook | hook | Driver declares it |
| Task (rollout) | `operator:prerequisites` | Create network policies and secrets | operator_phase | Created at the CR write; not for internal deployments |
| Task (rollout) | `operator:helmrelease` | Install or upgrade the HelmRelease | operator_phase | Same |
| Task (rollout) | `operator:services` | Create services and middlewares | operator_phase | Same |
| Task (rollout) | `operator:ready` | Wait for the deployment to be ready | operator_phase | Same |
| Task (`run_job`) | `command` | Run the job's command | command | Every job |
| Task (`delete_deployment`) | `resource:delete-request` | Request the deletion | resource_write | Every delete |
| Task (`delete_deployment`) | `operator:teardown` | Remove the deployment's resources and namespace | operator_phase | Every delete |
| Restore | `restore:namespace` | Delete the namespace | restore | Every restore |
| Restore | `restore:velero` | Run the Velero restore | restore | Every restore |
| Restore | `restore:recovery` | Run the recovery | restore | Velero restore completed |
| Backup | `backup:component:<name>` | Back up <name> | backup_component | One per component with a backup configuration |

Steps are listed by `started_at`, pending steps last, then by `created_on`.

## State transitions of a step

```text
            open (flow kinds)                 succeed
 (absent) ─────────────────────▶ running ─────────────▶ succeeded
    │                              │  ▲
    │ ensure_operator_steps        │  │ new attempt (operator_phase only)
    ▼                              ▼  │
 pending ──── operator starts ──▶ running ──── fail ──▶ failed
    │                              │
    └──────── supersede ───────────┴─────────────────▶ superseded (final)
```

Rules the recorder enforces:

- `succeeded` and `superseded` are final.
- `failed` is final for flow kinds. An `operator_phase` step goes from `failed` back to `running` when a later report shows the operator working on it again; `attempt_count` increases by one. When a report shows a later phase, a `failed` earlier step gets a new attempt and goes straight to `succeeded`.
- Opening a step that already exists and is running returns it unchanged, so a retried `STARTED` event is harmless.
- Each transition locks the step row (`SELECT … FOR UPDATE`). Two writers serialize on the row.
- Times: a writer can send `occurredAt`; otherwise the server's time is used. `ended_at` is never earlier than `started_at`.

## Task result calculation

Inputs: the task, its steps, the tasks started by its hook steps (transitively, with their steps), and the task's `status`. See [research.md](research.md) D8 for why the calculation uses the family.

```text
family       = {task} ∪ every task whose started_by_step_id is a step of a family member (visited set)
family_ids   = ids of family
family_steps = steps of every family member

if any family member's status is pending or running,
   or any family step is running, or pending in a member
   that has no failed step:                                        RUNNING
if any family member's status is failed, or any family step failed: FAILED
if any family step is superseded by a task not in family_ids:      SUPERSEDED
otherwise:                                                         SUCCEEDED
```

The `status` of each family member counts in addition to its steps, because the flow can fail, or still run, between two steps. The `apply_state` flow can fail after the plan step succeeded and before the remediation flow records a step, for example when it cannot create the action token. Prefect also starts the remediation flow some seconds after the plan step ended. A member whose flow succeeded counts by its steps only, so the operator-phase steps keep a task `RUNNING` after its flow ended. A task without steps, such as a task from before this feature, counts by its `status` only.

A pending step waits behind a failed step of its own task: the operator leaves the steps after a failed phase pending until it retries that phase, and the retry makes the failed step `running` again. So a pending step does not make a task with a failed step `RUNNING` (US3 acceptance scenario 1, SC-003).

Each started task also has its own result, calculated the same way on its own family. A `stop_components` task interrupted by its sibling `upgrade_deployment_version` task is `SUPERSEDED` on its own entry, while the upgrade that started both counts that interruption as its own work.

## Closing open steps

| Event | Effect |
|---|---|
| `callback` sets a task `FAILED` (flow failed; a `Crashed` or `Cancelled` state is rejected as unknown and leaves `status` unchanged) | Pending and running steps of a flow kind on that task fail with the state message |
| `apply_state` catches a failed or crashed remediation flow | Same, before it raises |
| The INTERNAL backup or restore flow sees its USER flow fail or crash | Pending and running steps of that backup or restore fail with the state message |
| A `resource:styrmindeployment` or `resource:delete-request` step succeeds | Open `operator_phase` steps of the deployment's older tasks become superseded by this task. A task is older when it was created first; tasks created at the same time are ordered by id. When a newer task already has one of these two steps succeeded, the first such newer task supersedes this task's `operator_phase` steps at once |

## Domain models

`backend/styrmin_backend/domain/models.py` gains:

- `StepStatus`, `StepKind`, `TaskResult` enums.
- `StepError` (`attempt`, `message`, `occurred_at`).
- `Step` (fields of the table; `parent` as a small value object with `task_id | backup_id | restore_id`).
- `Task.instance_id: UUID | None` and `Task.started_by_step_id: UUID | None`; `Task.create` accepts both.

## Validation rules

| Rule | Error |
|---|---|
| `recordStep` names a `stepId` that does not exist | `StepNotFoundError` (`NOT_FOUND`) |
| `recordStep` names a task, backup or restore that does not exist | `TaskNotFoundError`, `BackupNotFoundError`, `RestoreNotFoundError` (`NOT_FOUND`) |
| `recordStep` gives neither a `stepId` nor exactly one parent with a `key`, or a `STARTED` event without `name` and `kind` | `InvalidStepRecordError` (`VALIDATION_ERROR`) |
| `recordStep` called by a user other than `styrmin-actions` | Permission error `FORBIDDEN` (research D14) |
| `startedByStepId` names a step that does not exist, also when `updateDeploymentVersion` is a no-op | `StepNotFoundError` (`NOT_FOUND`) |
| `startedByStepId` names a step that is not a step of a task of the same deployment (a step of another deployment's task, of a backup or of a restore), also on a no-op | `InvalidStartingStepError` (`VALIDATION_ERROR`) |
| `startedByStepId` sent by a user other than `styrmin-actions` | Permission error `FORBIDDEN` |
| A transition the rules above forbid (for example `SUCCEEDED` on a superseded step) | Ignored and logged; returns the step unchanged. A late write from a slow writer is not an error. |
