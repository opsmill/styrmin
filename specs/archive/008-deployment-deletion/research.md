# Phase 0 Research: Deployment Deletion

The technical context in `plan.md` carried no `NEEDS CLARIFICATION` markers — every dependency, language, and storage choice is the project default and the spec was seeded from a fully-resolved PRD on issue #94. This document records the design decisions explicitly so they remain auditable, including the alternatives considered.

## R1. Mutation shape: `deleteDeployment(id: UUID!): Task!`

**Decision**: Non-null `Task!` return. The Task is created in `TaskStatus.SUCCESS` ("born complete") with `type=DELETE_DEPLOYMENT`.

**Rationale**:

- Matches the spec/PRD framing: the mutation is an audit record, not a progress channel. The Task captures actor + timestamp on the timeline; progress lives on the deployment's lifecycle state.
- Mirrors the existing `delete_backup` mutation pattern — every destructive lifecycle action returns a Task that the timeline renders consistently.
- Keeps the timeline join trivial: `DeploymentTimelineEvent` is derived from the Task table.

**Alternatives considered**:

- `Boolean!`: Loses audit + timeline propagation; the frontend would need a parallel "I just clicked delete" event channel.
- `Deployment!` (returning the mutated record): The record at the moment of mutation is still in its old state (e.g., `RUNNING`); returning it would mislead clients that expect to see `DELETING`. Also forces the frontend to refetch immediately, which urql cache invalidation would do anyway.

## R2. Backend → CRD patch path

**Decision**: Inside `services/deployment.py::delete_deployment`, use the same async `kr8s` client wiring already present in the agent / status-reporter code path to issue a strategic-merge patch on `spec/deletionRequested = true`. The patch body is `{"spec": {"deletionRequested": True}}`. The mutation is **idempotent at the cluster layer too** — re-patching with `true` is a no-op (and the CEL rule prevents `true → false`).

**Rationale**:

- Server-side CEL transition validation enforces monotonicity, so even a buggy or malicious client cannot reset the flag.
- The patch is the *only* mechanism — no controller-side mutating webhook, no privileged subresource. This keeps the security surface unchanged.
- Existing `kr8s.asyncio` client is already used elsewhere; no new client wiring is needed.

**Alternatives considered**:

- A dedicated `/delete` subresource on the CRD: Adds complexity (separate RBAC, separate openAPI schema) for no functional gain.
- The backend issues `kubectl delete styrmindeployment ...` directly: Conflates "ask for deletion" with "remove the record" and bypasses the kopf reconciler that owns teardown order.

## R3. Status reporter mapping

**Decision**: Extend `_DISPLAY_STATE_TO_STATUS` in `backend/styrmin_backend/services/deployment_status.py`:

```python
_DISPLAY_STATE_TO_STATUS = {
    "Deploying": DeploymentState.DEPLOYING,
    "Running":   DeploymentState.RUNNING,
    "Restoring": DeploymentState.RESTORING,
    "Error":     DeploymentState.FAILED,
    "Deleting":  DeploymentState.DELETING,
    "Deleted":   DeploymentState.DELETED,
}
```

When the target state is `DELETED` and the current state is *not* already `DELETED`, the reporter additionally sets `deployment.deleted_at = datetime.now(tz=timezone.utc)` inside the same UnitOfWork commit that flips the state. This is the **only** code path that sets `deleted_at`.

**Rationale**:

- Atomicity: the UnitOfWork wraps the row update — readers cannot observe `status == DELETED` with `deleted_at IS NULL`.
- Single writer: only the status reporter writes `deleted_at`. The mutation does not. This keeps the soft-delete semantics consistent with "DELETED is observed, not declared".
- Clean reuse: no new code paths or new orchestration. The reporter is already invoked off the existing reconciliation cadence.

**Alternatives considered**:

- A periodic janitor on the backend that sets `deleted_at` for any `status == DELETED && deleted_at IS NULL`: Allows a window where a row reads `DELETED` but `deleted_at IS NULL`. The default-list filter (`WHERE deleted_at IS NULL`) would then incorrectly include those rows.
- Setting `deleted_at` in the resolver at the moment the patch is issued: Wrong — the deployment is not yet deleted at that point; the row still describes a live deployment.

## R4. Cluster-side CR garbage collection

**Decision**: A new kopf timer in `backend/styrmin_backend/operator/janitor.py` runs every 30 minutes. For each `StyrminDeployment` it finds, it acts only when:

1. `status.phase == "Deleted"`, **and**
2. The `Deleted` entry in `status.conditions` has `lastTransitionTime` older than `DELETED_CR_TTL_HOURS` (default `6`, configurable via env var, parsed once at operator boot).

When both conditions hold, the timer issues a `kr8s` delete on the CR (which the existing `@kopf.on.delete` handler will short-circuit because everything is already gone).

