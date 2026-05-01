# Hooks and User Actions

## Overview

Application drivers can define **user actions** - custom Prefect workflows that execute driver-specific logic during deployment lifecycle events. Actions are organized into **hooks** with **modes** that determine when they run relative to the core operation.

```text
Driver Repository
├── driver.styrmin.yml       # Driver manifest (includes action declarations)
├── actions.py               # Action implementations (Prefect flows)
└── values.j2.yml            # Helm values template

                ┌──────────────────────┐
                │ driver.styrmin.yml   │ ── declares ──> Hook type + mode + location
                │   spec.actions:      │                 (inline in driver spec)
                └──────────┬───────────┘
                           │
                           v
                    ┌──────────────┐
                    │  actions.py  │ ── implements ──> Prefect @flow functions
                    └──────┬───────┘
                           │
             ┌─────────────┼─────────────┐
             │             │             │
        ┌────▼───┐   ┌────▼────┐   ┌───▼────┐
        │  pre   │   │  core   │   │  post  │
        │  hook  │   │  hook   │   │  hook  │
        └────────┘   └─────────┘   └────────┘
```

## Action Definition Format

### Action declarations in driver.styrmin.yml

Actions are declared inline within the driver spec under `spec.actions`:

```yaml
---
apiVersion: "styrmin.io/v1"
kind: ApplicationDriver
metadata:
  name: infrahub
spec:
  version: "1"
  supported_versions: ">=1.5,<1.9"
  helm:
    main:
      location: oci://registry.opsmill.io/opsmill/chart/infrahub
      version: 4.16.3
  # ... components, services, etc. ...
  actions:
    - name: upgrade              # Unique action name
      hook: upgrade              # Hook type: "setup" or "upgrade"
      mode: core                 # Execution phase: "pre", "core", or "post"
      description: Upgrade Infrahub
      location: "actions.py::upgrade"   # Python module::function

    - name: pre_setup
      hook: setup
      mode: pre
      description: Initial Setup of Infrahub
      location: "actions.py::pre_setup"

    - name: post_setup
      hook: setup
      mode: post
      description: Initial Setup of Infrahub
      location: "actions.py::post_setup"
```

### actions.py

```python
from styrmin_backend.actions import stop_components, GlobalContext, start_components, execute_commands
from prefect import flow, get_run_logger

@flow
async def upgrade(deployment_id, target_version):
    """Core upgrade hook - runs during version changes."""
    await stop_components(components=["server", "task-worker"], ...)
    await execute_commands(["sh", "-c", "infrahub db migrate"], ...)
    await start_components(components=["server", "task-worker"], ...)

@flow
def pre_setup(context):
    """Pre-setup hook - runs before Helm chart installation."""
    logger = get_run_logger()
    logger.info(f"Context: {context}")

@flow
def post_setup(context):
    """Post-setup hook - runs after Helm chart installation."""
    logger = get_run_logger()
    logger.info(f"Context: {context}")
```

## Data Models

### HookKind Enum

Located in `services/driver/models/resources/actions.py`:

```python
class HookKind(str, Enum):
    SETUP = "setup"       # Instance creation lifecycle
    UPGRADE = "upgrade"   # Version upgrade lifecycle
```

### ActionDefinition Model

```python
class ActionDefinition(BaseModel):
    name: str
    location: str          # Pattern: "module.py::function_name"
    description: str
    hook: HookKind
    parameters: list[Parameter] = []
    mode: Literal["pre", "core", "post"]
    image: str | None = None   # Custom Docker image for execution
```

Actions are embedded directly in the `Specification` model (`services/driver/models/resources/driver.py`) as an optional list:

```python
class Specification(BaseModel):
    # ... other fields ...
    actions: list[ActionDefinition] = []
```

### Database Model

Actions are persisted in the `action` table:

```python
class Action(StyrminModel, table=True):
    name: str
    description: str
    location: str
    image: str | None
    hook: str | None       # Stored as string value
    mode: str | None
    application_driver_version_id: UUID
```

## Validation

### UserActionsValidator (`services/driver/validators.py`)

Validates that all declared actions have corresponding function implementations:

1. Parses the driver's `actions.py` using Python AST
2. Extracts all top-level function definitions
3. For each action in `driver_spec.spec.actions`, verifies the function referenced in `location` exists
4. Functions must be at module root level (not nested)

## Registration Pipeline

When a driver is loaded via `load_application_driver_from_object()` in `services/applications.py`:

