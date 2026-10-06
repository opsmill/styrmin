# Kubernetes Operator

<!-- Extracted from specs/001-k8s-operator and specs/001-deployment-crd on 2026-04-06 -->

## Overview

The operator is a kopf-based Kubernetes controller that runs alongside the Prefect agent in a single container, sharing one async event loop. It manages the full lifecycle of Kubernetes resources for Styrmin deployments through a custom `StyrminDeployment` CRD.

```text
┌──────────────────────────────────────────────────────────┐
│                  Combined Container                       │
│                                                          │
│  ┌─────────────────┐    ┌─────────────────────────────┐  │
│  │  Prefect Agent   │    │     Kopf Operator           │  │
│  │  (worker loop)   │    │  (CRD watcher + reconciler) │  │
│  └────────┬─────────┘    └──────────┬──────────────────┘  │
│           │                         │                     │
│           └────────┬────────────────┘                     │
│                    │                                      │
│           Shared asyncio event loop                       │
└──────────────────────────────────────────────────────────┘
```

The entrypoint uses `asyncio.gather(kopf.operator(...), run_prefect_worker())` to run both components concurrently. See ADR-002 for the rationale.

## StyrminDeployment CRD

The operator watches `StyrminDeployment` custom resources (`styrmin.io/v1alpha1`). These are created by Prefect flows and contain the full deployment specification.

**API Group**: `styrmin.io` | **Version**: `v1alpha1` | **Kind**: `StyrminDeployment` | **Short name**: `sd`

### Spec Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `deploymentId` | string (UUID) | Yes | Links to Styrmin database deployment |
| `releaseReference` | string | Yes | Kubernetes release reference |
| `appName` | string | Yes | Application name from driver |
| `appVersion` | string | Yes | Application version |
| `context` | object | Yes | Serialized GlobalContext (full deployment config) |
| `helm` | object | Yes | Chart and repository specs |
| `labels` | object | No | Custom labels for managed resources |
| `parameters` | object | No | User-provided parameters |
| `deletionRequested` | boolean | No (default `false`) | Set to `true` by the backend's `deleteDeployment` mutation to request operator-driven teardown. Immutable once `true` (CEL transition rule `oldSelf == false \|\| self == true` enforced by the API server). |

The context is embedded directly in the CRD (see ADR-004), making the operator autonomous — no backend API calls needed during reconciliation.

### Namespace co-location (load-bearing constraint)

The CRD is `scope: Namespaced` and lives **inside the deployment's own namespace** (`styrmin-{deployment_id}`). Deleting that namespace deletes the CR with it. Any state transition you want observed must complete BEFORE the namespace is gone, OR you must rely on a separate "DB DELETING + CR absent → infer terminal" path (this is what the agent's status reporter does for the platform-driven delete flow — see [`overview.md`](overview.md) → Status Reporter and `services/deployment_status.py`). New work that needs a phase change to land after namespace deletion will silently fail without this callout — design accordingly.

### Status

| Field | Description |
|-------|-------------|
| `phase` | `Pending` / `CreatingPrerequisites` / `CreatingHelmRelease` / `CreatingServices` / `Ready` / `Failed` / `Deleting` / `Deleted` |
| `displayState` | User-facing state surfaced to the UI: `Deploying` / `Running` / `Restoring` / `Error` / `Deleting` / `Deleted` |
| `message` | The message of the current phase, or the reason of a failure |
| `conditions` | K8s-standard condition array: `NetworkPoliciesReady`, `SecretsReady`, `HelmReleaseReady`, `HelmReleaseRemediated`, `ServicesReady`, `MiddlewaresReady`, `Ready`, `Deleted` |
| `managedResources` | Counts by type (networkPolicies, secrets, helmReleases, services, middlewares) |
| `instanceId` | The `spec.instanceId` that the create, update or resume handler last acted on. Written at the end of the handler, also when the handler raises. The status reporter sends it, so the server can link each report to the task that rolled out that instance. |
| `rolloutStartedAt` | When the current rollout started (ISO 8601). Set by the create and update handlers; the resume handler sets it only when it is missing. The readiness timeout counts from it. |

The CRD's status schema keeps `x-kubernetes-preserve-unknown-fields: true`, so `instanceId`, `rolloutStartedAt` and `HelmReleaseRemediated` need no CRD change on existing installs. `helm/agent/crds/styrmin.io_styrmindeployments.yaml` documents them.

Printer columns for `kubectl get styrmindeployments`: Phase, App, Version, Age.

## Phase-Based Deployment

Resources are deployed in a guaranteed order using kopf sub-handlers (see ADR-005):

