# ADR-016: Forensic-retention CR janitor with TTL-gated reaping

**Status**: Accepted
**Date**: 2026-05-02
**Source**: specs/archive/008-deployment-deletion/research.md (R4)

## Context

After a platform-driven delete, operators may want to inspect the cluster-side `StyrminDeployment` CR to see how the teardown actually progressed — final conditions, reasons, the order of resource removals. If the operator deletes the CR immediately when the namespace is gone, that forensic data is lost.

But CRs cannot linger forever — every retired deployment would accumulate a stale CR, and the cluster's API server would page through them on every list. We need a TTL — long enough to support post-mortem inspection, short enough to keep the cluster tidy. Different environments care about different retention windows: production benefits from a long forensic trail, dev clusters benefit from aggressive cleanup.

Two failure modes have to be handled differently:

- A CR that **completed** teardown and reached `phase: Deleted`. Safe to reap on a clock.
- A CR that **stuck** in `phase: Deleting` (teardown failed). Reaping this on a clock would silently delete evidence of a real failure. Must be left for human intervention.

## Decision

Introduce a per-cluster janitor as a separate module (`backend/styrmin_backend/operator/janitor.py`) that runs as a `@kopf.timer` and applies a strict selection rule:

- **Reap iff**: `status.phase == "Deleted"` **AND** the `Deleted` condition's `lastTransitionTime` is older than `DELETED_CR_TTL_HOURS`.
- **Never reap**: CRs in `Deleting` (or any other phase). Those stay until human action resolves them, regardless of how old they are.

Configuration:

- `DELETED_CR_TTL_HOURS` (env var, default `6`) — the retention window. Read once at operator boot.
- `JANITOR_INTERVAL_SECONDS` (env var, default `1800` = 30 minutes) — how often the timer fires.

The selection rule is implemented as a pure function (`is_eligible_for_reap(status, *, now, ttl_hours)`) so it can be unit-tested without spinning up kopf or a real Kubernetes API server.

## Consequences

- **Easier**: forensic state is preserved by default. Operators have a deterministic, predictable window to inspect retired CRs without running `kubectl describe` immediately after every delete.
- **Easier**: failure-mode visibility is preserved. A teardown that hangs in `Deleting` stays visible indefinitely — a noisy `kubectl get styrmindeployments -A` is the right signal that something needs manual attention.
- **Easier**: the janitor is decoupled from per-CR reconciliation. The reconciliation handler reacts to events on a single CR; the janitor sweeps across all CRs on a clock. They don't fight over the same patches.
- **Harder**: there's no "retry the teardown" affordance — if a CR is stuck in `Deleting`, the janitor doesn't try to recover. This is intentional (failed teardown = human-attention case) but means a future "auto-retry stuck deletions" feature would need a different mechanism.
- **Slight cost**: every 30 minutes the operator does an extra list-all-CRs scan. For the project's expected scale this is negligible.

## Alternatives Considered

- **Kubernetes built-in TTL controller / `metadata.deletionGracePeriodSeconds`**: Built-in mechanisms operate on `metadata.deletionTimestamp`, not `status.phase`. They cannot select on "phase reached Deleted N hours ago"; they only work after a delete has been issued. Wrong tool.
- **Have the reconciliation handler self-schedule a delete via `asyncio.create_task(...)`**: Lifecycle of that task is fragile across operator restarts — a restart loses the in-flight schedule and the CR lingers forever.
- **Per-deployment retention TTL override** (e.g., `spec.deletedTtlHours`): Premature flexibility. Per-cluster via env var is the simplest contract that satisfies the use cases (different envs, different windows).
- **No retention — reap immediately on `phase: Deleted`**: Loses the forensic value entirely. Rejected because a 6h window is essentially free.
