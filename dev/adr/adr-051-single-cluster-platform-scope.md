# ADR-051: Single-cluster platform scope — enforce one cluster at the service layer

**Status**: Accepted
**Date**: 2026-05-17
**Source**: specs/archive/002-single-cluster-limit/research.md (R1) + spec scope decisions

## Context

The platform was originally modelled as multi-cluster — `Environment.cluster_id` is a real FK, `Cluster` is its own table, the resolver hierarchy `Cluster → Environment → Deployment` would happily accommodate any number of clusters in one database. But the product, as it actually ships and as it is operated, has **one** cluster per Styrmin instance. The multi-cluster surface produced consistent friction:

- The UI had to render a "clusters list" with a single row, and a "create new cluster" affordance that nobody should use.
- Operators creating a second cluster would silently produce an unsupported state — the platform doesn't fan out reconciliation across clusters, doesn't aggregate views, doesn't load-balance.
- New features kept asking "what does this mean across clusters?" for a configuration the operators never reach.

Two questions had to be settled:

1. **Where is "only one cluster" enforced?** — at the database (CHECK constraint, partial unique index), at the service layer, or only by convention?
2. **What does the cluster-creation surface look like with the limit in place?** — required `name`, optional `name` with a default, hidden entirely?

## Decision

The platform is **single-cluster** for the foreseeable future. The limit is enforced at the **service layer** in `services/clusters.py::create_cluster()`:

- Before inserting a new `Cluster`, the service calls `uow.clusters.get_all()` and raises `ClusterLimitReachedError` (code `CLUSTER_LIMIT_REACHED`) if any existing cluster is present.
- The error is typed (distinct from `ClusterAlreadyExistsError`, which is the name-collision case) so clients can differentiate and render an appropriate message.
- The GraphQL mutation surface is `createCluster(name: String! = "default", config: JSON)` — `name` is still non-null but has a Strawberry default, so clients that don't care about the name pass nothing and get the canonical default `"default"`.
- The frontend Settings page renders a single-cluster panel when one exists and an empty-state "Create cluster" button when none does, driven off `useListClustersQuery().data.clusters.length` (no extra query).

The decision **does not** add a DB-level constraint. The check-then-create pattern has a theoretical race window under PostgreSQL READ COMMITTED, but the operation is admin-only and infrequent; the worst-case outcome is two clusters when one was expected, which the next read surfaces immediately. Adding a partial unique index or a `SELECT FOR UPDATE` would buy pessimistic safety at the cost of a migration the project pre-Alembic governance gate doesn't want for an admin operation.

## Consequences

- Every cross-resource model (`Environment`, `Deployment`, `BackupStorageLocation`, …) can assume "there is one cluster" without inventing a "current cluster" abstraction or threading `cluster_id` through every lookup that would otherwise be cluster-scoped by default.
- The UI scopes naturally — no cluster picker, no cluster-aware routing — and the empty-state vs single-cluster-detail toggle is a one-line conditional.
- The cluster-creation flow is two clicks (open settings → press Create) instead of "fill in a name + config + worry about uniqueness". The default name `"default"` is the same value the existing scenarios and fixtures already use.
- `ClusterLimitReachedError` gives any future client (CLI, SDK, alternate UI) a typed signal to render "you already have a cluster" instead of a generic validation error.
- The platform's identity as a single-cluster product is now structural, not just operational. Multi-cluster support is a future architectural project, not a missing feature — anyone proposing it has to revisit this ADR.
- The theoretical race window is acceptable in v1. If concurrent creation ever becomes a real problem (it shouldn't — clusters are created once at install time), a database-level partial unique index can be added later as a tightening.

## Alternatives Considered

- **Database CHECK constraint or partial unique index enforcing `count(cluster) ≤ 1`**: rejected for v1. Provides strongest race-free guarantee but requires a migration the project's no-Alembic governance gate doesn't want for an admin operation. Easy to add later if the race becomes real.
- **`SELECT FOR UPDATE` with a new `count()` repository method**: rejected. Pessimistic locking is overkill for an operation that runs at most once per platform install.
- **GraphQL middleware / directive enforcement**: rejected. Violates the layered architecture (Constitution Principle III) by putting business logic outside the service layer.
- **Reuse `ClusterAlreadyExistsError` for the limit**: rejected. Semantically incorrect — the issue is a system-wide limit, not a name collision. Clients can't differentiate the two cases, which is exactly the case where typed errors earn their keep.
- **Keep `createCluster(name: String!)` without a default**: rejected. Forces every client to pass a name they don't care about; UX hostile when the platform already knows the canonical answer.
- **Backend default plus frontend pre-fill**: this is the **selected** approach — the backend default ensures CLI/SDK callers get the right behaviour without ceremony, and the frontend pre-fill is for visual consistency in the form field.
- **Hide the "Create cluster" button when one exists instead of removing it**: chosen variant — hiding cleanly expresses single-cluster semantics; a disabled button still suggests the action is normally available.
