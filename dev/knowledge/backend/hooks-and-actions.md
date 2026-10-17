# Hooks and User Actions

## Overview

Application drivers can define **user actions** - custom Prefect workflows that execute driver-specific logic during deployment lifecycle events. Actions are organized into **hooks** with **modes** that determine when they run relative to the core operation.

```text
Driver directory (repository root, or a folder such as drivers/infrahub/)
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

When a driver is loaded via `load_application_driver_from_object()` in `services/applications.py` (step 3 runs only for loads from git; local loads register no actions):

```text
1. Parse driver.styrmin.yml ──> DriverSpec (with embedded actions)
2. Validate actions.py ──> UserActionsValidator
3. For each action in driver_spec.spec.actions:
   a. ActionsWorkflowBuilder.build_user_action_workflow_definition(action)
      ──> Creates a GitSourceWorkflowDefinition with:
          - source: driver's Git repository, pinned to source_commit_sha
          - module/function: from action.location (entrypoint actions.py:<function>)
          - image: from action.image (optional)
          - set_directory: the driver directory (GitSource.driver_directory), or None
   b. PrefectManager.register_user_action(
          workflow, application, version, hook, mode, fingerprint, driver_directory)
      ──> Saves deployment to Prefect with tags:
          - "application/{name}"
          - "version/{supported_versions}"
          - "hook/{hook.value}"
          - "mode/{mode}"
          - "fingerprint/{short fingerprint}"
          - "directory/{driver_directory}"  (driver directory versions only)
   c. Save Action to database via UnitOfWork
```

### Pull steps

A driver version loaded from the repository root has one pull step, `prefect.deployments.steps.git_clone`, which clones the repository at the recorded commit into `<repository name>-<short commit>` and leaves the working directory at the root of the clone.

A driver version loaded from a driver directory has a second pull step, `prefect.deployments.steps.set_working_directory`, with the relative path `<repository name>-<short commit>/<driver directory>` (`set_directory_pull_step` in `workflows/utils.py`). Prefect resolves the path against the folder that `git_clone` cloned into. That folder is not the image's working directory: `prefect flow-run execute`, the command of each action's Kubernetes Job, creates a temporary `prefect-flow-run-*` folder and changes into it before it runs the pull steps, so `git_clone` clones there. The entrypoint stays `actions.py:<function>`, so Prefect's script loader puts only the driver directory on `sys.path`: `actions.py` imports modules from the driver directory and not from other folders of the repository ([ADR-076](../../adr/0076-driver-actions-import-only-from-their-driver-directory.md)).

### Deployment names

Prefect replaces a deployment with the same flow and deployment name, and refuses `/` in deployment names. The name therefore carries the driver name, the short fingerprint and, for a driver version loaded from a driver directory, the first 7 hex characters of the SHA-256 of the driver directory (`driver_directory_digest` in `services/driver/driver_directory.py`):

| Driver version | Deployment name | Extra tag |
|----------------|-----------------|-----------|
| Loaded from the repository root | `User Action: setup (infrahub@0123456)` | none |
| Loaded from `drivers/infrahub` | `User Action: setup (infrahub@0123456 c8dc0c0)` | `directory/drivers/infrahub` |

Two driver versions loaded from different driver directories at one commit, also with the same driver name, keep separate deployments. Driver versions loaded from the repository root keep the names and tags they had before spec 028.

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
    fingerprint: str | None = None,       # short fingerprint of the driver version
    driver_directory: str | None = None,  # source_path of a git driver version
) -> UUID | None:
    """Query Prefect deployments by tag combination. Returns None if not found."""
```

Queries Prefect for deployments that carry all of these tags, newest first:

- `application/{application}`
- `hook/{hook.value}`
- `mode/{mode}`
- `version/{version}`
- `fingerprint/{fingerprint}`, when a fingerprint is given
- `directory/{driver_directory}`, when a driver directory is given

Without a driver directory (a driver version loaded from the repository root), the lookup drops every deployment that carries a `directory/` tag before it picks one, so a root driver version never runs the action of a driver directory version with the same driver name, version and commit. Prefect's tag filter cannot exclude a tag, so Styrmin filters the results.

The callers (`instantiate_application` in `services/applications.py` and the create and upgrade paths in `services/reconciliation/remediation.py`) pass `driver_directory_of(source_type=..., source_path=...)` from `services/driver/labels.py`: the `source_path` of a git driver version, and `None` for a local one.

