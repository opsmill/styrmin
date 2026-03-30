# Quickstart: Name-Based Resource Lookup

**Feature**: 001-graphql-name-lookup
**Date**: 2026-03-29

## Implementation Order

Follow this order to maintain a working system at each step:

### Step 1: Database Model Change

1. Update `Environment` model in `backend/styrmin_backend/db/models.py`:
   - Remove `unique=True` from `name` field
   - Add `__table_args__` with `UniqueConstraint("name", "cluster_id")`
   - No migration script needed (pre-production)

### Step 2: Repository Layer

1. Add `get_by_name_in_cluster(name, cluster_id)` to `EnvironmentRepository`
2. Update `create_environment` service to use per-cluster uniqueness check
3. Remove or deprecate global `get_by_name` on `EnvironmentRepository`

### Step 3: Service Layer -- Resolver Helpers

1. Add `AmbiguousIdentifierError` to `exceptions.py`
2. Add `resolve_cluster(uow, cluster_id, cluster_name)` to `clusters.py`
3. Add `resolve_environment(uow, environment_id, environment_name, cluster_id, cluster_name)` to `environments.py`
4. Update existing service functions to use resolvers

### Step 4: GraphQL API

1. Update `query.py` -- add optional name params to `cluster()` and `environment()` queries
2. Update `mutation.py` -- add optional name params to `delete_cluster()`, `delete_environment()`, `create_environment()`, `deploy()`
3. Regenerate `schema.graphql`: `uv run styrmin export graphql-schema schema.graphql`

### Step 5: SDK

1. Update `.graphql` query files to include optional name variables
2. Regenerate SDK types: `uv run invoke generate`
3. Update SDK resource methods to accept optional name parameters
4. Update SDK resource methods to build variable dicts conditionally

### Step 6: CLI

1. Add new type aliases to `types.py` (ClusterName, EnvironmentName, optional ID flags)
2. Update cluster commands (get, delete) -- name as positional, `--id` as flag
3. Update environment commands (get, delete, create) -- name as positional, `--cluster`/`--cluster-id` flags
4. Update deployment create command -- environment name + cluster flags
5. Update backup-locations assign/unassign -- environment name + cluster flags

### Step 7: Tests

1. Backend unit tests for resolver helpers (both-provided, neither-provided, name-only, id-only)
2. Backend unit tests for per-cluster environment uniqueness
3. Backend integration tests for name-based GraphQL queries and mutations
4. CLI tests for new parameter patterns

## Key Commands

```bash
# Format and lint
uv run invoke format lint

# Regenerate GraphQL schema
uv run styrmin export graphql-schema schema.graphql

# Regenerate SDK types
uv run invoke generate

# Run backend tests
uv run invoke test

# Run CLI tests (if applicable)
cd cli && uv run pytest
```
