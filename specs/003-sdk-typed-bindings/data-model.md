# Data Model: Leverage Generated Typed Bindings in SDK

**Feature**: 003-sdk-typed-bindings | **Date**: 2026-04-01

## Overview

This document maps the current hand-written SDK domain models to their generated type counterparts from ariadne-codegen, identifying field-level differences and the re-export strategy.

## Entity Mapping

### Cluster

| Hand-written (`models/cluster.py`) | Generated (`GetClusterCluster`) | Notes |
|---|---|---|
| `id: UUID` | `id: UUID` | Identical |
| `name: str` | `name: str` | Identical |
| `config: Any \| None = None` | `config: Any` | Generated is non-optional — compatible (None is a valid `Any`) |

**Re-export**: `GetClusterCluster as Cluster`
**Other operations**: `CreateClusterCreateCluster`, `ListClustersClusters` — same fields, structurally compatible.

---

### Deployment

| Hand-written (`models/deployment.py`) | Generated (`GetDeploymentDeployment`) | Notes |
|---|---|---|
| `id: UUID` | `id: UUID` | Identical |
| `name: str` | `name: str` | Identical |
| `status: str` | `status: str` | Identical |
| `config: Any \| None = None` | `config: Any` | Generated is non-optional |
| `application_version: str` | `application_version: str` | Identical (Field alias `applicationVersion`) |
| `application_driver_version_id: UUID` | `application_driver_version_id: UUID` | Identical |
| `environment_id: UUID` | `environment_id: UUID` | Identical |
| `application_instance: ApplicationInstance \| None = None` | `application_instance: Optional[GetDeploymentDeploymentApplicationInstance]` | Nested type name differs |
| `components: list[Component] = []` | `components: list[GetDeploymentDeploymentComponents]` | Nested type name differs |

**Nested types**:
- `ApplicationInstance` → `GetDeploymentDeploymentApplicationInstance` (fields: `id: UUID`, `status: str` — identical)
- `Component` → `GetDeploymentDeploymentComponents` (fields: `id: UUID`, `name: str`, `enabled: bool` — identical)

**Re-exports**:
- `GetDeploymentDeployment as Deployment`
- `GetDeploymentDeploymentApplicationInstance as ApplicationInstance`
- `GetDeploymentDeploymentComponents as Component`

---

### Environment

| Hand-written (`models/environment.py`) | Generated (`GetEnvironmentEnvironment`) | Notes |
|---|---|---|
| `id: UUID` | `id: UUID` | Identical |
| `name: str` | `name: str` | Identical |
| `config: Any \| None = None` | `config: Any` | Generated is non-optional |
| `cluster: ClusterRef` | `cluster: GetEnvironmentEnvironmentCluster` | Nested type name differs |

**Nested types**:
- `ClusterRef` → `GetEnvironmentEnvironmentCluster` (fields: `id: UUID`, `name: str` — identical)

**Re-exports**:
- `GetEnvironmentEnvironment as Environment`
- `GetEnvironmentEnvironmentCluster as ClusterRef`

---

### Backup

| Hand-written (`models/backup.py`) | Generated (`GetBackupBackup`) | Notes |
|---|---|---|
| `id: UUID` | `id: UUID` | Identical |
| `name: str` | `name: str` | Identical |
| `status: str` | `status: str` | Identical |
| `instance_id: UUID` | `instance_id: UUID` | Identical |
| `error_message: str \| None = None` | `error_message: Optional[str]` | Identical |
| `started_at: datetime \| None = None` | `started_at: Optional[datetime]` | Identical |
| `completed_at: datetime \| None = None` | `completed_at: Optional[datetime]` | Identical |
| `size_bytes: int \| None = None` | `size_bytes: Optional[int]` | Identical |
| `created_on: datetime \| None = None` | `created_on: datetime` | **STRICTER** — generated is non-optional |
| `updated_on: datetime \| None = None` | `updated_on: Optional[datetime]` | Identical |

**Re-export**: `GetBackupBackup as Backup`

---

### Restore

| Hand-written (`models/backup.py`) | Generated (`GetRestoreRestore`) | Notes |
|---|---|---|
| `id: UUID` | `id: UUID` | Identical |
| `name: str` | `name: str` | Identical |
| `status: str` | `status: str` | Identical |
| `backup_id: UUID` | `backup_id: UUID` | Identical |
| `target_namespace: str` | `target_namespace: str` | Identical |
| `target_instance_id: UUID \| None = None` | `target_instance_id: Optional[UUID]` | Identical |
| `error_message: str \| None = None` | `error_message: Optional[str]` | Identical |
| `started_at: datetime \| None = None` | `started_at: Optional[datetime]` | Identical |
| `completed_at: datetime \| None = None` | `completed_at: Optional[datetime]` | Identical |
| `created_on: datetime \| None = None` | `created_on: datetime` | **STRICTER** — generated is non-optional |
| `updated_on: datetime \| None = None` | `updated_on: Optional[datetime]` | Identical |