```text
1. Parse driver.styrmin.yml ──> DriverSpec (with embedded actions)
2. Validate actions.py ──> UserActionsValidator
3. For each action in driver_spec.spec.actions:
   a. ActionsWorkflowBuilder.build_user_action_workflow_definition(action)
      ──> Creates a GitSourceWorkflowDefinition with:
          - source: driver's Git repository + branch
          - module/function: from action.location
          - image: from action.image (optional)
   b. PrefectManager.register_user_action(workflow, application, version, hook, mode)
      ──> Saves deployment to Prefect with tags:
          - "application/{name}"
          - "version/{supported_versions}"
          - "hook/{hook.value}"
          - "mode/{mode}"
   c. Save Action to database via UnitOfWork
```

## Lookup

### PrefectManager.get_user_action_deployment_id()

Located in `workflows/manager.py`:

```python
async def get_user_action_deployment_id(
    self,
    application: str,            # e.g., "infrahub"
    version: str,                # e.g., ">=1.5,<1.7"
    hook: HookKind,              # e.g., HookKind.SETUP
    mode: Literal["pre", "core", "post"],
) -> UUID | None:
    """Query Prefect deployments by tag combination. Returns None if not found."""
```

Queries Prefect for deployments matching ALL four tags:

- `application/{application}`
- `hook/{hook.value}`
- `mode/{mode}`
- `version/{version}`

Returns the first matching deployment's UUID, or `None`.

## Execution

Hooks are called via `arun_deployment()` from Prefect, which triggers the registered workflow in the user work pool (Kubernetes):

```python
from prefect.deployments.flow_runs import arun_deployment

# In orchestration flows:
if prehook:
    await arun_deployment(
        flow_run_name=f"Run {context.app.name} pre-hook",
        name=prehook,                          # UUID of Prefect deployment
        parameters={"context": context},        # GlobalContext passed to user function
    )
```

## Action Primitives

Located in `actions/primitives.py`. These are Prefect `@task` functions that driver actions can import and call:

| Primitive | Signature | Description |
|-----------|-----------|-------------|
| `stop_components` | `(components: list[str], context: GlobalContext)` | Calls internal GraphQL to disable components |
| `start_components` | `(components: list[str], context: GlobalContext)` | Calls internal GraphQL to enable components |
| `execute_commands` | `(commands: list[str], image: str, context: GlobalContext, env_from_component: str \| None = None, labels_from_component: str \| None = None)` | Runs commands as a Kubernetes Job. `image` is required; the optional `*_from_component` arguments copy env vars and labels from a named component pod. |

Drivers import these from `styrmin_backend.actions`:

```python
from styrmin_backend.actions import stop_components, start_components, execute_commands, GlobalContext
```

## Work Pools

| Pool | Name | Worker Type | Purpose |
|------|------|-------------|---------|
| Internal | `styrmin-work-pool` | `process` | System workflows (orchestration, apply_state) |
| User | `user-work-pool` | Kubernetes | User-defined actions from drivers |

User actions run in the Kubernetes work pool, meaning they execute as K8s Jobs with the driver's specified image.

## Setup Hooks - IMPLEMENTED

The setup hook lifecycle is fully implemented for instance creation. Under the CRD-based flow ([ADR-008](../adr/adr-008-prefect-crd-intent-declaration.md)), Prefect no longer creates the HelmRelease directly — the kopf operator does, by reconciling the `StyrminDeployment` CRD that the flow writes. Driver pre/post hooks remain Prefect-managed.

### Remediation (`InstanceCreationStrategy`)

When a new deployment is created (no current instance):

1. Diff type: `InstanceCreation`
2. Strategy: `InstanceCreationStrategy`
3. Looks up:
   - `PrefectAction.CREATE_INSTANCE` flow
   - Setup pre-hook: `get_user_action_deployment_id(hook=SETUP, mode="pre")`
   - Setup post-hook: `get_user_action_deployment_id(hook=SETUP, mode="post")`
4. Reads the parent deployment's `internal` flag (e.g. for the ingress controller).
5. Returns `Remediation(type=CREATE_INSTANCE, parameters={instance, prehook, posthook, internal})`. There is no separate "core HelmRelease hook" lookup — the CRD flow does not need one.

### Orchestration (`create_instance_crd` flow)

The catalogue registers the CRD variant. Execution order:

```text
1. Run pre-hook (if exists)             ──> User's pre_setup function
2. Build StyrminDeployment CRD body from the resolved context
3. Apply the deployment namespace with labels
4. Upsert the StyrminDeployment CRD     ──> operator reconciles
                                            NetworkPolicies, Secrets,
                                            HelmRelease, Services,
                                            Middlewares in ordered phases
5. Apply cross-namespace service aliases (if any)
6. Run post-hook (if exists)            ──> User's post_setup function
```

Pre/post hooks are user-defined and optional. Utilities (ingress, service-discovery) are part of the CRD spec and are reconciled by the operator, not orchestrated as separate Helm releases by Prefect.

## Upgrade Hooks - IMPLEMENTED

