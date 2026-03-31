# Research: Name-Based Resource Lookup

**Feature**: 001-graphql-name-lookup
**Date**: 2026-03-29

## R1: Database Schema Change Strategy (No Alembic)

**Decision**: Modify the SQLModel definition only. No migration script needed -- project is pre-production.

**Rationale**: The project is not in production. Schema is managed via `SQLModel.metadata.create_all()` in `backend/styrmin_backend/db/utils.py:57-61`. Changing the model definition is sufficient; `metadata.create_all()` handles fresh database creation automatically.

**Implementation approach**:
1. Change `Environment` model: replace `Field(unique=True)` on `name` with a `UniqueConstraint("name", "cluster_id")` in `__table_args__`
2. `metadata.create_all()` handles database creation automatically
3. No migration script needed (pre-production)

## R2: Resolver Pattern for Dual Identifiers (ID vs Name)

**Decision**: Create resolver helper functions in the service layer that accept optional `id` and `name` parameters, validate mutual exclusivity, and return the resolved entity.

**Rationale**: The existing pattern has services accepting a single `entity_id: UUID`. Adding optional name params at the service layer keeps validation logic centralized and follows the layered architecture (Constitution III). GraphQL resolvers stay thin -- they pass both optional params to the service.

**Alternatives considered**:
- Validation in GraphQL layer: Rejected -- violates layered architecture principle
- Strawberry input types: Rejected -- adds complexity; optional params on existing operations are simpler and backward-compatible
- Union input types: Rejected -- Strawberry doesn't support GraphQL input unions

**Implementation pattern**:
```python
# Service layer helper
async def resolve_cluster(
    uow: UnitOfWork,
    cluster_id: UUID | None = None,
    cluster_name: str | None = None,
) -> Cluster:
    if cluster_id and cluster_name:
        raise AmbiguousIdentifierError("Provide either cluster_id or cluster_name, not both")
    if cluster_id:
        cluster = await uow.clusters.get(cluster_id)
    elif cluster_name:
        cluster = await uow.clusters.get_by_name(cluster_name)
    else:
        raise AmbiguousIdentifierError("Either cluster_id or cluster_name is required")
    if cluster is None:
        raise ClusterNotFoundError()
    return cluster
```

## R3: Environment Repository -- Scoped Name Lookup

**Decision**: Add `get_by_name_in_cluster(name: str, cluster_id: UUID)` method to `EnvironmentRepository`.

**Rationale**: The existing `get_by_name(name: str)` works with globally unique names. Once uniqueness becomes per-cluster, name-only lookup is ambiguous. A new method scoped to cluster_id is needed. The old `get_by_name` can be removed since it will no longer be correct.

**Alternatives considered**:
- Add optional `cluster_id` param to existing `get_by_name`: Rejected -- changing the signature of an abstract method is riskier; a new explicit method is clearer
- Filter in service layer after `get_by_name`: Rejected -- would return wrong results if names collide across clusters

## R4: GraphQL Schema Design for Optional Name Parameters

**Decision**: Add optional name parameters alongside existing ID parameters on all affected queries and mutations. Use `None` defaults for backward compatibility.

**Rationale**: This is purely additive -- existing callers that pass only IDs are unaffected. Strawberry supports optional parameters with `None` defaults natively.

**Schema changes**:
```graphql
# Queries
cluster(clusterId: UUID = null, clusterName: String = null): Cluster
environment(environmentId: UUID = null, environmentName: String = null, clusterId: UUID = null, clusterName: String = null): Environment

# Mutations
deleteCluster(clusterId: UUID = null, clusterName: String = null): String
deleteEnvironment(environmentId: UUID = null, environmentName: String = null, clusterId: UUID = null, clusterName: String = null): String
createEnvironment(name: String!, clusterId: UUID = null, clusterName: String = null, config: JSON = null): Environment
deploy(..., environmentId: UUID = null, environmentName: String = null, clusterId: UUID = null, clusterName: String = null): Task
```

**Alternatives considered**:
- Separate named queries (e.g., `clusterByName`): Rejected -- creates API surface sprawl and inconsistent patterns
- Input types: Rejected -- unnecessary indirection for 1-2 optional params

## R5: SDK Parameter Design

**Decision**: Add optional name parameters to SDK resource methods, mirroring the GraphQL API. Names are passed as GraphQL variables; resolution happens server-side.

**Rationale**: Per clarification (Q3), the SDK passes names through to the API. This keeps the SDK thin and avoids duplicating lookup logic. The CLI stays equally thin -- it passes user-provided names directly to the SDK.

**Implementation pattern**:
```python
# SDK resource method
async def get(
    self,
    cluster_id: str | UUID | None = None,
    cluster_name: str | None = None,
) -> Cluster:
    variables: dict[str, Any] = {}
    if cluster_id is not None:
        variables["clusterId"] = str(cluster_id)
    if cluster_name is not None:
        variables["clusterName"] = cluster_name
    result = await self._execute("get_cluster", variables)
    ...
```

## R6: CLI Parameter Pattern (Cyclopts)

**Decision**: Change positional parameters from UUID to name (string). Add `--id` flag for UUID fallback. For environment commands, add `--cluster` (defaults to "default") and `--cluster-id` flags.

**Rationale**: Per clarification (Q1 and Q2), names are the primary identifier. Cyclopts supports `Annotated` types with `Parameter` for flags.

**Implementation approach**:
- New type aliases: `ClusterName`, `EnvironmentName` (no UUID validation, just strings)
- `--id` flag: `Annotated[str | None, Parameter(name="--id", help="UUID of the resource")]` with UUID validation
- `--cluster` flag: `Annotated[str, Parameter(name="--cluster", help="Cluster name")]` defaulting to `"default"`
- `--cluster-id` flag: `Annotated[str | None, Parameter(name="--cluster-id", help="UUID of the cluster")]` with UUID validation
- Mutual exclusion validated at the CLI command level before calling SDK

## R7: Error Handling for Dual Identifiers

**Decision**: Add a new `AmbiguousIdentifierError` exception to the service layer. Use existing `ErrorCode.VALIDATION_ERROR` code.

**Rationale**: The existing error extension (`StructuredErrorExtension` in `backend/styrmin_backend/api/errors.py`) catches `ServiceError` subclasses and enriches GraphQL errors. A new exception subclass integrates naturally.

**Error cases**:
1. Both ID and name provided → `AmbiguousIdentifierError("Provide either ID or name, not both")`
2. Neither ID nor name provided → `AmbiguousIdentifierError("Either ID or name is required")`
3. Environment name without cluster context → `AmbiguousIdentifierError("Cluster identifier required when looking up environment by name")`
