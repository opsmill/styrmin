# Phase 0 Research: Environment-Config Update with Deployment Fanout

## 1. Input shape — Strawberry input mirroring `EnvironmentConfig`

**Decision**: Define `UpdateEnvironmentInput` as a Strawberry input that mirrors the post-008 `EnvironmentConfig` Pydantic model field-for-field. Nested objects (`DedicatedIngressConfig`, `SchedulingConfig`, `AffinityBlock`, `ResourceRequirements`, `Toleration`, `TopologySpreadConstraint`, `PostRenderInjection`) get corresponding `*Input` Strawberry input types. Scalars stay scalar (`fqdn_suffix: String`, `external_url_port: Int`, etc.). Enums (`external_dns_endpoints_type`, `external_url_scheme`) get Strawberry enum mirrors. The mutation handler converts the typed input into the existing `EnvironmentConfig` Pydantic model via `EnvironmentConfig.model_validate(...)` on the dict view of the input.

**Rationale**: The existing JSON-blob path round-trips through `EnvironmentConfig.model_validate(raw_dict)` for validation. The typed input shortens the chain to "Strawberry parses → input.dict() → Pydantic validates" — no behaviour change at the validation layer, just a typed boundary. This preserves all the work done in 008-deployment-env-vars (env var size caps, regex validation, the `_prevalidate_environment_env_vars` helper that surfaces precise error codes) without rewriting it.

**Alternatives considered**:

- *Strawberry-Pydantic auto-derivation* (`strawberry.experimental.pydantic.input(...)` decorator): rejected for v1. The codebase already mixes hand-rolled Strawberry types with Pydantic models elsewhere, and the Strawberry-Pydantic bridge has known issues with deeply nested optional fields — discoverable only at request time. Hand-rolling the inputs takes more lines but is more debuggable.
- *Single `JSON` input wrapped in a thin typed wrapper*: rejected. The whole point of US2 is to remove the JSON-blob write surface; a thin wrapper would just relocate it.
- *Partial-update with `UNSET` sentinels*: rejected for v1 by the user's explicit decision (full-replacement is the v1 contract). A future incremental-update mutation may revisit.

**Reference**: `backend/styrmin_backend/context/models/config.py` (the Pydantic models being mirrored); `backend/styrmin_backend/services/env_vars/exceptions.py` (the typed errors that survive the mutation boundary thanks to `_prevalidate_environment_env_vars`).

## 2. Redeploy fanout — reuse `update_deployment_version`'s instance-generation pipeline

**Decision**: Extract a shared helper `redeploy_for_environment_update(deployment, uow) -> Task` that performs the steps `update_deployment_version` already performs after deciding the new version: `generate_instance_from_deployment` → `set_active_instance` → `apply_state`. Call this helper once per non-tombstoned, non-internal deployment in the environment from the new fanout step inside `update_environment`. Each call returns one `Task`; the mutation collects them but does not block on them.

**Rationale**: `update_deployment_version` already has the reconciliation choreography we need — it generates a new `ApplicationInstance`, dispatches a Task through the Prefect workflow, and records a timeline entry through the existing `context_diff` machinery. The "version" parameter is the only thing we don't need; the new helper keeps the deployment's current driver version unchanged and just regenerates the instance with the (now-updated) environment config flowing through `_resolve_instance_context`. This way the env-config update arrives at every deployment via the same path a version upgrade does — same Task type, same timeline shape, same failure semantics.

**Alternatives considered**:

- *Introduce a new Task type `UPDATE_ENVIRONMENT_FANOUT`*: rejected. New Task types fragment the timeline, and the operational story ("an env-config update redeploys the deployment") is already captured by the existing redeploy flow + the `context_diff` field that records what changed.
- *Skip the per-deployment ApplicationInstance row and rely on a single environment-level event*: rejected. The user explicitly asked for "something in the timeline that shows that something has changed" per deployment. ApplicationInstance versioning is the existing per-deployment timeline anchor; using it gives operators one place to look.
- *Dispatch the fanout as a single Prefect parent flow with N children*: rejected for v1. Adds Prefect-flow plumbing without operational benefit; the Tasks are independent and don't need a parent. If observability gaps emerge after ship, parent/child wiring is a follow-up.

**Reference**: `backend/styrmin_backend/services/deployment.py:383-583` (`update_deployment_version`); `backend/styrmin_backend/services/deployment_timeline.py` (the existing `context_diff` machinery the timeline reads from).

## 3. No-op detection

**Decision**: Compute a stable canonical form of both the input and the persisted config, compare for equality, and skip the fanout when equal. The canonical form is `EnvironmentConfig.model_dump(exclude_none=True, mode='json')` with sorted keys at every level — this is what Pydantic's `.model_dump_json(... sort_keys=True)` produces. Both sides go through the same Pydantic model first, so `None` vs missing-key drift is normalised away.