The upgrade hook lifecycle is fully implemented. Like setup, the CRD-based flow lets the operator reconcile resources; Prefect only runs the driver hooks and updates the CRD spec.

### Remediation (`InstanceUpdateStrategy`)

When an `InstanceUpdate` diff contains an `ApplicationVersionChange`, the strategy routes to upgrade:

1. Diff type: `InstanceUpdate` with `ApplicationVersionChange` entry
2. Strategy: `InstanceUpdateStrategy._handle_upgrade()`
3. Looks up:
   - Driver version and application from the NEW instance
   - Upgrade core hook: `get_user_action_deployment_id(hook=UPGRADE, mode="core")`
   - If no core hook found → **falls back to regular update** (no error)
   - If core hook found, also looks up (in parallel):
     - `PrefectAction.UPGRADE_INSTANCE` flow
     - Upgrade pre-hook: `get_user_action_deployment_id(hook=UPGRADE, mode="pre")`
     - Upgrade post-hook: `get_user_action_deployment_id(hook=UPGRADE, mode="post")`
4. Returns `Remediation(type=UPGRADE_INSTANCE, parameters={instance, upgrade_hook, target_version, prehook, posthook})`. The CRD flow does not need separate `update_flow` / `apply_utility_flow` parameters — those concerns now live on the operator side.

### Orchestration (`upgrade_instance_crd` flow)

The catalogue registers the CRD variant. Located in `agent/tasks/orchestration.py`:

```python
@flow(flow_run_name="Upgrade instance (CRD)")
async def upgrade_instance_crd(
    instance: Instance,
    upgrade_hook: UUID,           # Prefect deployment ID for driver's core upgrade action
    target_version: str,          # Application version being upgraded to
    prehook: UUID | None = None,  # Optional driver pre-upgrade hook
    posthook: UUID | None = None, # Optional driver post-upgrade hook
) -> None
```

Execution order:

```text
1. Build and upsert StyrminDeployment CRD body (the new spec)
2. Patch CRD status to displayState=Deploying / phase=Pending atomically
   with the spec change so a stale "Running" displayState cannot race
   the agent into reporting the new instance as already healthy.
3. Run pre-hook (if exists)              ──> User's pre-upgrade function
4. Run core upgrade hook                 ──> User's upgrade function
                                              (e.g. stop, migrate, start)
5. Apply cross-namespace service aliases (if any)
6. Run post-hook (if exists)             ──> User's post-upgrade function
```

The CRD spec is written *before* the hooks run because driver upgrade hooks frequently call back into the server (e.g. `stop_components`, `upgrade_deployment_version`), and each callback spawns a nested `update_instance_crd` flow. Writing the CRD up front lets those nested updates layer correctly; writing it at the end would stomp them with this flow's older instance.

The core hook for upgrade is a USER action (the driver's upgrade function). Pre/post hooks are also user-defined and optional.

### Fallback Behavior

If no upgrade core hook is defined for the application version, `_handle_upgrade` returns `None` and the strategy falls back to `_handle_update()`, which returns `Remediation(type=UPDATE_INSTANCE, parameters={instance})`. The catalogue maps this to `update_instance_crd`, which simply rewrites the CRD spec and lets the operator reconcile the new HelmRelease. Drivers without upgrade actions still work; version changes just trigger a CRD-driven Helm release update.

## Key Files

| File | Purpose |
|------|---------|
| [services/driver/models/resources/actions.py](backend/styrmin_backend/services/driver/models/resources/actions.py) | `HookKind`, `ActionDefinition` |
| [services/driver/models/resources/driver.py](backend/styrmin_backend/services/driver/models/resources/driver.py) | `Specification` (embeds `actions: list[ActionDefinition]`) |
| [services/driver/validators.py](backend/styrmin_backend/services/driver/validators.py) | `UserActionsValidator` (AST validation) |
| [services/user.py](backend/styrmin_backend/services/user.py) | `ActionsWorkflowBuilder` |
| [services/applications.py](backend/styrmin_backend/services/applications.py) | Action registration during driver loading |
| [workflows/manager.py](backend/styrmin_backend/workflows/manager.py) | `register_user_action`, `get_user_action_deployment_id` |
| [workflows/catalogue.py](backend/styrmin_backend/workflows/catalogue.py) | Workflow registry (UPGRADE_INSTANCE definition) |
| [actions/primitives.py](backend/styrmin_backend/actions/primitives.py) | `stop_components`, `start_components`, `execute_commands` |
| [agent/tasks/orchestration.py](backend/styrmin_backend/agent/tasks/orchestration.py) | `create_instance_crd`, `update_instance_crd`, `upgrade_instance_crd` flows |
| [services/reconciliation/remediation.py](backend/styrmin_backend/services/reconciliation/remediation.py) | `InstanceCreationStrategy`, `InstanceUpdateStrategy` |