```text
StyrminDeployment Created
    │
    ├── Phase 1: NetworkPolicies + Secrets
    │   (HelmRelease is NOT created until all prerequisites are verified)
    │
    ├── Phase 2: HelmRelease
    │   (Wait for FluxCD to report the HelmRelease's current generation Ready)
    │
    └── Phase 3: Services + Middlewares
         │
         └── phase: Ready
```

Sub-handlers provide automatic idempotency — completed phases are never re-executed on retry. If the operator restarts mid-deployment, it resumes from the last completed phase.

### Deletion

Two paths exist:

**Platform-driven (preferred)**: the backend's `deleteDeployment` mutation patches `spec.deletionRequested = true`. A `@kopf.on.update(field="spec.deletionRequested", new=True)` handler observes the flip and runs `_teardown_owned_resources` in reverse order (Services/Middlewares → HelmRelease → NetworkPolicies/Secrets), then issues a namespace delete. The periodic timer advances `phase` to `Deleted` once the namespace returns 404. Because the StyrminDeployment CR lives inside the deployment's own namespace, the CR is garbage-collected with the namespace; the agent's status reporter detects "DB DELETING + CR absent" and synthesises a final `displayState: Deleted` report so the DB is tombstoned race-free.

**Manual safety-net**: `kubectl delete styrmindeployment ...` triggers the existing `@kopf.on.delete` handler, which runs the same `_teardown_owned_resources` helper. This path does **not** produce a DB tombstone — it's a recovery mechanism for when the platform-driven path is unavailable.

After the platform-driven path completes, the StyrminDeployment CR remains in `phase: Deleted` for `DELETED_CR_TTL_HOURS` (default 6h, env-configurable) so operators can inspect cluster-side state. A `@kopf.timer` janitor in `operator/janitor.py` reaps CRs whose `Deleted` condition's `lastTransitionTime` is past the TTL. CRs stuck in `Deleting` are NEVER auto-reaped.

## Drift Detection and Reconciliation

A timer handler fires every 60s to compare desired vs actual state for all managed resource types. Drift on any resource is automatically corrected.

### Reconciliation States

| State | Condition |
|-------|-----------|
| `Ready` | All resources match desired state |
| `CreatingPrerequisites` / `CreatingHelmRelease` / `CreatingServices` | Deployment or update in progress |
| `Failed` | Reconciliation failed (API error, permission denied) |

In `CreatingHelmRelease` and, for non-internal deployments, `Ready`, the timer also reads the HelmRelease once per tick. When its current generation failed on the component-container guard (the guard key `styrmin.io~1component-container~1…` in a condition message, Ready not `True`), the CR goes to `Failed` / `Error` at once with `HelmReleaseReady=False` and `Ready=False`, reason `ComponentContainerNotFound`, and the typed `COMPONENT_CONTAINER_NOT_FOUND` message naming the component and container (spec 018, FR-007). During a rollout, the timer also follows FluxCD's state of the current generation, as described in the next section. Once the CR is `Ready`, the timer checks only the guard: a later HelmRelease failure without a spec change is not reflected in the CR status.

## HelmRelease readiness during a rollout

<!-- Extracted from specs/019-task-steps on 2026-10-06 -->

The operator judges the HelmRelease only on its current generation, so an update or an upgrade reaches `Ready` only after FluxCD has applied the new release ([ADR-060](../../adr/0060-steps-and-derived-task-result.md)). Before this rule, the update handler kept `HelmReleaseReady=True` from the previous rollout, and the timer moved the CR to `Ready` on its next tick.

### Start of a rollout

The create and update handlers:

- set `HelmReleaseReady` to `Unknown` with reason `Progressing` ("Waiting for FluxCD to apply the HelmRelease");
- remove `HelmReleaseRemediated`, which belonged to the previous rollout;
- set `status.rolloutStartedAt` to the current time.

A kopf retry of these handlers (for example after `kopf.TemporaryError`) runs them again, so it resets `rolloutStartedAt` too. The resume handler continues the rollout: it does not reset `HelmReleaseReady`, and it sets `rolloutStartedAt` only when it is missing, so an operator restart does not extend the readiness timeout.

### Current-generation rule

A FluxCD condition of the HelmRelease counts only when its `observedGeneration` equals the HelmRelease's `metadata.generation`. A condition without `observedGeneration` is compared through `status.lastAttemptedGeneration`. This is the same rule as the component-container guard. `operator/reconciler.py::observe_helmrelease` reads the HelmRelease once per tick and returns FluxCD's `Ready` and `Released` conditions, `Remediated` and `Stalled` when they are `True`, and the guard failure, all for the current generation. It also returns whether FluxCD's newest release is its rollback of a failed release (see [Rollback reported Ready](#rollback-reported-ready)).

### What the timer writes in `CreatingHelmRelease`

