# ADR-046: Delete DeployedService rows on deployment tombstone

**Status**: Accepted
**Date**: 2026-06-21
**Source**: bug — "service name already exists" when redeploying after a delete

## Context

Deleting a deployment and then recreating one that resolves to the same
service name failed with `ServiceNameConflictError` ("Service name '…' already
exists in environment"). An E2E reproduction
(`backend/tests/e2e/test_redeploy_after_delete_api.py`, since folded into
`test_delete_deployment_api.py`) confirmed the flow:
deploy → delete (to terminal `DELETED`) → recreate with the same service name
raises `ALREADY_EXISTS`.

Root cause: a deployment is **soft-deleted** (tombstoned — `deleted_at`
stamped, row retained per ADR-008), but its `DeployedService` rows were never
removed. `delete_services_for_deployment` existed but was only called on the
*upgrade* path (when a new driver version declares no services); the SQLAlchemy
`cascade="all, delete-orphan"` only fires on a hard-delete that never happens
for a tombstone. The service-name uniqueness check
(`_check_name_uniqueness` → `get_by_resolved_name_and_environment_id`) has no
`deleted_at` awareness, so the orphaned row from the deleted deployment blocks
reuse of the name.

The same orphaned rows have a second effect: `context.py`
(`generate_context_from_deployment`) builds every deployment's
service-discovery context from `get_by_environment_id`, so a deleted
deployment's services also leak as **ghost services** into other live
deployments' rendered config (and into the `Environment` services GraphQL
query).

ADR-011 already solved the parallel problem for deployment **names** with a
partial unique index `(environment_id, name) WHERE deleted_at IS NULL`, and
explicitly set that as "the convention to replicate" for any future
soft-deleted resource needing uniqueness. The obvious move would be to apply
the same convention to service names.

## Decision

Do **not** make service-name uniqueness tombstone-aware via an index/filter.
Instead, **delete the deployment's `DeployedService` rows when it transitions
to the terminal `DELETED` state**, in the same `UnitOfWork` commit that stamps
`deleted_at` (`services/deployment_status.py`, the sole writer of
`deleted_at`). Cleanup is gated on the terminal `DELETED` transition — the
non-terminal `DELETING` state leaves the rows in place.

This diverges from the ADR-011 convention deliberately, because
`DeployedService` rows differ from the deployment row in kind:

- They carry **no audit value**. ADR-011 rejected hard-deleting (or renaming)
  the deployment row because its name is part of its identity in the timeline,
  backups, and any external system that scraped it. A `DeployedService` row is
  pure operational discovery/uniqueness state — nothing references a deleted
  deployment's services.
- A filter/index would fix only the *uniqueness* symptom. The ghost-service
  **discovery leak** would remain unless every read site
  (`get_by_environment_id` in `context.py` and `query.py`,
  `get_by_resolved_name_and_environment_id` in the uniqueness check) also grew
  a tombstone-aware join. Deleting the rows at the single tombstone point fixes
  all consumers at once and keeps the table free of unbounded orphan
  accumulation.

## Consequences

- **Fixed**: redeploying with a previously-used service name succeeds once the
  prior deployment reaches `DELETED`. Covered by
  `test_delete_deployment_api.py` (E2E, step 10) and
  `test_deployment_status_service.py::test_deleted_cleans_up_deployed_services`
  / `::test_deleting_does_not_clean_up_deployed_services` (unit).
- **Fixed**: a deleted deployment's services no longer leak into other
  deployments' service-discovery context.
- **Timing**: service names free up only at the *terminal* `DELETED`
  transition, which is gated server-side on namespace teardown. A user cannot
  reclaim a name in the brief `DELETING` window — consistent with "the old
  deployment must actually be gone first".
- **No DB-level race guard**: `DeployedService` has no unique constraint
  (uniqueness was always service-layer only), so this change neither adds nor
  removes race safety for concurrent same-name creates. If that ever becomes a
  requirement, the ADR-011 partial-index pattern remains available and is not
  precluded by this decision.
- **Convention note**: ADR-011's partial-index convention still stands for
  resources whose tombstoned rows must be *retained* (audit/identity). This ADR
  records the carve-out for resources that are pure operational state and can
  be reaped on tombstone instead.

## Alternatives Considered

- **Tombstone-aware partial index / query filter on service names (ADR-011
  convention)**: Would fix the uniqueness symptom but leaves orphaned rows
  accumulating forever and does not fix the discovery leak unless every read
  site is updated. More surface area, more places to forget the filter.
  Rejected in favour of single-point cleanup.
- **Hard-delete the deployment row too**: Contradicts ADR-008 (soft-delete
  preserves audit + backups). Rejected.
- **Clean up at the `DELETING` transition instead of `DELETED`**: Would free
  the name earlier, but the cluster workload (and its Kubernetes Services) may
  still be terminating. Gating on the terminal state keeps DB state aligned
  with cluster reality. Rejected.