**Re-export**: `GetRestoreRestore as Restore`

---

### BackupSchedule

| Hand-written (`models/backup.py`) | Generated (`GetBackupScheduleBackupSchedule`) | Notes |
|---|---|---|
| All fields | All fields | Identical except `created_on` is non-optional in generated |

**Re-export**: `GetBackupScheduleBackupSchedule as BackupSchedule`

---

### BackupStorageLocation

| Hand-written (`models/backup_storage_location.py`) | Generated (`GetBackupStorageLocationBackupStorageLocation`) | Notes |
|---|---|---|
| All fields | All fields | Field-for-field match |

**Re-export**: `GetBackupStorageLocationBackupStorageLocation as BackupStorageLocation`

---

### Task

| Hand-written (`models/task.py`) | Generated (`GetTaskTask`) | Notes |
|---|---|---|
| `id: UUID` | `id: UUID` | Identical |
| **`type: str`** | **`type_: str = Field(alias="type")`** | **BREAKING** — Python attribute renamed to avoid `type` builtin |
| `status: str` | `status: str` | Identical |
| `message: str \| None = None` | `message: Optional[str]` | Identical |
| `deployment_id: UUID \| None = None` | `deployment_id: Optional[UUID]` | Identical |

**Breaking change**: `task.type` → `task.type_`. However, since the generated model has `alias="type"` and uses `populate_by_name=True` (from the base model config), consumers accessing `task.type` via Pydantic's alias mechanism may not break. The Python attribute name is `type_` but the model can still be accessed with `type` as alias.

**Mitigation**: Keep a thin wrapper class for `Task` that adds a `type` property delegating to `type_`, OR accept the breaking change and document it.

**Re-export**: `GetTaskTask as Task` (with documented `type_` attribute change)

---

### ApplicationDriver / ApplicationDriverVersion

| Hand-written | Generated | Notes |
|---|---|---|
| `ApplicationDriver` (id, name, versions) | No single "get driver" operation | Driver loaded via `load_local/remote_application_driver_version` |
| `ApplicationDriverVersion` (full details) | `LoadLocalApplicationDriverVersionLoadLocalApplicationDriverVersion` | Structurally identical |
| `HelmChart` | `...HelmChart` (nested) | Identical fields |
| `Action` | `...Actions` (nested) | Identical fields |
| `ComponentConfig` | `...ComponentConfigs` (nested) | Identical fields |
| `ApplicationDriverVersionSummary` | No direct equivalent | Only used in `ApplicationDriver.versions` |

**Re-exports**:
- `LoadLocalApplicationDriverVersionLoadLocalApplicationDriverVersion as ApplicationDriverVersion`
- Nested types: `...HelmChart as HelmChart`, `...Actions as Action`, `...ComponentConfigs as ComponentConfig`
- `ApplicationDriver` and `ApplicationDriverVersionSummary`: May need to remain hand-written if no matching generated type exists, OR the GraphQL queries need to be updated to return these shapes.

---

### Context

| Hand-written (`models/context.py`) | Generated | Notes |
|---|---|---|
| `context: Any` | Depends on the query | Need to check `get_context` generated type |

**Re-export**: TBD — depends on the generated type shape.

---

## Summary of Breaking Changes

| Entity | Change | Severity | Mitigation |
|---|---|---|---|
| `Task.type` → `Task.type_` | Attribute rename | Medium | Thin wrapper with `type` property, or document as breaking |
| `Backup.created_on` | `Optional` → required | Low | Stricter typing is generally safe |
| `Restore.created_on` | `Optional` → required | Low | Same as above |
| `Cluster.config` | `Optional` → `Any` | Low | `None` still valid under `Any` |

## Type Re-export Strategy

`models/__init__.py` will become a pure re-export module:

```python
from styrmin_sdk.graphql._generated.get_backup import GetBackupBackup as Backup
from styrmin_sdk.graphql._generated.get_backup_schedule import GetBackupScheduleBackupSchedule as BackupSchedule
from styrmin_sdk.graphql._generated.get_backup_storage_location import GetBackupStorageLocationBackupStorageLocation as BackupStorageLocation
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
from styrmin_sdk.graphql._generated.load_local_application_driver_version import (
    LoadLocalApplicationDriverVersionLoadLocalApplicationDriverVersion as ApplicationDriverVersion,
    LoadLocalApplicationDriverVersionLoadLocalApplicationDriverVersionActions as Action,
    LoadLocalApplicationDriverVersionLoadLocalApplicationDriverVersionComponentConfigs as ComponentConfig,
    LoadLocalApplicationDriverVersionLoadLocalApplicationDriverVersionHelmChart as HelmChart,
)
```

Types that have no generated equivalent (`ApplicationDriver`, `ApplicationDriverVersionSummary`, `Context`) will remain hand-written until matching queries are added.
