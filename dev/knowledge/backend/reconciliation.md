# Reconciliation Engine

## Overview

The reconciliation engine implements declarative state management. It compares the **desired state** (a new `Instance` generated from a `Deployment`) with the **current state** (the existing active `Instance`) and produces a remediation plan to converge them.

```text
Deployment (desired state)
      |
      v
generate_instance_from_deployment()
      |
      v
New Instance ──┐
               ├── Comparator.compare() ──> DiffReport
Current Instance ─┘                            |
                                               v
                                     Remediator.generate_remediation()
                                               |
                                               v
                                         Remediation
                                               |
                                               v
                                     PrefectManager.run_action(APPLY_STATE)
                                               |
                                               v
                                     apply_state flow -> remediation.apply()
                                               |
                                               v
                                     Orchestration flow (create/update/upgrade)
```

## Entry Point: `apply_state`

Located in `services/reconciliation/__init__.py`.

```python
@inject(cast_result=False)  # type: ignore[arg-type]
async def apply_state(
    deployment: Deployment,
    current_instance: Instance | None,
    uow: UnitOfWork,
    prefect_manager: PrefectManager = Depends(get_manager),
) -> Task
```

Called by service functions in `services/deployment.py`:

- `deploy_application()` - First deployment (current_instance is None)
- `update_deployment()` - Config change
- `update_deployment_version()` - Version change
- `refresh_deployment()` - Re-reconcile

Steps:

1. Read `deployment.active_instance` as the new instance
2. Create a `Comparator(current_instance, new_instance)`
3. Call `comparator.compare()` to get a `DiffReport`
4. Create a `Remediator(uow)` and call `generate_remediation(diff_report)`
5. Create a `Task` with `type=TaskType(remediation.type.value)` if a remediation was generated, otherwise `type=TaskType.NOOP`
6. Submit `PrefectAction.APPLY_STATE` to Prefect with parameters `{deployment_id, remediation, task_id}`
7. Set `task.prefect_flow_run_id = flow_info.id` from the submission result
8. Return the task

The companion function `generate_instance_from_deployment()` creates a new `Instance` by resolving the deployment context and tagging the context with the instance id so the CRD can carry it for status correlation:

```python
async def generate_instance_from_deployment(deployment: Deployment, uow: UnitOfWork) -> Instance:
    context = await generate_context_from_deployment(deployment=deployment, uow=uow)
    instance = Instance.create(
        application_version=deployment.application_version,
        deployment_id=deployment.id,
        application_driver_version_id=deployment.application_driver_version_id,
        context=context,
    )
    # Tag the context with the instance id so the CRD carries it and the server
    # can correlate agent status reports to the active instance.
    instance.context.instance.id = instance.id
    return instance
```

## Diff Computation

### Comparator (`diffs/comparison.py`)

Compares two `Instance` objects using `deepdiff.DeepDiff`.

```python
class Comparator:
    def __init__(self, current_instance: Instance | None, new_instance: Instance | None)
    def compare(self) -> DiffReport
```

**Decision matrix:**

| current_instance | new_instance | Result |
|:---:|:---:|---|
| None | None | No diff |
| None | Present | `InstanceCreation` |
| Present | None | `InstanceDeletion` |
| Present | Present | `InstanceUpdate` (with diff entries) |

When both instances exist, DeepDiff compares their `model_dump()` output:

- Excludes `id`, `name`, `status` from comparison
- Collapses all context sub-changes into a single `ContextChange` entry
- The raw diff is serialized into typed `DiffEntry` objects

### Diff Types (`diffs/diffs.py`)

**Top-level diff types** (one per comparison):

```python
class Diff(BaseModel):
    instance: Instance  # Always the NEW instance

class InstanceCreation(Diff): ...
class InstanceDeletion(Diff): ...
class InstanceUpdate(Diff):
    diffs: list[DiffEntry]  # What changed
```

**Diff entries** (within `InstanceUpdate`):

```python
class ApplicationVersionChange(DiffEntry):
    current_value: str   # e.g., "1.5.0"
    new_value: str       # e.g., "1.6.0"

class ApplicationDriverVersionChange(DiffEntry):
    current_value: UUID  # Old driver version ID
    new_value: UUID      # New driver version ID

class ContextChange(DiffEntry):
    current_value: dict  # Old context dump
    new_value: dict      # New context dump
```

### Diff Serializer (`diffs/serializer.py`)

Maps DeepDiff paths to typed `DiffEntry` objects:

```python
class DiffSerializer:
    SERIALIZERS = {
        DiffEntrySerializer(
            paths=[ValuePath(path=["application_version"])],
            diff_class=ApplicationVersionChange,
        ),
        DiffEntrySerializer(
            paths=[ValuePath(path=["context"])],
            diff_class=ContextChange,
        ),
        DiffEntrySerializer(
            paths=[ValuePath(path=["application_driver_version_id"])],
            diff_class=ApplicationDriverVersionChange,
        ),
    }
```

The serializer builds an index of DeepDiff paths (e.g., `root['application_version']`) to serializer instances. When processing raw diffs, it looks up each changed path and creates the corresponding `DiffEntry`.

Unknown paths are silently ignored.

## Remediation Strategies

### Strategy Pattern (`remediation.py`)

```text
                    Remediator
                        |
                        v
                DiffReport.diff
                   /    |     \
                  /     |      \
InstanceCreation  InstanceUpdate  InstanceDeletion
       |                |               |
       v                v               v
InstanceCreation   InstanceUpdate   InstanceDeletion
   Strategy          Strategy         Strategy
       |                |               |
       v                v               v
  Remediation      Remediation       NotImplemented
(CREATE_INSTANCE) (UPDATE_INSTANCE
                   or UPGRADE_INSTANCE)
```

