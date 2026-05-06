# Phase 0 Research: Deployment Env Vars

## 1. Mutation surface — typed inputs vs JSON `config`

**Decision**: Env var writes ride the existing `config: JSON` argument on `deploy()` and `updateDeployment()`. Reads are exposed as typed `envVars: [EnvVar!]!` and `componentEnvVars: [ComponentEnvVars!]!` query fields on `Deployment`. **No new mutation argument is added.**

**Rationale**: The Pydantic-driven configuration model is the load-bearing input contract — `EnvironmentConfig`, `DeploymentConfig`, and the per-component config block are all serialised through the JSON `config` channel today. The 001-pod-scheduling-config feature took the same path: scheduling values flow in via `config: JSON` and are validated against `SchedulingConfig` server-side. Adding typed mutation arguments alongside the JSON channel would create a second write path with different validation semantics — a known footgun (which validator wins on conflict?). The downside of "JSON for writes, typed for reads" is mild: API clients that prefer typed inputs can construct the JSON via the SDK's `EnvironmentConfig`/`DeploymentConfig` Pydantic models.

**Alternatives considered**:

- *Strict-typed mutation args* (`envVars: [EnvVarInput!]`, `componentEnvVars: [ComponentEnvVarsInput!]`): closer to the PRD's literal text in §"GraphQL surface". Rejected because it duplicates the JSON `config` write surface and forks the validation story between Pydantic (`config`) and Strawberry input types (`envVars`). Reviewers may revisit during `/speckit.critique-run` if a typed-input UX is judged worth the cost.
- *New top-level `setDeploymentEnvVars` mutation*: explicitly forbidden by the PRD ("**No new mutation is added**"). Not pursued.

**Reference**: `backend/styrmin_backend/api/schema/mutation.py:402-471` (existing `deploy` / `update_deployment` shape); `specs/001-pod-scheduling-config/plan.md` (precedent).

## 2. Resolution & precedence — reuse the SchedulingConfig merge story

**Decision**: Env var resolution lives next to the existing context-resolver merge for `SchedulingConfig`. A new `_merge_env_vars(env, dep, comp) -> dict[str, str]` performs per-key deepest-wins, mirroring the existing `_merge_scheduling_config` that produces `ResolvedComponentScheduling`. The resolver emits a `ResolvedComponentEnvVars(config: dict[str, str], provenance: dict[str, ProvenanceLevel])` per component, including the same provenance contract.

**Rationale**: The PRD calls out "the existing `ResolvedConfig` pipeline rather than living as a parallel system". Putting env vars next to scheduling is the lowest-risk path: same merge primitives, same provenance machinery, same per-component pre-computation, and the post-renderer already knows how to look up `context.components[*].scheduling`-shaped data. The deployment-with-no-components fallback (apply broadly) is the same branch the scheduling resolver already encodes.

**Alternatives considered**:

- *Inline merge inside the patch builder*: rejected. Would re-introduce the parallel-system risk and make the operator/agent path harder to test.
- *Global "everything-is-merged" resolver*: out of scope for this feature; deferred to a future refactor if multiple feature-specific merges accumulate. Premature abstraction otherwise.

**Reference**: `backend/styrmin_backend/context/resolvers.py`, `backend/styrmin_backend/context/models/components.py:51-63`.

## 3. Storage — JSON columns vs new schema

**Decision**: Env vars merge into the existing `Environment.config` and `ApplicationInstance.context` JSON columns via the existing Pydantic models. **No new database column or migration.**

**Rationale**: `EnvironmentConfig` and `DeploymentConfig` are already serialised to/from JSON columns; adding `env_vars: dict[str, str] | None` and `component_env_vars: list[ComponentEnvVars] | None` to those models is a Pydantic-only change that flows automatically through the existing repository layer. The platform's per-deployment context-embedding mechanism (ADR-006) already carries the resolved config to the agent layer; nothing operator-side needs touching.

**Alternatives considered**:

