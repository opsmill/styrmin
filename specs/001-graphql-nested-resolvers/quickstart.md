# Quickstart: Add Nested Object Resolvers to GraphQL Schema

## What This Feature Does

Adds 8 nested object fields to the GraphQL schema so clients can traverse entity relationships in a single query instead of making multiple round-trip requests.

**Before** (multiple queries):
```graphql
query {
  deployment(name: "my-app") {
    environmentId        # Returns UUID only
  }
}
# Client must make a second query to get environment details
```

**After** (single query):
```graphql
query {
  deployment(name: "my-app") {
    environmentId        # Still available (backward compatible)
    environment {        # NEW: returns full object inline
      id
      name
      config
    }
  }
}
```

## Files to Modify

| File | Change |
|------|--------|
| `backend/styrmin_backend/api/definitions/deployment/model.py` | Add `environment()` and `application_driver_version()` resolver methods |
| `backend/styrmin_backend/api/definitions/application_driver/model.py` | Add `application_driver()` resolver on `ApplicationDriverVersion` |
| `backend/styrmin_backend/api/definitions/deployment/model.py` | Add `application_driver_version()` resolver on `ApplicationInstance` |
| `backend/styrmin_backend/api/definitions/task/model.py` | Add `deployment()` resolver |
| `backend/styrmin_backend/api/definitions/backup/schedule.py` | Add `deployment()` resolver |
| `backend/styrmin_backend/api/definitions/backup/backup.py` | Add `instance()` resolver (rename existing `instance` Private field) |
| `backend/styrmin_backend/api/definitions/backup/restore.py` | Add `backup()` resolver (rename existing `instance` Private field) |

## Implementation Pattern

### Async resolver (most fields)

```python
@strawberry.field
async def environment(self, info: strawberry.Info) -> Environment:
    uow = info.context["uow"]
    async with uow:
        entity = await uow.environments.get(self.environment_id)
        if entity is None:
            msg = f"Environment {self.environment_id} not found"
            raise ValueError(msg)
        return Environment.from_instance(entity)
```

### Sync resolver (ApplicationDriverVersion.applicationDriver only)

```python
@strawberry.field
def application_driver(self) -> ApplicationDriver:
    return ApplicationDriver.from_instance(self.instance.application_driver)
```

## Post-Implementation Steps

```bash
# 1. Regenerate schema
uv run styrmin export graphql-schema schema.graphql

# 2. Regenerate SDK types
uv run invoke generate

# 3. Format and lint
uv run invoke format lint

# 4. Run tests
uv run invoke test
```

## Key Decisions

- **Async resolvers via UoW** (not eager-loading) — only fetches data when field is requested
- **Nullable handling** — Task.deployment returns `None` if `deployment_id` is `None`; non-nullable resolvers raise on missing data
- **No depth limit** — deferred to future optimization
- **No authorization changes** — nested fields inherit parent authorization (FR-012)
