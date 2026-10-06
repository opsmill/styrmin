# Orchestration Flows

> **Where this runs.** Prefect spans both processes. The **server** registers workflows and submits flow runs through `PrefectManager` (this doc). The **agent** runs the Prefect *worker* that picks up internal flow runs and executes them — see [`../agent/overview.md`](../agent/overview.md). User-defined driver actions execute as separate Kubernetes Jobs in the user work pool, not on the agent's worker.

## Overview

Orchestration flows are Prefect `@flow` functions that execute multi-step deployment operations. They live in `agent/tasks/orchestration.py` (executed by the agent's Prefect worker) and are submitted via the `PrefectManager` (server-side).

```text
                        PrefectManager.run_action(APPLY_STATE)
                                    |
                                    v
                            ┌───────────────┐
                            │  apply_state  │  <-- Has all callbacks
                            │   (wrapper)   │      (on_completion, on_failure, etc.)
                            └───────┬───────┘
                                    │
                                    v
                            remediation.apply()
                                    │
                ┌───────────────────┼───────────────────┐
                │                   │                   │
        ┌───────▼──────────┐ ┌─────▼──────────┐ ┌─────▼──────────────┐
        │create_instance_  │ │update_instance_│ │upgrade_instance_   │
        │       crd        │ │      crd       │ │       crd          │
        └──────────────────┘ └────────────────┘ └────────────────────┘

    Standalone (not wrapped by apply_state):
            ┌──────────────┐
            │   run_job    │  <-- INTERNAL, has own callbacks
            └──────┬───────┘
                   │ run_deployment_or_fail()
                   v
         ┌──────────────────┐
         │ run_job_command  │  <-- USER, runs the Kubernetes Job
         └──────────────────┘
```

The non-CRD variants (`create_instance`, `update_instance`, `upgrade_instance`) still exist in `agent/tasks/orchestration.py` for now but are not registered in the catalogue and are not on the live execution path. The CRD variants are what the operator actually drives — see [ADR-006](../adr/0006-prefect-crd-intent-declaration.md).

## Lifecycles without Prefect

<!-- Extracted from specs/008-deployment-deletion on 2026-05-02 -->

Not every lifecycle action goes through a Prefect flow. Two patterns coexist:

- **Orchestration-driven** (most lifecycle actions documented in this file): the mutation creates a `Task` with `status=PENDING` and a `prefect_flow_run_id`, dispatches a Prefect flow that runs the multi-step operation, and the flow's lifecycle callbacks (`on_completion`, `on_failure`, …) flip the task to its terminal state via the `callback` mutation.
- **State-driven** (added by the deployment-deletion feature): the mutation patches a single field on the cluster-side CRD, creates a **born-complete** `Task` (`status=SUCCESS`, `prefect_flow_run_id=None`) as the audit record, and returns immediately. There is no flow. Every subsequent state transition is observed off the existing reconciliation cadence — the operator drives the cluster work, and the agent's status reporter projects the resulting CRD state back to the DB.

Use state-driven when:

- The work to do is fundamentally one cluster patch (or a small set of synchronous calls) plus an asynchronous wait for the cluster to converge.
- The reconciler / status reporter already exists and can observe the relevant transitions without new instrumentation.
- The Task's role is to record "this was requested, by whom, when" (timeline / audit), not to track progress.

The current example is `delete_deployment` — see `dev/knowledge/backend/services.md` § "Deployment Lifecycle (incl. tombstoning)" for the full path. The pattern avoids reintroducing a long-running flow when the operator already has the same observation loop.

## Callback Mechanism

### orchestration_callback

Located at the top of `agent/tasks/orchestration.py`. POSTs to the server's GraphQL API to update task state:

```python
async def orchestration_callback(flow, flow_run: FlowRun, state: State) -> None:
    styrmin_server_url = config.SETTINGS.url.graphql
    async with httpx.AsyncClient() as client:
        await client.post(
            styrmin_server_url,
            json={
                "variables": {
                    "taskId": str(flow_run.parameters["task_id"]),
                    "stateName": state.name,
                    "stateMessage": state.message,
                    "stateType": state.type,
                },
                "query": "mutation Callback(...) { callback(...) { message success } }",
            },
        )
```

The callback reads `task_id` from the flow run parameters. Only flows that have `task_id` in their signature should register callbacks.

### Callback lifecycle

The internal `callback` mutation in `api/schema/mutation.py` maps Prefect states to task/deployment states:

| Prefect State | Task Status | Deployment Status |
|:---:|:---:|:---:|
| RUNNING | RUNNING | PENDING |
| COMPLETED | SUCCESS | RUNNING |
| FAILED | FAILED | FAILED |

When the callback sets a task to `FAILED`, `update_task_state` (`services/tasks.py`) also fails every pending or running step of the task that a flow records (every step kind except `OPERATOR_PHASE`), with the Prefect state message, or "The flow run failed" when Prefect sent none. The flow that owned those steps can no longer end them.

## Steps recorded by the flows

<!-- Extracted from specs/019-task-steps on 2026-10-06 -->

Each flow records its units of work as steps of its task, backup or restore, so users can view what ran, how long it took and why it failed without access to Prefect. The step recorder (`services/steps/recorder.py`) is the only code that creates or changes a step. Flows reach it in two ways, depending on the work pool they run on. See [ADR-060](../../adr/0060-steps-and-derived-task-result.md).

- **INTERNAL flows** (`styrmin-work-pool`, database access) call the recorder directly through `services/steps/internal_flows.py`: `open_task_step`, `end_step` and `fail_open_steps`. Each write runs in its own transaction.
- **USER flows and driver actions** (`user-work-pool`, no database access) use the flow step reporter (`agent/steps/reporter.py`). `StepReporter.from_env()` reads the action token from `config.SETTINGS.agent.api_token` (loaded from `STYRMIN_TOKEN`) and the step parent from the Job's environment, and sends `recordStep` events to the API with `Authorization: Bearer <STYRMIN_TOKEN>`. `reporter.step(key, name, kind)` is an async context manager: it records `STARTED`, then `SUCCEEDED`, or `FAILED` with the formatted exception before it re-raises. Each event carries `occurredAt`, the writer's clock.

A step write never fails the work. When the token or the parent variable is missing, the reporter does nothing. When a write fails (network error, GraphQL error, timeout after 10 seconds), the reporter or the INTERNAL helper logs a warning and the flow continues.

### Job variables

`action_job_variables(token, *, task_id=None, backup_id=None, restore_id=None, step_id=None)` (`agent/tasks/utils.py`) builds the Prefect job variables that put these values in the `env` of the flow run's Job. Prefect adds them to the work pool's default `env`. Values that are `None` are left out, and the function returns `{}` when all are `None`.

| Variable | Meaning |
|---|---|
| `STYRMIN_TOKEN` | The action token (ADR-059). |
| `STYRMIN_TASK_ID`, `STYRMIN_BACKUP_ID`, `STYRMIN_RESTORE_ID` | The parent of the steps the Job records. The caller sets one of them. |
| `STYRMIN_STEP_ID` | Set only for a driver action's Job: the hook step that runs the action. |

`Remediation.apply(api_token, task_id)` passes the token and `STYRMIN_TASK_ID` to the remediation flow's Job. `run_driver_action_or_fail(step_id=..., **kwargs)` forwards `STYRMIN_TOKEN` and `STYRMIN_TASK_ID` from the current Job's environment and adds `STYRMIN_STEP_ID`. See [hooks-and-actions.md](hooks-and-actions.md) for what an action does with it.

### Task types of reconcile tasks

The `apply_state` service function (`services/reconciliation/__init__.py`) takes a `task_type` argument and stores the new instance in `Task.instance_id`, so operator reports find the task. Each caller passes the operation it starts:

| Caller | Task type |
|---|---|
| `deploy_application` (`deploy`) | `create_instance` |
| `update_deployment`, `refresh_deployment`, `redeploy_for_environment_update` | `update_instance` |
| `_ensure_ingress_controller` | `create_instance` when the ingress controller has no instance yet, else `update_instance` |
| `update_deployment_version` (`updateDeploymentVersion`) | `upgrade_instance` |
| `stop_components`, `start_components` (`services/primitives.py`) | `stop_components`, `start_components` |

The type names the operation the user asked for, not the flow that runs: a version change is an `upgrade_instance` task even when the driver has no upgrade hook and the remediation runs `update_instance_crd`. The step list shows which flow ran. Tasks created before this change keep the type `noop`; `noop` remains the default of the argument.

`stop_components`, `start_components` and `update_deployment_version` also accept `started_by_step_id`. Each checks it with `check_starting_step` (`services/steps/reads.py`) right after it loads the deployment, before it changes anything and before the no-op return of `update_deployment_version`: `StepNotFoundError` when it names no step, `InvalidStartingStepError` when the step is not a step of a task of the same deployment. `apply_state` stores it in `Task.started_by_step_id`.

## Flow: apply_state

The top-level orchestration wrapper. Has all lifecycle callbacks.

```python
@flow(
    on_cancellation=[orchestration_callback],
    on_completion=[orchestration_callback],
    on_failure=[orchestration_callback],
    on_crashed=[orchestration_callback],
    on_running=[orchestration_callback],
)
async def apply_state(
    task_id: UUID,
    deployment_id: UUID,
    new_instance_id: UUID,
    current_instance_id: UUID | None,
) -> State | None:
    plan_step_id = await open_task_step(task_id, steps.PLAN)
    try:
        # Loads the deployment and both instances, diffs them, builds the remediation,
        # or returns Completed(message="No remediation needed").
        remediation = await _plan_remediation(...)
    except Exception as exc:
        await end_step(plan_step_id, error=format_exception(exc))
        raise
    await end_step(plan_step_id)
    if isinstance(remediation, State):
        return remediation

    async with action_api_token() as api_token:
        try:
            flow_info = await remediation.apply(api_token=api_token, task_id=task_id)
        except Exception as exc:
            await fail_open_steps(StepParent.of_task(task_id), str(exc))
            raise
    return flow_info.state
```

Called by: `PrefectManager.run_action(PrefectAction.APPLY_STATE, parameters={...})`

The flow records the `plan` step ("Plan the changes") through the recorder directly. The service that schedules `apply_state` commits the task row after it dispatches the flow, so `open_task_step` retries every 0.5 seconds while the task row does not exist, for up to 10 seconds, then logs a warning and returns `None`; `end_step(None)` does nothing. A task with nothing to apply has only the `plan` step.

The flow applies the remediation after the unit of work closes, so the session's database connection is released while the inner flow runs, and the action token's writes do not overlap it. When the remediation flow run fails or crashes, `run_deployment_or_fail` raises, and `apply_state` fails the task's open flow-kind steps with the error before it re-raises: a crashed Job cannot end the step it was running.

The `remediation.apply()` method calls `arun_deployment(name=self.flow_id, parameters=self.parameters, job_variables=...)`, which triggers one of the inner flows below.

`action_api_token()` creates a session for the built-in `styrmin-actions` user and deletes it when the remediation ends. The token reaches the inner flow's Job as `STYRMIN_TOKEN` through the flow run's `env` job variable, together with `STYRMIN_TASK_ID`, and the inner flow passes both on to each driver action with `run_driver_action_or_fail`. The inner flow records its steps with the token, and the action primitives send it as a bearer token. See [ADR-059](../../adr/0059-driver-action-api-tokens.md).

**Key**: Only `apply_state` has callbacks. Inner flows do NOT register callbacks because they run as sub-flows within `apply_state`.

## Flow: create_instance_crd

Creates a new application instance by writing a `StyrminDeployment` CRD; the kopf operator reconciles all Kubernetes resources from the CRD spec.

```python
@flow(flow_run_name="Create instance (CRD)")
async def create_instance_crd(
    instance: Instance,
    prehook: UUID | None,        # Optional user pre-setup hook
    posthook: UUID | None,       # Optional user post-setup hook
    internal: bool = False,      # True for system deployments (e.g. ingress controller)
) -> None
```

Execution order, with the step that each part records:

```text
1. Extract context, release_reference, namespace from instance.context
2. Run pre-hook (if prehook is not None)  step hook:setup:pre
3. Build the StyrminDeployment CRD body   step resource:styrmindeployment
   from the resolved context              (steps 3 to 5)
4. Apply the deployment namespace with labels
5. Upsert the StyrminDeployment CRD       ──> operator reconciles in
                                              ordered phases (NetworkPolicies,
                                              Secrets -> HelmRelease ->
                                              Services, Middlewares)
6. Apply cross-namespace ExternalName     step resource:service-aliases
   service aliases (if any)               (only when there are aliases)
7. Run post-hook (if posthook is not None) step hook:setup:post
```

When the `resource:styrmindeployment` step succeeds, the recorder creates this task's four operator-phase steps (none for an internal deployment) and supersedes the open operator-phase steps of the deployment's older tasks. See [Remediation-flow steps](#remediation-flow-steps).

Called via `Remediation(type=CREATE_INSTANCE, flow_id=<CREATE_INSTANCE deployment>, parameters={instance, prehook, posthook, internal})`.

## Flow: update_instance_crd

Updates an existing instance (config change, no version change) by rewriting the CRD spec.

```python
@flow(flow_run_name="Update instance (CRD)")
async def update_instance_crd(
    instance: Instance,
) -> None
```

Execution order:

```text
1. Extract context, release_reference, namespace from instance.context
2. Build the new StyrminDeployment CRD body  step resource:styrmindeployment
3. Upsert the CRD                          ──> operator reconciles
                                              the new HelmRelease and
                                              utility resources
4. Apply cross-namespace service aliases   step resource:service-aliases
   (if any)
```

Called via `Remediation(type=UPDATE_INSTANCE, flow_id=<UPDATE_INSTANCE deployment>, parameters={instance})`. No hooks are involved in updates.

## Flow: upgrade_instance_crd

Upgrades an application instance when a version change is detected and the driver defines upgrade hooks.

```python
@flow(flow_run_name="Upgrade instance (CRD)")
async def upgrade_instance_crd(
    instance: Instance,
    upgrade_hook: UUID,           # Driver's core upgrade action
    target_version: str,          # Application version being upgraded to
    prehook: UUID | None = None,  # Optional driver pre-upgrade hook
    posthook: UUID | None = None, # Optional driver post-upgrade hook
) -> None
```

Execution order:

```text
1. Build and upsert StyrminDeployment CRD (the new spec)   step resource:styrmindeployment
2. Patch CRD status to displayState=Deploying / phase=Pending atomically
   with the spec change. Without this, a stale "Running" displayState
   could race the agent into reporting the new instance as healthy
   before the new rollout has even started.   (still resource:styrmindeployment)
3. Run pre-hook (if prehook is not None)                   step hook:upgrade:pre
4. Run core upgrade hook (driver's upgrade function —      step hook:upgrade:core
   e.g. stop, migrate, start)
5. Apply cross-namespace service aliases (if any)          step resource:service-aliases
6. Run post-hook (if posthook is not None)                 step hook:upgrade:post
```

Called via `Remediation(type=UPGRADE_INSTANCE, flow_id=<UPGRADE_INSTANCE deployment>, parameters={instance, upgrade_hook, target_version, prehook, posthook})`.

The CRD spec is written *before* the hooks run because driver upgrade hooks frequently call back into the server (e.g. `stop_components`, `upgrade_deployment_version`), each of which spawns a nested `update_instance_crd` flow. Writing the CRD up front lets nested updates layer correctly; writing it at the end would stomp them with this flow's older instance.

**Key differences from `create_instance_crd`:**

- Core hook is a USER action (driver's upgrade function); setup has no separate core hook in the CRD path.
- Passes `target_version` to all hooks so driver code knows what version it's upgrading to.
- Writes the CRD spec at the very start so hook-driven nested CRD updates layer correctly.

## Remediation-flow steps

The three CRD flows record their steps with `StepReporter.from_env()`. Keys, names and kinds come from `domain/steps.py`:

| Key | Name | Kind | Recorded by |
|---|---|---|---|
| `plan` | Plan the changes | `PLAN` | `apply_state`, directly |
| `hook:setup:pre` | Run the setup pre-hook | `HOOK` | `create_instance_crd`, when the driver has a setup pre-hook |
| `resource:styrmindeployment` | Write the StyrminDeployment resource | `RESOURCE_WRITE` | all three CRD flows |
| `hook:upgrade:pre` | Run the upgrade pre-hook | `HOOK` | `upgrade_instance_crd`, when the driver has an upgrade pre-hook |
| `hook:upgrade:core` | Run the upgrade hook | `HOOK` | `upgrade_instance_crd` |
| `resource:service-aliases` | Create service aliases | `RESOURCE_WRITE` | all three CRD flows, only when the context has aliases |
| `hook:setup:post` | Run the setup post-hook | `HOOK` | `create_instance_crd`, when the driver has a setup post-hook |
| `hook:upgrade:post` | Run the upgrade post-hook | `HOOK` | `upgrade_instance_crd`, when the driver has an upgrade post-hook |

A hook step covers one run of a hook mode. The flow passes the hook step's id to `run_driver_action_or_fail(step_id=...)`, which sends it to the action's Job as `STYRMIN_STEP_ID`.

The flows do not record the operator's work. When `resource:styrmindeployment` succeeds, the recorder:

1. Creates this task's operator-phase steps: `operator:prerequisites` ("Create network policies and secrets") as running, then `operator:helmrelease` ("Install or upgrade the HelmRelease"), `operator:services` ("Create services and middlewares") and `operator:ready` ("Wait for the deployment to be ready") as pending. An internal deployment gets none, because the status reporter does not report internal deployments.
2. Supersedes the pending and running operator-phase steps of the deployment's older tasks (status `SUPERSEDED`, `superseded_by_task_id` set to this task), because the operator abandons an earlier rollout as soon as the spec changes. A task is older when it was created first; tasks created at the same time are ordered by id. The steps of newer tasks do not change. When a `resource:styrmindeployment` or `resource:delete-request` step of a newer task has already succeeded, this success arrived late: the first such newer task supersedes this task's new operator-phase steps instead.

The status reporter's reports then move those steps forward (`services/steps/operator_history.py`, called from `report_deployment_statuses`). See [`../agent/operator.md`](../agent/operator.md) for the CR status that drives them.

A delete has no flow. `delete_deployment` records `resource:delete-request` ("Request the deletion") as succeeded after it patches the CR, supersedes the open operator-phase steps of the deployment's older tasks (all its other tasks, because the delete task is the newest), and creates `operator:teardown` ("Remove the deployment's resources and namespace") as pending. Reports in the `Deleting` and `Deleted` phases go to the deployment's newest `delete_deployment` task.

## Flow: run_job

`runJob` (`services/primitives.py`) creates a `run_job` task and starts `PrefectAction.RUN_JOB`. The work runs in two flows, so that the INTERNAL flow can create and delete the action token and the USER flow can create the Kubernetes Job.

```python
@flow(
    on_cancellation=[orchestration_callback],
    on_completion=[orchestration_callback],
    on_failure=[orchestration_callback],
    on_crashed=[orchestration_callback],
    on_running=[orchestration_callback],
)
async def run_job(  # INTERNAL, styrmin-work-pool
    task_id: UUID,
    runtime_class: str,
    env: list[dict],
    namespace: str,
    commands: list[str],
    image: str,
) -> None:
    async with action_api_token() as api_token:
        try:
            await run_deployment_or_fail(
                name="run_job_command/run_job_command",
                parameters={...},  # the same arguments
                job_variables=action_job_variables(api_token, task_id=task_id),
            )
        except Exception as exc:
            await fail_open_steps(StepParent.of_task(task_id), str(exc))
            raise


@flow(flow_run_name="Run job command")
async def run_job_command(...) -> None:  # USER, user-work-pool
    ...
```

`run_job` keeps the lifecycle callbacks, because it is not wrapped by `apply_state`. `run_job_command` builds the Kubernetes Job manifest with:

- Pod affinity to Neo4j instances
- Tolerations for node failures
- Custom container `prefect-job` with the specified image, env, and commands
- `metadata.generateName: job-run-<task_id>-`, so Kubernetes names the Job

It runs `run_kubernetes_job(manifest, namespace)` inside the `command` step ("Run the job's command", kind `COMMAND`). `run_kubernetes_job` polls the Job by the name Kubernetes gave it; before this change it read `metadata.name` from the manifest when the Job failed, which raised `KeyError` for a manifest with only `generateName`. When the Job fails, `run_kubernetes_job` raises `JobFailedError` carrying the end of the output of the manifest's first container (see [hooks-and-actions.md](hooks-and-actions.md#command-output-of-a-failed-job)); `run_job_command` records that output on the `command` step, and the step fails with the error. When `run_job_command` fails or crashes, `run_job` fails the task's open flow-kind steps before it re-raises.

## Rendering Tasks

### Core Tasks (`agent/tasks/core.py`)

```python
@task
async def render_application_helm_release_specifications(context: GlobalContext) -> dict:
    """Render the Helm release specification for the application using Jinja2 template."""
```

### Shared Tasks (`agent/tasks/shared.py`)

```python
@task
async def get_context(instance_id: UUID) -> GlobalContext:
    """Fetch GlobalContext from the internal API by instance ID."""

@task
async def render_helm_chart_specifications(helm: HelmInfo) -> dict:
    """Create chart spec dict from HelmInfo."""

@task
async def render_helm_repository_specifications(helm: HelmInfo) -> dict:
    """Create repository spec dict from HelmInfo."""
```

### Application Tasks (`agent/tasks/application.py`)

```python
@flow
async def create_helm_release(
    namespace: str,
    reference: str,
    release_spec: dict,
    helm_repositories: list[dict],
    charts: list[dict],
) -> None:
    """Add Helm repos, install charts, create HelmRelease CRD, poll for status."""

@flow
async def update_helm_release(
    namespace: str,
    reference: str,
    release_spec: dict,
) -> None:
    """Update existing HelmRelease CRD with new spec."""
```

### Extra Tasks (`agent/tasks/extra.py`)

```python
async def install_utility(utility, release_reference, context, namespace, instantiation_flow):
    """Install a utility (e.g., ingress) as a HelmRelease."""

async def update_utility(utility, release_reference, context, namespace, update_flow):
    """Update an existing utility HelmRelease."""
```

## Workflow Catalogue

Located in `workflows/catalogue.py`. Maps `PrefectAction` enums to `WorkflowDefinition` objects. Every entry today uses `LocalSourceWorkflowDefinition` (no Git pull at flow-run time):

| PrefectAction | Flow Function | Module | Type |
|---|---|---|---|
| `APPLY_STATE` | `apply_state` | `agent.tasks.orchestration` | INTERNAL |
| `RUN_JOB` | `run_job` | `agent.tasks.orchestration` | INTERNAL |
| `RUN_JOB_COMMAND` | `run_job_command` | `agent.tasks.orchestration` | USER |
| `CREATE_HELM_RELEASE` | `create_helm_release` | `agent.tasks.application` | USER |
| `UPDATE_HELM_RELEASE` | `update_helm_release` | `agent.tasks.application` | USER |
| `CREATE_INSTANCE` | `create_instance_crd` | `agent.tasks.orchestration` | USER |
| `UPDATE_INSTANCE` | `update_instance_crd` | `agent.tasks.orchestration` | USER |
| `UPGRADE_INSTANCE` | `upgrade_instance_crd` | `agent.tasks.orchestration` | USER |
| `EXECUTE_BACKUP` | `execute_backup_workflow` | `workflows.templates.backup` | INTERNAL |
| `EXECUTE_RESTORE` | `execute_restore_workflow` | `workflows.templates.backup` | INTERNAL |
| `EXECUTE_VELERO_BACKUP` | `execute_velero_backup_flow` | `workflows.templates.backup` | USER |
| `EXECUTE_VELERO_RESTORE` | `execute_velero_restore_flow` | `workflows.templates.backup` | USER |

The `WorkflowType` distinction (`INTERNAL` vs `USER`) controls which Prefect work pool the flow runs on (`styrmin-work-pool` vs `user-work-pool`). User-defined driver actions, registered separately at driver-load time, use `GitSourceWorkflowDefinition` so the worker pulls the driver's repo at runtime.

## PrefectAction Enum

Located in `workflows/models.py`:

```python
class PrefectAction(Enum):
    APPLY_STATE = "apply_state"

    CREATE_HELM_RELEASE = "create_instance"
    UPDATE_HELM_RELEASE = "update_instance"

    CREATE_INSTANCE = "orchestrate_instance_creation"
    UPDATE_INSTANCE = "orchestrate_instance_update"
    UPGRADE_INSTANCE = "orchestrate_instance_upgrade"
    RUN_JOB = "run_job"
    RUN_JOB_COMMAND = "run_job_command"

    EXECUTE_BACKUP = "execute_backup"
    EXECUTE_RESTORE = "execute_restore"
    EXECUTE_VELERO_BACKUP = "execute_velero_backup"
    EXECUTE_VELERO_RESTORE = "execute_velero_restore"

    def to_tag(self) -> str:
        return f"action/{self.value}"
```

Note: The enum values are used as Prefect deployment tags for lookup.

## CRD-Based Deployment

<!-- Extracted from specs/001-deployment-crd on 2026-04-06 -->

For new deployments, Prefect flows create/update/delete `StyrminDeployment` CRDs instead of directly managing HelmReleases and utility resources. The kopf operator handles all Kubernetes resource lifecycle from the CRD (see [`../agent/operator.md`](../agent/operator.md) for details).

**What the Prefect flow does:**

1. Compute GlobalContext from deployment configuration
2. Render Helm chart/repository specifications
3. Serialize context into StyrminDeployment CRD spec
4. Create/update/delete the CRD via kubernetes-asyncio API
5. Run driver pre/post hooks (unchanged)
6. Callback to update task status (unchanged)

**What is no longer done by Prefect:**

- Direct HelmRelease creation/update
- Direct utility resource creation/update (`install_utility`, `update_utility`)
- Namespace label management
- HelmRelease polling

See ADR-006 for the rationale behind this responsibility shift.

## Key Files

| File | Purpose |
|------|---------|
| [agent/tasks/orchestration.py](backend/styrmin_backend/agent/tasks/orchestration.py) | `apply_state`, `create_instance_crd`, `update_instance_crd`, `upgrade_instance_crd`, `run_job`, `run_job_command` (plus the legacy `create_instance` / `update_instance` / `upgrade_instance` flows, currently unregistered) |
| [agent/tasks/utils.py](backend/styrmin_backend/agent/tasks/utils.py) | `action_job_variables`, `run_deployment_or_fail`, `run_driver_action_or_fail` |
| [agent/steps/reporter.py](backend/styrmin_backend/agent/steps/reporter.py) | Flow step reporter: `recordStep` calls from USER flows and driver actions |
| [services/steps/internal_flows.py](backend/styrmin_backend/services/steps/internal_flows.py) | Step writes from INTERNAL flows (`open_task_step`, `end_step`, `fail_open_steps`) |
| [services/steps/recorder.py](backend/styrmin_backend/services/steps/recorder.py) | Step recorder, the only code that changes steps |
| [domain/steps.py](backend/styrmin_backend/domain/steps.py) | Step keys, names and kinds |
| [services/reconciliation/__init__.py](backend/styrmin_backend/services/reconciliation/__init__.py) | `apply_state` service function (`task_type`, `instance_id`, `started_by_step_id`) |
| [agent/tasks/application.py](backend/styrmin_backend/agent/tasks/application.py) | `create_helm_release`, `update_helm_release` |
| [agent/tasks/core.py](backend/styrmin_backend/agent/tasks/core.py) | `render_application_helm_release_specifications` |
| [agent/tasks/shared.py](backend/styrmin_backend/agent/tasks/shared.py) | `get_context`, `render_helm_chart_specifications`, `render_helm_repository_specifications` |
| [agent/tasks/extra.py](backend/styrmin_backend/agent/tasks/extra.py) | `install_utility`, `update_utility` |
| [workflows/catalogue.py](backend/styrmin_backend/workflows/catalogue.py) | Workflow registry |
| [workflows/models.py](backend/styrmin_backend/workflows/models.py) | `PrefectAction`, `WorkflowDefinition` |
| [workflows/manager.py](backend/styrmin_backend/workflows/manager.py) | `PrefectManager` |
