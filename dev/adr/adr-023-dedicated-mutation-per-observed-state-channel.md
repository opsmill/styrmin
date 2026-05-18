# ADR-023: Dedicated `report<X>Statuses` mutation per observed-state channel

**Status**: Accepted
**Date**: 2026-05-17
**Source**: specs/archive/001-agent-status-reporting/research.md (R4)

## Context

The agent reports observed cluster state back to the backend on a polling cadence. The first such channel is per-pod status. Earlier, the only agent → backend mutation was `callback(...)`, which the Prefect worker invokes when a task transitions state.

The question was the wire shape for status reports:

1. Extend the existing `callback()` mutation to also carry status data.
2. Add a dedicated `reportPodStatuses` mutation.
3. Use a REST endpoint.
4. Use gRPC streaming.

## Decision

Add a dedicated `reportPodStatuses(reports: [DeploymentPodStatusReport!]!)` GraphQL mutation. The mutation accepts a batched payload covering every active deployment in one HTTP round-trip. Server-side, the handler upserts pod rows and removes stale ones (see [[adr-024-two-pronged-stale-data-cleanup]]).

This establishes the **pattern** for every subsequent observed-state channel: each kind of observed state gets its own `report<X>Statuses` mutation, batched per cycle. [[adr-020-separate-crd-status-reporting-mutation]] later applied the same pattern to CRD status (`reportDeploymentStatuses` / `reportCrdStatuses`).

## Consequences

- Task lifecycle (`callback`) stays separate from workload observation (`report<X>Statuses`). The two have different cadences (task-event-driven vs periodic), different consumers (Task/Instance state vs observed-state tables), and different failure modes (a failed status report does not flip a task to FAILED).
- Each observed-state channel can evolve its schema independently. Adding fields to pod reports doesn't ripple into CRD reports and vice versa.
- A failure in one channel doesn't sink the others: the reporter loop catches per-mutation exceptions and continues with the next channel on the next cycle.
- Batching per cycle keeps HTTP overhead bounded — one mutation call per channel per polling interval, regardless of how many deployments are managed.
- All status-report mutations live on the same GraphQL endpoint as user-facing operations. There is no separate "internal" GraphQL endpoint — authentication and authorization gate them the same way.

## Alternatives Considered

- **Extend `callback()`**: rejected. Conflates Prefect task lifecycle with continuous workload observation; forces a single mutation schema to grow as new observation kinds are added; entangles failure modes that should stay orthogonal.
- **REST endpoint**: rejected. Breaks the convention that all agent ↔ backend traffic flows through GraphQL. No technical advantage; pure inconsistency cost.
- **gRPC streaming**: rejected. Over-engineering for a 60s polling interval — the data volume per cycle fits comfortably in one HTTP request, and streaming infrastructure (proto definitions, codegen pipeline, separate transport) is pure overhead at this scale.
