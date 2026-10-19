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
    image: str | None = None   # Job variable "image"; no effect today, see "Work Pools"
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

When a driver is loaded via `load_application_driver_from_object()` in `services/applications.py`, `ensure_action_registrations(driver_object, prefect_manager)` registers the actions of driver versions loaded from git and from a local directory (spec 029). It runs on both paths of the load: when the identity lookup finds a stored driver version, before the load returns it; and for a new driver version, after the service and component validations and just before the insert, so a refused load leaves no deployment in Prefect.

```text
1. Parse driver.styrmin.yml ──> DriverSpec (with embedded actions)
2. Validate actions.py ──> UserActionsValidator
3. Look up the identity tuple (get_by_identity):
   - found:     ensure_action_registrations, then return the stored version
   - not found: validate services and components, ensure_action_registrations,
                then insert the version and its Action rows
ensure_action_registrations(driver_object, prefect_manager):
   a. No declared action ──> return 0
   b. LocalSource whose path contains "{" or "}" ──> raise DriverLoadingError
   c. key = ActionRegistrationKey.key_for_driver_object(driver_object)
      (driver name, supported versions, short fingerprint,
       directory = action_directory_of(source type, path or driver directory))
   d. For each declared (hook, mode) pair:
      PrefectManager.get_user_action_deployment_id(..., key)
   e. Keep the actions of the pairs that the lookup does not find;
      none ──> return 0 (no Prefect write)
   f. GitSource ──> PrefectManager.register_token(namespace="user", token)
   g. For each kept action:
      ActionsWorkflowBuilder(source, commit_sha, content_hash)
        .build_user_action_workflow_definition(action)
        ──> GitSource:   GitSourceWorkflowDefinition
                         - repository pinned to source_commit_sha
                         - set_directory: GitSource.driver_directory, or None
            LocalSource: LocalDriverActionWorkflowDefinition
                         - directory: LocalSource.path
                         - content_hash: the full provenance fingerprint
                         - spec_file, values_template, actions_file:
                           the server's STYRMIN_DRIVER_* file names
        (both: entrypoint actions.py:<function> from action.location,
         image from action.image)
      PrefectManager.register_user_action(
          workflow, application, version, hook, mode, fingerprint,
          driver_directory=key.directory)
      ──> Saves deployment to Prefect with tags:
          - "application/{name}"
          - "version/{supported_versions}"
          - "hook/{hook.value}"
          - "mode/{mode}"
          - "fingerprint/{short fingerprint}"
          - "directory/{driver_directory}"  (driver directory and local versions)
```

