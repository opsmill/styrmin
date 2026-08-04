# Contract: GraphQL `deployment(name, environmentId)` query

This contract defines the new top-level GraphQL query that allows lookup of a single deployment by its natural identity `(name, environmentId)`.

## Schema

The existing `deployment(deploymentId: UUID!)` query is extended to accept an alternative argument shape:

```graphql
extend type Query {
  """
  Fetch a single deployment by its natural identity.

  Provide either:
    - deploymentId, OR
    - name AND environmentId.

  Internal/system-managed deployments are hidden (returns null).
  Returns null if no matching deployment exists.
  """
  deployment(
    deploymentId: UUID
    name: String
    environmentId: UUID
  ): Deployment
}
```

Existing call sites that pass `deploymentId` only continue to work unchanged.

### Argument validation

The resolver enforces, at runtime, **exactly one** of:
- `deploymentId` set, with `name` and `environmentId` unset, OR
- `name` AND `environmentId` set, with `deploymentId` unset.

Any other combination raises a `ServiceError` with code `INVALID_DEPLOYMENT_LOOKUP_ARGS` and the message `"specify either deploymentId or (name + environmentId), not both"` — caught by `StructuredErrorExtension` and surfaced as a structured GraphQL error.

### Return semantics

| Database state | Returned value |
|---|---|
| matching deployment exists, `internal=False` | the `Deployment` |
| matching deployment exists, `internal=True` | `null` (hidden, matches `deployment(deploymentId)` behaviour) |
| no matching deployment | `null` |
| matching deployment is soft-deleted (`deletedAt IS NOT NULL`) | `null` (matches existing behaviour) |

The new shape never raises a "not found" error — it returns `null`. The `INVALID_DEPLOYMENT_LOOKUP_ARGS` error is the only error path specific to the new shape.

## Service-layer contract

```python
async def get_deployment_by_name(
    *,
    name: str,
    environment_id: UUID,
    uow: UnitOfWork,
) -> Deployment | None:
    """Return the non-internal, non-deleted deployment matching (name, environment_id), or None."""
```

- **Repository call**: `uow.deployments.find_one_by_name_and_environment(name=name, environment_id=environment_id)`.
- **Filters**: excludes `internal=True` and `deletedAt IS NOT NULL` rows.
- **No exceptions** for "not found"; returns `None`.
- **Strict equality**: `name` is matched exactly (no fuzzy matching, no case-insensitivity in v1).

The existing `get_deployment(deployment_id, uow)` function is unchanged. The new resolver function in `query.py` dispatches to whichever service function matches the argument shape.

## Performance

- The repository query is bound by the existing index supporting `unique_deployment_name_per_environment`. No new indexes are required.
- The query is O(1) on database side (single-row lookup).
- No N+1 risks: the resolver returns a single `Deployment` (or `null`), not a list.

## Backward compatibility

- The schema change is **purely additive** — existing operations using `deployment(deploymentId: $id)` are unaffected.
- The signature of the existing `Query.deployment` field is widened (its `deploymentId` argument becomes optional), which is a backward-compatible change in GraphQL schema evolution. No existing client breaks.
- After this change, `schema.graphql` MUST be regenerated (`uv run styrmin export graphql-schema schema.graphql`) and SDK types regenerated (`uv run invoke generate`). CI fails otherwise.

## Test coverage required (per Constitution §V)

A propagation test is mandatory. Three cases at minimum:

1. **Found case** — a real (non-internal, non-deleted) deployment exists; the resolver returns it.
2. **Not-found case** — no deployment matches; the resolver returns `null`.
3. **Internal-deployment hidden** — an `internal=True` deployment exists for `(name, environment_id)`; the resolver returns `null`.

A fourth case for soft-deleted deployments may be added if the test infrastructure supports it; otherwise the existing `deployment(deploymentId)` test's coverage of soft-delete is sufficient because both code paths share the same repository filter.

A fifth, "argument-validation" case (passing both `deploymentId` and `name`) MUST also be covered — this is a new error path introduced by the schema change.
