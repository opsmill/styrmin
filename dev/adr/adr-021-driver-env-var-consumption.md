# ADR-021: Driver-Side Env Var Consumption via Values Template

**Status**: Accepted
**Date**: 2026-05-08
**Source**: specs/010-driver-env-var-consumption/ (spec, plan, research)
**Supersedes**: the post-render env-vars injection portions of [ADR-019](adr-019-deployment-env-vars.md) (§3 conflict policy + the `EnvVarsPatch` / `envVarCollisions` surfaces); ADR-020's environment-config fanout is unaffected.

## Context

008-deployment-env-vars (ADR-019 §3) shipped operator-set environment variables through a **post-render JSON-patch**: `EnvVarsPatch` did `replace` on `/spec/template/spec/containers/0/env`. The "operator value wins on collision" promise was technically true but operationally meaningless — every chart-rendered env entry was clobbered, not just the colliding ones. A chart that set `LOG_LEVEL=warn` as a default would have that default disappear the moment any operator-set env var was applied to the deployment, even an unrelated one.

The pivot: stop injecting at the post-render layer entirely. The platform's job is to **resolve and expose** env vars to the driver's `values.j2.yml` Jinja context. The driver author **consumes** them however the chart expects. Inheritance/merging across env→dep→comp scopes still happens platform-side (the resolution pipeline from 008 is correct; only injection was broken). Drivers receive a ready-to-use merged dict.

This ADR records the load-bearing decisions behind that pivot so future maintainers don't relitigate them.

## Decision

### 1. Why post-render injection failed

Kubernetes strategic-merge has no container-name wildcard — the merge key for the `containers` array is `name`. JSON-patch `replace` on `/spec/template/spec/containers/0/env` clobbers whatever the chart set. Per-container strategic-merge by chart-known names would require the platform to know container names, but that information lives in the chart's templates, not in the driver manifest.

We considered two ways to give the platform that information and rejected both:

- **Re-render the chart server-side, inspect the rendered manifest, then patch.** Heavy; couples the platform to chart internals; doubles the rendering cost on every reconcile.
- **Require driver authors to declare every container name in `driver.styrmin.yml`.** Significantly more intrusive than driver-side template consumption — a new contract that drivers must keep in sync with their chart's container layout for no operator-visible benefit.

Driver-side consumption sidesteps the entire question. The chart-rendering layer already knows its own container names; we let it stay in charge.

### 2. Why driver-side consumption is the right boundary

Drivers know their charts. The platform's job is to **resolve and expose**; the driver author owns the **consumption shape**:

- which container the env vars land on,
- which `env:` list the values feed into (or whether the values drive ConfigMap content, chart conditionals, feature gates, etc.),
- which precedence policy applies on chart-vs-operator collisions,
- whether to scope per component, per pod-template, or globally.

This matches how typed parameters already flow through `values.j2.yml`, but free-form (no schema declaration required — drivers receive a `dict[str, str]` directly).

### 3. Why merged dicts (not layered)

Drivers receive the merged result: `instance.config.env_vars` (env→dep merged) and `components[<name>].env_vars.config` (env→dep→comp merged). They do **not** receive the raw layers separately. Layered access (raw env / raw dep / raw comp dicts) was considered and deferred — no concrete driver-author use case has surfaced. Merged-only is simpler; the merge order is an operator concern, controlled through the standard mutation surface.

When (if) a driver author asks for layered access, FR-024 codifies it as a future feature, not a v1 commitment.

### 4. Why no helper macros

The v1 surface is `dict[str, str]` and Jinja's standard filters (`tojson`, `items`, `default`). No `render_env_vars()` helper, no included macros, no chart-side library imports.

Drivers know their charts' env-list shape (some want `env:`, some want `extraEnv:`, some want `envFrom:`, some want a ConfigMap). Bundling a helper that fits one shape would be wrong for the others; bundling all shapes would be premature. Helpers can land when patterns accumulate across multiple drivers — for now, the simple-app reference and this guide are the canonical pattern.

### 5. Migration responsibility

Driver authors update their values templates to consume operator-set env vars. The platform does not auto-migrate. Drivers from before 010 silently opt out — operator-set env vars are stored, queryable, and editable through the unchanged 008+009 surfaces, but don't reach pods until the driver author explicitly wires up consumption.

