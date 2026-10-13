# ADR-054: Backend-authoritative no-op detection, signalled by a null `Task`

**Status**: Accepted
**Date**: 2026-08-04
**Source**: specs/archive/014-deployment-update-noop/research.md (R1 – R9)
**Related**: [ADR-048](0048-declarative-apply-client-side-orchestration.md) (the caller
whose idempotence depends on this), [ADR-012](0012-environment-config-fanout.md) §1
(per-deployment no-op detection in the fanout path), [ADR-018](0018-typed-update-deployment-input.md)
(the full-replacement input being compared).

## Context

`updateDeployment` and `updateDeploymentVersion` did work unconditionally.
Submitting a deployment's current configuration persisted a fresh
`ApplicationInstance`, flipped the deployment to `PENDING`, created a `Task`, and
dispatched a reconcile — which the Prefect `apply_state` flow then short-circuited
with "No remediation needed". The diff already existed and already knew nothing
had changed; it just ran **after** the writes.

The cost was visible: a throwaway instance row and a spurious timeline entry per
no-op save, a deployment briefly reported as `PENDING` when nothing was
happening, and pods re-reconciled for no reason. Declarative apply made this
acute — re-applying an unchanged manifest is the *normal* case for a CI pipeline,
so a no-op had to be genuinely free.

A stopgap (`6f8713a`) had put change detection in the SDK: skip when the input is
empty, compare versions client-side, and synthesise `unchanged` locally. That put
platform semantics in a client, which contradicts the thin-CLI principle — the
CLI and SDK are transports, not policy.

## Decision

**No-op detection is the backend's job, runs before any write, and is signalled
to clients by returning `null` instead of a `Task`.**

### 1. Run the existing diff before persistence and dispatch

`update_deployment` and `update_deployment_version` both generate a candidate
instance, then — **before** setting it active, before dispatching `apply_state`,
before any status change — build a `Comparator(current_instance, candidate)` and
call `compare()`. If `report.diff is None`, log and return `None`. Only a
non-empty diff proceeds to persist, dispatch, and commit.

This reuses `Comparator.compare()` unchanged. Nothing new computes a diff.

Discarding the candidate is free: `generate_instance_from_deployment()` calls
`Instance.create(...)` and returns it **without adding it to the session**.
Persistence happens only via `set_active_instance()` + `save()` + `commit()`, so
returning early leaves nothing to expunge or roll back.

### 2. Compare the *resolved* instance, not the submitted config

The candidate carries the fully-resolved `GlobalContext` — cluster, environment,
and deployment config merged. So a manifest whose `spec.config` is byte-identical
but whose **inherited** environment or cluster config has moved produces a
different candidate and is correctly treated as a change.

This is why a shallow "compare the submitted dict to the persisted dict" was
rejected: it would silently skip real work whenever an inherited value changed.

### 3. `null` is the signal — no schema change

Both mutations already returned a **nullable** `Task`:

```graphql
updateDeployment(deploymentId: UUID!, input: UpdateDeploymentInput!): Task
updateDeploymentVersion(deploymentId: UUID!, version: String!, parameters: JSON = null): Task
```

Returning `null` on a no-op is a behaviour change only — no field, argument, input
type, or mutation is added or altered. No `schema.graphql` regeneration, no SDK
codegen churn. Service signatures become `-> Task | None`.

Clients distinguish "nothing to do" from "work dispatched" directly: the SDK maps
a null task to `ApplyOutcome(action="unchanged")`. Nothing else is needed for
reporting in v1.

### 4. Both mutations, symmetrically

`update_deployment_version` shares the identical generate → persist → dispatch
shape, so it gets the same guard. The SDK consequently **drops** its client-side
`existing.application_version != manifest.version` check and always calls
`updateDeploymentVersion`; requesting the current version no-ops server-side.
Guarding only `update_deployment` would have left version comparison stranded in
the client.

### 5. The "at least one field" guard is removed

`update_deployment` previously raised
`InvalidContextError("At least one of config, parameters, name, or serviceNameOverrides must be provided")`.
That guard existed to approximate "this call would do nothing" from the shape of
the input; the real diff now answers that question properly, so an empty input is
simply a no-op returning `null`.

Validation of *malformed* input — invalid env-var names, duplicate component or
parameter names, malformed scheduling — is untouched and still fires before
instance generation.

## Consequences

- **A no-op update writes nothing.** Zero `ApplicationInstance` rows, zero `Task`
  rows, no status transition, no timeline entry, no reconcile.
- **`apply` is idempotent for free.** Re-applying an unchanged manifest is cheap
  by construction, which is what lets [ADR-048](0048-declarative-apply-client-side-orchestration.md)
  decline to diff anything client-side.
- **Status is excluded from the diff, so recovery still needs an explicit path.**
  `Comparator` already ignores `root['id']`, `root['name']`, and `root['status']`,
  which means a `FAILED` deployment compared against an identical candidate is a
  no-op — resubmitting the same config will **not** retry a failed deployment.
  That falls out of existing comparison semantics rather than any special-casing
  here. Exposing `refresh_deployment` as a user-facing redeploy is the intended
  recovery route and is a separate feature.

  > **Note — amended ([#428](https://github.com/opsmill/styrmin/issues/428)).**
  > `refresh_deployment` and the deployment page's Redeploy button, which had no
  > click handler, were removed instead of exposed. A redeploy with an unchanged
  > config sends FluxCD the same HelmRelease spec, so it cannot make FluxCD retry
  > a HelmRelease that has used all its retries. Retrying a failed deployment
  > without changing its config or version is not supported.
- **`null` is now overloaded.** A null `Task` means "no work needed"; it used to
  imply only an error path. Any client treating null as failure would break — the
  frontend's `ConfigDiffDialog` is safe because it awaits the mutation and then
  invalidates queries without reading the returned task.
- **The UI's client-side `hasChanges` stays, as UX only.** It drives Apply-button
  state and the diff display; it is not the authority on whether to mutate. A
  no-op save through the UI now correctly does not redeploy.
- **No field-level "what changed" report.** Clients learn *whether* anything
  changed, not *what*. A structured report is a possible additive follow-up.
- **The double reconcile when config and version both change is unaffected** —
  still two mutations, still two reconciles, unchanged from spec 009.

## Alternatives Considered

- **Keep detection in the SDK (the `6f8713a` stopgap).** Rejected: puts platform
  semantics in a client, so every other SDK consumer re-implements it and any
  divergence becomes a correctness bug. Reverted by this decision.
- **Compare the submitted config dict against the persisted one.** Rejected:
  misses changes inherited from environment or cluster config, silently skipping
  real work.
- **A new nullable `changed: Boolean!` field or a dedicated result type.**
  Rejected: the already-nullable `Task` carries the signal, so this would be a
  schema change and an SDK regeneration for information clients can already read.
- **Guard only `update_deployment`.** Rejected: leaves version comparison in the
  client, half-undoing the stopgap.
- **Keep the "at least one field" guard alongside the diff.** Rejected: it is a
  worse approximation of the same question and would reject an empty input with an
  error where the correct answer is a no-op.
- **Detect the no-op inside the Prefect flow (where the short-circuit already
  existed).** Rejected: by then the instance, the task row, and the status change
  are already persisted — the writes are the cost, not the reconcile.
