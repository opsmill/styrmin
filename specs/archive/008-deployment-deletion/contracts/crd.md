# Contract: StyrminDeployment CRD

File: `helm/agent/crds/styrmin.io_styrmindeployments.yaml`

## `spec.deletionRequested` (NEW)

```yaml
spec:
  type: object
  properties:
    ...
    deletionRequested:
      type: boolean
      default: false
      description: |
        Set to true by the Styrmin backend to request teardown of all owned
        resources. The operator reconciles the flip and progresses the CR
        through phase: Deleting -> Deleted. Immutable once true (CEL rule).
  x-kubernetes-validations:
    - rule: "!has(oldSelf.deletionRequested) || oldSelf.deletionRequested == false || self.deletionRequested == true"
      message: "deletionRequested cannot be set back to false once true"
```

### CEL rule semantics

| Old value | New value | Result |
|-----------|-----------|--------|
| absent / `false` | `false` | accepted (no-op) |
| absent / `false` | `true` | accepted (request deletion) |
| `true` | `true` | accepted (no-op) |
| `true` | `false` | **rejected** by API server: `deletionRequested cannot be set back to false once true` |

The `!has(oldSelf.deletionRequested)` clause covers CRs that pre-date this field; once the operator has reconciled at least once, all CRs carry the field with default `false`.

## `status.phase` enum (additions)

```yaml
phase:
  type: string
  enum:
    - Pending
    - CreatingPrerequisites
    - CreatingHelmRelease
    - CreatingServices
    - Ready
    - Restoring
    - Failed
    - Deleting          # already present
    - Deleted           # NEW (terminal)
```

Lifecycle:

```text
... -> Deleting -> Deleted
```

`Deleted` is set by the reconciler **only after** the namespace finalizers complete and the namespace is gone. While any owned resource (Service, HelmRelease, NetworkPolicy, Secret, namespace) still exists, the CR remains in `Deleting`.

## `status.displayState` enum (additions)

```yaml
displayState:
  type: string
  enum:
    - Deploying
    - Running
    - Restoring
    - Error
    - Deleting   # NEW
    - Deleted    # NEW
```

The status reporter maps `displayState` directly to `Deployment.status` (see `services/deployment_status.py::_DISPLAY_STATE_TO_STATUS`). When the projected state is `DELETED`, the reporter atomically sets `Deployment.deleted_at = now()`.

## `status.conditions` — new condition type

The reconciler emits a `type: "Deleted"` condition when the namespace is fully gone:

```yaml
conditions:
  - type: Deleted
    status: "True"
    reason: NamespaceGone
    message: "All owned resources removed; namespace styrmin-{id} no longer exists"
    lastTransitionTime: "2026-05-01T..."
```

The janitor (see below) reads `lastTransitionTime` to compute TTL eligibility.

## Reconciliation responsibilities

The existing per-CR reconciliation handler in `backend/styrmin_backend/operator/handlers/styrmin_deployment.py` observes `spec.deletionRequested`:

1. When the flip is observed (any update event, or on resume after operator restart) and `phase != Deleted`, the handler runs the teardown pipeline in reverse order:
   - delete owned `Service`s
   - delete the owned `HelmRelease`
   - delete owned `NetworkPolicies` and `Secrets`
   - delete the deployment's namespace `styrmin-{id}`
2. Conditions and `phase`/`displayState` are advanced as each step completes.
3. Once the namespace is gone (verified via `kr8s` get returning 404), the handler sets `phase: Deleted`, `displayState: Deleted`, and emits the `Deleted` condition.

The existing `@kopf.on.delete` handler is **retained** as a safety net for manual `kubectl delete styrmindeployment ...`. It runs the same teardown pipeline; it does **not** create a backend tombstone (out of scope per spec).

## Janitor (`operator/janitor.py`)

A new module-level kopf timer:

```python
@kopf.timer("styrmin.io", "v1alpha1", "styrmindeployments", interval=1800.0)
async def janitor_reap_deleted(spec, status, meta, **_):
    if status.get("phase") != "Deleted":
        return
    deleted_cond = next(
        (c for c in status.get("conditions", []) if c.get("type") == "Deleted"),
        None,
    )
    if deleted_cond is None:
        return
    last_transition = parse_rfc3339(deleted_cond["lastTransitionTime"])
    if datetime.now(timezone.utc) - last_transition < timedelta(hours=DELETED_CR_TTL_HOURS):
        return
    # Issue kr8s delete on the CR; the @kopf.on.delete handler will short-circuit.
    await kr8s_delete_styrmin_deployment(name=meta["name"], namespace=meta["namespace"])
```

Selection rule (from `data-model.md`):

- `status.phase == "Deleted"` AND
- `status.conditions[type=Deleted].lastTransitionTime` older than `DELETED_CR_TTL_HOURS` hours.

Records stuck in `Deleting` are **never** reaped automatically — they remain visible until human action resolves them.

## RBAC

The backend already has `patch` rights on `styrmindeployments` via the operator/agent service account. No new RBAC is required for the patch path.

The janitor runs in-process inside the operator (same service account, same `delete` rights it already uses for the `@kopf.on.delete` safety-net path).

## Backwards compatibility

Adding the optional `deletionRequested` field with `default: false` and an `x-kubernetes-validations` block is backwards compatible. CRs created against the old schema will be admitted; the field appears with its default once they are next read.

The two new `phase` and `displayState` values are additive — existing clients that switch on these enums must add cases for `Deleting`/`Deleted` (this is enforced in the operator and backend by `match`/`Enum` exhaustiveness checks).
