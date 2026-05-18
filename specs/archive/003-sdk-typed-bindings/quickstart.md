# Quickstart: Leverage Generated Typed Bindings in SDK

**Feature**: 003-sdk-typed-bindings | **Date**: 2026-04-01

## Prerequisites

- Python 3.12+
- `uv sync --all-groups` (install dependencies)
- Generated types are up to date: `uv run invoke generate`

## Approach

**Keep**: Transport, load_query(), _check_graphql_errors(), StyrminClient constructor, BaseResource._transport
**Replace**: Hand-written model validation with generated outer wrapper type validation
**Delete**: Hand-written model files (except context.py, driver.py partial)

## Implementation Order

### Step 1: Update models/__init__.py to re-export generated types

**File**: `python_sdk/src/styrmin_sdk/models/__init__.py`

Replace hand-written model imports with generated type re-exports:

```python
"""Styrmin SDK response models."""

# Generated type re-exports (canonical names for public API)
from styrmin_sdk.graphql._generated.get_backup import GetBackupBackup as Backup
from styrmin_sdk.graphql._generated.get_backup_schedule import (
    GetBackupScheduleBackupSchedule as BackupSchedule,
)
from styrmin_sdk.graphql._generated.get_backup_storage_location import (
    GetBackupStorageLocationBackupStorageLocation as BackupStorageLocation,
)
from styrmin_sdk.graphql._generated.get_cluster import GetClusterCluster as Cluster
from styrmin_sdk.graphql._generated.get_deployment import (
    GetDeploymentDeployment as Deployment,
    GetDeploymentDeploymentApplicationInstance as ApplicationInstance,
    GetDeploymentDeploymentComponents as Component,
)
from styrmin_sdk.graphql._generated.get_environment import (
    GetEnvironmentEnvironment as Environment,
    GetEnvironmentEnvironmentCluster as ClusterRef,
)
from styrmin_sdk.graphql._generated.get_restore import GetRestoreRestore as Restore
from styrmin_sdk.graphql._generated.get_task import GetTaskTask as Task
from styrmin_sdk.graphql._generated.load_remote_application_driver_version import (
    LoadRemoteApplicationDriverVersionLoadRemoteApplicationDriverVersion as ApplicationDriverVersion,
    LoadRemoteApplicationDriverVersionLoadRemoteApplicationDriverVersionActions as Action,
    LoadRemoteApplicationDriverVersionLoadRemoteApplicationDriverVersionComponentConfigs as ComponentConfig,
    LoadRemoteApplicationDriverVersionLoadRemoteApplicationDriverVersionHelmChart as HelmChart,
)

# Hand-written models (no generated equivalent)
from styrmin_sdk.models.context import Context
from styrmin_sdk.models.driver import ApplicationDriver, ApplicationDriverVersionSummary
```

### Step 2: Migrate one resource (start with ClusterResource)

**File**: `python_sdk/src/styrmin_sdk/resources/clusters.py`

Pattern change — replace `Model.model_validate(result["data"]["key"])` with `OuterType.model_validate(result["data"]).inner_attr`:

```python
from styrmin_sdk.graphql._generated.create_cluster import CreateCluster
from styrmin_sdk.graphql._generated.get_cluster import GetCluster
from styrmin_sdk.graphql._generated.list_clusters import ListClusters

class ClusterResource(BaseResource):
    async def create(self, name: str, config: JsonValue | None = None) -> CreateClusterCreateCluster:
        variables: dict[str, Any] = {"name": name}
        if config is not None:
            variables["config"] = config
        result = await self._transport.execute(load_query("create_cluster"), variables)
        self._check_graphql_errors(result)
        data = CreateCluster.model_validate(result["data"])
        return data.create_cluster

    async def list(self) -> list[ListClustersClusters]:
        result = await self._transport.execute(load_query("list_clusters"))
        self._check_graphql_errors(result)
        data = ListClusters.model_validate(result["data"])
        return data.clusters or []

    async def get(self, cluster_id=None, cluster_name=None) -> GetClusterCluster:
        variables: dict[str, Any] = {}
        if cluster_id is not None:
            variables["clusterId"] = str(cluster_id)
        if cluster_name is not None:
            variables["clusterName"] = cluster_name
        result = await self._transport.execute(load_query("get_cluster"), variables)
        self._check_graphql_errors(result)
        data = GetCluster.model_validate(result["data"])
        return data.cluster

    async def delete(self, cluster_id=None, cluster_name=None) -> None:
        # Unchanged — error checking on raw dict, no model validation needed
        variables: dict[str, Any] = {}
        if cluster_id is not None:
            variables["clusterId"] = str(cluster_id)
        if cluster_name is not None:
            variables["clusterName"] = cluster_name
        result = await self._transport.execute(load_query("delete_cluster"), variables)
        self._check_graphql_errors(result)
```

### Step 3: Migrate remaining resources

Repeat Step 2 pattern for: backups, deployments, environments, backup_storage_locations, drivers, schedules, tasks.

### Step 4: Update test fixtures

**File**: `python_sdk/tests/conftest.py` and test files

Tests still mock `Transport.execute()` to return raw dicts. The test dict structures stay the same — the change is in assertions. Response objects are now generated types, so assertions should use the generated type's attribute names (e.g., `task.type_` instead of `task.type`).

### Step 5: Clean up model files

- Delete: `models/cluster.py`, `models/backup.py`, `models/deployment.py`, `models/environment.py`, `models/task.py`, `models/backup_storage_location.py`
- Trim `models/driver.py` to keep only `ApplicationDriver` and `ApplicationDriverVersionSummary`
- Keep: `models/context.py`

### Step 6: Verify

```bash
uv run invoke test          # All tests pass
uv run invoke format lint   # Clean formatting and linting
```

## Key Gotchas

1. **`Task.type` → `Task.type_`**: All generated Task types use `type_` with `alias="type"`. This is an accepted breaking change — document it.

2. **Return type varies per operation**: `create()` returns `CreateClusterCreateCluster`, `get()` returns `GetClusterCluster`. Field access is identical but `isinstance()` checks differ. The `models/__init__.py` aliases point to the "get" variant.

3. **List operations**: Use `data.field or []` to handle the `Optional[list[...]]` safely.

4. **Delete/assign/unassign operations**: No model validation needed. Error checking on raw dict is sufficient.

5. **Transport and _queries.py are KEPT**: The execution path is unchanged. Only the response parsing layer changes.
