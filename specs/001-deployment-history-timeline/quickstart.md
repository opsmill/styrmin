# Quickstart: Deployment History Timeline

**Feature**: 001-deployment-history-timeline  
**Date**: 2026-04-03

## What This Feature Does

Adds a deployment history timeline to the deployment detail page, showing all operations (create, update, upgrade, etc.) with timestamps, version info, and context diffs between operations.

## Implementation Layers

### 1. Backend — Repository Layer

**File**: `backend/styrmin_backend/repository/tasks.py`

Add `find_by_deployment(deployment_id: UUID) -> list[TaskEntity]` method that queries tasks filtered by `deployment_id`, ordered by `created_on DESC`.

### 2. Backend — Service Layer

**File**: `backend/styrmin_backend/services/tasks.py` (or new `services/deployment_timeline.py`)

Add a service function that:
- Fetches tasks for a deployment via the new repository method
- Fetches all `ApplicationInstance` records for the deployment
- Correlates each task with the application version active at that time
- Computes context diffs between consecutive ApplicationInstance contexts
- Returns enriched timeline entries

### 3. Backend — GraphQL Layer

**Files**:
- `backend/styrmin_backend/api/definitions/task/model.py` — Add `created_on`, `updated_on` fields
- `backend/styrmin_backend/api/definitions/deployment_timeline/` — New types: `DeploymentTimelineEntry`, `ContextDiff`, `ContextChange`
- `backend/styrmin_backend/api/schema/query.py` — Add `deployment_timeline(deployment_id)` query

### 4. Schema Regeneration

After GraphQL changes:
```bash
uv run styrmin export graphql-schema schema.graphql
uv run invoke generate
```

### 5. Frontend — GraphQL Query

**File**: `frontend/src/graphql/queries/get_deployment_timeline.graphql`

See `contracts/query-deployment-timeline.graphql` for the query definition.

### 6. Frontend — Timeline UI

**File**: `frontend/src/pages/deployments/DeploymentDetailPage.tsx` (new section)

Add a "History" Card section using the existing Collapsible pattern (same as backups/restores). Each task is a row; expanding shows the context diff.

## Key Patterns to Follow

- **Repository**: Use `select().where().order_by()` with `selectinload()` for eager loading
- **Service**: Use `async with uow:` context manager pattern
- **GraphQL**: Use `Type.from_instance()` for domain→GraphQL conversion
- **Frontend**: Use urql `useQuery` hook, Radix Card/Collapsible components

## Testing Approach

- **Unit tests**: Service logic for version correlation and context diffing
- **Integration tests**: GraphQL query returns correct timeline data
- **Frontend tests**: Timeline component renders tasks, handles empty state, expands diffs
