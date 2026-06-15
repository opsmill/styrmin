# ADR-031: Dual-identifier resolution — optional `<resource>Id` / `<resource>Name` validated at the service layer

**Status**: Accepted
**Date**: 2026-05-17
**Source**: specs/archive/001-graphql-name-lookup/research.md (R2, R3, R4, R7)

## Context

Operators routinely refer to platform resources by human-readable name, not UUID. The original GraphQL surface only accepted UUIDs (`cluster(clusterId: UUID!)`, `environment(environmentId: UUID!)`, `deleteCluster(clusterId: UUID!)`, …), forcing the SDK and CLI to do their own lookup-by-name round-trips, and operators using `curl` / GraphiQL to first run `clusters { id name }` just to find the UUID they wanted to act on.

The natural fix is "let queries and mutations accept names". The design space spans three orthogonal questions:

1. **Wire shape** — separate `<resource>ByName(name: String!)` operations, or fold name into existing operations as an optional parameter?
2. **Where do you validate "exactly one of id/name"** — at the GraphQL layer, at the service layer, or in an input type?
3. **Where does name lookup happen** — server-side resolution from name → entity, or client-side resolution from name → UUID before the call?

Environment names additionally need cluster scoping: a `(name, cluster_id)` unique constraint is the source of truth for "which environment do you mean by `production`?".

## Decision

Treat dual-identifier resolution as a **service-layer pattern**, with thin wire surfaces on both ends:

1. **GraphQL shape**: every operation that historically took `<resource>Id: UUID!` now takes a pair of nullable parameters: `<resource>Id: UUID = null` and `<resource>Name: String = null`. The change is additive; existing UUID-only callers are unaffected. Environment-name operations additionally accept `clusterId: UUID = null` / `clusterName: String = null` to scope the lookup.
2. **Validation location**: the GraphQL resolver is thin — it forwards both optional arguments to a service-layer helper. The helper validates mutual exclusivity, performs the lookup, and raises a typed error.
3. **Service helper shape**: pattern is `resolve_<resource>(uow, <resource>_id=None, <resource>_name=None) -> <Resource>`. It raises `AmbiguousIdentifierError` (mapped to GraphQL `VALIDATION_ERROR`) when both are provided, neither is provided, or when an environment lookup omits its cluster scope. It raises `<Resource>NotFoundError` when the identifier doesn't match a row.
4. **Lookup happens server-side**: SDK / CLI just pass the operator's input straight through to GraphQL variables. The name → entity resolution lives once, in the service layer, with the canonical scoping rules.
5. **Name uniqueness scopes** that back the lookup:
   - `Cluster.name` — globally unique (single-cluster platform per [[0011-scoped-tombstone-aware-name-uniqueness]] is unrelated here — clusters themselves remain globally unique).
   - `Environment.name` — `UniqueConstraint("name", "cluster_id")`. The repository method is `EnvironmentRepository.get_by_name_in_cluster(name, cluster_id)`; the old global `get_by_name` is removed.
   - `Deployment.name` — `(environment_id, name)` partial unique index (already established by [[0011-scoped-tombstone-aware-name-uniqueness]]).

## Consequences

- Operators get name-based access uniformly across queries and mutations without API-surface sprawl (no `clusterByName`, no input unions, no separate operations).
- The "exactly one of id/name" invariant has one home — the service-layer helper — and one error code (`VALIDATION_ERROR` via `AmbiguousIdentifierError`). Adding a new resource that needs the same treatment is a copy-paste of the helper, not a new pattern.
- The SDK stays thin: every resource method accepts both `<resource>_id` and `<resource>_name` as optional parameters and forwards them as GraphQL variables. The CLI similarly accepts a positional name and an `--id` flag for UUID fallback.
- Mutual exclusivity is caught with a clear message instead of GraphQL doing something silent (e.g., picking one over the other) — operators get a typed error code they can branch on programmatically.
- The pattern is additive at every layer: introducing it does not break any existing call site that used UUIDs.

## Alternatives Considered

- **Separate named operations (`clusterByName`, `environmentByName`, …)**: rejected. Doubles the API surface for every resource and creates inconsistent patterns ("does `delete` take the name version?"). The optional-parameter pattern adds one nullable per operation and is symmetric across read / write.
- **Validate mutual exclusivity in the GraphQL layer**: rejected. Violates the layered-architecture principle — validation logic that depends on what a *valid resource lookup* looks like belongs with the service that owns lookups. GraphQL resolvers become thin pass-throughs, which they should be.
- **Strawberry input types wrapping `{ id?, name? }`**: rejected. Adds an indirection (`cluster(input: ClusterIdentifierInput!)`) for a two-field shape that's clearer as positional optionals. Also doesn't match how existing operations expose primary IDs.
- **Union input types**: rejected. Strawberry doesn't support GraphQL input unions at all.
- **Client-side name → UUID resolution in SDK/CLI**: rejected. Forces every client to implement its own lookup logic, with race conditions between the lookup and the subsequent operation, and duplicates the name-scoping rules (cluster-scoped environments, env-scoped deployments) across every client.
- **Add optional `cluster_id` to existing `get_by_name`**: rejected. Mutating an abstract repository method's signature is riskier than adding an explicit new method named for its scope (`get_by_name_in_cluster`).
