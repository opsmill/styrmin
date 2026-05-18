# ADR-036: Capabilities recalculated in service-layer mutations

**Status**: Accepted
**Date**: 2026-05-17
**Source**: specs/archive/001-cluster-env-capabilities/research.md (R2)

## Context

[[adr-035-capabilities-as-extensible-json-column]] establishes that capabilities are persisted (not computed on every read). That introduces a cache-coherence question: when does the persisted value get refreshed?

Capabilities derive from a small, well-known set of inputs:

- `Cluster.config` (storage class, ingress, fqdn_suffix, …)
- `Environment.config` (same fields, environment-scoped)
- `Environment.backup_storage_location_id` (FK relationship)

All of these change through a finite set of mutations: `create_cluster`, `update_cluster`, `create_environment`, `update_environment`, `assign_backup_storage_location`, `unassign_backup_storage_location`. There are no out-of-band writes — no background process, no operator, nothing else writes these fields.

## Decision

Recalculate capabilities **synchronously in the service-layer function** that performs each relevant mutation. Each create/update path computes capabilities from the new inputs (via `compute_cluster_capabilities()` / `compute_environment_capabilities()` in `services/capabilities.py`) and persists the result on the same `UnitOfWork` as the triggering write, so the row's `config` and `capabilities` are committed in one transaction.

There is no separate refresh job, no event bus, no database trigger.

## Consequences

- Capabilities are always consistent with the config that produced them, by transaction boundary. Readers never see a temporal skew between the inputs and their derived view.
- The mutation latency includes the cost of capability derivation, but derivation is pure computation over a handful of fields — measured in microseconds, dominated by the surrounding DB roundtrip.
- The service-layer functions are the **only** legitimate writers of the underlying fields, so this discipline structurally prevents drift. Anyone bypassing the service layer (raw SQL, fresh code path) is a layered-architecture violation and a separate bug, not a capability-derivation bug.
- Adding a new capability input means updating both the derivation logic and the set of mutations that need to call it. The trigger table in `dev/knowledge/backend/services.md` is the canonical list.
- Recomputation is idempotent and cheap, so it's safe to run on every mutation even if the input fields haven't changed — keeping the contract simple is worth more than the micro-optimisation of "only recompute when the inputs differ".

## Alternatives Considered

- **Database triggers**: rejected. The project uses SQLModel/SQLAlchemy async over `metadata.create_all()` — there's no Alembic, no migration story for trigger DDL, and no precedent for raw-SQL behaviour. Triggers would also fight the layered architecture (Constitution III): they hide business logic in the DB where service-layer code can't see it.
- **Background task (Prefect flow)**: rejected. Capability derivation is a synchronous computation over fields the mutation already has in hand; punting it to Prefect adds orchestration latency between config change and capability update, plus a new failure mode (flow failed → capabilities stale forever).
- **Event-driven recalculation**: rejected. No event bus exists in the project. Introducing one for a single use case is infrastructure debt for no win.
