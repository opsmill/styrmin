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
            │   run_job    │  <-- Has own callbacks
            └──────────────┘
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
    api_url = os.environ.get("STYRMIN_URL_API", "http://localhost:8000")
    styrmin_server_url = f"{api_url}/graphql"
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
    remediation: Remediation | None,
) -> State | None:
    if remediation is None:
        return Completed(message="No remediation needed")
    flow_info = await remediation.apply()
    return flow_info.state
```

Called by: `PrefectManager.run_action(PrefectAction.APPLY_STATE, parameters={...})`

The `remediation.apply()` method calls `arun_deployment(name=self.flow_id, parameters=self.parameters)`, which triggers one of the inner flows below.

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

Execution order:

```text
1. Extract context, release_reference, namespace from instance.context
2. Run pre-hook (if prehook is not None)
3. Build the StyrminDeployment CRD body from the resolved context
4. Apply the deployment namespace with labels
5. Upsert the StyrminDeployment CRD       ──> operator reconciles in
                                              ordered phases (NetworkPolicies,
                                              Secrets -> HelmRelease ->
                                              Services, Middlewares)
6. Apply cross-namespace ExternalName service aliases (if any)
7. Run post-hook (if posthook is not None)
```

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
2. Build the new StyrminDeployment CRD body
3. Upsert the CRD                          ──> operator reconciles
                                              the new HelmRelease and
                                              utility resources
4. Apply cross-namespace service aliases (if any)
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
1. Build and upsert StyrminDeployment CRD (the new spec)
2. Patch CRD status to displayState=Deploying / phase=Pending atomically
   with the spec change. Without this, a stale "Running" displayState
   could race the agent into reporting the new instance as healthy
   before the new rollout has even started.
3. Run pre-hook (if prehook is not None)
4. Run core upgrade hook (driver's upgrade function — e.g. stop, migrate, start)
5. Apply cross-namespace service aliases (if any)
6. Run post-hook (if posthook is not None)
```

Called via `Remediation(type=UPGRADE_INSTANCE, flow_id=<UPGRADE_INSTANCE deployment>, parameters={instance, upgrade_hook, target_version, prehook, posthook})`.

The CRD spec is written *before* the hooks run because driver upgrade hooks frequently call back into the server (e.g. `stop_components`, `upgrade_deployment_version`), each of which spawns a nested `update_instance_crd` flow. Writing the CRD up front lets nested updates layer correctly; writing it at the end would stomp them with this flow's older instance.

**Key differences from `create_instance_crd`:**

- Core hook is a USER action (driver's upgrade function); setup has no separate core hook in the CRD path.
- Passes `target_version` to all hooks so driver code knows what version it's upgrading to.
- Writes the CRD spec at the very start so hook-driven nested CRD updates layer correctly.

## Flow: run_job

Standalone flow for one-off Kubernetes Jobs. Has its own callbacks.

```python
@flow(
    on_cancellation=[orchestration_callback],
    on_completion=[orchestration_callback],
    on_failure=[orchestration_callback],
    on_crashed=[orchestration_callback],
    on_running=[orchestration_callback],
)
async def run_job(
    task_id: UUID,
    runtime_class: str,
    env: list[dict],
    namespace: str,
    commands: list[str],
    image: str,
) -> None
```

Builds a Kubernetes Job manifest with:

- Pod affinity to Neo4j instances
- Tolerations for node failures
- Custom container with specified image, env, and commands

Then calls `run_kubernetes_job(manifest, namespace)`.

**Note**: `run_job` has its own callbacks because it is NOT wrapped by `apply_state`. It is triggered directly by `PrefectManager.run_action(PrefectAction.RUN_JOB)`.

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
| `RUN_JOB` | `run_job` | `agent.tasks.orchestration` | USER |
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
| [agent/tasks/orchestration.py](backend/styrmin_backend/agent/tasks/orchestration.py) | `apply_state`, `create_instance_crd`, `update_instance_crd`, `upgrade_instance_crd`, `run_job` (plus the legacy `create_instance` / `update_instance` / `upgrade_instance` flows, currently unregistered) |
| [agent/tasks/application.py](backend/styrmin_backend/agent/tasks/application.py) | `create_helm_release`, `update_helm_release` |
| [agent/tasks/core.py](backend/styrmin_backend/agent/tasks/core.py) | `render_application_helm_release_specifications` |
| [agent/tasks/shared.py](backend/styrmin_backend/agent/tasks/shared.py) | `get_context`, `render_helm_chart_specifications`, `render_helm_repository_specifications` |
| [agent/tasks/extra.py](backend/styrmin_backend/agent/tasks/extra.py) | `install_utility`, `update_utility` |
| [workflows/catalogue.py](backend/styrmin_backend/workflows/catalogue.py) | Workflow registry |
| [workflows/models.py](backend/styrmin_backend/workflows/models.py) | `PrefectAction`, `WorkflowDefinition` |
| [workflows/manager.py](backend/styrmin_backend/workflows/manager.py) | `PrefectManager` |