Returns the first matching deployment's UUID, or `None`.

## Execution

Hooks are called via `run_driver_action_or_fail()` (`agent/tasks/utils.py`), which wraps Prefect's `arun_deployment()`, triggers the registered workflow in the user work pool (Kubernetes), raises when the flow run fails, and passes this Job's `STYRMIN_TOKEN` (ADR-059) and `STYRMIN_TASK_ID` to the action's Job. Each run of a hook mode is recorded as one hook step of the task, and the flow passes that step's id as `step_id`, which reaches the action's Job as `STYRMIN_STEP_ID`:

```python
from styrmin_backend.agent.tasks.utils import run_driver_action_or_fail

# In orchestration flows:
if prehook:
    async with reporter.step(*steps.SETUP_PRE_HOOK) as step:
        await run_driver_action_or_fail(
            step_id=step.id,                       # The hook step; None when not recorded
            flow_run_name=f"Run {context.app.name} pre-hook",
            name=prehook,                          # UUID of Prefect deployment
            parameters={"context": context},        # GlobalContext passed to user function
        )
```

The hook step succeeds when the action's flow run completes, and fails with the formatted exception when `run_driver_action_or_fail` raises. The hook step keys are `hook:setup:pre`, `hook:setup:post`, `hook:upgrade:pre`, `hook:upgrade:core` and `hook:upgrade:post`; see [orchestration-flows.md](orchestration-flows.md#remediation-flow-steps) for the full list of steps a remediation flow records.

## Action Primitives

Located in `actions/primitives.py`. These are Prefect `@task` functions that driver actions can import and call:

