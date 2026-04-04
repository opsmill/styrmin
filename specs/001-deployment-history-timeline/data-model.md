# Data Model: Deployment History Timeline

**Date**: 2026-04-03  
**Feature**: 001-deployment-history-timeline

## Existing Entities (no schema changes)

### Task

Already exists in `backend/styrmin_backend/db/models.py`.

| Field | Type | Notes |
|-------|------|-------|
| id | UUID | PK (from StyrminModel) |
| created_on | datetime (tz-aware) | server-default now() — **needs GraphQL exposure** |
| updated_on | datetime (tz-aware) | server-default now(), onupdate now() — **needs GraphQL exposure** |
| type | TaskType enum | NOOP, CREATE_INSTANCE, DELETE_INSTANCE, UPDATE_INSTANCE, UPGRADE_INSTANCE, STOP_COMPONENTS, START_COMPONENTS, RUN_JOB |
| status | TaskStatus enum | PENDING, RUNNING, SUCCESS, FAILED |
| message | str or null | Error/status message |
| prefect_flow_run_id | UUID or null | Link to Prefect flow run |
| deployment_id | UUID | FK → deployment.id |

**Relationships**: `deployment: Deployment` (many-to-one)

### Deployment

Already exists. Relevant fields for this feature:

| Field | Type | Notes |
|-------|------|-------|
| id | UUID | PK |
| name | str | Unique |
| application_version | str | Current desired version |
| active_application_instance_id | UUID or null | FK → applicationinstance.id |

**Relationships**:
- `tasks: list[Task]` (one-to-many) — already defined
- `application_instances: list[ApplicationInstance]` (one-to-many) — all historical instances
- `active_application_instance: ApplicationInstance or null` (one-to-one) — current active

### ApplicationInstance

Already exists. Key fields for context diff:

| Field | Type | Notes |
|-------|------|-------|
| id | UUID | PK |
| created_on | datetime (tz-aware) | When instance was created |
| application_version | str | Version at this point in time |
| context | dict (JSON) or null | Full GlobalContext — the diff source |
| deployment_id | UUID | FK → deployment.id |

**Context structure** (GlobalContext fields): cluster, environment, deployment, instance, app, labels, components, utilities, parameters, services, deployed_services.

## New Data Structures (no database changes)

### TaskTimelineEntry (API-level concept)

Represents a task enriched with version and diff data for the timeline. Not a database model — constructed in the service or resolver layer.

| Field | Type | Notes |
|-------|------|-------|
| id | UUID | From Task |
| type | str | Task type |
| status | str | Task status |
| message | str or null | Task message |
| created_on | datetime | Task creation timestamp |
| updated_on | datetime | Task last update timestamp |
| application_version | str or null | Version from correlated ApplicationInstance |
| context_diff | ContextDiff or null | Diff between this and previous operation's context |

### ContextDiff (API-level concept)

Represents the diff between two ApplicationInstance context objects.

| Field | Type | Notes |
|-------|------|-------|
| previous_context | dict or null | Context from previous operation (null for first) |
| current_context | dict or null | Context from this operation |
| changes | list[ContextChange] | List of individual changes |

### ContextChange

| Field | Type | Notes |
|-------|------|-------|
| path | str | Dot-notation path to changed field (e.g., "deployment.version") |
| action | str | "added", "removed", "modified" |
| old_value | JSON or null | Previous value (null for additions) |
| new_value | JSON or null | New value (null for removals) |

## Entity Relationships (for this feature)

```
Deployment (1) ──── (*) Task
     │                    │
     │                    │ (correlated by timestamp)
     │                    ▼
     └──── (*) ApplicationInstance
                  │
                  └── context (JSON) ← diff source
```

## Version Correlation Strategy

To associate an `application_version` with each task:

1. Query all `ApplicationInstance` records for the deployment, ordered by `created_on`
2. For each task, find the ApplicationInstance whose `created_on` is closest to (but not after) the task's `created_on`
3. If no instance exists before the task, use the earliest instance

This avoids schema changes while providing accurate historical version data.

## Validation Rules

- Tasks without a deployment_id cannot appear in the timeline (enforced by FK constraint)
- Context diff is only computed when both current and previous ApplicationInstance have non-null context fields
- Timeline entries are always ordered by `created_on DESC` (newest first)
