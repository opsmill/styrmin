# Orchestration Flows

## Overview

Orchestration flows are Prefect `@flow` functions that execute multi-step deployment operations. They live in `agent/tasks/orchestration.py` and are submitted via the `PrefectManager`.

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
                    ┌───────────────┼───────────────┐
                    │               │               │
            ┌───────▼──────┐ ┌─────▼──────┐ ┌─────▼──────────┐
            │create_instance│ │update_     │ │upgrade_        │
            │              │ │instance    │ │instance        │
            └──────────────┘ └────────────┘ └────────────────┘

    Standalone (not wrapped by apply_state):
            ┌──────────────┐
            │   run_job    │  <-- Has own callbacks
            └──────────────┘
```

## Callback Mechanism

### orchestration_callback

Located at the top of `agent/tasks/orchestration.py`. POSTs to the internal GraphQL API to update task state:

```python
async def orchestration_callback(flow, flow_run: FlowRun, state: State) -> None:
    styrmin_server_url = os.environ.get(
        "STYRMIN_URL_INTERNAL_API", "http://localhost:8000/internal/graphql"
    )
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

## Flow: create_instance

Creates a new application instance with setup hooks.

```python
@flow
async def create_instance(
    instance: Instance,
    corehook: UUID,             # CREATE_HELM_RELEASE deployment ID
    prehook: UUID | None,       # Optional user pre-setup hook
    posthook: UUID | None,      # Optional user post-setup hook
) -> None
```

Execution order:

```text
1. Extract context, release_reference, namespace from instance.context
2. Render specs in parallel:
   - render_helm_chart_specifications(helm)
   - render_helm_repository_specifications(helm)
   - render_application_helm_release_specifications(context)
3. Run pre-hook (if prehook is not None):
   arun_deployment(name=prehook, parameters={"context": context})
4. Run core hook (CREATE_HELM_RELEASE):
   arun_deployment(name=corehook, parameters={
       "namespace": namespace,
       "reference": release_reference,
       "release_spec": release_spec,
       "helm_repositories": [helm_repo_spec],
       "charts": [chart_spec],
   })
5. Run post-hook (if posthook is not None):
   arun_deployment(name=posthook, parameters={"context": context})
6. Install utilities in parallel:
   asyncio.gather(*[install_utility(...) for utility in context.utilities])
```

Called via `Remediation(type=CREATE_INSTANCE, flow_id=<CREATE_INSTANCE deployment>, parameters={instance, corehook, prehook, posthook})`.

## Flow: update_instance

Updates an existing instance (config change, no version change).

```python
@flow
async def update_instance(
    instance: Instance,
    update_flow: UUID,          # UPDATE_HELM_RELEASE deployment ID
) -> None
```

Execution order:

```text
1. Extract context, release_reference, namespace from instance.context
2. Update utilities in parallel:
   asyncio.gather(*[update_utility(...) for utility in context.utilities])
3. Render application Helm release specs:
   render_application_helm_release_specifications(context)
4. Update Helm release:
   arun_deployment(name=update_flow, parameters={
       "namespace": namespace,
       "release_spec": release_spec,
       "reference": f"extra-{release_reference}",
   })
```

Called via `Remediation(type=UPDATE_INSTANCE, flow_id=<UPDATE_INSTANCE deployment>, parameters={instance, update_flow})`.

No hooks are involved in updates.

## Flow: upgrade_instance

Upgrades an application instance when a version change is detected and the driver defines upgrade hooks.

```python
@flow(flow_run_name="Upgrade instance")
async def upgrade_instance(
    instance: Instance,
    upgrade_hook: UUID,                    # Driver's core upgrade action
    update_flow: UUID,                     # UPDATE_HELM_RELEASE deployment ID
    target_version: str,                   # Application version being upgraded to
    apply_utility_flow: UUID | None = None,# APPLY_UTILITY_RESOURCES deployment ID
    prehook: UUID | None = None,           # Optional driver pre-upgrade hook
    posthook: UUID | None = None,          # Optional driver post-upgrade hook
) -> None
```

Execution order:

