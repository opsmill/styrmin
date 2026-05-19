# Research: Leverage Generated Typed Bindings in SDK

**Feature**: 003-sdk-typed-bindings | **Date**: 2026-04-01

## Decision 1: Execution Layer — Keep Transport + load_query(), Replace Models Only

**Decision**: Keep the existing `Transport.execute()` + `load_query()` execution path unchanged. Only replace hand-written Pydantic models with the generated response types from ariadne-codegen.

**Rationale**: The generated `Client` class in `_generated/client.py` embeds GraphQL query strings inline and uses its own `AsyncBaseClient` HTTP layer. Switching to it would:
- Duplicate transport configuration (server address, timeout, headers)
- Require reworking the SDK's `_check_graphql_errors()` error-mapping layer
- Make the `.graphql` query files unused (they're already the source for codegen)

The generated response types alone provide the type-safety benefit without execution-layer disruption.

**Alternatives considered**:
- Use generated `Client` class directly: rejected — too much transport refactoring, error handling rework
- Use generated `Client` wrapped with error mapping: rejected — unnecessary complexity

---

## Decision 2: Response Validation Pattern — Outer Wrapper Type

**Decision**: Use the generated outer wrapper type to validate the full `result["data"]` dict, then extract the inner field via typed attribute access.

**Before** (current pattern):
```python
result = await self._transport.execute(load_query("create_cluster"), variables)
self._check_graphql_errors(result)
return Cluster.model_validate(result["data"]["createCluster"])
```

**After** (new pattern):
```python
result = await self._transport.execute(load_query("create_cluster"), variables)
self._check_graphql_errors(result)
data = CreateCluster.model_validate(result["data"])
return data.create_cluster
```

**Rationale**: Using the outer wrapper eliminates manual dictionary key access (`result["data"]["createCluster"]`), which is error-prone and not validated by the type system. The generated outer type has typed attributes for each operation field. Error checking still operates on the raw `result` dict before validation.

**Alternatives considered**:
- Validate inner type directly (e.g., `CreateClusterCreateCluster.model_validate(result["data"]["createCluster"])`): rejected — still requires manual dict key access

---

## Decision 3: Task.type → Task.type_ Breaking Change

**Decision**: Accept the `type` → `type_` field rename on all Task-like response types. Document as a breaking change.

**Rationale**: ariadne-codegen renames `type` to `type_` because `type` is a Python builtin. All Task-returning operations (deploy, update_deployment, update_deployment_version, start_components, stop_components, run_job, get_task, list_tasks) use `type_` in the generated types.

**Migration impact**: SDK consumers accessing `task.type` must change to `task.type_`. Since `populate_by_name=True` is set on the generated base model, both `type_` (field name) and `type` (alias) work for model construction, but attribute access uses `type_`.

---

## Decision 4: Models With No Generated Equivalent

**Decision**: Keep `ApplicationDriver`, `ApplicationDriverVersionSummary`, and `Context` as hand-written models.

**Rationale**:
- `ApplicationDriver` / `ApplicationDriverVersionSummary`: No list/get driver queries exist in the SDK; ariadne-codegen generates no types for them
- `Context`: Uses a REST endpoint (`/deployments/{id}/context`), not GraphQL — no generated type exists

---

## Decision 5: Public API Re-export Strategy

**Decision**: `models/__init__.py` will re-export generated inner types under the original names using `as` aliases. The `models/` package becomes a facade.

```python
# models/__init__.py
from styrmin_sdk.graphql._generated.get_cluster import GetClusterCluster as Cluster
from styrmin_sdk.graphql._generated.get_deployment import GetDeploymentDeployment as Deployment
# etc.
```

**Rationale**: Preserves backward-compatibility for `from styrmin_sdk import Cluster`. Each operation generates its own version of a type (e.g., `GetClusterCluster`, `CreateClusterCreateCluster`, `ListClustersClusters`), but field access is identical across all variants. The "get" operation's type is chosen as the canonical re-export since it typically has the most complete field set.

**Challenge**: `isinstance(obj, Cluster)` won't match objects returned from `create()` (which returns `CreateClusterCreateCluster`). This is acceptable — SDK consumers use field access, not isinstance checks.

---

## Decision 6: List Operations Pattern

**Before**:
```python
return [Cluster.model_validate(c) for c in result["data"].get("clusters", [])]
```

**After**:
```python
data = ListClusters.model_validate(result["data"])
return data.clusters or []
```

**Rationale**: The generated outer type handles deserialization of list items. No manual list comprehension needed. `or []` handles the edge case where the field is `None`.

---

## Decision 7: Delete/Assign/Unassign Operations

**Decision**: Delete operations still check errors via `_check_graphql_errors()` on the raw dict, then either return `None` or `True` as today. The outer wrapper validation is optional for these since the return value is discarded.

For consistency, we can still validate through the outer type, but the return value is unused:
```python
result = await self._transport.execute(load_query("delete_cluster"), variables)
self._check_graphql_errors(result)
# No model validation needed — error check is sufficient
```

---

## Complete Operation-to-Type Mapping

### ClusterResource

| Method | Query | Outer Type | Inner Attribute | Inner Type |
|--------|-------|-----------|-----------------|------------|
| create | create_cluster | CreateCluster | create_cluster | CreateClusterCreateCluster |
| list | list_clusters | ListClusters | clusters | list[ListClustersClusters] |
| get | get_cluster | GetCluster | cluster | GetClusterCluster |
| delete | delete_cluster | N/A (no validation) | N/A | N/A |

### BackupResource

| Method | Query | Outer Type | Inner Attribute | Inner Type |
|--------|-------|-----------|-----------------|------------|
| create_backup | create_backup | CreateBackup | create_backup | CreateBackupCreateBackup |
| get_backup | get_backup | GetBackup | backup | GetBackupBackup |
| list_backups | list_backups | ListBackups | backups | list[ListBackupsBackups] |
| delete_backup | delete_backup | N/A | N/A | N/A |
| create_restore | create_restore | CreateRestore | create_restore | CreateRestoreCreateRestore |
| get_restore | get_restore | GetRestore | restore | GetRestoreRestore |
| list_restores | list_restores | ListRestores | restores | list[ListRestoresRestores] |

### DeploymentResource

| Method | Query | Outer Type | Inner Attribute | Inner Type |
|--------|-------|-----------|-----------------|------------|
| create (deploy) | deploy | Deploy | deploy | DeployDeploy |
| get | get_deployment | GetDeployment | deployment | GetDeploymentDeployment |
| update | update_deployment | UpdateDeployment | update_deployment | UpdateDeploymentUpdateDeployment |
| update_version | update_version | UpdateDeploymentVersion | update_deployment_version | UpdateDeploymentVersionUpdateDeploymentVersion |
| start_components | start_components | StartComponents | start_components | StartComponentsStartComponents |
| stop_components | stop_components | StopComponents | stop_components | StopComponentsStopComponents |
| run_job | run_job | RunJob | run_job | RunJobRunJob |
| get_context | REST endpoint | N/A | N/A | Context (hand-written, unchanged) |

### EnvironmentResource

| Method | Query | Outer Type | Inner Attribute | Inner Type |
|--------|-------|-----------|-----------------|------------|
| create | create_environment | CreateEnvironment | create_environment | CreateEnvironmentCreateEnvironment |
| list | list_environments | ListEnvironments | environments | list[ListEnvironmentsEnvironments] |
| get | get_environment | GetEnvironment | environment | GetEnvironmentEnvironment |
| delete | delete_environment | N/A | N/A | N/A |

### DriverResource

| Method | Query | Outer Type | Inner Attribute | Inner Type |
|--------|-------|-----------|-----------------|------------|
| load_version | load_version | LoadRemoteApplicationDriverVersion | load_remote_application_driver_version | LoadRemoteApplicationDriverVersionLoadRemoteApplicationDriverVersion |
| load_local_version | load_local_version | LoadLocalApplicationDriverVersion | load_local_application_driver_version | LoadLocalApplicationDriverVersionLoadLocalApplicationDriverVersion |

### ScheduleResource

| Method | Query | Outer Type | Inner Attribute | Inner Type |
|--------|-------|-----------|-----------------|------------|
| create | create_schedule | CreateBackupSchedule | create_backup_schedule | CreateBackupScheduleCreateBackupSchedule |
| get | get_schedule | GetBackupSchedule | backup_schedule | GetBackupScheduleBackupSchedule |
| list | list_schedules | ListBackupSchedules | backup_schedules | list[ListBackupSchedulesBackupSchedules] |
| update | update_schedule | UpdateBackupSchedule | update_backup_schedule | UpdateBackupScheduleUpdateBackupSchedule |
| delete | delete_schedule | N/A | N/A | N/A |

### TaskResource

| Method | Query | Outer Type | Inner Attribute | Inner Type |
|--------|-------|-----------|-----------------|------------|
| list | list_tasks | ListTasks | tasks | list[ListTasksTasks] |
| get | get_task | GetTask | task | GetTaskTask |

### BackupStorageLocationResource

| Method | Query | Outer Type | Inner Attribute | Inner Type |
|--------|-------|-----------|-----------------|------------|
| create | create_backup_storage_location | CreateBackupStorageLocation | create_backup_storage_location | CreateBackupStorageLocationCreateBackupStorageLocation |
| list | list_backup_storage_locations | ListBackupStorageLocations | backup_storage_locations | list[ListBackupStorageLocationsBackupStorageLocations] |
| get | get_backup_storage_location | GetBackupStorageLocation | backup_storage_location | GetBackupStorageLocationBackupStorageLocation |
| update | update_backup_storage_location | UpdateBackupStorageLocation | update_backup_storage_location | UpdateBackupStorageLocationUpdateBackupStorageLocation |
| delete | delete_backup_storage_location | N/A | N/A | N/A |
| assign | assign_backup_storage_location | N/A | N/A | N/A |
| unassign | unassign_backup_storage_location | N/A | N/A | N/A |
