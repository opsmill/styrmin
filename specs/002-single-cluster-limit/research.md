# Research: Enforce Single-Cluster Limit

**Feature**: `002-single-cluster-limit` | **Date**: 2026-03-28

## R1: Single-Cluster Enforcement Strategy

**Decision**: Service-layer check using existing `get_all()` repository method before cluster creation.

**Rationale**: The `create_cluster` service already validates name uniqueness via `get_by_name()`. Adding a count/existence check before creation follows the same pattern. The service layer is the correct enforcement point per the layered architecture (Constitution Principle III). No database migration is needed.

**Alternatives considered**:
- **Database constraint (CHECK or partial unique index)**: Would provide strongest guarantee against race conditions but requires a migration, which is out of scope.
- **New `count()` repository method with `SELECT FOR UPDATE`**: Provides pessimistic locking for concurrency safety. Overkill for an admin-only operation.
- **GraphQL middleware/directive**: Would violate the layered architecture by putting business logic outside the service layer.

**Concurrency note**: The check-then-create pattern has a theoretical race window under PostgreSQL READ COMMITTED isolation. For a single-cluster admin operation, this is acceptable. If concurrent creation occurs, the second request would either succeed (creating an unsupported multi-cluster state) or fail on the UNIQUE name constraint. A future enhancement could add a database-level constraint if needed.

## R2: Error Type for Cluster Limit

**Decision**: New `ClusterLimitReachedError` exception class in `services/exceptions.py` with error code `"CLUSTER_LIMIT_REACHED"`.

**Rationale**: Follows existing typed error pattern (Constitution Principle IV). Distinct from `ClusterAlreadyExistsError` (name uniqueness) — this is a system-wide limit, not a naming conflict. The error code is specific enough for clients to differentiate and display an appropriate message.

**Alternatives considered**:
- **Reuse `ClusterAlreadyExistsError`**: Semantically incorrect — the issue isn't a name collision but a system limit.
- **Generic `ServiceError`**: Loses specificity for client-side handling.
- **GraphQL union type (`Cluster | ClusterLimitReached`)**: Would require a schema change and new type definition. Current pattern uses exception-based errors enriched via GraphQL extensions, which is sufficient.

## R3: Default Cluster Name

**Decision**: Make `name` parameter optional with default `"default"` at both the service layer and GraphQL mutation level.

**Rationale**: The Strawberry `@strawberry.mutation` signature `name: str = "default"` generates a GraphQL field with a default value. This is backward-compatible — existing callers that provide a name are unaffected. The frontend pre-fills the form field with "default" for visual consistency.

**Alternatives considered**:
- **Frontend-only default**: Would not apply to API-only callers (CLI, SDK). Server-side default ensures consistency across all clients.
- **Backend-only default (keep `name: String!` in GraphQL)**: Forces all clients to always provide a name, even when they don't care. Less ergonomic.
- **Both frontend and backend**: Selected approach. Frontend pre-fills for UX; backend default for API completeness.

**Schema impact**: `createCluster(name: String! = "default", config: JSON)` — the `!` remains (non-null), but the field now has a default value. Requires `schema.graphql` regeneration and SDK type regeneration.

## R4: Frontend Layout Strategy

**Decision**: Conditionally render single-cluster view vs. empty state based on `clusters.length` from the existing `useListClustersQuery()` hook.

**Rationale**: The query already fetches all clusters. Checking `data.clusters.length > 0` is the simplest conditional. No additional queries needed.

**Layout changes**:
- **Cluster exists**: Show cluster details directly (single card/panel, no grid). Hide "New Cluster" button.
- **No cluster**: Show "New Cluster" button with empty state message. Creation dialog pre-fills name with "default".

**Alternatives considered**:
- **Separate `clusterCount` query**: Unnecessary overhead; the list query already provides this information.
- **Disable button instead of hiding**: Hiding is cleaner for single-cluster semantics — a disabled button still implies the action is normally available.
- **Redirect to cluster detail page**: Overcomplicates routing; a single-item layout on the Settings page is simpler and keeps the existing URL structure.