### Remediator

```python
class Remediator:
    def __init__(self, uow: UnitOfWork):
        self.strategies = {
            InstanceCreation: InstanceCreationStrategy(uow=self.uow),
            InstanceDeletion: InstanceDeletionStrategy(uow=self.uow),
            InstanceUpdate: InstanceUpdateStrategy(uow=self.uow),
        }

    async def generate_remediation(self, diff_report: DiffReport) -> Remediation | None
```

Maps diff TYPE to strategy. Only one strategy per diff type.

### Remediation Model

```python
class Remediation(BaseModel):
    instance: Instance
    flow_id: UUID          # Prefect deployment ID for the orchestration flow
    parameters: dict       # Parameters to pass to the flow
    type: RemediationType  # CREATE_INSTANCE, UPDATE_INSTANCE, UPGRADE_INSTANCE, etc.

    async def apply(self) -> FlowRun:
        """Call run_deployment_or_fail(name=self.flow_id, parameters=self.parameters)"""
```

### RemediationType Enum

```python
class RemediationType(str, Enum):
    CREATE_INSTANCE = "create_instance"
    DELETE_INSTANCE = "delete_instance"
    UPDATE_INSTANCE = "update_instance"
    UPGRADE_INSTANCE = "upgrade_instance"
    DOWNGRADE_INSTANCE = "downgrade_instance"
```

### Strategy interface

All concrete strategies implement `RemediationStrategy.execute(diff, prefect_manager) -> Remediation | None` (decorated with `@inject` to bind the manager). `Remediator._handle_diff` looks up the strategy for the diff type and calls `execute`. Strategies that don't apply to the given diff return `None`.

### InstanceCreationStrategy

Handles `InstanceCreation` diffs. The CRD flow only needs setup hooks — the operator handles HelmRelease creation and utility resource management — so no "core" HelmRelease hook is resolved here.

1. Gets the driver version from `diff.instance.application_driver_version_id`
2. Gets the application from the driver version
3. Looks up the `CREATE_INSTANCE` internal flow via `prefect_manager.get_action_deployment_id`
4. Looks up setup hooks in parallel: `get_user_action_deployment_id(hook=HookKind.SETUP, mode="pre"/"post", version=driver_version.application_supported_versions)`
5. Reads the parent deployment's `internal` flag (e.g., for ingress controller deployments)
6. Returns `Remediation(type=CREATE_INSTANCE, instance=…, flow_id=create_instance_flow, parameters={instance, prehook, posthook, internal})`

### InstanceUpdateStrategy

Handles `InstanceUpdate` diffs. Routes version changes to the upgrade path when upgrade hooks are defined:

1. Checks if any diff entry is an `ApplicationVersionChange`
2. If yes, calls `_handle_upgrade()`:
   - Looks up the driver's upgrade core hook from Prefect (`hook=UPGRADE, mode="core"`)
   - If not found: returns `None` and the strategy falls back to `_handle_update()`
   - If found: looks up `PrefectAction.UPGRADE_INSTANCE` plus the upgrade pre/post hooks (in parallel), then returns `Remediation(type=UPGRADE_INSTANCE, parameters={instance, upgrade_hook, target_version, prehook, posthook})`
3. If no version change (or upgrade fallback), calls `_handle_update()`:
   - Iterates the diff entries; for any actionable entry (`ApplicationVersionChange`, `ApplicationDriverVersionChange`, or `ContextChange`), looks up `PrefectAction.UPDATE_INSTANCE` and returns `Remediation(type=UPDATE_INSTANCE, parameters={instance})`. The CRD flow only needs the instance — the operator handles HelmRelease and utility resource reconciliation.

Drivers with upgrade hooks get the lifecycle pre → driver core hook → post; drivers without upgrade hooks fall back to a regular update where the CRD spec is updated and the operator reconciles the HelmRelease.

### InstanceDeletionStrategy

Not implemented. `execute` raises `NotImplementedError`.

## Version Change Scenarios

When `update_deployment_version()` is called:

**Same driver version** (new version within same specifier):

- `deployment.application_version` changes
- `deployment.application_driver_version_id` stays the same
- Diff: `ApplicationVersionChange` + `ContextChange`

**Different driver version** (new version requires different driver):

- `deployment.application_version` changes
- `deployment.application_driver_version_id` changes
- Components are recreated from the new driver version
- Diff: `ApplicationVersionChange` + `ApplicationDriverVersionChange` + `ContextChange`

In both cases, `ApplicationVersionChange` is always present when the version changes.

## Key Files

| File | Purpose |
|------|---------|
| [services/reconciliation/**init**.py](backend/styrmin_backend/services/reconciliation/__init__.py) | `apply_state`, `generate_instance_from_deployment` |
| [services/reconciliation/diffs/comparison.py](backend/styrmin_backend/services/reconciliation/diffs/comparison.py) | `Comparator` - diff computation |
| [services/reconciliation/diffs/diffs.py](backend/styrmin_backend/services/reconciliation/diffs/diffs.py) | Diff types and entry types |
| [services/reconciliation/diffs/serializer.py](backend/styrmin_backend/services/reconciliation/diffs/serializer.py) | `DiffSerializer` - maps DeepDiff paths to typed entries |
| [services/reconciliation/remediation.py](backend/styrmin_backend/services/reconciliation/remediation.py) | Remediation strategies and `Remediator` |
| [services/deployment.py](backend/styrmin_backend/services/deployment.py) | Service functions that call `apply_state` |
