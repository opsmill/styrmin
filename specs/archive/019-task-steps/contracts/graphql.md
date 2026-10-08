# Contract: GraphQL Changes

**Feature**: [spec.md](../spec.md) | **Data model**: [data-model.md](../data-model.md)

All changes are additive. Every new field, argument, input type and mutation gets a propagation test ([`dev/guides/graphql-propagation-tests.md`](../../../dev/guides/graphql-propagation-tests.md)). After the change, `schema.graphql` is regenerated and `uv run invoke generate` updates the SDK and frontend types.

## New enums

```graphql
enum StepStatus { PENDING RUNNING SUCCEEDED FAILED SUPERSEDED }

enum StepKind { PLAN HOOK RESOURCE_WRITE OPERATOR_PHASE COMMAND RESTORE BACKUP_COMPONENT }

enum TaskResult { RUNNING FAILED SUCCEEDED SUPERSEDED }

enum StepEvent { STARTED SUCCEEDED FAILED OUTPUT }
```

## New types

```graphql
"""One unit of work inside a task, a backup or a restore."""
type Step {
  id: UUID!
  key: String!
  name: String!
  kind: StepKind!
  status: StepStatus!
  startedAt: DateTime
  endedAt: DateTime
  """Seconds between startedAt and endedAt; null until both are set."""
  durationSeconds: Float
  attemptCount: Int!
  """The error of each failed attempt, oldest first."""
  errors: [StepError!]!
  """The newest error, or null."""
  error: String
  """FluxCD's current reason and message, HelmRelease step only."""
  detail: String
  rolledBackAt: DateTime
  rollbackMessage: String
  hasOutput: Boolean!
  """End of a failed command's output. Request it only for one step at a time."""
  output: String
  outputTruncated: Boolean!
  """The later task that interrupted this step."""
  supersededBy: Task
  """Tasks that this hook step started."""
  startedTasks: [Task!]!
  """Set while a running operator-phase step has had no agent report for more than 60 seconds."""
  noReportSince: DateTime
  taskId: UUID
  backupId: UUID
  restoreId: UUID
}

type StepError {
  attempt: Int!
  message: String!
  occurredAt: DateTime!
}
```

## Changed types

```graphql
type Task {
  # existing fields unchanged, including status (FR-015)
  steps: [Step!]!
  result: TaskResult!
  """The task whose hook step started this task."""
  startedBy: Task
  startedByStepId: UUID
  """Tasks started by this task's hook steps."""
  startedTasks: [Task!]!
}

type Backup {
  # existing fields unchanged
  steps: [Step!]!
}

type Restore {
  # existing fields unchanged
  steps: [Step!]!
}
```

`DeploymentTimelineEntry.task` returns the extended `Task`, so the timeline gets steps and results without a new field.

## New query field

```graphql
type Query {
  """One step, for example to load its output. Any signed-in user."""
  step(stepId: UUID!): Step
}
```

Raises `StepNotFoundError` (`NOT_FOUND`) for an unknown id. Every read field above requires only authentication; `READ_ONLY` users read the same data as `ADMIN` users (FR-011, SC-004).

## New mutation

```graphql
input RecordStepInput {
  """Address an existing step. Use instead of a parent and key."""
  stepId: UUID
  taskId: UUID
  backupId: UUID
  restoreId: UUID
  key: String
  """Required with STARTED when the step does not exist yet."""
  name: String
  kind: StepKind
  event: StepEvent!
  """Required with FAILED."""
  error: String
  """Used with OUTPUT, and allowed with FAILED."""
  output: String
  outputTruncated: Boolean! = false
  """When the event happened, in the writer's clock. Defaults to the server's time."""
  occurredAt: DateTime
}

type Mutation {
  """Record a step event. Called by Styrmin's own flows and actions with the action token."""
  recordStep(input: RecordStepInput!): Step! @requiresRole @isActionsServiceAccount  # READ_WRITE, and only the styrmin-actions user
}
```

Access: `PermissionExtension([RequiresRole(Role.READ_WRITE), IsActionsServiceAccount()])`. The second permission accepts only the built-in `styrmin-actions` user (`ACTIONS_SERVICE_ACCOUNT_USERNAME`), so a person cannot change the record of what happened (research D14). No person can get a session for that user: `login` rejects its username, `resetUserPassword` and `changePassword` refuse it, and `createUser` refuses the username (ADR-059).

Semantics:

| Event | Effect |
|---|---|
| `STARTED` | Creates the step as `running` (attempt 1), or returns it when already running |
| `SUCCEEDED` | `running` → `succeeded` |
| `FAILED` | `running` → `failed`; appends `error` to `errors`; stores `output` when given |
| `OUTPUT` | Stores `output` and `outputTruncated` on the step, whatever its status |

Side effects in the recorder:

- `SUCCEEDED` on `resource:styrmindeployment` creates the task's operator-phase steps (not for internal deployments) and supersedes open operator-phase steps of the deployment's older tasks. It never changes the steps of a newer task: when a newer task of the deployment has already written the StyrminDeployment or requested the deletion, the first such newer task supersedes the new operator-phase steps at once.
- The server keeps at most the last 200 lines and 64 KiB of `output`.

Errors: `StepNotFoundError`, `TaskNotFoundError`, `BackupNotFoundError`, `RestoreNotFoundError` (all `NOT_FOUND`); `InvalidStepRecordError` (`VALIDATION_ERROR`). Unauthenticated calls get `UNAUTHENTICATED`; `READ_ONLY` callers and every user other than `styrmin-actions`, including admins, get `FORBIDDEN`.

## Read model for lists

Most of Styrmin's resolvers query per object (`api/resolvers.py`). To keep the timeline at a fixed number of queries:

- `build_deployment_timeline` returns, with each entry, the task's steps, its started tasks (with their steps), the summaries of superseding tasks, the family result, and the deployment's last report time.
- `Task` and `Step` GraphQL objects hold that data in `strawberry.Private` fields (`steps_view`, `result_view`, `started_tasks_view`, `superseded_by_view`, `no_report_since_view`). Each resolver returns the private value when it is set, and queries otherwise (single reads: `Query.task`, `Query.step`).
- `Backup.steps` and `Restore.steps` read through per-request data loaders (`api/loaders.py`): one query for the steps of all the backups in a response, one for the steps of all its restores, and none when `steps` is not requested.
- A unit test counts the database queries of `deploymentTimeline` for 20 tasks with 10 steps each and fails when the count grows with the number of tasks.

## Changed mutations

```graphql
type Mutation {
  stopComponents(deploymentId: UUID!, components: [String!]!, startedByStepId: UUID = null): Task
    @requiresRole @startedByStepRequiresActionsServiceAccount
  startComponents(deploymentId: UUID!, components: [String!]!, startedByStepId: UUID = null): Task
    @requiresRole @startedByStepRequiresActionsServiceAccount
  updateDeploymentVersion(
    deploymentId: UUID!, version: String!, parameters: JSON = null,
    driverVersionId: UUID = null, startedByStepId: UUID = null
  ): Task @requiresRole @startedByStepRequiresActionsServiceAccount
}
```

`startedByStepId` sets `Task.startedByStepId` on the task the mutation creates. Omitting it keeps today's behaviour. The argument adds the new task to the started tasks of the hook step and so changes the result of the hook's task, so the server accepts it only under two rules:

- Only the built-in `styrmin-actions` user can send it. Access: `PermissionExtension([RequiresRole(Role.READ_WRITE), StartedByStepRequiresActionsServiceAccount()])`. A call without the argument needs only `READ_WRITE`. Every other user who sends it, admins included, gets `FORBIDDEN`.
- The step must be a step of a task of the same deployment. Hook steps belong only to tasks, so a step of a backup or a restore is rejected too.

`check_starting_step` (`services/steps/reads.py`) checks the step in `stop_components`, `start_components` and `update_deployment_version` right after it loads the deployment, before the mutation changes anything and before the no-op return of `update_deployment_version`.

Errors: `StepNotFoundError` (`NOT_FOUND`) when the id names no step; `InvalidStartingStepError` (`VALIDATION_ERROR`) when the step is not a step of a task of the deployment.

## Unchanged

- `reportDeploymentStatuses` input. FluxCD's reason and rollbacks travel in the existing `conditions` (see [operator-status.md](operator-status.md)).
- `callback`. Its service function additionally fails the task's open flow-kind steps when the state is `FAILED`.
- The allow-list in `api/auth/allowlist.py`.

## Propagation tests

| Surface | Write reaches the database | Database reaches the resolver |
|---|---|---|
| `recordStep` (each event, each parent) | yes | returned `Step` |
| `recordStep` without a token / as `READ_ONLY` / as a `READ_WRITE` or `ADMIN` person | rejected, nothing written | — |
| `startedByStepId` on the three mutations | `task.started_by_step_id` | `Task.startedBy`, `Task.startedTasks`, `Step.startedTasks` |
| `startedByStepId` from a `READ_WRITE` or `ADMIN` person, naming no step, or naming a step of another deployment's task | rejected (`FORBIDDEN`, `NOT_FOUND`, `VALIDATION_ERROR`), no task created | — |
| Every `Step` field | — | seeded row → field |
| `Task.steps`, `Task.result` (four values, including a family with a sibling-superseded started task and one interrupted by an outside task), `Backup.steps`, `Restore.steps`, `Query.step` | — | seeded rows → fields, read as `READ_ONLY` |
| `Task.type` for tasks created by each caller in research D19 | `task.type` | `Task.type` |
| `Step.noReportSince` | — | seeded `DeploymentStatus.last_polled_at` → field |