- *Dedicated `deployment_env_vars` table*: rejected. Would require a migration, repository changes, and a parallel persistence path — and would not improve query semantics because env vars are always read together with the rest of the deployment config.
- *Per-component env vars stored on the per-component config sub-block (already JSON)*: same conclusion as the deployment scope; this is the chosen approach.

**Reference**: `backend/styrmin_backend/context/models/config.py:424-461` (`EnvironmentConfig`, `DeploymentConfig`), ADR-006 deployment CRD context embedding.

## 4. Conflict detection between operator-set env vars and chart-rendered env

**Decision**: Conflict detection runs inside the new patch builder, at render time. The patch builder walks the rendered manifest's container `env` list (it already has access via the strategic-merge target) and records a `ChartEnvCollision(component, container, name, chart_value, user_value)` per collision on the patch result. The agent layer pulls these collisions out and surfaces them via two channels:

1. **Primary**: a structured field on the per-task deployment timeline entry. The timeline today is built from tasks + context diffs (`backend/styrmin_backend/services/deployment_timeline.py:39-73`); we extend `TimelineEntry` with an optional `env_var_collisions: list[ChartEnvCollision]` and surface it as `DeploymentTimelineEntry.envVarCollisions: [EnvVarCollision!]!` (default `[]`).
2. **Fallback**: a structured `logger.warning("env_var_chart_collision", deployment_id=..., name=..., chart_value=..., user_value=...)` log line from the patch builder, emitted unconditionally so the signal exists even when timeline emission degrades (FR-028).

**Rationale**: The deployment timeline is currently a *derived view* — there is no event-emission API today (verified by reading `services/deployment_timeline.py`). Adding one would be a heavier scope creep than the PRD warrants. Piggy-backing on `TimelineEntry` is a one-field extension and keeps the conflict signal visible to operators in the same place they already read upgrade history.

**Alternatives considered**:

- *Detect at HelmRelease post-render time, on-cluster*: rejected. Conflict reporting needs to flow back to the platform, and the agent layer is already the bridge for everything else.
- *Block the deployment on collision*: explicitly rejected by the PRD ("non-blocking; if conflict detection is awkward to wire at the patch layer, it degrades to a structured log entry rather than blocking the feature").
- *Dedicated `DeploymentTimelineEvent` table*: deferred to a separate ADR if/when more event types accumulate. Premature for v1.

**Reference**: `backend/styrmin_backend/services/deployment_timeline.py`, `backend/styrmin_backend/api/definitions/deployment_timeline/model.py`.

## 5. Driver upgrade orphan handling

**Decision**: Orphan detection runs inside the env vars resolver during configuration resolution. For every stored `componentEnvVars` block whose target component name does not appear in the deployment's current driver's component map, the resolver:

1. Sets `is_orphaned = True` on the resolved block (exposed as `ComponentEnvVars.isOrphaned`).
2. Skips the block during effective-dict computation — orphaned env vars are **not** injected.
3. Leaves the stored config block intact (no auto-deletion).

