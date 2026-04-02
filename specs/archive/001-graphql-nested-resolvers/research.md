# Research: Add Nested Object Resolvers to GraphQL Schema

## R1: Resolver Pattern Selection

**Decision**: Use async UoW-based resolvers for most new fields; use synchronous resolver for ApplicationDriverVersion.applicationDriver.

**Rationale**: The codebase has two established resolver patterns:
1. **Synchronous** — access `self.instance.relationship` when the relationship is already eager-loaded by the repository (e.g., `Environment.cluster`, `ApplicationDriverVersion.helm_chart`)
2. **Asynchronous** — fetch via `info.context["uow"]` when data must be loaded on demand (e.g., `Deployment.deployed_services`)

The async pattern is preferred for new resolvers because:
- Most repositories (Deployment, Task, Backup, Restore, BackupSchedule, ApplicationInstance) do **not** eager-load the relationships we need
- Adding eager-loading to those repositories would load related data for every query, even when the nested field isn't requested
- Async resolvers only execute when the GraphQL field is actually requested

**Exception**: `ApplicationDriverVersion.applicationDriver` can use the synchronous pattern because the ADV repository already eager-loads `application_driver` via `selectinload`.

**Alternatives considered**:
- *Add eager-loading to all repositories*: Rejected — would cause unnecessary DB joins on every query
- *DataLoader batching*: Deferred per spec assumptions — lazy-loading is acceptable for this iteration

## R2: Nullable vs Non-Nullable Resolver Behavior

**Decision**: Match resolver nullability to the foreign key nullability in the database model.

**Rationale**: From the database models:

| Resolver | FK Field | FK Nullable? | Resolver Return |
|----------|----------|-------------|-----------------|
| Deployment.environment | `environment_id: UUID` | No | `Environment` (non-nullable) |
| Deployment.applicationDriverVersion | `application_driver_version_id: UUID` | No | `ApplicationDriverVersion` (non-nullable) |
| ApplicationDriverVersion.applicationDriver | `application_driver_id: UUID` | No | `ApplicationDriver` (non-nullable) |
| ApplicationInstance.applicationDriverVersion | `application_driver_version_id: UUID` | No | `ApplicationDriverVersion` (non-nullable) |
| Task.deployment | `deployment_id: UUID` | Yes (`UUID | None` based on GraphQL schema showing `deploymentId: UUID`) | `Deployment | None` (nullable) |
| BackupSchedule.deployment | `deployment_id: UUID` | No | `Deployment` (non-nullable) |
| Backup.instance | `instance_id: UUID` | No | `ApplicationInstance` (non-nullable) |
| Restore.backup | `backup_id: UUID` | No | `Backup` (non-nullable) |

**Note on Task.deployment**: The spec states this is nullable (FR-005). The GraphQL schema shows `deploymentId: UUID` without `!` which confirms nullability. The resolver must handle `deployment_id` being `None`.

**Error handling for non-nullable resolvers (FR-013)**: If a non-nullable resolver fails to find the referenced entity (data integrity violation), it must raise an exception that Strawberry converts to a GraphQL field error. A simple `ValueError` or custom exception will suffice.

**Alternatives considered**:
- *Return None for all resolvers*: Rejected — non-nullable FKs guarantee the entity exists; returning None would weaken the type contract
- *Custom error union types*: Rejected — spec says standard resolver exception behavior is sufficient

## R3: Circular Import Handling

**Decision**: Use `strawberry.lazy()` and `Annotated` for types that would create circular imports.

**Rationale**: The codebase already handles circular dependencies between GraphQL types using this pattern (e.g., `Environment.backup_storage_location`):

```python
from __future__ import annotations
from typing import Annotated

@strawberry.field
def some_field(self) -> Annotated["OtherType", strawberry.lazy("module.path")]:
    from module.path import OtherType
    return OtherType.from_instance(self.instance.relationship)
```

Potential circular imports in this feature:
- `Deployment` ↔ `ApplicationDriverVersion`: Deployment already imports ApplicationInstance; ADV is in a separate module — no circular issue for the `Deployment.applicationDriverVersion` direction. For `ApplicationDriverVersion.applicationDriver`, it's same-file (both in `application_driver/model.py`) — no import needed.
- `Task` → `Deployment`: Task imports Deployment — check for reverse. Deployment does NOT import Task, so no circular issue.
- `Backup` → `ApplicationInstance`: Backup is in `backup/backup.py`, ApplicationInstance is in `deployment/model.py`. Check if deployment/model.py imports from backup — it does not. No circular issue.
- `Restore` → `Backup`: Both in `backup/` package. Restore imports Backup — no reverse dependency. No circular issue.
- `BackupSchedule` → `Deployment`: Same analysis as Task. No circular issue.

**Decision**: Use `strawberry.lazy()` only where circular imports actually occur. Based on analysis, standard imports should work for all 8 resolvers. If circular imports arise during implementation, apply the lazy pattern.

## R4: Existing from_instance Pattern

**Decision**: Reuse existing `from_instance()` class methods for converting DB models to GraphQL types.

**Rationale**: Every GraphQL type already has a `from_instance()` class method that converts the SQLModel database entity to the Strawberry GraphQL type. The async resolvers will:
1. Fetch the related entity from the repository via UoW
2. Call `TypeName.from_instance(entity)` to convert it

This is consistent with how all existing resolvers work (e.g., `Environment.deployments`, `ApplicationDriver.versions`).

## R5: Repository Method Availability

**Decision**: Use existing `get()` methods on repositories accessed via UoW.

**Rationale**: All needed repositories are available on the UnitOfWork instance:
- `uow.environments.get(id)` → Environment
- `uow.application_driver_versions.get(id)` → ApplicationDriverVersion
- `uow.deployments.get(id)` or equivalent → Deployment
- `uow.application_instances` → ApplicationInstance (has base `get()`)
- `uow.backups` → Backup (has base `get()`)

For the Deployment resolver on Task/BackupSchedule, the UoW exposes `uow.deployments`. The base repository class provides a `get(id)` method.

**Note**: Some repositories (Task, Backup, Restore) have minimal implementations but inherit `get()` from `BaseSQLModelRepository`. The base `get()` does not use eager-loading, so the returned entity will have unloaded relationships — but this is fine because we only need the entity itself for the `from_instance()` conversion.
