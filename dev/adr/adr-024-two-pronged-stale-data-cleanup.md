# ADR-024: Two-pronged stale-data cleanup for observed-state tables

**Status**: Accepted
**Date**: 2026-05-17
**Source**: specs/archive/001-agent-status-reporting/research.md (R6)

## Context

Observed-state tables (starting with `PodStatus`, later extended by `DeploymentStatus` per [[adr-021-deployment-crd-status-snapshot-table]]) record the latest snapshot of cluster-side resources. Two failure modes accumulate stale rows:

1. **Resource-level churn within a live deployment**: rolling updates, scaling events, or pod deletions remove individual pods. The corresponding `PodStatus` rows must be cleaned up — leaving them would falsely report dead pods as "last seen running".
2. **Whole-deployment removal**: when a `Deployment` is removed from the platform, every observed-state row for it must vanish — orphaned rows would point to a non-existent FK.

Neither problem can rely on the agent alone to "send a delete" because the agent's view is "what currently exists"; it has no notion of "what existed before that's now gone unless I tell the server". The cleanup must be a server-side responsibility derived from the snapshot the agent sends.

## Decision

Server-side cleanup runs in two coordinated passes:

1. **Per-poll-cycle stale removal**: each call to `reportPodStatuses` carries the **complete active set** of pods for every deployment in the batch. The server-side handler (`services/pod_status.py::report_pod_statuses`) upserts the active set and calls `delete_stale` on the repository to remove any row whose `(deployment_id, pod_name)` is not in the report. The agent only ever sends "what exists now"; the server derives "what disappeared since last cycle".
2. **Deployment-level cascade delete**: the FK from `PodStatus.deployment_id` → `Deployment.id` declares `ON DELETE CASCADE` (or SQLAlchemy `cascade="all, delete-orphan"` on the relationship). Removing a `Deployment` row collapses every observed-state row pointing at it in one transaction.

The same two-pronged pattern is the prescribed shape for future observed-state tables.

## Consequences

- The agent's wire contract stays "send the active set"; it never has to compute deltas. This is robust to agent restarts, missed cycles, and partial outages — the next successful cycle re-converges the server to whatever the cluster actually shows.
- Stale rows have a bounded lifetime equal to the polling interval. There is no TTL knob to tune and no janitor to babysit.
- Deployment teardown atomically reclaims every observed-state row through standard FK cascade — no orphans, no separate cleanup pass to schedule.
- The pattern composes: new observed-state tables (CRD status, future kinds) follow the same recipe — server-side stale-set diff + FK cascade — without inventing per-table cleanup logic.

## Alternatives Considered

- **TTL-based expiry**: rejected. Introduces a tunable knob (how long is "stale"?) that has to be tuned per table and per polling interval. Also fails to handle the deployment-deletion case cleanly: rows would linger until the TTL fired, leaving a window where queries return orphans.
- **Cleanup only on deployment deletion**: rejected. Leaves stale per-pod rows accumulating across rolling updates and scale events for the lifetime of the deployment. Users would see deleted pods reported as "still observed".
- **Agent computes and sends deletes explicitly**: rejected. Forces the agent to remember the previous snapshot, which complicates restart semantics and leaks state that the server is the natural owner of.
