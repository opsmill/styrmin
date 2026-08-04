# ADR-021: `DeploymentCrdStatus` as a one-to-one observed-state snapshot table

**Status**: Accepted
**Date**: 2026-05-17
**Source**: specs/archive/001-crd-status-reporting/research.md (R5)

## Context

The agent reports the latest StyrminDeployment CRD status — phase, conditions (list of typed objects), managed resource counts (dict of integers), and a `last_polled_at` timestamp — on every poll cycle. The backend needs to persist this data so the API can serve it without round-tripping to Kubernetes.

Two questions had to be settled:

1. Should CRD status live on the `Deployment` model directly, or in its own table?
2. Should the nested fields (`conditions`, `managedResourceCounts`) be normalized into relational tables, or stored as JSON blobs?

This decision sits in the same family as [[0007-pod-status-records-observed-state-not-declared-state]] — both are observed-state snapshots fed by the agent. The pod-status pattern is the established precedent.

## Decision

Introduce a new `DeploymentCrdStatus` SQLModel with a one-to-one relationship to `Deployment`:

- `deployment_id` UUID, FK → `Deployment.id`, UNIQUE NOT NULL (one record per deployment, upsert semantics).
- `phase` string NOT NULL.
- `message` string nullable.
- `conditions` JSON nullable — list of `{type, status, reason, message, lastTransitionTime}` objects.
- `managed_resource_counts` JSON nullable — dict like `{networkPolicies, secrets, helmReleases, services, middlewares}`.
- `last_polled_at` datetime NOT NULL.
- Cascade DELETE on Deployment removal.

Conditions and managed resource counts are stored as JSON, not normalized.

> **Note — amended implementation (revision `b9c0d1e2f3a4`).** The cascade is
> the SQLAlchemy `cascade="all, delete-orphan"` on `Deployment.crd_status`, not
> a database-level `ON DELETE CASCADE`. The FK-level cascade was declared in
> revision `b2c3d4e5f6a7` but never existed in any database, because the schema
> was built by `metadata.create_all()` from the models — which never declared
> it — and the migration chain did not apply end-to-end until 2026-08-04.
> `b9c0d1e2f3a4` drops it so both build paths agree. See
> [[0024-two-pronged-stale-data-cleanup]] for the full rationale.

## Consequences

- The `Deployment` model stays free of Kubernetes-specific observed fields; declared-state and observed-state remain cleanly separated, consistent with [[0007-pod-status-records-observed-state-not-declared-state]].
- Upsert semantics on `deployment_id` keep the table size O(deployments) — no historical accumulation, no janitor needed.
- JSON storage is appropriate here because conditions and resource counts are **read-only snapshots**: the backend never queries `WHERE condition.type = X` or aggregates across deployments. The whole blob is read together, displayed, and replaced on the next poll.
- The relationship cascade means cleanup is automatic when a deployment is removed (FR-009).
- Future evolution of the CRD status structure (new condition types, new resource kinds) requires no migrations.

## Alternatives Considered

- **Store CRD fields directly on the `Deployment` model**: rejected. Pollutes the declared-state model with K8s-specific observed fields; conflicts with [[0007-pod-status-records-observed-state-not-declared-state]] which already separates the two concerns for pods.
- **Normalize conditions into a separate `CrdCondition` table**: rejected as over-normalized. Conditions are a read-only snapshot replaced atomically each poll; relational queries against them have no use case, and the join cost on every read is pure overhead.
- **Reuse the `PodStatus` table with a discriminator column**: rejected. PodStatus is per-pod (one Deployment → many rows); CRD status is one-to-one. Forcing them into one table would either denormalize the pod relationship or invent a sentinel pod for CRD rows.