| FluxCD state of the current generation | CR status |
|---|---|
| No condition yet | Nothing changes |
| `Ready=True`, and the newest release is not FluxCD's rollback | `HelmReleaseReady=True`, reason `FluxReady`; in the same tick the timer creates the services and middlewares and, when that succeeds, moves the CR to `Ready` |
| `Ready` not `True` | `HelmReleaseReady` gets FluxCD's `Ready` status and transition time. When `Ready=False`, the reason and message come from `Released=False` when FluxCD has it (after a rollback, `Ready` describes the rollback), else from `Ready` |
| `Remediated=True` | Copied into `HelmReleaseRemediated` (status, reason such as `RollbackSucceeded` or `UninstallSucceeded`, message, transition time). The phase does not change, because FluxCD tries again after each rollback (`remediation.retries: 3` for install and upgrade) |
| `Stalled=True` | Phase `Failed`, `displayState: Error`, message `"<Stalled message>: <failure message>"`, and `Ready=False` with the `Stalled` reason, for example `RetriesExceeded`. FluxCD has used all its retries |
| `Ready=True` for FluxCD's rollback of a failed release of this generation | Phase `Failed`, `displayState: Error`, message `"FluxCD rolled the release back after release v<N> failed: <failure message>"`, and `Ready=False` with reason `RolledBack`. `HelmReleaseReady` keeps FluxCD's failure, or becomes `False` with reason `RolledBack` when the timer did not see the failure |

The timer writes a condition only when its status, reason, message or transition time changes (`operator/crd/status.py::replace_condition`), so a slow rollout does not write the status on every tick.

An internal deployment, such as the ingress controller, also counts as ready when one of its pods is ready, because its HelmRelease can stay `Progressing` while a LoadBalancer gets no external IP. A ready pod wins over `Stalled`.

### Readiness timeout

While the phase is not `Ready`, `Failed` or `Deleting`, the timer compares the time since `status.rolloutStartedAt` with `STYRMIN_OPERATOR_DEPLOYMENT_READY_TIMEOUT` (default 300 seconds). A CR written by an older operator, without `rolloutStartedAt`, counts from `metadata.creationTimestamp`. After the timeout, the timer sets `displayState: Error` and the message `Deployment did not reach Ready within <timeout>s (phase: <phase>)`. The phase does not change, so a later FluxCD attempt that succeeds still moves the CR to `Ready` and `displayState: Running`. The timeout is the safety net when FluxCD never reports `Stalled`.

### Rollback reported Ready

FluxCD can report `Ready=True` for the current generation after it rolled that generation back. With helm-controller v1.1.0, the version in `helm/agent`, this happens to a change that only adds or changes post-render overrides (image or environment variable overrides, [ADR-057](../../adr/0057-post-render-component-overrides.md) and [ADR-058](../../adr/0058-image-overrides-and-component-container-guard.md)). Observed in `test_task_steps.py::test_helmrelease_failure_shows_fluxcd_reason`:

1. The upgrade to release v3 fails at FluxCD's 5-minute timeout. FluxCD rolls back to v2, which creates release v4 ("Rollback to 2"), and sets `Released=False` (`UpgradeFailed`) and `Remediated=True` (`RollbackSucceeded`).
2. 11 to 38 seconds later in E2E runs, FluxCD finds v4 in sync with the current generation, because after an attempt at a generation it compares only the chart and the values, not the post-renderers. It sets `Ready=True` and `Released=True`, both with reason `UpgradeSucceeded` and the message "Helm upgrade succeeded for release <name>.v4", removes `Remediated`, and records the new post-renderers digest. It does not try again.

So FluxCD's conditions cannot tell this state from a retry that succeeded, and with the default 60-second timer interval the timer can miss `Remediated` altogether. FluxCD's release history can: the timer counts FluxCD's `Ready=True` as a rollback when FluxCD counted a failed install or upgrade for the current generation (`status.installFailures` or `status.upgradeFailures`, which FluxCD resets for each new generation), and the newest entry of `status.history` is `deployed` and has the version right after a `failed` entry. While failures are counted, FluxCD rolls back each failed release before it tries again, so that entry is the rollback. A retry that succeeds adds a newer release after the rollback, so it still moves the CR to `Ready`. The timer then fails the CR as described in the table above. An internal deployment with a ready pod still counts as ready.

## Steps of a rollout

