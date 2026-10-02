# Feature Specification: Platform-Owned Env Var Injection via Post-Render

**Feature Branch**: `fac/feat-operator-env-vars-chart-s-deployment-334-3xvoh`

**Created**: 2026-10-02

**Status**: Draft

**Input**: Idea brief "Platform-owned env var injection via post-render" — [opsmill/styrmin#385 (comment)](https://github.com/opsmill/styrmin/issues/385#issuecomment-5956413845). Seed issue: [#385](https://github.com/opsmill/styrmin/issues/385). Related: [#334](https://github.com/opsmill/styrmin/issues/334) (infrahub task-manager `PROMETHEUS_MULTIPROC_DIR`), [#281](https://github.com/opsmill/styrmin/issues/281), [#20](https://github.com/opsmill/styrmin/issues/20) (image overrides, next on the same mechanism).

## Context

Today a driver's `values.j2.yml` injects user-set env vars by writing the chart's env key (via the `component_env_vars` template filter). When the chart models env as a list, Helm replaces the whole list instead of merging it, so every default env var the chart ships is silently dropped. Bumping the `infrahub` driver to chart `4.33.2` lost the chart's `PROMETHEUS_MULTIPROC_DIR=/tmp` and `PREFECT_UI_SERVE_BASE=/` on the task manager, which then crash-loops while the deployment looks healthy in Styrmin. Driver authors work around it by copying chart defaults into the template and re-syncing them on every chart bump.

This feature moves env var injection out of the driver's values template and into the platform: Styrmin merges each component's resolved env vars into one driver-declared container — the **component container** — by env var `name`, after the chart has rendered. Chart entries survive; a user value of the same name replaces the chart's. The values-template injection route is retired.

## User Scenarios & Testing *(mandatory)*

The primary actor is the **driver author**, who stops copying chart env defaults into `values.j2.yml` and stops re-syncing them on chart bumps. The secondary actor is the **user setting env vars on a deployment** (via SDK, CLI, or frontend), whose env vars reach the container without any driver wiring and can replace a chart default of the same name.

### User Story 1 - Component-scope env var merges into the chart's rendered env (Priority: P1)

A user sets an env var on one component of a deployment. The driver declares that component's component container and its `values.j2.yml` does not mention env vars at all. On the next reconcile the container carries the user's env var **and** every env entry the chart rendered. Setting a var with the same name as a chart default replaces the chart's value; clearing it brings the chart default back.

**Why this priority**: This is the defect in #385 and the headline value. Without it, any chart with list-shaped env loses its defaults the moment a driver wires user env vars, and the failure surfaces only at runtime.

**Independent Test**: Deploy simple-app (whose chart renders a list-shaped env with a `STYRMIN_CHART_DEFAULT` marker and whose `values.j2.yml` no longer wires env vars). Set `LOG_LEVEL=debug` on the `server` component, then override `STYRMIN_CHART_DEFAULT`, then clear both — reading the live pod spec after each reconcile.

**Acceptance Scenarios**:

1. **Given** a chart rendering list-shaped env with `PROMETHEUS_MULTIPROC_DIR=/tmp` and a `values.j2.yml` that does not mention env vars, **When** a user sets `LOG_LEVEL=debug` on that component and it reconciles, **Then** the component container has `LOG_LEVEL=debug` and every chart-rendered env entry unchanged.
2. **Given** the state above, **When** the user also sets `PROMETHEUS_MULTIPROC_DIR=/data`, **Then** the user value replaces the chart's — including when the chart entry is a `valueFrom` reference rather than a literal value.
3. **Given** the state above, **When** the user clears both env vars and it reconciles, **Then** `LOG_LEVEL` is gone from the container and `PROMETHEUS_MULTIPROC_DIR=/tmp` (the chart default) is back.

---

### User Story 2 - Deployment- and environment-scope env vars reach every component (Priority: P2)

A user sets an env var at deployment scope (or environment scope) on a deployment whose driver declares several components, each with a component container. Every component container receives the env var, and the existing per-key deepest-wins precedence (environment → deployment → component) still decides the final value.

**Why this priority**: Broad-scope env vars are already a shipped surface; this story preserves them under the new injection path. It builds directly on US1's per-component merge.

**Independent Test**: Covered by the existing deployment- and environment-scope env var E2E scenarios (`test_us2` / `test_us3` in `test_deployment_env_vars.py`), re-run against drivers that no longer wire env vars in their values templates.

**Acceptance Scenarios**:

1. **Given** a deployment with several components each declaring a component container, **When** a user sets `LOG_LEVEL=debug` at deployment scope, **Then** every component container gets `LOG_LEVEL=debug`.
2. **Given** an environment-scope `LOG_LEVEL=info`, a deployment-scope `LOG_LEVEL=warn`, and a component-scope `LOG_LEVEL=debug` on one component, **When** the deployment reconciles, **Then** that component's container has `LOG_LEVEL=debug` and every other component container has `LOG_LEVEL=warn`.
3. **Given** a driver where one component declares a component container and another does not, **When** a user sets a deployment-scope env var, **Then** the first component's container receives it and the second component is left untouched, without any error.

---

### User Story 3 - Driver author declares a component container (Priority: P2)

A driver author adds a single container name to a component in the driver specification file (`components.<name>.container`). That one declaration is all the driver needs for user env vars to reach that component; the author removes all env var wiring from `values.j2.yml`.

**Why this priority**: The declaration is the contract that makes US1 and US2 possible, and it is the driver-author-facing value (no more copied chart defaults).

**Independent Test**: Load a driver specification file declaring `components.server.container: simple-app` and confirm the driver registers and the component container is visible on the driver version. Load one with a malformed value and confirm registration is rejected.

**Acceptance Scenarios**:

1. **Given** a driver specification file declaring `container` on a component, **When** the driver is loaded, **Then** registration succeeds and the component container is readable on the driver version.
2. **Given** a driver specification file whose component omits `container`, **When** the driver is loaded, **Then** registration succeeds and that component is treated as having no component container.
3. **Given** a driver whose `values.j2.yml` still calls `component_env_vars`, **When** a deployment of that driver renders, **Then** rendering fails with a typed error that names the migration guide, and no partially-rendered release is applied.

---

### User Story 4 - Writes to components that can't receive env vars are rejected (Priority: P3)

A user tries to set a component-scope env var on a component whose driver declares no component container. The write is rejected up front with a typed error, before any reconcile starts. In the frontend, the component env var editor is not offered for such components.

**Why this priority**: Prevents silent no-ops — the failure mode the values-template route had. Lower priority because it guards an edge rather than delivering the primary flow.

**Independent Test**: Against a driver where one component has no component container, submit a component-scope env var write targeting it; assert the typed error and that no reconcile task was submitted. Render the deployment's env var editor in the frontend and assert it is not editable for that component.

**Acceptance Scenarios**:

1. **Given** a component with no component container, **When** a user submits a component-scope env var for it, **Then** the mutation fails with a typed error naming the component, and no reconcile is triggered.
2. **Given** the same component in the frontend, **When** the user opens the deployment's env var editor, **Then** component-scope env vars cannot be edited for that component.
3. **Given** a component with no component container, **When** a user submits a deployment- or environment-scope env var, **Then** the write succeeds (those scopes skip the component silently, per US2 Sc.3).

---

### User Story 5 - Stored env vars survive a driver upgrade that drops a component container (Priority: P3)

A deployment has component-scope env vars on a component. A driver upgrade removes that component's component container declaration. The stored values are kept, the read surface flags them as not applied, and they stop reaching the container.

**Why this priority**: Mirrors the existing orphaned-component policy so a driver upgrade never silently destroys user configuration. Rare in practice.

**Independent Test**: Resolve a deployment whose stored component env vars target a component that no longer declares a component container; assert the read surface returns the values with a not-applied flag and the rendered post-render patches omit them.

**Acceptance Scenarios**:

1. **Given** stored component-scope env vars on a component, **When** the deployment's driver is upgraded to a version where that component has no component container, **Then** the upgrade succeeds and the stored env vars are kept.
2. **Given** the state above, **When** a user reads the deployment's component env vars, **Then** the block is returned with a flag indicating it is not applied.
3. **Given** the state above, **When** the deployment reconciles, **Then** none of those env vars reach any container.

---

### Edge Cases

- **Component container name missing from a matched workload**: the merge adds an image-less container with that name, so the release fails loudly instead of silently no-op'ing. Documented for driver authors.
- **One identifier label matching several workloads**: only `Deployment` and `StatefulSet` workloads are patched, so chart `Job`s and `CronJob`s sharing the label are untouched.
- **Chart `valueFrom` entry with the same name as a user env var**: replaced by the user's literal value (US1 Sc.2).
- **Same key provided through the chart's `envFrom`**: the user value wins by Kubernetes `env`-over-`envFrom` precedence.
- **Ordering**: user-set entries (new and replacing) are placed before the chart's remaining entries, and the component container becomes the first container of the pod. A chart env entry referencing a user var via `$(USER_VAR)` expands; a user value referencing a chart var via `$(CHART_VAR)` does not. Documented for driver authors (research D-002).
- **Deployment created before this change**: its stored chart values still carry env entries written by the old values template. On its first reconcile on a migrated driver version those entries are removed, so later clearing an env var restores the chart default (FR-011).
- **Re-submitting or trimming stored env vars** for a component without a component container (e.g. a full-config edit of another field after US5's driver upgrade, or removing a stale value): accepted; only added or changed values are rejected (FR-003).
- **One write that switches driver version and sets component env vars**: validated against the target driver version, so a component that loses its container in that version rejects new values instead of storing them inert (FR-003).
- **Chart Jobs and init containers**: user env vars reach only the component container. A chart that previously fed the same values key into a migration `Job` or an init container no longer passes user env vars there (documented in the migration guide).
- **Driver upgrade drops a component container**: stored values kept, flagged, skipped (US5).
- **Driver upgrade drops the component entirely**: unchanged existing orphaned-component behaviour.
- **Clearing**: the post-render patches are regenerated on every reconcile from the resolved env vars, so removing an env var removes it from the container; no empty-list or `null` marker is needed.
- **Disabled component** (scaled to zero): env var patches still apply; the component's replica count is governed independently.
- **Driver with no components**: deployment-scope env vars are accepted and have no effect.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Driver authors MUST be able to declare one component container name per component (`components.<name>.container`) in the driver specification file. The declaration is optional per component; a malformed value MUST reject driver registration. *Verify: driver-load unit test.*
- **FR-002**: System MUST merge each component's resolved env vars into its component container by env var `name`, on `Deployment` and `StatefulSet` workloads only. Chart-rendered entries survive; a same-name entry is replaced, including a `valueFrom` entry. *Verify: rendered-patch unit test, US1 E2E.*
- **FR-003**: System MUST reject a component-scope env var write that adds or changes a value on a component with no component container in the driver version the deployment will be pinned to after the write, with a typed `ServiceError`, before any reconcile is submitted. Re-submitting the stored values unchanged, or removing some or all of them, MUST be accepted. *Verify: mutation error tests for add / change / remove / unchanged, on a stable and on a version-switching write, asserting no task submitted on rejection.*
- **FR-004**: System MUST apply deployment- and environment-scope env vars only to components with a component container, skipping the rest without error. *Verify: render unit test on a mixed driver.*
- **FR-005**: System MUST keep stored component env vars that became non-applicable after a driver upgrade (component container removed), flag them as not applied on read, and omit them from rendered patches. *Verify: propagation test, render unit test.*
- **FR-006**: Users MUST NOT be able to edit component-scope env vars in the frontend for a component without a component container. Stored values on such a component (FR-005) are shown read-only and can be removed. *Verify: frontend component test.*
- **FR-007**: System MUST fail rendering with a typed error naming the migration guide when a `values.j2.yml` uses `component_env_vars`. *Verify: render unit test.*
- **FR-008**: All in-repo example drivers MUST declare a component container on each component that receives env vars today, and MUST stop wiring env vars in `values.j2.yml`. *Verify: driver-load tests, migrated-driver E2Es.*
- **FR-009**: System MUST keep `instance.config.env_vars` and `components[<name>].env_vars.config` in the rendering context as read-only data, so a driver can still read resolved env vars for non-injection purposes (e.g. ConfigMap content, chart conditionals). *Verify: render unit test.*
- **FR-010**: System MUST regenerate the env var post-render patches on every reconcile from the currently resolved env vars, so setting, changing, or clearing an env var converges the running container. *Verify: US1 Sc.3 E2E (clear restores chart default).*
- **FR-011**: On every reconcile, the chart values the platform applies MUST fully replace the previously applied ones, so env entries written by a pre-migration values template do not linger after the deployment moves to a migrated driver version. *Verify: unit test on the release apply; US1 E2E step that seeds a stale values entry and asserts its removal.*

### Key Entities *(include if feature involves data)*

- **Component container** (new `CONTEXT.md` term, lands with this change): the single container in a component's pod template that the driver declares (`components.<name>.container`) as the target of per-component post-render overrides — env vars now, images next (#20). Single name in v1; may widen later to a list whose first entry is primary.
- **Component**: gains the optional `container` attribute, stored with the rest of the component definition on the driver version (existing storage; no schema migration).
- **Env vars** (environment / deployment / component scopes): existing model and resolver, unchanged. Resolution precedence stays per-key deepest-wins (environment → deployment → component).
- **Application driver / Driver specification file / Component overrides**: existing; the values-template env var injection route (`component_env_vars`) is retired.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Zero chart-rendered env entries are lost from a container after users set env vars, except those overridden by name — verified by reading back the live pod spec.
- **SC-002**: A driver chart bump needs zero `values.j2.yml` env edits; no in-repo driver carries copied chart env defaults.
- **SC-003**: The infrahub driver on chart `4.33.2` brings the task manager to Ready with the chart's `PROMETHEUS_MULTIPROC_DIR` intact and unmentioned in the driver's values template.
- **SC-004**: Setting, changing, or clearing an env var is reflected in the running container within one reconcile cycle; clearing restores the chart default.
- **SC-005**: 100% of non-applicable component-scope env var writes are rejected before reconcile; only upgrade-orphaned component env vars (FR-005) are stored without reaching a container.

## Assumptions

- Flux's Kustomize post-renderer applies strategic merge keyed by container `name` on `Deployment` / `StatefulSet`, including `valueFrom` removal when a user value replaces a chart `valueFrom` entry — verified in planning with kustomize v5.7.1 (research D-001, D-002).
- Each in-repo driver component that receives env vars today has one stable application container name in its chart.
- Third-party drivers are few enough (pre-1.0) that a loud FR-007 rendering failure plus a migration guide is an acceptable migration path, with no deprecation window.
- The existing `container_overrides[].container` field stays informational; `command` / `args` overrides keep their values-template route in v1.
- Environment-scope env var edits keep fanning out to per-deployment redeploys exactly as today; only the injection point changes.

## Out of Scope (v1)

- Image overrides (#20) — next, built on the component container.
- Moving `command` / `args` container overrides to post-render — follow-up; `component_command` / `component_args` stay.
- Multiple containers per component, per-container env scoping, native sidecars in `initContainers`, webhook-injected sidecars.
- Env injection on `Job`, `CronJob`, `DaemonSet`.
- User-set `valueFrom` / Secret references.
- A driver lint check that the component container exists in the rendered chart.

## Dependencies

- Existing env var resolver and orphaned-component handling (008 / 010 / 011).
- Existing per-component post-render patch pipeline (scheduling, component labels, backup annotations) targeted by component identifier labels.
- Documentation: one ADR covering #385 and #20 that supersedes ADR-013 §1 and its FR-026 non-feature; rewrite of `dev/guides/driver-env-var-consumption.md`; updates to `dev/knowledge/backend/deployment-env-vars.md`, `docs/docs/drivers/creating-a-driver.md`, `docs/docs/drivers/context.md`; a driver migration guide; towncrier `removed` + `changed` fragments; human "operator" wording swept to "user" in touched docs.