This is a feature, not a bug: each driver decides whether to expose the surface. A driver that has good reasons to ignore env vars (security-locked appliance images, compliance-driven contracts) is unaffected by 010 and stays that way until its author opts in. This is the same opt-in shape as every other rendering-context field — typed parameters, scheduling, ip_whitelist, etc.

### 6. Relationship to ADR-019 + ADR-020

010 supersedes **ADR-019 §3** (the post-render injection design + the conflict-policy machinery: `EnvVarsPatch`, `EnvVarCollision`, `ChartEnvCollision`, `DeploymentTimelineEntry.envVarCollisions`, `PostRenderInjection.envVars`). The operator-facing config model (ADR-019 §1, §2, §4 — typed-vs-free-form boundary, doc-only driver-side declarations, upgrade-orphan policy) and the validation pipeline (name regex, size caps, error codes) are preserved.

ADR-020 (009's env-config fanout) is unaffected. Environment-config edits still trigger per-deployment redeploys; the redeploy path now flows through the driver's values template (010) instead of a post-render patch (008). The fanout machinery itself is identical.

## Consequences

- **Drivers gain control over env-var consumption.** A driver author chooses whether `extraEnv` appends or `env` overrides, whether values feed a ConfigMap or a container directly, whether a sidecar receives the values or only the primary container. This is the same trade-off as every other config field — uniformity over special-casing.
- **Operators experience a one-time migration.** Drivers from pre-010 silently opt out (env vars stored but not applied) until their authors update the values template. The simple-app reference shows the canonical shape; the new driver-author guide documents it.
- **The platform's surface area shrinks.** `EnvVarsPatch`, the patch builder module, the `ChartEnvCollision` dataclass, the `EnvVarCollision` GraphQL type, and the timeline collision field all go away — fewer code paths to maintain, fewer edge cases to test.
- **Multi-container per-pod injection becomes driver-author land.** It was always difficult-to-do-correctly at the platform layer (the chart's container names live in chart templates); 010 stops pretending the platform can do it generically.
- **Helm-chart-default env entries are preserved.** The load-bearing operational invariant 008 violated. SC-002 + the FR-014a E2E (`backend/tests/e2e/test_deployment_env_vars.py::test_us1_deployment_level_env_var`) explicitly assert at least one chart-default env entry stays present alongside operator-set entries.
- **Future work this opens up**: layered template context (raw env / dep / comp dicts, FR-024 deferred); driver-author-side helper macros once patterns accumulate (FR-025 deferred); a `driver lint` check that warns when `spec.env_vars` declarations don't match what the template actually consumes.
- **Future work this closes off**: any form of platform-side post-render env-var injection. FR-026 codifies the non-feature.

## Alternatives Considered

- **Fix the injection layer in place via per-container strategic-merge by chart-known container names.** Rejected — see §1 above. The platform doesn't have the container-name information without an invasive new contract or a server-side chart re-render.
- **Phased deletion (mark deprecated in one release, delete in the next).** Rejected — the surface was always broken; nothing legitimate uses it. There is no deprecation period worth honouring.
- **Expose a top-level `env_vars` rendering field outside `instance.config` for terser driver-side access** (e.g., `{{ env_vars.LOG_LEVEL }}` instead of `{{ instance.config.env_vars.LOG_LEVEL }}`). Rejected for v1 — the `instance.config.*` namespace is consistent with how every other resolved config field is exposed (scheduling, ip_whitelist, etc.). Driver authors learn one namespace, not two.
- **Ship layered template context** (raw env / dep / comp dicts alongside the merged result). Deferred — no concrete use case yet. FR-024 codifies the deferral.
- **Ship opinionated render macros** (Jinja `render_env_vars()` helper). Deferred — drivers know their charts' env-list shape; v1 minimum surface area, helpers can land when patterns emerge. FR-025 codifies the deferral.
- **Auto-migrate existing drivers** (platform inserts `extraEnv` consumption into pre-010 drivers' templates on registration). Rejected — too magic; would surprise driver authors who deliberately omit env-var consumption; the simple-app reference + this guide make the manual update trivial.