**Rationale**: The naive comparison `input.dict() == environment.config` would false-positive on key-ordering differences and false-negative on `None` vs missing fields. Going through `EnvironmentConfig` first normalises both sides into the same shape. Pydantic's `exclude_none=True` is the right canonical form because the persisted config also excludes none-valued fields by convention (the existing JSON-blob path persists `model_dump(exclude_none=True)`).

**Edge case — updated-at semantics**: A no-op update still persists the config row (potentially incrementing an `updated_at` timestamp if the model has one). This matters because operators sometimes "touch" an environment to force a re-emission of audit logs; the fanout-skip is purely about deployment Tasks, not about whether the row update happens. **The platform persists the row even on a no-op**.

**Alternatives considered**:

- *Hash-based comparison (SHA-256 of JSON)*: rejected. Hashing has no real benefit over equality on already-validated Pydantic objects, and obscures debugging when the comparison disagrees.
- *Skip the row update too on a no-op*: rejected. Operators may rely on `updated_at` ticking to trigger audit-log rotation; we don't break that contract just to save one row write.
- *Per-field diff (only fanout if specific fields changed)*: rejected for v1. Determining which fields actually need a redeploy requires knowing each field's reconcile semantics; an env var change always needs redeploy, but an `external_url_port` change might not. v1 ships the conservative "any change → fanout" rule; per-field optimisation is a follow-up.

**Reference**: `backend/styrmin_backend/services/environments.py` (the existing `update_environment` for the post-008 baseline).

## 4. Per-deployment failure isolation

**Decision**: Inside the fanout loop, wrap each per-deployment redeploy invocation in a `try/except` that catches `Exception` (broadly), records the failure on the per-deployment Task, logs the failure structured, and continues to the next deployment. The mutation result is success once every loop iteration has either dispatched a Task or recorded a failure; it does not surface per-deployment failures in the mutation envelope.

**Rationale**: The existing Task machinery already records per-deployment failures on the Task row; the deployment timeline already surfaces them. The mutation's contract is "I dispatched the work" — the operator finds failures by inspecting individual deployment timelines, which they would do anyway when investigating. Surfacing per-deployment failures in the mutation result would force the response shape to be a list (`[FanoutResult!]!`) which is more API surface for limited gain — the operator inspects one deployment at a time when triaging.

**Edge case — what counts as "dispatched a Task"**: Successful instance generation + `apply_state` returning a Task object. If `apply_state` itself raises (e.g., Prefect dispatch fails), that's a failure case; we record it on whatever scaffolding exists (a born-failed Task, or a structured log if no Task was created).

**Alternatives considered**:

- *Surface per-deployment failures as a list in the mutation result*: rejected — see rationale above. Future work if operators ask for it.
- *Roll back the env-config row update on any per-deployment failure*: rejected by the user's explicit choice (per-deployment failures don't impact the env update or peer deployments). Matches FR-008 exactly.
- *Stop the fanout loop on the first failure*: rejected. The loop must process every deployment; one bad deployment shouldn't lock out updates for peer deployments.

**Reference**: existing Task-status reporting in `backend/styrmin_backend/services/deployment_status.py`.

## 5. Frontend integration — extending `EnvironmentDetailPage` vs a new route

**Decision**: Extend the existing `EnvironmentDetailPage.tsx` (`frontend/src/pages/environments/EnvironmentDetailPage.tsx`) with a new "Configuration" tab. The page already has a tabs scaffold (`Overview`, `Parameters`, `Backups`); adding `Configuration` slots in alongside them. The configuration tab is its own component (`EnvironmentConfigurationTab.tsx`) that renders read-only sections (US3) and embeds the `EnvVarsForm` (US4) inside the env-vars section.

**Rationale**: A new top-level route would duplicate breadcrumbs, page scaffolding, and the environment-fetch hook the existing page already wires up. Adding a tab is one component file + one entry in the tab-list array. The `Parameters` tab pattern is the model — it edits part of the environment's state in-place; configuration follows the same shape.

**Alternatives considered**:

- *Full-page modal for the config view*: rejected. The configuration view is informational + edit-form; tabs are the established UI pattern for that on environment detail pages.
- *Inline within the Overview tab*: rejected. Overview is intentionally lightweight; adding the full configuration view would make it cluttered. Tabs scope each concern.

**Reference**: `frontend/src/pages/environments/EnvironmentDetailPage.tsx` (the page being extended).

## 6. Confirmation dialog UX — naming the deployment count

**Decision**: When the operator clicks Save on the env-vars form, surface a confirmation dialog (`RedeployConfirmDialog.tsx`) that displays the count of deployments in the environment that will be redeployed, plus a list of deployment names. The dialog reads the count + list from the environment's already-fetched data (no extra GraphQL round-trip — `Environment.deployments` is already in the page's query result). The dialog has two buttons: Cancel, Redeploy.

**Rationale**: The redeploy fanout has visible blast radius — every deployment in the environment gets a new Task. The operator must explicitly acknowledge that. Listing the deployment names (not just the count) lets the operator catch "wait, that environment also has the production deployment in it" before they confirm.

