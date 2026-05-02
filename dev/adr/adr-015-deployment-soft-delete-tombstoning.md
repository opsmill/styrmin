# ADR-015: Soft-delete tombstoning with status reporter as sole writer

**Status**: Accepted
**Date**: 2026-05-02
**Source**: specs/archive/008-deployment-deletion/research.md (R3) + session learning during E2E iteration

## Context

Deployment deletion needs to:

1. Tear down the cluster-side workload (HelmRelease, services, network policies, namespace).
2. Preserve the platform-side audit trail — the deployment row, its timeline (Tasks), its associated backups — so operators can review what happened, restore from a backup, or audit who retired what and when.
3. Hide retired deployments from the day-to-day list view but keep them addressable by direct id forever.

A pure hard-delete (DROP the row) loses (2) and (3). A pure soft-delete (mark a flag, leave workload running) defeats (1).

Layered on top of those product requirements, an architectural constraint emerged during E2E iteration: the `StyrminDeployment` CRD is `scope: Namespaced` and lives **inside the deployment's own namespace** (`styrmin-{deployment_id}`). Deleting the namespace deletes the CR with it. So any state-machine that depends on patching the CR after the namespace is gone will silently fail — the timer can't advance a CR that no longer exists.

## Decision

Adopt a **hybrid soft-delete** model with a single-writer invariant:

- Hard-delete cluster-side: the operator tears down all owned resources and the namespace.
- Soft-delete platform-side: a new `Deployment.deleted_at: datetime \| None` column tombstones the row. `status` gains `DELETING` and `DELETED` values. `DELETED` is terminal.
- The agent's status reporter is the **sole writer** of `deleted_at`. It atomically stamps `deleted_at = now()` in the same UnitOfWork commit that flips `Deployment.status` to `DELETED`. No other code path writes the column. This guarantees readers cannot observe `status == DELETED` with `deleted_at IS NULL`.
- To handle the namespace/CR co-location: the reporter additionally synthesises a final `displayState: Deleted` report when the DB says `DELETING` and the CR is no longer present on the cluster. This makes the terminal transition race-free regardless of whether the CR was reaped by the namespace finalizer or by an explicit delete.

The `deleteDeployment(id) -> Task!` mutation does not write `deleted_at` — it patches `spec.deletionRequested = true` on the CRD and emits a born-complete `DELETE_DEPLOYMENT` task. Every observable state transition flows through the existing reconciliation cadence.

## Consequences

- **Easier**: timeline, backup, and audit data survive deletion automatically — no cascade-delete rules to maintain. The `Deployment` row is the only stable id callers need to forget.
- **Easier**: writers don't have to coordinate. Every place that wants to know "is this deployment retired?" reads `deleted_at IS NOT NULL`. Every default list excludes those rows with a single `WHERE` clause.
- **Easier**: no new long-running orchestration. The mutation is synchronous and trivial; the operator + reporter already exist.
- **Harder**: the "single writer" invariant is enforced socially (and by code review) rather than at the DB level. A future contributor adding a different code path that sets `deleted_at` would silently break ordering. Mitigated by the constitutional propagation tests, which assert the only-the-status-reporter-stamps-`deleted_at` behaviour explicitly.
- **Harder**: the CR-absent inference path adds a second responsibility to the status reporter (it now reasons about "what does an absent CR mean?"). Documented in `dev/knowledge/agent/operator.md` so the next contributor doesn't rediscover the namespace co-location constraint.

## Alternatives Considered

- **Pure hard-delete**: Simple, but orphans Tasks/timeline/backups (no FK cascade rules exist on those relations) and breaks the "Deleted at &lt;timestamp&gt;" detail-page UX.
- **Pure soft-delete (leave workload running)**: Keeps the platform consistent but leaves resources running on the cluster — the whole point of "delete" is gone.
- **Move the CR to a non-deployment namespace**: Would let the operator advance the CR through `phase: Deleted` after the namespace is gone, removing the need for the reporter's CR-absent inference. Rejected because every other operator-resource relationship currently assumes the CR co-locates with the namespace it owns; moving it would require a wider refactor.
- **Operator-side DB writes**: Have the operator update the DB directly when the namespace deletion completes. Rejected because the operator has no DB connection today (it talks to the cluster only); coupling it to the DB would invert the existing layering.