The operator does not write steps. The server builds the operator-phase steps of a task ("Create network policies and secrets", "Install or upgrade the HelmRelease", "Create services and middlewares", "Wait for the deployment to be ready") from the status reports, using `status.instanceId`, the phase, `displayState`, `message` and the conditions above. FluxCD's reasons, rollbacks (`HelmReleaseRemediated`) and retries (`HelmReleaseReady` back to `Progressing`) become the HelmRelease step's detail, rollback and attempts. See [Status Reporter](overview.md#status-reporter) and [ADR-060](../../adr/0060-steps-and-derived-task-result.md).

## Managed Resources

The operator is the sole owner of all utility resources for CRD-managed deployments:

| Resource | API Version | Created By |
|----------|------------|------------|
| NetworkPolicy | `networking.k8s.io/v1` | Operator |
| Secret | `v1` | Operator |
| HelmRelease | `helm.toolkit.fluxcd.io/v2` | Operator (reconciled by FluxCD) |
| Service | `v1` | Operator |
| Middleware | `traefik.io/v1alpha1` | Operator |

### Labels

All resources created from a StyrminDeployment carry:

| Label | Value | Purpose |
|-------|-------|---------|
| `app.kubernetes.io/managed-by` | `styrmin` | Identifies Styrmin-managed resources |
| `styrmin.io/deployment-crd` | `<crd-name>` | Links to parent StyrminDeployment |
| `styrmin.io/release-reference` | `<release-ref>` | Links to deployment's release reference |
| `styrmin.io/resource-phase` | `prerequisites` / `helm` / `services` | Deployment phase that created this resource |

### Resource Naming

- NetworkPolicies: `{release_reference}-{policy_name}` (e.g., `abc123def-default-deny-egress`)
- NetworkPolicies per deployment: default-deny-egress, default-deny-ingress, allow-traefik-ingress, traefik-netpolicy-egress, prefect-netpolicy-egress, plus app-specific

### Apply semantics

<!-- Extracted from specs/017-post-render-env-vars on 2026-10-03 -->

Custom resources go through `upsert_custom_resource`
(`agent/service/kubernetes/primitives.py`): a create, then a patch on `409 Conflict`. Two
callers opt into `replace_spec_keys_on_update=True`: the operator's HelmRelease apply
(`operator/pipeline.py`) and the agent's StyrminDeployment CR applies
(`agent/tasks/orchestration.py::_apply_styrmin_deployment_crd`, used on create, update, and
upgrade). Every other custom resource keeps JSON merge-patch.

| Path | Behaviour |
|------|-----------|
| Create | Body as rendered; the HelmRelease apply also sets `prune_none_on_create`, so a `null` marker is dropped rather than stored. |
| Update, `spec` (opted in) | One JSON Patch (`application/json-patch+json`): an `add` per top-level spec key the body sets, nested `None` pruned. A top-level key set to `None` becomes `add {}` then `remove`. |
| Update, `metadata.labels` / `metadata.annotations` (opted in) | An `add` per key the body sets (RFC 6901 escaping), so merge semantics hold and Flux's finalizer and kopf's annotations are untouched. |
| Update (not opted in) | `application/merge-patch+json` (RFC 7386): maps merge, keys the body omits survive. |

The rule is: **Styrmin owns each top-level spec key it writes; everything else merges.**
`spec.values` on the HelmRelease and `spec.context` on the CR are replaced, so nested keys a
new render no longer writes disappear (a cleared env var, a values-template key a migrated
driver dropped). Spec keys Styrmin never writes survive: `spec.suspend` set by
`flux suspend hr`, and the server-owned `spec.deletionRequested` on the CR, which the CRD's
CEL rule forbids resetting after a delete request. See
[ADR-057](../../adr/0057-post-render-component-overrides.md) §6.

## Kubernetes Events

The operator emits events on the StyrminDeployment resource for observability:

| Event | Type | When |
|-------|------|------|
| `ReconcileSucceeded` | Normal | All resources match desired state |
| `DriftDetected` | Normal | Resource modified or deleted unexpectedly |
| `ReconcileFailed` | Warning | Failed to reconcile a resource |

Events are visible via `kubectl describe styrmindeployment <name>`.

## Leader Election

Uses kopf's built-in peering with `ClusterKopfPeering` CRD (see ADR-003). Priority-based: the highest-priority operator instance runs while others pause. Peer records expire after a configurable lifetime (default 60s).

## Relationship to Prefect Flows

Prefect flows create/update/delete StyrminDeployment CRDs as a declaration of intent (see ADR-006). The operator then manages all Kubernetes resources. Driver pre/post hooks still execute via Prefect.

```text
Prefect Flow                          Operator
    │                                     │
    ├── Compute GlobalContext              │
    ├── Serialize into CRD spec            │
    ├── Create StyrminDeployment ─────────►├── Phase 1: Prerequisites
    │                                     ├── Phase 2: HelmRelease
    ├── Run driver hooks                  ├── Phase 3: Services
    ├── Update task status                └── Continuous drift detection
    │
```

Pre-existing deployments without a StyrminDeployment CRD continue to work unchanged (forward-only).