**Why a separate module**: keeps the janitor decoupled from the per-deployment reconciliation handler in `handlers/styrmin_deployment.py`. The handler reacts to events on a single CR; the janitor sweeps across all CRs on a clock.

**Rationale**:

- Targets only `Deleted` (terminal). `Deleting`-stuck CRs are intentionally left for human inspection (constitution: explicit failure visibility > implicit auto-cleanup).
- 30-minute tick is well below 6-hour TTL — average GC delay ≈ 15 min after expiry, well-bounded.
- Retention is per-cluster via env var, not per-deployment — matches the spec's scope decision and avoids premature flexibility.

**Alternatives considered**:

- Kubernetes `metadata.deletionGracePeriodSeconds` / TTL controller: Cannot select on `status.phase == Deleted` and only acts on `metadata.deletionTimestamp`. Wrong tool.
- Reconciliation handler self-schedules its own deletion via `asyncio.create_task(...)`: Lifecycle of that task is fragile across operator restarts.

## R5. Idempotency and "not found" semantics

**Decision**:

- `delete_deployment` reads `Deployment.status` and the most recent existing `DELETE_DEPLOYMENT` task **before** deciding to issue a new patch.
- If `status in {PENDING, DEPLOYING, RUNNING, FAILED}`: patch + create new Task + emit timeline event. Return the new Task.
- If `status == DELETING`: do **not** patch (CEL rule would no-op anyway, but we avoid the round-trip and avoid double-emitting the timeline event). Return the most-recent existing `DELETE_DEPLOYMENT` Task. If for some reason there is no prior task (e.g., a stale row migrated in), fall through and create one.
- If `status == DELETED`: raise `DeploymentNotFoundError`.
- If `status == RESTORING`: raise `DeploymentRestoringError` (`error_code=DEPLOYMENT_RESTORING`).

**Rationale**:

- Spec FR-008 (idempotent retries), FR-009 (clear "not found" outcome), FR-007 (explicit data-integrity refusal during restore).
- Conflating already-deleted with "id doesn't exist" is intentional: the spec says clients should be able to treat both identically. The error *code* (`DEPLOYMENT_NOT_FOUND`) is what scripts pattern-match on.

## R6. Default visibility filter

**Decision**:

- New argument: `deployments(includeDeleted: Boolean = false)`. When `false` (default), the resolver chains `WHERE deleted_at IS NULL` into the SQL filter. When `true`, no filter on `deleted_at`.
- `deployment(id)` query is **unfiltered** with respect to `deleted_at` — direct id lookup always works.
- `Deployment.deletedAt` scalar is exposed on the GraphQL type so the UI can render the banner / relative timestamp.

**Rationale**:

- `DELETING` rows have `deleted_at IS NULL` until terminal, so they remain visible in the default list (Spec FR-028, US3 acceptance #1).
- A single argument matches the React toggle naturally; the urql cache key includes the variable, so toggling refetches without component restructuring.
- Detail-page reachability (FR-032) is enforced at the query level rather than at the route level, which keeps the URL contract stable forever.

**Alternative considered**: A separate `listDeletedDeployments` query. Rejected: forces the frontend to swap queries on toggle, complicates the urql cache, and makes "show in-flight `DELETING` only when default" awkward to express.

## R7. Frontend dialog gating

**Decision**: Reuse the type-to-confirm pattern already present in `frontend/src/pages/deployments/.../*Backup*.tsx` and `*Environment*.tsx` dialogs:

- Dialog accepts a `requiredText` prop equal to the deployment's `name`.
- Confirm button is disabled until `inputValue === requiredText` (case-sensitive `===`, no `trim()`, no normalisation).
- Body copy enumerates: workload + namespace teardown, retained backups, "Show deleted" reveal window.
- On confirm: fire mutation, navigate to `/deployments` list (replaces, not pushes — operator does not navigate back into the dialog).

**Rationale**: established pattern, predictable UX, zero new shared components needed.

## R8. Constitutional alignment

The non-negotiable principles from `.specify/memory/constitution.md` were re-checked against this design:

- **§I Declarative State Reconciliation**: passes — desired-state-only mutation, observed transitions through reconciliation.
- **§III Layered Architecture**: passes — resolver → service → repository → DB, no cross-layer leakage; CRD patch is encapsulated in the service.
- **§V Test-First (E2E + Propagation NON-NEGOTIABLE)**: enforced by `tasks.md` and the spec's success criteria. Two E2Es + full propagation coverage.
- **§VI Format and Lint**: deferred to the implementation phase's pre-commit hook; no design-time consequences.

No constitution amendments are required.

## Open questions

None. The PRD on issue #94 fully resolved the design space. Any new questions raised during implementation are out-of-band for `research.md` and should be raised in the PR.