**Edge case — zero deployments**: When the deployment count is zero, the dialog displays "No deployments will be redeployed" and the Redeploy button is enabled — this is still a real config update, just one that has no fanout. The operator confirms to commit the env-config row.

**Alternatives considered**:

- *Skip the dialog when the count is zero*: rejected — confusing if operators sometimes see the dialog and sometimes don't. Always show it for write actions.
- *Inline-confirmation in the form ("are you sure?" toggle on the Save button)*: rejected. Modal dialogs are the project's established pattern for write-action confirmations (see `CreateEnvironmentDialog.tsx` for the model).

## 7. Schema-removal coordination — `config: JSON` clean replace

**Decision**: Remove the `config: JSON` argument from `Mutation.updateEnvironment` in the same commit that adds `input: UpdateEnvironmentInput!`. CI's "GraphQL schema freshness" pre-commit hook ensures `schema.graphql` and the SDK + frontend codegen reflect the new shape. Any caller that passed the old JSON shape gets a schema validation error at request time — this is the explicit contract per FR-024 ("the deprecated `config: JSON` argument MUST NOT remain in the schema, the SDK, or the documentation after this feature ships").

**Rationale**: Clean replace is what the user asked for. There is no external consumer that the SDK doesn't already serve; the SDK regenerates from the schema. Frontend code uses the generated GraphQL hooks; those regenerate too. Internal SDK consumers (e.g., E2E tests) update in the same PR.

**Out of scope**: A deprecation window using GraphQL's `@deprecated` directive — would be appropriate if the SDK had external consumers we don't control. Internal-only API → clean replace is fine.

## 8. Testing strategy

| Test bundle | Layer | Coverage |
|---|---|---|
| `test_environment_update_inputs.py` | Unit | Strawberry input → Pydantic `EnvironmentConfig` conversion: every input field maps to its Pydantic counterpart; nested optionals (`scheduling`, `dedicated_ingress`) round-trip cleanly; missing fields produce the unset state on the Pydantic side; invalid env-var rows raise `InvalidEnvVarNameError` at the right point. |
| `test_environments.py` (extend existing) | Unit | Fanout dispatch over a fixture environment with N deployments; no-op detection skips fanout; tombstoned and internal deployments excluded from fanout; per-deployment failure caught and logged; mutation result not affected by per-deployment failures. |
| `test_environment_update_propagation.py` | Propagation (Constitution §V) | Every new GraphQL field/argument on `UpdateEnvironmentInput` and its nested inputs has one assertion: round-trip mutation → DB read → query projection. The matrix is defined in `contracts/graphql.md` §4. **One assertion per row.** Three error-code rejection paths: `INVALID_ENV_VAR_NAME`, `ENV_VAR_SIZE_LIMIT_EXCEEDED`, `DUPLICATE_ENV_VAR_NAME`. |
| `test_environment_update.py` | E2E (`api_only` for the headline; `[ui-chromium]` for US4 form) | **Two scenarios:** (1) US1 headline — environment with three deployments, set env var via mutation, assert pods on all three carry the new env entry within one reconcile cycle, assert each deployment's timeline records the change. (2) US1 failure-isolation — environment with two deployments where deployment B has a deliberate render-fail (e.g., bad scheduling override that's compatible with env A but not B's chart); assert env-config row persists, deployment A converges, deployment B's timeline records the failed Task, peer deployments unaffected. |
| `EnvVarsForm.test.tsx` | Frontend unit (Vitest) | Add/edit/remove rows; client-side validation rules (regex, size caps, duplicates); confirm dialog opens with deployment count; submit-disabled state when invalid. |

**Prior art**:

- `backend/tests/functional/graphql/test_env_vars_propagation.py` from 008 — exact template for the propagation bundle.
- `backend/tests/e2e/test_deployment_env_vars.py` from 008 — exact template for the E2E.
- `frontend/src/__tests__/` for Vitest fixtures (existing component test patterns).

## 9. Out of scope (explicit)

- **Incremental-update mutation** (partial replacement). v1 ships full-replacement only; future revisit if operator UX demands it.
- **Env-var-name autocomplete from `spec.env_vars`**. The driver-side doc surface (US4 of 008) is queryable but the form doesn't yet pull suggestions from it. Follow-up.
- **Optimistic concurrency control** (`If-Match` / version field). v1 accepts last-write-wins on concurrent submissions. Follow-up if a real workload demands it.
- **Surfacing per-deployment failures in the mutation envelope**. The mutation returns `Environment` (the persisted row); per-deployment failures are observable on each deployment's timeline. If operators ask for a fanout-result list, that's a follow-up.
- **New environment-config fields**. This feature exposes the existing `EnvironmentConfig` shape; it does not add new fields. Field additions are separate features.
- **Dedicated parent Prefect flow for the fanout**. v1 dispatches independent Tasks; if observability of "this env update produced these N Tasks" becomes important, a parent flow can be retrofitted.
