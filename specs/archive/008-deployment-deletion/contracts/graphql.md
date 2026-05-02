# Contract: GraphQL Surface

## Mutation

```graphql
"""Request deletion of a deployment.

Patches `spec.deletionRequested = true` on the cluster-side StyrminDeployment.
The operator drives teardown; the deployment's lifecycle state is observed via
the existing status reporter and progresses DELETING -> DELETED.

The returned Task is born complete (status = SUCCESS) and serves as the audit
record on the deployment timeline.

Idempotent: a second call while the deployment is already DELETING returns the
most recent existing DELETE_DEPLOYMENT task without issuing another patch.
"""
deleteDeployment(id: UUID!): Task!
```

### Resolver guard table

| Current `Deployment.status` | Behaviour |
|------------------------------|-----------|
| `PENDING`, `DEPLOYING`, `RUNNING`, `FAILED` | Patch `spec.deletionRequested = true`; create new `DELETE_DEPLOYMENT` Task (status `SUCCESS`); emit timeline event; return Task. |
| `DELETING` | Return the most recent existing `DELETE_DEPLOYMENT` Task (idempotent). Do **not** re-patch (CEL rule would no-op anyway, but the round-trip is wasteful and timeline duplication must be avoided). If for some reason no prior task exists (e.g., legacy / migrated row), fall through to the patch path. |
| `DELETED` | Raise `DeploymentNotFoundError` → GraphQL error code `DEPLOYMENT_NOT_FOUND`. |
| `RESTORING` | Raise `DeploymentRestoringError` → GraphQL error code `DEPLOYMENT_RESTORING`. |

### Visibility guard

The resolver short-circuits when `Deployment.deleted_at IS NOT NULL` even before reading `status`, raising `DeploymentNotFoundError`. This is independent of the `includeDeleted` read filter because it is a write-side guard: tombstoned records cannot be the target of a destructive write.

## Query argument

```graphql
"""List deployments. By default, deleted (tombstoned) deployments are excluded.
Pass `includeDeleted: true` to surface them — they appear with a non-null
`deletedAt` field."""
deployments(includeDeleted: Boolean = false): [Deployment!]!
```

The default value is `false`. `DELETING` rows have `deleted_at IS NULL` until the terminal `DELETED` transition, so they remain visible in the default view.

`deployment(id: UUID!): Deployment` is **unfiltered** with respect to `deleted_at`. Direct id lookup always returns the record (live, deleting, or tombstoned).

## Type additions

### `Deployment.deletedAt` (NEW)

```graphql
type Deployment {
  ...
  """Timestamp when the deployment was tombstoned. Null for live deployments
  (including those currently being deleted — DELETING state)."""
  deletedAt: DateTime
}
```

### `DeploymentState` enum (additions)

```graphql
enum DeploymentState {
  PENDING
  DEPLOYING
  RUNNING
  RESTORING
  FAILED
  DELETING   # NEW
  DELETED    # NEW
}
```

### `TaskType` enum (addition)

```graphql
enum TaskType {
  ...
  DELETE_DEPLOYMENT
}
```

## Error codes (`StructuredErrorExtension` extensions.code)

| Code | When raised | Service exception class |
|------|-------------|-------------------------|
| `DEPLOYMENT_NOT_FOUND` | id is unknown OR deployment is `DELETED` (intentional conflation per spec FR-009 / R6 in research) | `DeploymentNotFoundError` |
| `DEPLOYMENT_RESTORING` | Delete attempted while restore in progress | `DeploymentRestoringError` |

`DEPLOYMENT_RESTORING` is the only *new* error code. `DEPLOYMENT_NOT_FOUND` is reused.

## SDK (graphql-codegen) regeneration

After the schema is exported, run `uv run invoke generate` to regenerate:

- Pydantic types under `python_sdk/src/styrmin_sdk/graphql/_generated/`
- Frontend TypeScript bindings under `frontend/src/graphql/_generated/`

The propagation tests (see `tasks.md` Phase 4) will fail until both regenerations have run and the result is committed.

## Schema file

After mutation/argument/field/enum additions, regenerate `schema.graphql` at repo root:

```bash
uv run styrmin export graphql-schema schema.graphql
```

The resulting diff is committed alongside the implementation.
