# Implementation Plan: Backend No-Op Detection for Deployment Updates

**Spec**: [spec.md](./spec.md) · **Branch**: `009-deployments-apply` (pre-merge redesign) · **Status**: Draft

## Summary

Make `deployments apply` idempotent by detecting no-op updates **server-side, before any side effect**. Both `update_deployment` and `update_deployment_version` already generate a candidate `ApplicationInstance` in memory and then unconditionally persist it + dispatch a reconcile `Task`. We insert the existing `Comparator` between generation and persistence: if the candidate equals the current active instance, return `None` (no instance persisted, no task, status untouched). The SDK stops doing client-side change detection and always sends the full payload; it maps a `null` task to `action="unchanged"`. No GraphQL schema change, no DB change.

## Technical Context

- **Backend**: Python, Strawberry GraphQL, SQLModel, service layer, Prefect. The relevant service functions are `backend/styrmin_backend/services/deployment.py::update_deployment` (phase 2, ~L388-415) and `::update_deployment_version` (~L205-226).
- **Existing machinery to reuse**:
  - `generate_instance_from_deployment` (`services/reconciliation/__init__.py:17`) — builds an `Instance` purely in memory (`Instance.create`), no session add. Confirmed: discarding the candidate on a no-op leaves no orphan rows.
  - `Comparator(current_instance, new_instance).compare()` (`services/reconciliation/diffs/comparison.py:31`) — returns `DiffReport(diff=None)` when equal; already excludes `id` / `name` / `status` from the comparison (so a FAILED current instance vs a fresh candidate with identical intent diffs to `None` → FR-006 holds for free).
  - `apply_state` (`services/reconciliation/__init__.py:36`) — creates the `Task` + dispatches Prefect. This is the side-effecting call we now gate.
- **SDK**: `python_sdk/src/styrmin_sdk/resources/deployments.py` (`apply`, `_apply_update`, `update`, `update_version`) + `models/deployment_manifest.py` (`ApplyOutcome.action`).
- **CLI**: `cli/src/styrminctl/commands/deployments.py` (`_summary_line`, `_format_*`).
- **Frontend**: no code change (`ConfigDiffDialog.tsx` ignores the returned task).

## Approach (layered, per Constitution §III)

### Service layer (the core change)
1. In `update_deployment` phase 2 and in `update_deployment_version`, after `new_instance = await generate_instance_from_deployment(...)` and **before** `set_active_instance` / `set_status` / `apply_state`:
   - `report = Comparator(current_instance=current_instance, new_instance=new_instance).compare()`
   - `if report.diff is None:` → log a debug no-op line and `return None`. Do **not** set the active instance, do **not** change status, do **not** call `apply_state`, do **not** persist/commit a new instance.
   - else → proceed exactly as today.
2. Change both functions' return type from `Task` to `Task | None`.
3. Remove the `update_deployment` guard that raises `InvalidContextError("At least one of config, parameters, name, or serviceNameOverrides must be provided")` (FR-003). An update that resolves to no change is now a successful no-op, not an error. (Keep any *validation* errors — invalid env-var name, malformed scheduling, duplicate component — those still fire before generation.)

### GraphQL layer
- `updateDeployment` / `updateDeploymentVersion` resolvers already declare `-> Task | None`, but their bodies end with `return Task.from_instance(task)` (`mutation.py:805`, `:1115`) which **crashes on `task=None`** (critique M1). Change both to `return Task.from_instance(task) if task is not None else None`. **No schema change** — both are already `: Task` (nullable) in `schema.graphql`; no regen. Caller audit: only these two resolvers call the changed service functions (no internal callers), so the `Task | None` return is contained.

### SDK layer
- `update()` / `update_version()`: tolerate a `null` `data.updateDeployment*` payload → return `None` instead of raising in `_parse`.
- `_apply_update`: revert the `6f8713a` stopgap (FR-004) — remove the client-side empty-input skip and the `existing.application_version != manifest.version` comparison. Always call `update(...)` with the full typed input, and always call `update_version(...)` with the manifest version.
- Map results to `ApplyOutcome.action` (FR-005): if **both** `update` and `update_version` return `None` → `unchanged`; if either returned a `Task` → `updated`; the create path stays `created`. `task_id` is the last non-null task (or `None` for unchanged).
- `ApplyOutcome.action` Literal: `created | updated | unchanged | failed` (the `unchanged` value introduced by the stopgap is kept, now driven by the backend's null signal rather than a client guess).
- `_wait_for_terminal`: `unchanged` (and `failed`) are not polled (no task dispatched).

### CLI layer
- `_summary_line`: `"N created, M updated, K unchanged, J failed"` (already added by the stopgap; keep).
- `_format_outcome_line` / `_format_wait_event_line`: render `unchanged <name>`; an unchanged outcome with `--wait` emits no terminal event (kept from stopgap).

### Frontend
- No code change. Add coverage that a no-op save dispatches no reconcile (component or E2E assertion).

## Test Strategy (Constitution §V)

- **Unit (service)**: `update_deployment` / `update_deployment_version` no-op → returns `None`, no `apply_state` call, no instance persisted, status unchanged (assert via fakes/spies). Change → returns a `Task`, `apply_state` called once.
- **Functional / propagation**: update the existing `updateDeployment` / `updateDeploymentVersion` functional tests — the removed guard's error-path test flips to a no-op assertion (mutation returns `null`, DB unchanged). This satisfies the §V propagation rule for the (behaviourally) changed mutations; no new schema element is introduced.
- **SDK unit**: `update`/`update_version` map `null` → `None`; `_apply_update` always dispatches both calls and maps null/null → `unchanged`, task/none → `updated`; FAILED-deployment no-op stays `unchanged`.
- **CLI unit**: summary + wait-line rendering of `unchanged` (largely already covered by the stopgap tests; keep/adjust).
- **E2E (definition of done)**: `test_apply_unchanged_manifest_is_noop` — apply a manifest, settle, re-apply identical, assert no new instance + no new task (query instance/task counts before/after). Extend the existing apply E2E with the partial-change P2 assertions (config-only → 1 reconcile; version-only → 1 upgrade). Must run to a local PASS with recorded evidence per §V.

## Risks & Mitigations

- **Flow-side Comparator becomes redundant** (the Prefect `apply_state` flow re-diffs). Harmless — it will now always find a diff because we only dispatch when one exists. Leave it as belt-and-suspenders; do not remove in this feature.
- **Return-type churn** (`Task` → `Task | None`) touches callers of these service functions. Audit all callers (`deploy`, frontend redeploy paths, refresh) — most already treat the result opaquely. `refresh_deployment` is a separate function and unaffected.
- **`set_status(PENDING)` skipped on no-op** is the desired behaviour (status untouched) — confirm no downstream relies on a status bump per update.

## Governance Gates

All ruled out: no DB/migration, no GraphQL schema change (behaviour-only, return already nullable), no new dependency, no CI change, no auth change. This is a service-layer behaviour change.
