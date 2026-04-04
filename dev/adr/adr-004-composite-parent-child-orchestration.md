# ADR-003: Composite Operations via Parent-Child Orchestration

**Status**: Accepted
**Date**: 2026-04-05
**Source**: specs/archive/001-env-backup-restore/research.md (R1, R2, R3)

## Context

Environment-level backup and restore operations need to coordinate multiple per-instance operations concurrently. The system already has per-instance backup/restore workflows, but no pattern exists for orchestrating a group of related operations as a single logical unit with aggregate status tracking.

Three interrelated design questions arise:
1. How to limit concurrency when dispatching many constituent operations
2. How to aggregate child statuses into a parent status
3. What architecture to use for the orchestrating flow

## Decision

**Composite operations use a parent-child model with three key patterns:**

### 1. Concurrency Limiting via asyncio.Semaphore

The orchestrating Prefect INTERNAL flow uses `asyncio.Semaphore` to gate concurrent constituent dispatches. This is configured per-operation (e.g., `max_concurrency=5` for environment backups).

```python
semaphore = asyncio.Semaphore(max_concurrency)
async def dispatch(child_id):
    async with semaphore:
        await prefect_manager.run_action(action, parameters)
await asyncio.gather(*(dispatch(cid) for cid in children))
```

### 2. Stored Parent Status with Aggregation

Parent status is stored as a persistent DB column and recomputed from child statuses after each child completes:

- All children COMPLETED → parent COMPLETED
- All children FAILED → parent FAILED
- Mix of COMPLETED and FAILED → parent PARTIALLY_FAILED
- Any PENDING/IN_PROGRESS → parent IN_PROGRESS

The `PARTIALLY_FAILED` status is unique to composite operations (not present in per-instance status enums).

### 3. Two-Tier Architecture (Mutation → INTERNAL Flow)

The GraphQL mutation creates all DB records synchronously (parent + children in PENDING state) and returns immediately. A Prefect INTERNAL flow is dispatched to handle the asynchronous orchestration: marking IN_PROGRESS, dispatching child operations, polling for completion, and updating the parent status.

This reuses existing per-instance workflows (e.g., `EXECUTE_BACKUP`) as children — no duplication of Velero logic.

## Consequences

**Easier:**
- Adding new composite operations (e.g., environment-level upgrades) follows this established pattern
- Parent status is always consistent (stored, not computed on read)
- Concurrency is bounded without affecting system-wide Prefect work pool limits

**Harder:**
- Parent status updates require re-querying all child statuses
- The polling loop in the INTERNAL flow adds latency between child completion and parent status update
- Timeout handling must coordinate between parent-level and child-level timeouts

## Alternatives Considered

- **Prefect work pool concurrency limits**: Too coarse — would affect all operations system-wide, not scoped to a single composite operation.
- **Computed status (query-time aggregation)**: Simpler but slower for list queries and inconsistent with the existing stored-status pattern.
- **Event-driven (child triggers parent update)**: Would require modifying existing per-instance workflows, violating the constraint of not changing existing behavior.
- **Service-layer-only orchestration**: Would lose Prefect observability and retry capabilities.