The "single timeline event per upgrade transition" requirement is satisfied by the existing `context_diff` machinery: an upgrade naturally produces one `Task` whose `context_diff` records the orphan (the component name appears in stored config but not in the new driver's component map). No new event type is added.

**Rationale**: The upgrade-orphan rule is fundamentally a *rendering-and-resolution-time* concern, not a *write-path* concern — the operator did not change anything; the driver did. Detection at resolution time is the right layer: it is run once per reconcile, the input (driver components + stored env vars) is fully available, and the output (`isOrphaned`) is naturally consumed by both the post-renderer (skip it) and the GraphQL query (expose it).

**Alternatives considered**:

- *Block the upgrade*: explicitly rejected by the PRD ("Driver upgrades that would orphan stored component env vars (component renamed or removed) **succeed**"). Aligns with US5.
- *Auto-delete the orphaned block at upgrade time*: rejected. Per the PRD "warn-and-keep rather than block" semantics, the block must remain visible so the operator can audit and clean up. The `isOrphaned` query field is a contract precondition.
- *Emit a dedicated "env vars orphaned" deployment timeline event*: rejected for v1 — see §4. The existing `context_diff` channel already records the visible drift, and the resolver's `isOrphaned` field gives operators a discoverability hook in the API/UI without a new event mechanism.

**Reference**: PRD §"Implementation Decisions / Validation rules" and §"Further Notes".

## 6. Testing strategy

| Test bundle | Layer | Coverage |
|---|---|---|
| `test_validator.py` | Unit | name regex acceptance/rejection (each character class), per-value cap (64 KiB), per-scope dict cap (100 entries / 256 KiB), duplicate-name rejection, empty-value acceptance, list↔dict conversion. |
| `test_resolver.py` | Unit | precedence matrix across env / dep / comp layers, deployment-only, environment-only, orphan detection (component renamed/removed), no-components-declared fallback, provenance recording. |
| `test_patch_builder.py` | Unit | deployment-level only, component-level only, mixed, opt-out via `inject.env_vars=False`, no-components-declared fallback, multi-container injection, chart-conflict detection emits `ChartEnvCollision` entries. |
| `test_env_var_doc_validator.py` | Unit | name regex, `level=component` requires non-empty `components`, every `components` reference exists in driver's component map, name uniqueness within the doc list, registration failure on any violation. |
| `test_application_builder_env_vars.py` | Unit | `build_env_vars_post_rendering_patches()` is invoked in `ApplicationBuilder.build()` next to scheduling patches; emitted patches reach `target_patches`. |
| `test_env_vars_propagation.py` | Propagation (Constitution §V) | Every new GraphQL field/argument flows from mutation input → repository → DB → query result. **One assertion per new field/argument.** |
| `test_deployment_env_vars.py` | E2E (`api_only`) | Single end-to-end scenario: deploy a multi-component app with env vars set at deployment scope and per-component scope (with overlap); assert pod containers' `env:` blocks reflect the merged set with component winning on collisions; assert driver query exposes the doc declarations; assert `componentEnvVars.isOrphaned` for an upgrade that removes a component. |

**Prior art** (templates to copy from):

- `backend/tests/unit/context/test_scheduling_resolver.py` — direct template for `test_resolver.py`.
- `backend/styrmin_backend/services/scheduling/validator.py` + tests — direct template for `test_validator.py`.
- `backend/tests/unit/agent/test_application_builder_scheduling.py` — direct template for `test_application_builder_env_vars.py`.
- `dev/guides/graphql-propagation-tests.md` — mandatory recipe for the propagation test bundle.

## 7. ADR commitment

**Decision**: Draft `dev/adr/adr-019-deployment-env-vars.md` alongside the implementation. The ADR records:

1. Why env vars exist parallel to typed parameters (boundary: typed-and-validated vs free-form).
2. Why driver-side declaration is doc-only (no validation, no defaults).
3. Why the chart-conflict policy is post-render-wins-with-warning (not block, not chart-wins).
4. Why upgrade orphaning is warn-and-keep rather than block (operational safety).
5. Why a `cluster` scope is excluded for v1 (cross-team blast radius without an auth model).
6. Why `isOrphaned` is a first-class API contract (degradation path otherwise renders orphans invisible).

**Rationale**: The PRD's "Further Notes" calls this an ADR candidate for the same reasons the rule of thumb uses (hard to reverse, surprising, real trade-offs). Drafting alongside the implementation prevents the ADR from being skipped under deadline pressure, and the ADR becomes the durable record once the spec is archived (per `dev/adr/`).

## 8. Out of scope (explicit)

The following are deliberately **not** addressed by this plan and are restated here so reviewers see them in one place:

- **Secret env vars** (`valueFrom.secretKeyRef`, encrypted-at-rest, masking) — separate ticket.
- **Cluster-scoped env vars** — deferred until an auth model exists.
- **Per-container injection** — components are the smallest addressable unit; all containers in a pod template receive the merged set.
- **Driver-side validation/defaults/required env vars** — driver authors who need these use parameters.
- **UI editing surfaces** — frontend ticket follows separately.
- **Existing parameter migration** — no auto-rewrite.
