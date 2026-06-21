# Research: Backend No-Op Detection for Deployment Updates

## R1 — The diff already exists; the defect is ordering
`Comparator.compare()` (`services/reconciliation/diffs/comparison.py:31`) already returns `DiffReport(diff=None)` when current and new instances are equal, and the Prefect `apply_state` flow already short-circuits ("No remediation needed"). But `update_deployment` persists the new instance, flips status to `PENDING`, and dispatches the `Task` *before* that diff runs. **Decision (D1):** run the existing instance-level diff in the service, before persistence/dispatch. Reuse, don't reinvent.

## R2 — Instance generation is in-memory (no orphan risk)
`generate_instance_from_deployment` (`services/reconciliation/__init__.py:17`) calls `Instance.create(...)` and returns it without adding to the session. Persistence happens only via `deployment.set_active_instance(new_instance)` + `uow.deployments.save(...)` + `uow.commit()`. **Therefore** the no-op path can discard the candidate by simply returning before those calls — no expunge, no rollback needed. Confirmed by reading the function body.

## R3 — Status is already excluded from the diff → FR-006 free
`Comparator` excludes `root['id']`, `root['name']`, `root['status']` (`comparison.py:60`). So a FAILED current instance vs a fresh candidate with identical resolved context diffs to `None`. A no-op re-apply against a failed deployment therefore stays a no-op without any status-aware special-casing. **Decision (D5)** falls out of the existing comparison semantics.

## R4 — Diff is against the *resolved* instance, not the raw manifest
The candidate instance carries the fully-resolved `GlobalContext` (cluster + environment + deployment config merged). So a manifest whose `spec.config` is byte-identical but whose inherited environment/cluster config changed produces a *different* candidate instance → correctly detected as a change. This is why a shallow "compare submitted config dict to persisted dict" was rejected — it would miss inherited changes.

## R5 — Both mutations already return nullable `Task` → no schema change
`schema.graphql`: `updateDeployment(...): Task` and `updateDeploymentVersion(...): Task` (both nullable). Returning `null` on a no-op is a behaviour change only — no field/arg/input/mutation added or altered, no `schema.graphql` regen, no SDK codegen churn. **Decision (D3).**

## R6 — Symmetric treatment of the version path (D2)
`update_deployment_version` shares the identical generate→persist→dispatch pattern, so it gets the same guard. The SDK then drops its client-side `existing.application_version != manifest.version` check and always calls `updateDeploymentVersion`; same-version → backend no-ops. Half-thinning (only `update_deployment`) would leave version comparison in the CLI, contradicting the thin-CLI principle.

## R7 — Frontend caller ignores the task (D4)
`frontend/src/components/deployment/configuration/ConfigDiffDialog.tsx` does `await updateMutation.mutateAsync(...)` then `invalidateQueries` + `onApplySuccess()` — it never reads the returned task, so a `null` return is safe. Its client-side `diffResult.hasChanges` is UX (Apply-button state / diff display), not the authority on whether to mutate, and stays. Behaviour change: a no-op save no longer redeploys (desirable).

## R8 — Reporting comes free from task-nullability
Because the backend returns `null` on no-op and a `Task` on real work, the SDK distinguishes `unchanged` vs `updated`/`created` directly — no new GraphQL report type needed in v1. A field-level "what changed" report is a possible additive follow-up (out of scope).

## R9 — Relationship to the committed stopgap `6f8713a`
The stopgap put change detection in the SDK (empty-input skip + version compare) and derived `unchanged` client-side — the wrong direction per the thin-CLI principle. FR-004 reverts that client logic; the `unchanged` action value is retained but now driven by the backend's null signal.

## Out-of-scope confirmations
- Exposing `refresh_deployment` as a user-facing redeploy/refresh (the D5 recovery path) — separate feature.
- Collapsing the config-update + version-upgrade double reconcile when both change — unchanged from 009.
- Field-level change report — additive follow-up.