`ensure_action_registrations` decides that a flow is missing with the lookup that hooks use, so a repeated load registers only what hooks cannot resolve and never replaces a deployment that hooks already find (FR-006). A local path with `{` or `}` is refused only for a driver that declares actions, because only such a driver gets the check pull step whose inputs Prefect templates (see [Pull steps](#pull-steps)). `ActionsWorkflowBuilder` refuses a `LocalSource` without a `content_hash` with `DriverLoadingError`, and keeps the path with the checked `content_hash` (`CheckedLocalSource`). `LocalDriverActionWorkflowDefinition` also refuses, with a pydantic `ValidationError`, a `directory` that contains `{` or `}` and an empty `content_hash`, so no other caller can build such a pull step; the `DriverLoadingError` of `ensure_action_registrations` comes first and gives the message for the user.

### Pull steps

A driver version loaded from the repository root has one pull step, `prefect.deployments.steps.git_clone`, which clones the repository at the recorded commit into `<repository name>-<short commit>` and leaves the working directory at the root of the clone.

A driver version loaded from a driver directory has a second pull step, `prefect.deployments.steps.set_working_directory`, with the relative path `<repository name>-<short commit>/<driver directory>` (`set_directory_pull_step` in `workflows/utils.py`). Prefect resolves the path against the folder that `git_clone` cloned into. That folder is not the agent's working directory: the agent's Prefect `ProcessWorker` creates a temporary folder for each flow run and runs the pull steps in it, so `git_clone` clones there (see [Work Pools](#work-pools)). The entrypoint stays `actions.py:<function>`, so Prefect's script loader puts only the driver directory on `sys.path`: `actions.py` imports modules from the driver directory and not from other folders of the repository ([ADR-079](../../adr/0079-driver-actions-import-only-from-their-driver-directory.md)). The loader puts the folder of the resolved script on `sys.path`, so the git load refuses an `actions.py`, `driver.styrmin.yml` or `values.j2.yml` that is a symlink to a path outside the driver directory (`GitDriverProvider._check_driver_directory` in `services/driver/provider.py`).

The pull steps need Prefect 3.6.9 or later: `git_clone` accepts `clone_directory_name` from that release on. The agent runs every action as a process in its own pod, so the agent's Prefect runs the pull steps, and the image that the agent runs needs Prefect 3.6.9 or later. An action's `image` has no effect today (see [Work Pools](#work-pools)). The driver directory is refused when it contains `{` or `}`, because Prefect fills in `{{ ... }}` templates (blocks, variables, environment variables) in the `set_working_directory` step before it runs it.

#### Pull step of a local driver version: the check of the driver files

A driver version loaded from a local directory has one pull step, `styrmin_backend.workflows.local_driver.check_local_driver` (`CHECK_LOCAL_DRIVER_STEP`), added by `LocalDriverActionWorkflowDefinition.to_deployment()` in `workflows/models.py`. Prefect imports a pull step by its fully qualified name (`run_step`), so the step is a plain function. Its inputs are the driver version's path (`directory`), its full `content_hash`, and the three driver file names of the server settings when the driver was loaded (`spec_file`, `values_template`, `actions_file`), because the agent does not carry the `STYRMIN_DRIVER_*` settings. The entrypoint is `actions.py:<function>`, as for git, so Prefect's script loader puts the driver version's path on `sys.path`.

`check_local_driver_files` does the check, and `check_local_driver` wraps it:

- When the path is not a folder, or the specification file or the actions file is missing in it, it raises `DriverFilesNotFoundError` with the missing path or file names. A missing values template is hashed as empty bytes, as the loader does.
- Otherwise it computes `compute_driver_directory_fingerprint(..., include_actions=True)` (`services/driver/hash.py`), the function the local loader also calls. When the result differs from `content_hash`, it raises `DriverFingerprintMismatchError` with both fingerprints; the message shows their first 7 characters.
- A file removed between that check and its read raises `DriverFilesNotFoundError` too. Any other `OSError` of the read, such as a `PermissionError` on `actions.py` or a values template path that is a directory, is raised as it is.
- On success, `check_local_driver` logs one `INFO` line in the flow run with the path and the short fingerprint and returns `{"directory": <path>}`. Prefect then changes into the path and imports the entrypoint from it.
- On failure, `check_local_driver` logs the error at `ERROR` in the flow run (`flow_run_logger` with `PREFECT__FLOW_RUN_ID`) before it raises: the text of a typed error, or `Could not check the driver files at <path>: <exception type>: <message>` for any other exception. Prefect 3.8.6 runs pull steps in a workspace supervisor that prints the traceback of a failed step and logs nothing in the flow run, so this log is how the error reaches the hook step (see [Errors of a crashed action on the hook step](#errors-of-a-crashed-action-on-the-hook-step)).

The step never imports `actions.py`, so changed or missing files are never run. `LocalDriverActionWorkflowDefinition.get_function()` runs the same check before it imports the function. `workflows/local_driver.py` imports only Prefect and the driver modules `hash` and `exceptions`, so it imports without server settings or a database.

Only on the error paths, `_action_image()` reads from the Prefect API the image that the errors name: the flow run in `PREFECT__FLOW_RUN_ID`, then its deployment's `job_variables["image"]`, otherwise the default `image` of its work pool's base job template. `describe_action_image(image, work_pool)` in `services/driver/exceptions.py` writes `the image <image>`, `the default image of the work pool <work pool>` when only the work pool was read, or `the image of this action's Job` when neither was. A failed read is logged as a warning and never replaces the error. The default image of `user-work-pool` is `STYRMIN_K8S_WORKER_IMAGE`, which the Helm chart sets to the server's image; in a standard install, that is also the image the agent runs. The texts of the errors name "the action's image" although the action runs in the agent pod; the maintainer kept these texts on 2026-10-19 ([ADR-081](../../adr/0081-local-driver-actions-check-their-files-at-the-driver-path.md)).

### Deployment names

Prefect replaces a deployment with the same flow and deployment name, and refuses `/` in deployment names. The name therefore carries the driver name, the short fingerprint and, for a driver version loaded from a driver directory or from a local directory, the first 12 hex characters of the SHA-256 of the driver directory or path (`driver_directory_digest` in `services/driver/driver_directory.py`):

| Driver version | Deployment name | Extra tag |
|----------------|-----------------|-----------|
| Loaded from the repository root | `User Action: setup (infrahub@0123456)` | none |
| Loaded from `drivers/infrahub` | `User Action: setup (infrahub@0123456 c8dc0c0d9f46)` | `directory/drivers/infrahub` |
| Loaded from the local directory `/styrmin/drivers/infrahub` | `User Action: setup (infrahub@0123456 a93c0a65fecd)` | `directory//styrmin/drivers/infrahub` |

Two driver versions loaded from different driver directories at one commit, also with the same driver name, keep separate deployments. Two local driver versions loaded from two paths keep separate deployments too, also when their files, and so their fingerprints, are the same: each runs the `actions.py` at its own path. Driver versions loaded from the repository root keep the names and tags they had before spec 028.

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
    fingerprint: str | None = None,  # short fingerprint of the driver version
    *,
    driver_directory: str | None,    # no default: action_directory_of(source_type, source_path)
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

The two callers build the arguments with `ActionRegistrationKey` (`services/driver/hooks.py`), so registration and lookup use the same key: hook resolution (`key_for_version`, from a stored driver version) and `ensure_action_registrations` (`key_for_driver_object`, from a loaded driver). The key passes `driver_directory=action_directory_of(source_type=..., source_path=...)` from `services/driver/labels.py`: the `source_path` of a git driver version (its driver directory, or `None` for the repository root) and of a local driver version (the path as given on the server), and `None` for any other source type. A git value never starts with `/`, because `normalise_driver_directory` refuses a leading `/`. A local value starts with `/` only when the path given on the server is absolute: the CLI (`styrminctl drivers load-local-version`), the SDK, the GraphQL mutation `loadLocalApplicationDriverVersion` and `LocalDriverProvider` pass the path on as given and do not refuse a relative one. A local driver version loaded from a relative path, such as `drivers/my-app`, therefore gets the same registration key as a git driver version of the same driver and supported versions loaded from the driver directory `drivers/my-app` when their short fingerprints are equal; [`specs/029-local-driver-actions/follow-ups.md`](../../../specs/029-local-driver-actions/follow-ups.md#give-a-local-driver-version-loaded-from-a-relative-path-its-own-action-registrations) lists this, and it is not yet opened as an issue. `driver_directory_of` in the same module keeps its meaning for the GraphQL field `driverDirectory` only, which is null for a local driver version.

Returns the first matching deployment's UUID, or `None`.

## Hook Resolution

`services/driver/hooks.py` decides what "declared but not registered" means, for the remediations, the request check of `update_deployment_version` and repeated loads (spec 029, FR-005):

| Function | Returns |
|----------|---------|
| `resolve_hook_flow(driver_version, application_name, hook, mode, *, uow, prefect_manager)` | `None` when the driver version declares no action for the hook and mode, without a Prefect lookup; the registered flow otherwise |
| `resolve_setup_hooks(...)` | `(pre, post)` for the `setup` hook |
| `resolve_upgrade_hooks(...)` | `None` when the driver version declares no `upgrade`/`core` action, without looking up `pre` or `post`; otherwise `UpgradeHookFlows(core, pre, post)` |

The declared actions are the driver version's `Action` rows, read with `uow.actions.list_by_driver_version(driver_version_id)` in the caller's transaction. When a hook and mode with a declared action has no registered flow, the functions raise `ActionNotRegisteredError` (`services/driver/exceptions.py`) for the first such pair in the order `pre`, `post` for setup and `core`, `pre`, `post` for upgrade, so the error names the same hook step on every run. The error carries `hook` and `mode` as attributes and names:

- the driver name and the driver version label (`format_driver_version_label`, such as `1.0.0@a1b2c3d`);
- every declared action of the pair;
- the hook and the mode;
- the command that loads the driver again (`load_command_for`): `styrminctl drivers load-local-version <path>` for a local driver version, `styrminctl drivers load-version <repository> <branch>` for a git one, followed by `--driver-directory <driver directory>` when it has one. The repository URL is shown without its user info.

The message tells the operator to load the driver again, to request the change again, and to delete and create again a deployment whose creation failed.

Callers:

- `InstanceCreationStrategy.execute` (`services/reconciliation/remediation.py`) calls `resolve_setup_hooks`.
- `InstanceUpdateStrategy._handle_upgrade` calls `resolve_upgrade_hooks`. `None` keeps the fall-back to `_handle_update`; `ActionNotRegisteredError` propagates, so an upgrade whose target declares an `upgrade`/`core` action never falls back to an update.
- `update_deployment_version` calls `resolve_upgrade_hooks` for its request check (see [Request check before an upgrade](#request-check-before-an-upgrade)).

`instantiate_application`, which had no caller other than its unit tests, was deleted with spec 029.

### Recording a missing registration on the hook step

`apply_state` (`agent/tasks/orchestration.py`) plans the remediation inside the `plan` step. When planning raises `ActionNotRegisteredError`, `apply_state` ends the `plan` step without an error, opens the step of the error's hook and mode (`steps.hook_step(exc.hook, exc.mode)`, for example `hook:setup:pre`), ends it with `format_exception(exc)`, and re-raises. The flow fails, and its callback sets the task, the deployment and the instance to failed, as for any failed flow. Any other exception still fails the `plan` step. This covers a registration that disappears between the request and the plan.

### Request check before an upgrade

`update_deployment_version` (`services/deployment.py`) checks the upgrade hook before the first write, after the request's validations and before `_ensure_ingress_controller`. The check runs when the deployment has an active instance whose `application_version` differs from the target version, which is when the flow takes the upgrade path (`ApplicationVersionChange`). It calls `resolve_upgrade_hooks` for the target driver version. On `ActionNotRegisteredError`, `_fail_upgrade_of_unregistered_action`:

1. leaves the deployment unchanged: its version, driver binding, status and active instance;
2. saves a task of type `upgrade_instance` with status `failed`, no flow run, no instance, the request's `started_by_step_id`, and the error text as its message;
3. records the hook step of the error's hook and mode as failed with `format_exception(exc)`;
4. commits and returns the task.

Because the deployment keeps its active instance, the same request is not a no-op (`_update_is_noop`) once the driver has been loaded again, and starts a new task (FR-007). A change of driver version at the same application version runs no check, because the flow runs the update path, which runs no hook.

## Execution

Hooks are called via `run_driver_action_or_fail()` (`agent/tasks/utils.py`), which wraps Prefect's `arun_deployment()`, triggers the registered workflow in the user work pool, raises when the flow run fails or crashes, and passes the calling flow run's `STYRMIN_TOKEN` (ADR-059) and `STYRMIN_TASK_ID` to the action's flow run as job variables. The agent runs that flow run as a process in the agent pod (see [Work Pools](#work-pools)). Each run of a hook mode is recorded as one hook step of the task, and the flow passes that step's id as `step_id`, which reaches the action as `STYRMIN_STEP_ID`:

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

The hook step succeeds when the action's flow run completes, and fails with the formatted exception when `run_driver_action_or_fail` raises. A hook step can also fail before any action runs, when a declared action has no registered flow (see [Hook Resolution](#hook-resolution)). The hook step keys are `hook:setup:pre`, `hook:setup:post`, `hook:upgrade:pre`, `hook:upgrade:core` and `hook:upgrade:post`; see [orchestration-flows.md](orchestration-flows.md#remediation-flow-steps) for the full list of steps a remediation flow records.

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
once per reconcile, passes it to the remediation flow run, which passes it to each action's flow run
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

## The Job of `execute_commands`

`execute_commands` runs its commands as a Kubernetes Job (container `user-job`) through `run_job`
in `agent/service/kubernetes/primitives.py`. The Job is named `<release reference>-job`, in the
deployment's namespace, so every call on one deployment uses the same name. The Job has no
`ttlSecondsAfterFinished` and no owner, so it stays in the cluster after it ends, and an operator
can read it and its pod's output until the next call.

Before it creates the Job, `run_job` deletes the Job of that name that an earlier call left,
whether it completed, failed or is still running (#372):

- It reads the Job, then deletes it with the `Foreground` propagation policy and a `uid`
  precondition. Kubernetes removes the Job only after its pods, and the precondition keeps the
  delete from removing a Job that another writer created after the read.
- It reads the Job every second until the read answers 404 or finds a Job with another `uid`. When
  the Job is still there after 120 seconds (`JOB_DELETION_TIMEOUT_SECONDS`), it raises
  `JobNotDeletedError`, with the `kubectl` command that lists the Job's pods.
- It then creates the new Job. When the create answers 409, because a Job of the same name was
  created after the delete, it raises `JobAlreadyExistsError`. Before #372 the 409 raised
  `CustomResourceNotFound`, and every later call on the deployment failed until someone deleted
  the Job by hand.

Because the earlier Job's pods are gone before the new Job starts, the output reader below reads
only pods of the new Job.

## Command output of a failed Job

When the Job of `execute_commands` fails, `run_job` reads the end of the output before it raises
(`read_job_output_tail` in `agent/service/kubernetes/job_logs.py`):

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

## Errors of a crashed action on the hook step

A flow run crashes when its process exits before the flow ends normally, for example when the
check pull step of a local driver version raises. Prefect's state message then holds only the exit
status, such as `Process exited with status code: 1.`. For a crashed flow run,
`run_deployment_or_fail` (`agent/tasks/utils.py`) reads the first log of level `ERROR` or higher
of that flow run (`_first_error_log`: `read_logs` with a `LogFilter` on the flow run id and the
level, sorted by timestamp, limit 1), cuts it to 4,000 characters (`FIRST_ERROR_LOG_MAX_LENGTH`),
and raises `RuntimeError("Deployment flow run <id> crashed: <first error log> (<state message>)")`.
When the flow run has no such log, or the logs cannot be read, it logs a warning and raises with the
state message alone. A failed flow run (not crashed) keeps `Deployment flow run <id> failed:
<state message>`.

`StepReporter.step` records the formatted exception on the hook step, so the hook step's error
holds the first `ERROR` log of the action's flow run. Every signed-in user who can read the task
can read the step's errors, as for the command output above, so actions must not write secrets to
their logs.

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

| Pool | Name | Pool type | Polled by | Purpose |
|------|------|-----------|-----------|---------|
| Internal | `styrmin-work-pool` | `process` | `prefect worker start --pool styrmin-work-pool` in the task-worker | System workflows (orchestration, apply_state) |
| User | `user-work-pool` | `kubernetes` (`STYRMIN_WORKFLOW_DEFAULT_WORKER_TYPE`), with a Kubernetes Job base template | A Prefect `ProcessWorker` in the agent (`styrmin agent start --work-pool user-work-pool`, `entrypoint/combined.py`) | User-defined actions from drivers, and the other `USER` workflows |

The agent polls `user-work-pool` with a `ProcessWorker`, so every user action runs as a process in the agent pod, in a temporary folder that the worker creates for the flow run. No Kubernetes Job is created for an action. As a result:

- An action's `image` (the deployment's `image` job variable) has no effect today, for driver versions loaded from git and from a local directory. [`specs/029-local-driver-actions/follow-ups.md`](../../../specs/029-local-driver-actions/follow-ups.md#decide-what-the-image-of-an-action-does) lists this, and it is not yet opened as an issue.
- The actions of a local driver version read the driver from the agent pod's file system, at the same path as the server. The agent pod must hold the driver there; in a standard install, the server and the agent run the same Styrmin image, which holds the bundled drivers at `/styrmin/drivers/<name>`.
- The image that the errors of the local driver check name is the action's `image` when it sets one, otherwise the default image of `user-work-pool` (see [Pull step of a local driver version](#pull-step-of-a-local-driver-version-the-check-of-the-driver-files)).

The base job template of `user-work-pool` still holds a Kubernetes Job manifest, with the default image from `STYRMIN_K8S_WORKER_IMAGE` and the service account from the server settings (`workflows/catalogue.py`). The `ProcessWorker` does not use the Job manifest or the `image` of that template; it passes the `env` of the template and of the flow run's job variables to the action's process.

## Setup Hooks - IMPLEMENTED

The setup hook lifecycle is fully implemented for instance creation. Under the CRD-based flow ([ADR-006](../adr/0006-prefect-crd-intent-declaration.md)), Prefect no longer creates the HelmRelease directly — the kopf operator does, by reconciling the `StyrminDeployment` CRD that the flow writes. Driver pre/post hooks remain Prefect-managed.

### Remediation (`InstanceCreationStrategy`)

When a new deployment is created (no current instance):

1. Diff type: `InstanceCreation`
2. Strategy: `InstanceCreationStrategy`
3. Looks up:
   - `PrefectAction.CREATE_INSTANCE` flow
   - Setup pre-hook and post-hook: `resolve_setup_hooks(...)`. A mode without a declared action gives `None`; a declared action without a registered flow raises `ActionNotRegisteredError` (see [Hook Resolution](#hook-resolution))
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
   - Upgrade hooks: `resolve_upgrade_hooks(...)`
   - If the new driver version declares no `upgrade`/`core` action → **falls back to regular update** (no error)
   - If it declares one, `resolve_upgrade_hooks` resolves `core`, `pre` and `post`, and raises `ActionNotRegisteredError` for a declared action without a registered flow; the strategy does not fall back to an update then
   - With the hooks resolved, also looks up the `PrefectAction.UPGRADE_INSTANCE` flow
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

If the new driver version declares no `upgrade`/`core` action, `_handle_upgrade` returns `None` and the strategy falls back to `_handle_update()`, which returns `Remediation(type=UPDATE_INSTANCE, parameters={instance})`. The catalogue maps this to `update_instance_crd`, which simply rewrites the CRD spec and lets the operator reconcile the new HelmRelease. Drivers without upgrade actions still work; version changes just trigger a CRD-driven Helm release update.

## Key Files

| File | Purpose |
|------|---------|
| [services/driver/models/resources/actions.py](backend/styrmin_backend/services/driver/models/resources/actions.py) | `HookKind`, `ActionDefinition` |
| [services/driver/models/resources/driver.py](backend/styrmin_backend/services/driver/models/resources/driver.py) | `Specification` (embeds `actions: list[ActionDefinition]`) |
| [services/driver/validators.py](backend/styrmin_backend/services/driver/validators.py) | `UserActionsValidator` (AST validation) |
| [services/user.py](../../../backend/styrmin_backend/services/user.py) | `ActionsWorkflowBuilder` (git and local sources) |
| [services/applications.py](../../../backend/styrmin_backend/services/applications.py) | `ensure_action_registrations`: action registration during driver loading, also for a stored driver version |
| [services/driver/hooks.py](../../../backend/styrmin_backend/services/driver/hooks.py) | `ActionRegistrationKey`, `resolve_hook_flow`, `resolve_setup_hooks`, `resolve_upgrade_hooks`, `load_command_for` |
| [services/driver/exceptions.py](../../../backend/styrmin_backend/services/driver/exceptions.py) | `DriverFilesNotFoundError`, `DriverFingerprintMismatchError`, `ActionNotRegisteredError`, `describe_action_image` |
| [workflows/local_driver.py](../../../backend/styrmin_backend/workflows/local_driver.py) | `check_local_driver` pull step, `check_local_driver_files`, `_action_image` |
| [workflows/models.py](../../../backend/styrmin_backend/workflows/models.py) | `GitSourceWorkflowDefinition`, `LocalDriverActionWorkflowDefinition` |
| [services/driver/hash.py](../../../backend/styrmin_backend/services/driver/hash.py) | `compute_driver_directory_fingerprint`, shared by the local loader and the check |
| [services/deployment.py](../../../backend/styrmin_backend/services/deployment.py) | Request check of `update_deployment_version`, `_fail_upgrade_of_unregistered_action` |
| [entrypoint/combined.py](../../../backend/styrmin_backend/entrypoint/combined.py) | The agent's `ProcessWorker`, which runs user actions in the agent pod |
| [workflows/manager.py](backend/styrmin_backend/workflows/manager.py) | `register_user_action`, `get_user_action_deployment_id` |
| [workflows/utils.py](../../../backend/styrmin_backend/workflows/utils.py) | `set_directory_pull_step` (relative `set_working_directory` path) |
| [services/driver/driver_directory.py](../../../backend/styrmin_backend/services/driver/driver_directory.py) | `normalise_driver_directory`, `resolve_inside`, `driver_directory_digest` |
| [services/driver/labels.py](../../../backend/styrmin_backend/services/driver/labels.py) | `action_directory_of`: the driver directory that registrations and lookups pass; `driver_directory_of`: the GraphQL field `driverDirectory` |
| [workflows/catalogue.py](backend/styrmin_backend/workflows/catalogue.py) | Workflow registry (UPGRADE_INSTANCE definition) |
| [actions/primitives.py](backend/styrmin_backend/actions/primitives.py) | `stop_components`, `start_components`, `execute_commands`, `get_component_images`, `get_component_labels`, `upgrade_deployment_version` |
| [agent/service/kubernetes/primitives.py](backend/styrmin_backend/agent/service/kubernetes/primitives.py) | Kubernetes side of `get_component_images` (component container image first) and `get_component_env` (component container env); `run_job` and `run_kubernetes_job` raise `JobFailedError` with the end of the output |
| [services/component_container/overrides.py](backend/styrmin_backend/services/component_container/overrides.py) | `override_applies`, `applicable_overrides` (`ApplicableOverrides`): the env vars, image, `command` and `args` that apply in a context, shared by the patch builder and the action primitives |
| [agent/service/kubernetes/job_logs.py](backend/styrmin_backend/agent/service/kubernetes/job_logs.py) | `read_job_output_tail`: the end of a failed Job's output |
| [agent/steps/reporter.py](backend/styrmin_backend/agent/steps/reporter.py) | `StepReporter`: hook-step output and steps recorded through `recordStep` |
| [agent/tasks/utils.py](../../../backend/styrmin_backend/agent/tasks/utils.py) | `run_driver_action_or_fail` (`STYRMIN_TOKEN`, `STYRMIN_TASK_ID`, `STYRMIN_STEP_ID`); `run_deployment_or_fail` and `_first_error_log` (first `ERROR` log of a crashed flow run) |
| [driver/examples/simple-app/actions.py](driver/examples/simple-app/actions.py) | Reference `upgrade` action (`images[0]`, digest- and port-safe tag strip) |
| [agent/tasks/orchestration.py](../../../backend/styrmin_backend/agent/tasks/orchestration.py) | `create_instance_crd`, `update_instance_crd`, `upgrade_instance_crd` flows; `apply_state` records `ActionNotRegisteredError` on the hook step |
| [services/reconciliation/remediation.py](backend/styrmin_backend/services/reconciliation/remediation.py) | `InstanceCreationStrategy`, `InstanceUpdateStrategy` |
