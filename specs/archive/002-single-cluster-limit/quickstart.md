# Quickstart: Enforce Single-Cluster Limit

**Feature**: `002-single-cluster-limit` | **Date**: 2026-03-28

## Overview

This feature adds a single-cluster constraint to Styrmin. After implementation:
- The API rejects `createCluster` when a cluster already exists
- The cluster name defaults to "default" when not specified
- The Settings page shows a single-cluster layout instead of a grid

## Implementation Order

### Step 1: Backend — Error Type

Add `ClusterLimitReachedError` to `backend/styrmin_backend/services/exceptions.py`:

```python
class ClusterLimitReachedError(ServiceError):
    error_code = "CLUSTER_LIMIT_REACHED"
    default_message = "Only one cluster is allowed. Delete the existing cluster before creating a new one."
```

### Step 2: Backend — Service Layer

Modify `create_cluster` in `backend/styrmin_backend/services/clusters.py`:

1. Make `name` parameter optional with default `"default"`
2. Before the existing name-uniqueness check, add a cluster-existence check:
   - Call `uow.clusters.get_all()`
   - If any clusters exist, raise `ClusterLimitReachedError`

### Step 3: Backend — GraphQL Mutation

Update `create_cluster` mutation in `backend/styrmin_backend/api/schema/mutation.py`:

1. Change `name: str` to `name: str = "default"` in the method signature
2. Regenerate schema: `uv run styrmin export graphql-schema schema.graphql`
3. Regenerate SDK types: `uv run invoke generate`

### Step 4: Backend — Tests

Add tests in `backend/tests/unit/services/test_cluster_services.py`:

- Test that `create_cluster` raises `ClusterLimitReachedError` when a cluster exists
- Test that `create_cluster` uses "default" name when none is provided
- Test that deletion followed by creation works correctly

### Step 5: Frontend — CreateClusterDialog

Update `frontend/src/pages/settings/CreateClusterDialog.tsx`:

- Set `defaultValues: { name: "default" }` in the `useForm` call

### Step 6: Frontend — SettingsPage

Update `frontend/src/pages/settings/SettingsPage.tsx`:

- Conditionally hide `CreateClusterDialog` when `data.clusters.length > 0`
- Replace grid layout with single-item display when a cluster exists
- Keep empty state + "New Cluster" button when no clusters exist

### Step 7: Lint, Format, Validate

```bash
uv run invoke format lint
cd frontend && pnpm lint
uv run styrmin export graphql-schema schema.graphql
uv run invoke generate
```

## Key Files

| File | Change |
|------|--------|
| `backend/styrmin_backend/services/exceptions.py` | Add `ClusterLimitReachedError` |
| `backend/styrmin_backend/services/clusters.py` | Add existence check, default name |
| `backend/styrmin_backend/api/schema/mutation.py` | Make `name` optional with default |
| `backend/tests/unit/services/test_cluster_services.py` | Add constraint tests |
| `frontend/src/pages/settings/SettingsPage.tsx` | Conditional layout |
| `frontend/src/pages/settings/CreateClusterDialog.tsx` | Default name value |
| `schema.graphql` | Regenerated |
| `python_sdk/src/styrmin_sdk/graphql/_generated/` | Regenerated |

## Testing

```bash
# Backend
uv run invoke test

# Frontend
cd frontend && pnpm test
```
