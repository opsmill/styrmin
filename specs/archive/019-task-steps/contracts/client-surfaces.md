# Contract: Frontend, SDK and `styrminctl`

**Feature**: [spec.md](../spec.md) | **Research**: [research.md](../research.md) D15, D16

## Frontend

### Queries (`frontend/src/graphql/`)

| File | Change |
|---|---|
| `get_deployment_timeline.graphql` | `task { … result startedByStepId startedBy { id type } startedTasks { id type result } steps { id key name kind status startedAt endedAt durationSeconds attemptCount errors { attempt message occurredAt } error detail rolledBackAt rollbackMessage hasOutput outputTruncated supersededBy { id type } startedTasks { id type result } noReportSince } }`. No `output`. |
| `get_step_output.graphql` (new) | `step(stepId) { id output outputTruncated }` |
| `list_backups.graphql`, `list_restores.graphql` | `steps { id key name kind status startedAt endedAt durationSeconds attemptCount error errors { attempt message occurredAt } }` |

`pnpm codegen` regenerates the hooks.

### Components

- `components/deployment/StepList.tsx` (new): an ordered list of steps.
  - Each row: status icon with a text label (status is never shown by colour alone), name, duration (or "running for <elapsed>"), attempt count when above 1.
  - A failed step shows its error, each earlier attempt's error, FluxCD's `detail`, and "FluxCD rolled back the release at <time>: <message>" when `rolledBackAt` is set.
  - `hasOutput` shows "Show output", which loads `GetStepOutput` and renders it in a scrollable monospace block, with "Earlier output was cut" when `outputTruncated`.
  - A superseded step shows "Superseded by <task type>" linking to that timeline entry.
  - A hook step lists its started tasks with their result and a link to their entry.
  - `noReportSince` shows "No report from the agent since <time>".
- `components/deployment/TaskResultBadge.tsx` (new): the four results with the existing badge styles.
- `DeploymentTimeline.tsx`:
  - Shows `TaskResultBadge` instead of `StatusBadge(task.status)`.
  - Every entry can expand. The expanded area shows the step list, then the existing context diff.
  - A task started by a hook shows "Started by <task type>" with a link.
  - A finished task with no steps shows "No steps recorded for this task." (FR-010). An unfinished task with no steps shows "Waiting for the first step."
  - Entries with result `RUNNING` or `FAILED` start expanded.
  - `TASK_TYPE_LABELS` gains `delete_deployment: "Delete"` (FR-019).
  - Data attributes for E2E: `data-task-result` on the entry; `data-step-key`, `data-step-status` on each step row.
- `DeploymentDetailPage.tsx`:
  - `BackupRow` and `RestoreRow` show a `StepList` of their steps.
  - The Overview tab's "Recent Timeline" shows `TaskResultBadge` instead of `Task.status`, so both views agree.

Refresh stays at the existing `refetchInterval: 10_000` while auto-refresh is on (FR-005).

### Tests (Vitest, React Testing Library)

- `StepList`: each status; duration and elapsed time; errors per attempt; FluxCD detail; rollback; output loading and the cut notice; superseded link; started tasks; no-report notice.
- `DeploymentTimeline`: result badge; empty-steps notice; started-by link; default expansion.
- How each SC-001 failure type looks: a failed hook step with error; a failed hook step with output; a failed HelmRelease step with FluxCD detail and pod reasons; a failed prerequisites step with attempts.
- Backup and restore rows with steps.

## SDK (`python_sdk/`)

| Change | Detail |
|---|---|
| `graphql/get_task.graphql` | Adds `createdOn`, `result`, `startedByStepId`, `startedBy { id type }`, `startedTasks { id type status result }`, and `steps { … }` with the timeline's step fields except `outputTruncated`. No `output`, because `Step.output` is requested for one step at a time. |
| `graphql/get_step_output.graphql` (new) | `step(stepId) { id output outputTruncated }` |
| `graphql/get_deployment_timeline.graphql` | Adds `result` and `steps { … }` without `output` |
| `graphql/get_backup.graphql`, `get_restore.graphql`, `list_backups.graphql`, `list_restores.graphql` | Add `steps { … }` |
| `resources/tasks.py` | `get()` returns the extended generated model; new `step_output(step_id) -> StepOutput` that reads the output of one step; new `failed_step(task_id) -> FailedStep | None` that searches the task's steps, then its started tasks, and returns the step name, its task id and its error |
| `resources/deployments.py::_wait_for_terminal` | On terminal failure, sets `failure_reason` to `step "<name>" failed: <error>` when `failed_step(outcome.task_id)` finds one, and keeps `deployment reconciliation failed (status: <status>)` otherwise |

Tests: generated-model parsing with steps; the task query does not request `output`; `step_output` reads one step and maps `NOT_FOUND`; `failed_step` finds a step in the task and in a started task; `_wait_for_terminal` failure reason with and without a failed step.

## `styrminctl` (`cli/`)

### `styrminctl tasks get <id>`

Prints the existing task table with a `result` column, then a "Steps" table:

| Column | Value |
|---|---|
| `step` | Step name |
| `status` | Step status |
| `duration` | `durationSeconds` formatted as `1m 05s`, `running` while running |
| `attempts` | `attemptCount` |
| `error` | The error of each failed attempt as "attempt <n>: <message>", oldest first, then FluxCD's detail, then "output: <last line>" when the step has output; one per line |

The command reads the output of each step whose `hasOutput` is true with `tasks.step_output()`, one step at a time.

When the task has no steps: "No steps recorded for this task." When the task has started tasks: a "Started tasks" table with id, type and result.

### `styrminctl deployments apply --wait`

The `failed` line is unchanged in shape and gets the SDK's new reason:

```text
failed my-app: step "Install or upgrade the HelmRelease" failed: UpgradeFailed: Helm upgrade failed … Pods not ready: my-app-6d9 (app: ImagePullBackOff)
```

Tests: `tasks get` output with steps, with no steps and with started tasks; the `failed` line with a step reason.
