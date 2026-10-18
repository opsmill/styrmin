<!-- Extracted from specs/019-task-steps on 2026-10-08 -->

## Deployment Timeline and Steps

### Overview

The deployment detail page shows the steps of each task on the History timeline, and the steps of
each backup and restore on the Backups tab. Users follow a running task and read why a step
failed without access to Prefect, `kubectl` or server logs. Each timeline entry shows the task
result, not `Task.status`: the result also covers the operator's work after the flow ended and the
tasks that the task's hook steps started.

The server calculates the task result and every other value shown here. The page only displays
them. Design rationale: [ADR-060](../../adr/0060-steps-and-derived-task-result.md). GraphQL fields:
[api.md](../backend/api.md#step).

### File layout

```text
frontend/src/
├── components/deployment/
│   ├── DeploymentTimeline.tsx     # History card: one expandable entry per task
│   ├── StepList.tsx               # Ordered step rows, shared by tasks, backups and restores
│   ├── TaskResultBadge.tsx        # The four task results as badges
│   ├── BackupRestoreSteps.tsx     # Collapsible step list of one backup or restore row
│   ├── TaskLink.tsx               # Link to another task's timeline entry
│   └── timeline-links.ts          # Context that expands and scrolls to a linked entry
├── lib/task-display.ts            # Task type labels and task result display
└── graphql/
    ├── get_deployment_timeline.graphql  # Tasks with result, links and steps, without output
    ├── get_step_output.graphql          # The output of one step
    ├── list_backups.graphql             # Backups with their steps
    └── list_restores.graphql            # Restores with their steps
```

### Data loading

- The timeline, backup and restore queries refresh every 10 seconds while auto-refresh is on
  (`refetchInterval: autoRefreshEnabled ? 10_000 : false` in `DeploymentDetailPage.tsx`). With the
  agent's 5-second status reports, a step change reaches the page within about 15 seconds.
- The timeline query does not request `Step.output`, because output can be long and the page
  reloads it every 10 seconds. A step with `hasOutput` shows "Show output", and only a click runs
  `useGetStepOutputQuery({ stepId }, { enabled: open })`. "Earlier output was cut" appears when
  `outputTruncated` is true.
- A running step shows "running for <elapsed>". The `RunningFor` component updates itself every
  second, so only running rows render again between two refreshes.

### Timeline entries (`DeploymentTimeline.tsx`)

- Each entry shows `TaskResultBadge` (Running, Failed, Succeeded, Superseded). The Overview tab's
  "Recent Timeline" uses the same badge, so both views show the same value.
- Entries whose result is `RUNNING` or `FAILED` start expanded. The expanded state is kept by task
  id and set only the first time an entry appears, so an entry does not collapse when it finishes
  during a refresh.
- The expanded area shows the step list, then the context diff. A task without steps shows "No
  steps recorded for this task." when its `Task.status` is `success` or `failed`, and "Waiting
  for the first step." otherwise.
- A task started by a hook step shows "Started by <task type>". `TaskLink` expands the target
  entry, focuses its trigger and scrolls to it. When the target task is not in this deployment's
  timeline, the link is plain text with a tooltip.
- Task type labels come from `lib/task-display.ts` (`create_instance` → "Create",
  `delete_deployment` → "Delete", `noop` → "No-op", and so on).

### Step rows (`StepList.tsx`)

- Each row shows an icon and a text label for the status, so the status is never shown by colour
  alone. It also shows the name, the duration (or "running for <elapsed>"), and the attempt count
  when it is above 1.
- A failed step lists the error of each attempt, newest first, because the latest attempt is the
  likely cause. Then it shows FluxCD's `detail`, and "FluxCD rolled back the release at <time>:
  <message>" when `rolledBackAt` is set.
- A superseded step shows "Superseded by <task type>", linked to that task's entry.
- A hook step lists the tasks it started, with their result and a link.
- A running operator-phase step with `noReportSince` shows "No report from the agent since
  <time>".
- `showTimes` adds the start and end time under each name. The backup and restore rows use it.

### Backup and restore rows (`BackupRestoreSteps.tsx`)

A backup has one step per component; a restore has its three restore steps, and a cross-target
restore can have a fourth, "Create and delete service aliases". The list is
collapsible and starts expanded for a backup or restore that is pending, in progress or failed.
Its content stays mounted while collapsed. An empty list shows "No steps recorded for this
backup." (or restore) when the status is `completed` or `failed`, and "Waiting for the first
step." otherwise.

### Attributes for E2E tests

The Playwright page object `backend/tests/e2e/pages/deployment_detail.py` reads step and task
state from these data attributes:

| Element | Attributes |
|---------|------------|
| Timeline entry | `data-testid="timeline-entry"`, `data-task-id`, `data-task-result`, `data-started-by-step-id`, `data-started-by-task-id`, `data-started-by-task-type`, `data-expanded` |
| Step row | `data-step-id`, `data-step-key`, `data-step-kind`, `data-step-status`, `data-step-started-at`, `data-step-ended-at`, `data-step-attempts`, `data-step-has-output` |
| Task result badge | `data-testid="task-result-badge"`, `data-task-result` |
| Backup or restore step list | `data-testid="backup-steps"` or `"restore-steps"`, `data-backup-id` or `data-restore-id`, `data-expanded` |

### Tests

Vitest tests live in `frontend/src/__tests__/deployment-detail/`: `StepList.test.tsx`,
`StepListFailures.test.tsx` (how each failure type looks), `StepListLive.test.tsx` (following a
running task), `DeploymentTimelineSteps.test.tsx`, `TaskResult.test.tsx` and
`BackupRestoreSteps.test.tsx`.
