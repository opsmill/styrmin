# Data Model: Add Nested Object Resolvers to GraphQL Schema

## Entities

No new entities are introduced. This feature adds resolver fields to existing GraphQL types that expose already-existing database relationships.

## Relationship Map

```text
Deployment ──────────── Environment          (non-nullable, via environment_id)
Deployment ──────────── ApplicationDriverVersion (non-nullable, via application_driver_version_id)
ApplicationDriverVersion ── ApplicationDriver    (non-nullable, via application_driver_id)
ApplicationInstance ──── ApplicationDriverVersion (non-nullable, via application_driver_version_id)
Task ───────────────── Deployment              (nullable, via deployment_id)
BackupSchedule ─────── Deployment              (non-nullable, via deployment_id)
Backup ─────────────── ApplicationInstance     (non-nullable, via instance_id)
Restore ────────────── Backup                  (non-nullable, via backup_id)
```

## New Resolver Fields by Type

### Deployment

| Field | Return Type | Nullable | FK Source | Resolver Pattern |
|-------|------------|----------|-----------|-----------------|
| `environment` | `Environment` | No | `environment_id` | Async UoW |
| `applicationDriverVersion` | `ApplicationDriverVersion` | No | `application_driver_version_id` | Async UoW |

### ApplicationDriverVersion

| Field | Return Type | Nullable | FK Source | Resolver Pattern |
|-------|------------|----------|-----------|-----------------|
| `applicationDriver` | `ApplicationDriver` | No | `application_driver_id` | Sync (already eager-loaded) |

### ApplicationInstance

| Field | Return Type | Nullable | FK Source | Resolver Pattern |
|-------|------------|----------|-----------|-----------------|
| `applicationDriverVersion` | `ApplicationDriverVersion` | No | `application_driver_version_id` | Async UoW |

### Task

| Field | Return Type | Nullable | FK Source | Resolver Pattern |
|-------|------------|----------|-----------|-----------------|
| `deployment` | `Deployment | None` | Yes | `deployment_id` | Async UoW |

### BackupSchedule

| Field | Return Type | Nullable | FK Source | Resolver Pattern |
|-------|------------|----------|-----------|-----------------|
| `deployment` | `Deployment` | No | `deployment_id` | Async UoW |

### Backup

| Field | Return Type | Nullable | FK Source | Resolver Pattern |
|-------|------------|----------|-----------|-----------------|
| `instance` | `ApplicationInstance` | No | `instance_id` | Async UoW |

### Restore

| Field | Return Type | Nullable | FK Source | Resolver Pattern |
|-------|------------|----------|-----------|-----------------|
| `backup` | `Backup` | No | `backup_id` | Async UoW |

## Validation Rules

- **Non-nullable resolvers**: If `repository.get(id)` returns `None`, raise an exception (data integrity violation) per FR-013
- **Nullable resolvers**: If FK is `None`, return `None` without querying the database
- **Backward compatibility**: All existing `*Id` fields remain unchanged (FR-009)

## State Transitions

N/A — No state changes introduced. All new fields are read-only resolvers.
