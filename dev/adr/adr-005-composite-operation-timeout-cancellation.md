# ADR-004: Timeout and Cancellation for Composite Operations

**Status**: Accepted
**Date**: 2026-04-05
**Source**: specs/archive/001-env-backup-restore/research.md (R6)

## Context

Composite operations (see ADR-003) dispatch multiple child operations that each have their own timeouts. Without a parent-level timeout, an environment backup with one stuck child could block indefinitely. The system needs an overall ceiling that supersedes individual child timeouts, with clean cancellation of in-progress children when the ceiling is reached.

## Decision

The orchestrating INTERNAL flow tracks elapsed wall-clock time. When the configurable parent timeout is exceeded:

1. All children still in PENDING or IN_PROGRESS are marked FAILED with error message "Environment backup timeout exceeded"
2. The parent status is recomputed (typically transitions to FAILED or PARTIALLY_FAILED)

The timeout is configurable per-operation (default: 3600s for environment backups, 7200s for environment restores) and is independent of per-instance timeouts.

```python
poll_interval = 10
elapsed = 0
while elapsed < timeout:
    await asyncio.sleep(poll_interval)
    elapsed += poll_interval
    # Check if all children are terminal
    if all_terminal:
        break
else:
    # Timeout: mark remaining children as FAILED
    ...
```

## Consequences

**Easier:**
- Operations have a guaranteed upper time bound
- Operators can tune the timeout based on environment size

**Harder:**
- Child operations that are mid-execution when the parent times out may leave partial state in Kubernetes (Velero backups in progress)
- The polling interval (10s) introduces up to 10s of latency between the last child completing and the parent being updated

## Alternatives Considered

- **Rely solely on per-instance timeouts**: Doesn't provide an overall time bound for the composite operation.
- **Velero-level cancellation**: Would require K8s API access from the INTERNAL flow, breaking the two-worker separation where only USER flows have cluster access.
