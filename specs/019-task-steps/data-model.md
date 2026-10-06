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

`Task.status`, `Task.type` and `Task.message` keep their meaning (FR-015). Existing rows get nulls.

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
- `failed` is final for flow kinds. An `operator_phase` step goes from `failed` back to `running` when a later report shows the operator working on it again; `attempt_count` increases by one.
- Opening a step that already exists and is running returns it unchanged, so a retried `STARTED` event is harmless.
- Each transition locks the step row (`SELECT … FOR UPDATE`). Two writers serialize on the row.
- Times: a writer can send `occurredAt`; otherwise the server's time is used. `ended_at` is never earlier than `started_at`.

## Task result calculation

Inputs: the task's steps, the tasks started by its hook steps (with their own results), and the task's `status`.

```text
if no steps:
    RUNNING if status in (pending, running); SUCCEEDED if success; FAILED if failed
started_ids   = ids of tasks whose started_by_step_id is one of the task's steps
if any step pending or running, or any started task RUNNING:   RUNNING
if any step failed, or any started task FAILED:                FAILED
if any step superseded by a task not in started_ids:           SUPERSEDED
otherwise:                                                     SUCCEEDED
```

Started tasks are evaluated depth-first with a visited set.

## Closing open steps

| Event | Effect |
|---|---|
| `callback` sets a task `FAILED` (flow failed, crashed or was cancelled) | Pending and running steps of a flow kind on that task fail with the state message |
| `apply_state` catches a failed or crashed remediation flow | Same, before it raises |
| The INTERNAL backup or restore flow sees its USER flow fail or crash | Pending and running steps of that backup or restore fail with the state message |
| A `resource:styrmindeployment` or `resource:delete-request` step succeeds | Open `operator_phase` steps of the deployment's other tasks become superseded by this task |

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
| `startedByStepId` names a step that does not exist | `StepNotFoundError` |
| A transition the rules above forbid (for example `SUCCEEDED` on a superseded step) | Ignored and logged; returns the step unchanged. A late write from a slow writer is not an error. |