| Primitive | Signature | Description |
|-----------|-----------|-------------|
| `stop_components` | `(components: list[str], context: GlobalContext)` | Calls internal GraphQL to disable components |
| `start_components` | `(components: list[str], context: GlobalContext)` | Calls internal GraphQL to enable components |
| `execute_commands` | `(commands: list[str], image: str, context: GlobalContext, env_from_component: str \| None = None, labels_from_component: str \| None = None)` | Runs commands as a Kubernetes Job. `image` is required; the optional `*_from_component` arguments copy env vars and labels from a named component pod. `env_from_component` reads the component container (else `containers[0]`), then sets the env vars that apply in the action's context on top (#431). |
| `get_component_images` | `(component: str, context: GlobalContext) -> list[str]` | Images of every container in the component's `Deployment`/`StatefulSet` pod template (init containers excluded). When the component declares a component container present in the template, its image is element 0 (spec 018); the others keep pod-template order. When an image override applies in the action's context, element 0 is that override with `{{ app.version }}` substituted (#431). |
| `get_component_labels` | `(component: str, context: GlobalContext) -> dict[str, str]` | Pod template labels of the component's workload |
| `upgrade_deployment_version` | `(target_version: str, context: GlobalContext)` | Calls `updateDeploymentVersion` without a driver version and waits for the nested task, which completes when the CR is written, not when the rollout is done. On each call the server binds the latest driver version that supports `target_version`. When the deployment already has `target_version` and is already bound to that driver version, the server finds no change, starts no task and returns `null`, and the primitive returns without waiting. The bundled drivers' `upgrade` actions call it with the hook's `target_version`, which the upgrade already set, so there it starts a task only when the deployment is bound to a driver version other than that latest one, for example one the upgrade chose with `driverVersionId` |

Drivers import these from `styrmin_backend.actions`:

```python
from styrmin_backend.actions import stop_components, start_components, execute_commands, GlobalContext
```

### How the API primitives authenticate

`stop_components`, `start_components` and `upgrade_deployment_version` call GraphQL mutations
that require `READ_WRITE`, then poll `Query.task`. They send `Authorization: Bearer` with the
token in `STYRMIN_TOKEN`. `apply_state` creates that token for the built-in `styrmin-actions` user
once per reconcile, passes it to the remediation flow's Job, which passes it to each action's Job
(`run_driver_action_or_fail`), and deletes the session when the reconcile ends. Without the
variable, the calls fail with `Authentication is required`. See
[ADR-059](../../adr/0059-driver-action-api-tokens.md).

### Tasks started by a hook step

The same three primitives send `startedByStepId` with the value of `STYRMIN_STEP_ID` (or `null`
when it is unset or not a UUID) on `stopComponents`, `startComponents` and
`updateDeploymentVersion`. The server stores it in `Task.started_by_step_id`, so the task that ran
the hook lists the new task in `Task.startedTasks`, the new task links back through
`Task.startedBy`, and the hook's task result includes the started task's steps (see
[ADR-060](../../adr/0060-steps-and-derived-task-result.md)). The server accepts `startedByStepId`
only from the `styrmin-actions` user, so a person who sends it, admins included, gets `FORBIDDEN`.
The step must be a step of a task of the deployment that the mutation changes. The server checks
the step before it changes anything, also when `updateDeploymentVersion` is a no-op: a step id that
names no step fails the mutation with `StepNotFoundError`, and a step of another deployment's task,
of a backup or of a restore fails it with `InvalidStartingStepError`. The primitives always target
the deployment of the action's context, which is the deployment of the hook's task, so these rules
do not reject their calls. An action that calls the API through the SDK instead of these
primitives sends no `startedByStepId`, so the tasks it creates are not linked to the hook step.

## Command output of a failed Job

`execute_commands` runs its commands as a Kubernetes Job (container `user-job`) through `run_job`
in `agent/service/kubernetes/primitives.py`. When the Job fails, `run_job` reads the end of the
output before it raises (`read_job_output_tail` in `agent/service/kubernetes/job_logs.py`):

- It lists the Job's pods by the label `batch.kubernetes.io/job-name`, then by the older label
  `job-name`, and reads a failed pod before a retry that has not ended, then the newest one.
- It asks the Kubernetes log API for the last 201 lines and at most 65,537 bytes, and keeps at
  most the last 200 lines and 64 KiB. Getting more than that means earlier output was cut, and
  `truncated` is set.
- It raises `JobFailedError(message, output=..., truncated=...)`, which replaced the
  `RuntimeError` that `run_job` raised before. When the output cannot be read (no pod, or a
  Kubernetes API error), `output` is `None` and the message ends with "The output could not be
  read: <reason>".

`execute_commands` catches `JobFailedError`, records the output on the hook step named by
`STYRMIN_STEP_ID` with the `OUTPUT` event of `recordStep`, and re-raises. The hook step then fails
with the error when the action's flow run fails. Without `STYRMIN_STEP_ID` or the action token, the
output is not recorded. `run_kubernetes_job` (used by the `run_job_command` flow) reads the output
of the manifest's first container the same way, and `run_job_command` records it on its `command`
step.

The server stores the output on the step (`step.output`, `step.output_truncated`) and cuts it
again to the last 200 lines and 64 KiB. Every signed-in user can read it through `Step.output`,
`READ_ONLY` users included, so commands that actions run must not print secrets.

### Reading the component image in an upgrade action

The in-repo `upgrade` actions (`driver/examples/simple-app`, `infrahub`, `infrahub-enterprise`)
build their migration Job's image from `get_component_images(...)[0]` and the target version:
they drop any `@digest`, then strip the tag only when the part after the last `:` contains no
`/`, so a registry port (`registry:5000/app`) survives. `upgrade_deployment_version` returns before
the rollout, so the pod template read is usually the pre-upgrade one; rebuilding the tag is what
moves the Job to the target version. With a `{{ app.version }}` image override the Job runs the
override's repository at the target version; with a pinned override it does the same while the
component stays pinned (the upgrade dialog and `styrminctl apply` warn about it). Taking
`images[0]` replaced a substring match on the image name, which missed overrides. See
[ADR-058](../../adr/0058-image-overrides-and-component-container-guard.md) §6.

### Overrides set with the version change

Every action receives the context of the instance it runs for: the upgrade remediation passes
the new instance (`diff.instance`) to the pre, core and post hooks. Since ADR-065, one
`updateDeploymentVersion` call can write an image override or env vars with the version, and
the upgrade action then starts while the workload still runs the previous instance. The
primitives therefore take the component-container overrides from the context, through
`applicable_overrides` in `services/component_container/overrides.py`, which the patch builder
also uses (#431, ADR-069):

- `get_component_images` returns the applicable image override as element 0, with
  `{{ app.version }}` set to `context.app.version`. The other images still come from the pod
  template.
- `execute_commands(env_from_component=...)` reads env and envFrom from the component
  container (else `containers[0]`), then sets the applicable env vars on top: a same-name entry
  is replaced by a literal `value`, and a new name is appended.

An override applies when the component declares a component container and the override is not
orphaned (`override_applies`), as for the post-render patches. The primitives use only the `env`
and `image` of the result: `command` and `args` overrides do not reach action Jobs. Because
`execute_commands(env_from_component=...)` calls `applicable_overrides`, it also resolves the
image override, and raises `InvalidImageReferenceError` when the reference is invalid at the
context's application version. Such a reference is already rejected on write and before an
application version change (ADR-058 §5). An env var removed in the same call is still in the
workload's env and reaches the Job, because the action cannot tell an injected env var from a
chart one. A component whose workload does not exist yet still fails the lookup.

## Work Pools

| Pool | Name | Worker Type | Purpose |
|------|------|-------------|---------|
| Internal | `styrmin-work-pool` | `process` | System workflows (orchestration, apply_state) |
| User | `user-work-pool` | Kubernetes | User-defined actions from drivers |

User actions run in the Kubernetes work pool, meaning they execute as K8s Jobs with the driver's specified image.

## Setup Hooks - IMPLEMENTED

The setup hook lifecycle is fully implemented for instance creation. Under the CRD-based flow ([ADR-006](../adr/0006-prefect-crd-intent-declaration.md)), Prefect no longer creates the HelmRelease directly — the kopf operator does, by reconciling the `StyrminDeployment` CRD that the flow writes. Driver pre/post hooks remain Prefect-managed.

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
5. Apply cross-namespace service aliases and delete stale ones (if any)
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
5. Apply cross-namespace service aliases and delete stale ones (if any)
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
| [workflows/utils.py](../../../backend/styrmin_backend/workflows/utils.py) | `set_directory_pull_step` (relative `set_working_directory` path) |
| [services/driver/driver_directory.py](../../../backend/styrmin_backend/services/driver/driver_directory.py) | `normalise_driver_directory`, `resolve_inside`, `driver_directory_digest` |
| [services/driver/labels.py](../../../backend/styrmin_backend/services/driver/labels.py) | `driver_directory_of`: the driver directory a lookup passes |
| [workflows/catalogue.py](backend/styrmin_backend/workflows/catalogue.py) | Workflow registry (UPGRADE_INSTANCE definition) |
| [actions/primitives.py](backend/styrmin_backend/actions/primitives.py) | `stop_components`, `start_components`, `execute_commands`, `get_component_images`, `get_component_labels`, `upgrade_deployment_version` |
| [agent/service/kubernetes/primitives.py](backend/styrmin_backend/agent/service/kubernetes/primitives.py) | Kubernetes side of `get_component_images` (component container image first) and `get_component_env` (component container env); `run_job` and `run_kubernetes_job` raise `JobFailedError` with the end of the output |
| [services/component_container/overrides.py](backend/styrmin_backend/services/component_container/overrides.py) | `override_applies`, `applicable_overrides` (`ApplicableOverrides`): the env vars, image, `command` and `args` that apply in a context, shared by the patch builder and the action primitives |
| [agent/service/kubernetes/job_logs.py](backend/styrmin_backend/agent/service/kubernetes/job_logs.py) | `read_job_output_tail`: the end of a failed Job's output |
| [agent/steps/reporter.py](backend/styrmin_backend/agent/steps/reporter.py) | `StepReporter`: hook-step output and steps recorded through `recordStep` |
| [agent/tasks/utils.py](backend/styrmin_backend/agent/tasks/utils.py) | `run_driver_action_or_fail` (`STYRMIN_TOKEN`, `STYRMIN_TASK_ID`, `STYRMIN_STEP_ID`) |
| [driver/examples/simple-app/actions.py](driver/examples/simple-app/actions.py) | Reference `upgrade` action (`images[0]`, digest- and port-safe tag strip) |
| [agent/tasks/orchestration.py](backend/styrmin_backend/agent/tasks/orchestration.py) | `create_instance_crd`, `update_instance_crd`, `upgrade_instance_crd` flows |
| [services/reconciliation/remediation.py](backend/styrmin_backend/services/reconciliation/remediation.py) | `InstanceCreationStrategy`, `InstanceUpdateStrategy` |
