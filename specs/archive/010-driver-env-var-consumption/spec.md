# Feature Specification: Driver-Side Env Var Consumption via Values Template

**Feature Branch**: `010-driver-env-var-consumption`
**Created**: 2026-05-08
**Status**: Extracted
**Input**: Course-correction on 008-deployment-env-vars. The post-render injection layer added in 008 (`EnvVarsPatch`) does a JSON `replace` on `/spec/template/spec/containers/0/env`, which silently wipes every env entry the Helm chart set. The "operator value wins on collision" promise was technically true but operationally meaningless — every chart-rendered env var got clobbered, not just the colliding ones. This is unworkable in production.

The pivot: stop injecting at the post-render layer entirely. The platform's job is to **resolve and expose** env vars to the driver's `values.j2.yml` Jinja context. The driver author **consumes** them however the chart expects. Inheritance/merging across env→dep→comp scopes still happens platform-side (the resolution pipeline is correct; only injection was broken). Drivers receive a ready-to-use merged dict.

This shifts env vars from "platform-controlled, driver-unaware" to "operator-supplied, driver-consumed" — closer to how typed parameters already work, but free-form (no schema declaration required, just a dict).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Driver template consumes resolved env vars from the Jinja context (Priority: P1)

A driver author writing `values.j2.yml` reads operator-supplied env vars from the rendering context. The platform resolves env→dep→comp deepest-wins (the existing pipeline from 008) and exposes the merged result as `instance.config.env_vars` (a `dict[str, str]`) and per-component as `components[<name>].env_vars.config`. The driver author chooses how to render — typically as `env:` entries on a Helm chart's container spec, but they can also use the values to set chart conditionals, build ConfigMap content, gate features, etc.

**Why this priority**: Without this exposure, env vars are useless — they're stored, validated, queried, and edited via 008+009's surfaces, but they never reach a running pod. This is the load-bearing piece that makes everything before it actually do something.

**Independent Test**: Operator sets `LOG_LEVEL=debug` at the deployment scope on the simple-app driver. The simple-app `values.j2.yml` (updated in US3) renders an `env: [{ name: LOG_LEVEL, value: debug }]` block. After reconcile, every container of the simple-app pod carries `LOG_LEVEL=debug`. The 008/009 E2E tests for this scenario continue to pass — but now via driver-side consumption rather than platform-side injection.

**Acceptance Scenarios**:

1. **Given** a deployment whose driver consumes `instance.config.env_vars` in its values template, **When** the operator sets `envVars: { LOG_LEVEL: "debug" }` at the deployment scope, **Then** on the next reconcile the pod's container env contains `LOG_LEVEL=debug` (rendered through the chart, alongside any chart-default env entries the driver kept).
2. **Given** an environment with `envVars: { OTEL: "https://otel" }` and a deployment whose driver consumes the merged env dict, **When** the deployment reconciles, **Then** the rendered chart values include `OTEL=https://otel` (because the deployment-effective dict carries the environment-scope value through the merge).
3. **Given** a multi-component driver whose values template consumes `components[<name>].env_vars.config` per component, **When** an operator sets `componentEnvVars: [{ component: "worker", envVars: { WORKER_QUEUE: "orders" } }]`, **Then** the worker component's pods carry `WORKER_QUEUE=orders` while peer components do not.
4. **Given** a driver whose values template does **not** consume `instance.config.env_vars`, **When** the operator sets env vars at any scope, **Then** the env vars are stored, validated, and visible via `Deployment.envVars` / `Deployment.componentEnvVars` queries — but they do **not** reach any pod (the driver opted out by not consuming them; this is a feature, not a bug).
5. **Given** an operator clears all env vars (sets to `{}` at every scope), **When** the deployment reconciles, **Then** the rendered chart values reflect the empty dict — no operator-set env entries remain on pods (chart-default env entries are unchanged because the platform doesn't touch them).

---

### User Story 2 - Remove the broken post-render injection layer (Priority: P1)

The platform's `EnvVarsPatch`, `build_env_vars_post_rendering_patches`, `ApplicationBuilder.build_env_vars_post_rendering_patches()` invocation, the `PostRenderInjection.env_vars` flag, and the `container[0]`-only render-time narrowing all get deleted. The unit tests covering them are deleted along with them. US6 (component-level injection opt-out) and US7 (chart conflict warning) from 008 become meaningless — there is no platform-side injection to opt out of, and there are no platform-side collisions to detect — so their associated GraphQL surface (`PostRenderInjection.envVars`, `EnvVarCollision` type, `DeploymentTimelineEntry.envVarCollisions` field, `ChartEnvCollision` dataclass) is removed from the schema and the codebase.

**Why this priority**: Until the broken injection layer is removed, the platform has two contradictory mechanisms (broken injection + new template consumption) competing for the same pod env list. Operators would see chart env vars wiped by the old layer while drivers attempt to render env vars through the new path. The two must land in lockstep. P1 because it's a correctness prerequisite for US1.

**Independent Test**: After this story lands, `grep -rn "EnvVarsPatch\|build_env_vars_post_rendering_patches" backend/` returns zero hits in source code (test files may keep references temporarily until US3 lands the new tests). The schema does not advertise `PostRenderInjection.envVars`, `EnvVarCollision`, or `DeploymentTimelineEntry.envVarCollisions`. The `inject.env_vars` flag does not appear in the typed `UpdateEnvironmentInput` from 009.

**Acceptance Scenarios**:

1. **Given** a deployment that has env vars set, **When** the platform reconciles, **Then** no `EnvVarsPatch` post-renderer patch is generated and the rendered HelmRelease contains no env-var-injection patch in `spec.postRenderers`.
2. **Given** a Helm chart that sets default env entries on its containers (e.g., `LOG_LEVEL=warn` in the chart's `values.yaml`), **When** the platform reconciles a deployment using this chart with no operator-set env vars, **Then** the rendered pod's container env contains the chart's default entries unchanged — the platform does not delete, replace, or modify them.
3. **Given** a developer searches the codebase for the removed surface, **When** they grep for `PostRenderInjection.env_vars` or `EnvVarsPatch` or `ChartEnvCollision`, **Then** the only hits are in archived spec docs (`specs/008-deployment-env-vars/`) — no live source code references remain.

---

### User Story 3 - simple-app driver demonstrates the consumption pattern (Priority: P1)

The example `simple-app` driver under `driver/examples/simple-app/` is updated to consume `instance.config.env_vars` in its `values.j2.yml`, rendering the operator-supplied env vars as `env:` entries on the simple-app container. This demonstrates the canonical consumption pattern for driver authors writing new drivers, AND keeps the existing 008/009 E2E assertions green (operator sets `LOG_LEVEL=debug` → pod has it).

**Why this priority**: The platform exposing env vars in the context (US1) and removing the broken injection (US2) doesn't help operators unless at least one driver actually consumes them. The simple-app driver is the project's reference implementation; updating it both validates the new pattern end-to-end and preserves the E2E suite's existing pod-level assertions without contortion.

**Independent Test**: The 008/009 E2E test `test_us1_deployment_level_env_var` (operator sets `LOG_LEVEL=debug` on a simple-app deployment, asserts the pod's container env contains the entry) passes against a real cluster. The render path is now: operator → mutation → environment.config / deployment.config → resolved into instance.context → simple-app's `values.j2.yml` consumes `instance.config.env_vars` → Helm chart renders the env entry → FluxCD applies → kubelet runs with the env entry on the pod.

**Acceptance Scenarios**:

1. **Given** the simple-app driver is registered, **When** an operator deploys it without any env vars set, **Then** the pod runs with whatever env entries the simple-app Helm chart sets by default (no operator-set entries; chart-default behaviour preserved).
2. **Given** a simple-app deployment with `envVars: { LOG_LEVEL: "debug", FOO: "bar" }`, **When** the operator triggers a reconcile, **Then** the pod's container env contains both `LOG_LEVEL=debug` and `FOO=bar` alongside any chart-default entries.
3. **Given** the simple-app driver's `values.j2.yml` rendering with a partially-populated context (env vars set on the deployment but not on every component), **When** Jinja renders the template, **Then** the render does not crash on undefined keys (the existing `SilentUndefined` Jinja policy handles this; the template uses defensive accessors like `instance.config.env_vars or {}`).

---

### User Story 4 - Driver-author guide explains the consumption pattern (Priority: P2)

A new doc at `dev/guides/driver-env-var-consumption.md` (or appended to an existing driver-author guide) explains how env vars reach the template, the merged-dict shape, how to render them as Helm `env:` entries, how to scope them per component, and how to combine with chart-default env vars (the driver decides ordering and precedence — the platform doesn't impose a policy). At least two worked examples cover: single-component drivers consuming `instance.config.env_vars`, multi-component drivers consuming `components[<name>].env_vars.config`.

**Why this priority**: Without docs, driver authors discover the new pattern by reading simple-app's `values.j2.yml` and inferring. That works for trivial drivers but leaves multi-component scenarios undocumented and sets up cargo-cult patterns. P2 because the platform and reference driver work without it; the doc accelerates third-party driver authors.

**Independent Test**: A driver author unfamiliar with 008/009/010 reads the guide and writes a new driver template that consumes env vars correctly on the first try, without referring to the simple-app source.

**Acceptance Scenarios**:

1. **Given** a driver author reading the new guide, **When** they look for "how do I expose operator-set env vars to my chart", **Then** they find a documented `instance.config.env_vars` accessor with a worked example.
2. **Given** a multi-component driver author, **When** they read the guide, **Then** they find a `components[<name>].env_vars.config` example showing per-component scoping.
3. **Given** a driver author uncertain how to combine chart-default env entries with operator-set ones, **When** they read the guide, **Then** they understand the platform doesn't impose a policy — they choose ordering, deduplication, and overrides in the chart template.

---

### Edge Cases

- A driver template references `instance.config.env_vars` when no env vars are set anywhere — the field is `None`-or-empty in the Pydantic model; with `model_dump(exclude_none=True)` (the existing behaviour) the key may be absent from the rendering dict. Templates use `instance.config.env_vars or {}` to handle this defensively.
- A driver template references `components[<name>].env_vars.config` when a component has no env vars set — same shape as above; templates use `(components[name].env_vars.config if components[name].env_vars else {})` or equivalent.
- An operator sets `componentEnvVars` on a component the driver template does not consume — the env vars are stored and queryable but never reach a pod (driver opted out by not consuming them).
- An operator sets env vars on a deployment whose driver was registered before this feature shipped — the driver's old `values.j2.yml` doesn't consume env vars; operator-set env vars are stored but not applied. Operator must update the driver to consume them.
- 008's previously-injected env vars (in pre-010 deployments where the broken injection ran) persist on existing pods until the next reconcile. After 010 ships, the next reconcile renders pods through the new path; whether operator-set env vars survive depends on whether the driver consumes them. **Migration responsibility lies with driver authors**: any driver that previously relied on platform injection must add explicit `instance.config.env_vars` consumption to keep working.
- A driver template renders env vars in an unexpected order across reconciles (Python dict ordering changed) — Python 3.7+ preserves insertion order, but a defensive driver author might want to sort. The platform makes no ordering promise beyond "the dict is iteration-stable within a single render"; drivers needing deterministic ordering sort in the template.

## Requirements *(mandatory)*

### Functional Requirements

#### Template Context Exposure (US1)

- **FR-001**: The platform MUST expose the deployment-effective env vars dict to driver templates as `instance.config.env_vars` (a `dict[str, str]`). This is the env→dep-merged result computed by the existing `_resolve_instance_config` resolver from 008+009.
- **FR-002**: The platform MUST expose per-component effective env var dicts to driver templates as `components[<name>].env_vars.config` (a `dict[str, str]`). This is the env→dep→comp-merged result computed by the existing `EnvVarsResolver`.
- **FR-003**: Both fields MUST follow the existing `model_dump(exclude_none=True)` rendering convention used by `render_value_template` — i.e., the keys are present in the dumped dict when env vars are set at any layer, and may be absent when no env vars are set anywhere. Driver authors handle the absence with defensive Jinja accessors.
- **FR-004**: The exposed dicts MUST reflect the same canonical merge order documented by 008's FR-002 (env → dep → comp deepest-wins). The platform MUST NOT silently re-order, filter, or transform the dicts in any way that diverges from what `Deployment.envVars` / `Deployment.componentEnvVars` GraphQL fields project.

#### Removed Surface (US2 — clean replace)

- **FR-005**: `backend/styrmin_backend/agent/service/kubernetes/resources/blocks/patches.py:EnvVarsPatch` MUST be deleted.
- **FR-006**: `backend/styrmin_backend/services/env_vars/patch_builder.py:build_env_vars_post_rendering_patches` MUST be deleted (and the entire `services/env_vars/patch_builder.py` module if it has no other content).
- **FR-007**: `backend/styrmin_backend/agent/service/kubernetes/resources/builders/application.py:build_env_vars_post_rendering_patches` (the `ApplicationBuilder` method) AND its invocation from `ApplicationBuilder.build()` MUST be deleted.
- **FR-008**: The `PostRenderInjection.env_vars` field MUST be removed from `backend/styrmin_backend/context/models/config.py`. The corresponding Strawberry input mirror (`PostRenderInjectionInput.envVars`) added in 009 MUST be removed.
- **FR-009**: The `EnvVarCollision` Strawberry type, `ChartEnvCollision` dataclass, and `DeploymentTimelineEntry.envVarCollisions` GraphQL field MUST be removed (a US7 surface from 008 that became meaningless without injection).
- **FR-010**: All unit tests asserting against the removed surface (env-vars cases in `test_patch_builder.py`, env-vars-injection assertions in `test_application_builder_env_vars.py`, propagation tests for the removed GraphQL fields) MUST be deleted — not skipped, not deferred.
- **FR-011**: The `schema.graphql` and the regenerated SDK + frontend types MUST reflect the removed surface. `grep -rn "envVarCollisions\|ChartEnvCollision\|PostRenderInjection.*envVars" backend/ python_sdk/ frontend/src/ schema.graphql` MUST return zero hits (in source code; archived spec docs may retain historical references).

#### simple-app Driver Update (US3)

- **FR-012**: `driver/examples/simple-app/values.j2.yml` MUST be updated to consume `instance.config.env_vars` and emit them as standard Helm chart env entries on the simple-app container.
- **FR-013**: The simple-app driver's Helm chart (or its values shape, if the chart accepts a free-form env list) MUST support an `env: [{ name, value }]` array on the container spec. If the chart does not currently support this, the chart itself is updated alongside the values template — the simple-app driver and its chart are both project-controlled examples.
- **FR-014**: The 008/009 E2E test asserting "operator sets `LOG_LEVEL=debug`, pod has it" MUST continue to pass against the updated simple-app driver. The test bodies do not change; only the platform's render path differs (driver-side consumption replaces platform-side injection).
- **FR-014a**: The retained E2E (or a new sibling E2E assertion in the same file) MUST explicitly verify that at least one chart-default env entry is preserved alongside the operator-set entries. This is the load-bearing assertion vs 008's broken behaviour and the operationally-significant outcome of SC-002. Without this explicit assertion, a regression that re-introduced env-list clobbering would pass the existing E2E. The simple-app chart's existing default env entries (or a sidecar / postgresql container's chart-rendered env) are the natural assertion target.

#### What stays from 008+009 (preserved invariants)

- **FR-015**: The `env_vars` field on `EnvironmentConfig`, `DeploymentConfig`, and the per-component config block MUST remain unchanged. Operators continue to read and write env vars at all three scopes via the existing typed mutation surface from 009.
- **FR-016**: The validation pipeline MUST remain unchanged: name regex `^[A-Za-z_][A-Za-z0-9_]*$`, per-value cap 64 KiB, per-scope cap 100 entries / 256 KiB, no duplicate names, FR-008a resolved per-component / per-deployment caps from 008. Typed error codes (`INVALID_ENV_VAR_NAME`, `ENV_VAR_SIZE_LIMIT_EXCEEDED`, `DUPLICATE_ENV_VAR_NAME`, `UNKNOWN_COMPONENT_ENV_VAR`) continue to surface at the GraphQL boundary.
- **FR-017**: The resolution pipeline (`_merge_env_vars` env→dep→comp deepest-wins, `ResolvedComponentEnvVars` + provenance + `is_orphaned`) MUST remain unchanged. Per-deployment no-op detection from 009 (FR-010 of 009) MUST remain unchanged.
- **FR-018**: The GraphQL read surface (`Deployment.envVars`, `Deployment.componentEnvVars` with `isOrphaned`, `Environment.envVars`, `ApplicationDriverVersion.envVars`) MUST remain unchanged.
- **FR-019**: The driver-side `spec.env_vars` doc-only declarations + driver loader validation from 008 (US4) MUST remain unchanged. Their semantic meaning shifts subtly from "env vars this app respects" to "env vars this driver consumes" — but the wire shape is identical and no validator changes.
- **FR-020**: 009's `UpdateEnvironmentInput` typed mutation, the per-deployment redeploy fanout, and the frontend Configuration tab + env-vars edit form MUST remain unchanged. (The 009 frontend nested-clearing block from the post-implementation review continues to apply.)

#### Documentation (US4)

- **FR-021**: A new guide at `dev/guides/driver-env-var-consumption.md` MUST exist after this feature ships. It MUST document: how env vars reach the template (FR-001/FR-002 surfaces), the merged-dict shape, how to render them as Helm `env:` entries, how to scope them per component, and how to combine with chart-default env entries.
- **FR-022**: The guide MUST include at least two worked examples: a single-component driver consuming `instance.config.env_vars`, and a multi-component driver consuming `components[<name>].env_vars.config`. The examples MUST demonstrate **safe value escaping** — for instance, by using Jinja's `tojson` filter or equivalent quoting — so driver authors emitting env-var values into YAML do not silently produce broken values.yaml when a value contains characters that would break unquoted YAML (newlines, quotes, leading dashes, etc.). The platform does NOT escape values for drivers; this is a driver-author responsibility, and the guide MUST surface it explicitly.
- **FR-023**: `dev/knowledge/backend/deployment-env-vars.md` (created in 008's polish phase) MUST be updated to reflect the architecture change — the "post-render injection" paragraph is replaced with a "driver-side consumption" paragraph pointing at the new guide.

#### Out of Scope (codified)

- **FR-024**: The platform MUST NOT expose layered env / dep / comp env-var dicts separately to the driver template in v1. Drivers receive only the merged result. (A future feature may add layered access if a driver author asks.)
- **FR-025**: The platform MUST NOT ship opinionated render macros (e.g., a Jinja `render_env_vars()` helper) in v1. Drivers consume the dict directly.
- **FR-026**: The platform MUST NOT reintroduce platform-side post-render env-var injection in any form. Operators wanting env vars on their pods rely on driver-side consumption; drivers that don't consume operator-set env vars get an opt-out by default.

### Key Entities

- **`instance.config.env_vars`** (rendering-context field): the deployment-effective merged env-var dict (env+dep). Already exists as `DeploymentConfig.env_vars` post-008+009; this feature simply documents it as the consumption surface.
- **`components[<name>].env_vars.config`** (rendering-context field): the per-component effective merged env-var dict (env+dep+comp). Already exists as `ResolvedComponentEnvVars.config` post-008; this feature documents it as the consumption surface.
- **driver values template (`values.j2.yml`)**: the existing Jinja template every driver ships. Becomes the canonical consumption point for operator-set env vars.
- **Removed: `EnvVarsPatch`, `ChartEnvCollision`, `EnvVarCollision`, `PostRenderInjection.envVars`**: the broken injection-layer entities deleted by US2.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator who sets `envVars: { LOG_LEVEL: "debug" }` on a simple-app deployment sees `LOG_LEVEL=debug` on the pod's container env on the next reconcile, **alongside** any chart-default env entries the simple-app chart sets — chart-default entries are unchanged. The 008/009 E2E `test_us1_deployment_level_env_var` proves this.
- **SC-002**: A Helm chart that sets default env entries on its containers (e.g., `LOG_LEVEL=warn`) running on the platform with no operator-set env vars renders pods with the chart's defaults intact. The platform does NOT delete, replace, or modify chart-rendered env entries — verified by an E2E with a chart whose values.yaml sets a default env entry the driver does not override.
- **SC-003**: 100% of source-code references to `EnvVarsPatch`, `build_env_vars_post_rendering_patches`, `PostRenderInjection.env_vars`, `EnvVarCollision`, `ChartEnvCollision`, and `DeploymentTimelineEntry.envVarCollisions` are removed (verified by `grep` on `backend/`, `python_sdk/`, `frontend/src/`, `schema.graphql`). Archived spec docs may retain historical references.
- **SC-004**: The driver author guide at `dev/guides/driver-env-var-consumption.md` enables an unfamiliar driver author to write a values template consuming env vars correctly without reading simple-app source.
- **SC-005**: Every retained GraphQL field/argument from 008+009's env-vars surface continues to have a green propagation test. The removed surface loses its tests cleanly.
- **SC-006**: The mandatory E2E for "operator sets env var → pod has it" passes via driver-side consumption (US3 update) — no platform-side injection in the render path.

## Assumptions

- Driver authors are willing to update their values templates to consume operator-set env vars. The simple-app reference implementation + the new guide make this a small, well-documented change. Drivers that don't update simply opt out — operator-set env vars are stored, queryable, and editable, but don't reach a pod for that driver.
- The existing `model_dump(exclude_none=True)` convention used by `render_value_template` is the right canonical form for exposing env vars to the template. Driver authors handle the "key may be absent" case with defensive Jinja accessors (`instance.config.env_vars or {}`). This matches how every other config field in the rendering context is exposed today.
- The simple-app Helm chart's container spec accepts a free-form `env:` list (or can be trivially extended to accept one). If the chart's structure makes this awkward, the chart itself is updated alongside the values template — both are project-controlled examples.
- The `SilentUndefined` Jinja policy (in `get_jinja_environment`) is sufficient for handling absent context fields. Driver authors who want stricter behaviour can add explicit defensive accessors.
- 008's `spec.env_vars` driver-side documentation field's semantic shift (from "things this app respects" to "things this driver's template consumes") is acceptable as a doc-only change. The wire shape, validators, and registration semantics stay identical; only the prose around what the field "means" updates.
- The two skipped E2Es from prior work (T026 from 008's failure-isolation, T061 from 009's UI form flow) remain skipped through 010 — they were skipped for reasons orthogonal to the injection-layer pivot. 010 does not unskip them.
- 008's PR (#197) gets rewritten in place as part of 010's implementation. The branch chain 008 → 009 → 010 is reordered/squashed at PR-merge time so the broken injection commits never land in `develop`. The exact rebase shape is a merge-time concern; the spec doesn't constrain it.