```text
1. Run pre-hook (if prehook is not None):
   arun_deployment(name=prehook, parameters={"context": context, "target_version": target_version})
2. Run core upgrade hook:
   arun_deployment(name=upgrade_hook, parameters={"context": context, "target_version": target_version})
3. Update utilities in parallel (if any):
   asyncio.gather(*[update_utility(...) for utility in context.utilities])
4. Render and update Helm release:
   render_application_helm_release_specifications(context)
   arun_deployment(name=update_flow, parameters={namespace, release_spec, reference, namespace_labels})
5. Run post-hook (if posthook is not None):
   arun_deployment(name=posthook, parameters={"context": context, "target_version": target_version})
```

Called via `Remediation(type=UPGRADE_INSTANCE, flow_id=<UPGRADE_INSTANCE deployment>, parameters={instance, upgrade_hook, update_flow, apply_utility_flow, target_version, prehook, posthook})`.

**Key differences from `create_instance`:**
- Core hook is a USER action (driver's upgrade function), not an internal action
- Passes `target_version` to all hooks so driver code knows what version it's upgrading to
- Updates Helm release AFTER the upgrade hook (so chart values reflect the new version)
- Follows the same utility update pattern as `update_instance`

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

Located in `workflows/catalogue.py`. Maps `PrefectAction` enums to `WorkflowDefinition` objects:

| PrefectAction | Flow Function | Module | Work Pool |
|---|---|---|---|
| `APPLY_STATE` | `apply_state` | `agent.tasks.orchestration` | Internal |
| `RUN_JOB` | `run_job` | `agent.tasks.orchestration` | User |
| `CREATE_HELM_RELEASE` | `create_helm_release` | `agent.tasks.application` | User (Git) |
| `UPDATE_HELM_RELEASE` | `update_helm_release` | `agent.tasks.application` | User (Git) |
| `CREATE_INSTANCE` | `create_instance` | `agent.tasks.orchestration` | Internal |
| `UPDATE_INSTANCE` | `update_instance` | `agent.tasks.orchestration` | Internal |
| `UPGRADE_INSTANCE` | `upgrade_instance` | `agent.tasks.orchestration` | Internal |

**Internal** flows use `LocalSourceWorkflowDefinition` (run in-process).
**User/Git** flows use `GitSourceWorkflowDefinition` (pull from Git, run in K8s).

## PrefectAction Enum

Located in `workflows/models.py`:

```python
class PrefectAction(Enum):
    APPLY_STATE = "apply_state"
    CREATE_HELM_RELEASE = "create_instance"
    UPDATE_HELM_RELEASE = "update_instance"
    PATCH_INSTANCE = "patch_instance"
    CREATE_INSTANCE = "orchestrate_instance_creation"
    UPDATE_INSTANCE = "orchestrate_instance_update"
    UPGRADE_INSTANCE = "orchestrate_instance_upgrade"
    RUN_JOB = "run_job"

    def to_tag(self) -> str:
        return f"action/{self.value}"
```

Note: The enum values are used as Prefect deployment tags for lookup.

## Key Files

| File | Purpose |
|------|---------|
| [agent/tasks/orchestration.py](backend/styrmin_backend/agent/tasks/orchestration.py) | `apply_state`, `create_instance`, `update_instance`, `upgrade_instance`, `run_job` |
| [agent/tasks/application.py](backend/styrmin_backend/agent/tasks/application.py) | `create_helm_release`, `update_helm_release` |
| [agent/tasks/core.py](backend/styrmin_backend/agent/tasks/core.py) | `render_application_helm_release_specifications` |
| [agent/tasks/shared.py](backend/styrmin_backend/agent/tasks/shared.py) | `get_context`, `render_helm_chart_specifications`, `render_helm_repository_specifications` |
| [agent/tasks/extra.py](backend/styrmin_backend/agent/tasks/extra.py) | `install_utility`, `update_utility` |
| [workflows/catalogue.py](backend/styrmin_backend/workflows/catalogue.py) | Workflow registry |
| [workflows/models.py](backend/styrmin_backend/workflows/models.py) | `PrefectAction`, `WorkflowDefinition` |
| [workflows/manager.py](backend/styrmin_backend/workflows/manager.py) | `PrefectManager` |
