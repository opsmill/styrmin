# Feature Specification: Per-Component Image Overrides via Post-Render

**Feature Branch**: `fac/feat-docker-image-per-component-p62fy`

**Created**: 2026-10-03

**Status**: Extracted

**Input**: Idea brief "per-component image overrides (post-render)" — [opsmill/styrmin#20 (comment)](https://github.com/opsmill/styrmin/issues/20#issuecomment-5973303433). Seed issue: [#20](https://github.com/opsmill/styrmin/issues/20). The brief replaces the values-path PRD earlier in the issue and resolves the open questions of the [direction-change comment](https://github.com/opsmill/styrmin/issues/20#issuecomment-5953589459). Builds on [#387](https://github.com/opsmill/styrmin/issues/387) / [ADR-057](../../../dev/adr/0057-post-render-component-overrides.md) (post-render env vars into a declared **component container**). Related: [#388](https://github.com/opsmill/styrmin/issues/388) (`apply` validates against the pre-switch driver version).

## Context

A component's container image is fixed by the Helm chart bundled with the deployment's **driver version**. A user who runs a custom or patched build of one component has no deployment-level way to point that component at it: today they fork the driver.

ADR-057 gave every in-repo component a driver-declared **component container** and a post-render patch that targets it, so Styrmin can change one container of one component without the driver's values template wiring anything. This feature adds the second override on that path: one image reference per component, applied to the component container after the chart has rendered. The driver opts in by declaring the component container; it needs no other change.

## Clarifications

### Session 2026-10-03 (autonomous, from the idea brief)

- Q: Should the "never add a container" guard (FR-007) also run when only env vars target the component container? → A: Yes. Both overrides share one mechanism and one guard. A wrong name fails the reconcile with the same typed error whichever override is set, instead of the image-less-container API rejection ADR-057 relies on today.
- Q: `styrminctl apply` has no interactive confirmation. How does FR-008 apply to it? → A: `apply` prints the pinned-override warning in its output when a manifest changes a deployment's application version. It adds no prompt and does not block the apply.
- Q: How many `{{ app.version }}` tokens may a reference carry? → A: Any number. Every occurrence is replaced. The result is validated as a whole.
- Q: How is a reference containing the token validated on write? → A: It is validated after substituting the deployment's application version at the time of the write. A token counts as an explicit tag when it sits in the tag position.

## User Scenarios & Testing *(mandatory)*

The primary actor is an **application owner or operator** who runs a custom or patched build of one component and wants it deployed without forking the driver. They set the override through GraphQL, the SDK, a `styrminctl apply` manifest, or the deployment's configuration editor.

### User Story 1 - Run a custom build on one component (Priority: P1)

A user sets one image reference on the `server` component of a running deployment and applies. After the next reconcile, the `server` component container runs that image. Nothing else in the pod changes, and reading the deployment back shows what was stored, what it resolved to, and that it is applied.

**Why this priority**: This is the headline value: a custom build runs with zero driver changes.

**Independent Test**: Deploy `simple-app` (its driver declares a component container for `server`). Set `server`'s image to a locally built `simple-app` image re-tagged under a distinct reference, apply, wait for one reconcile, then read the live pod spec and the deployment's read surface.

**Acceptance Scenarios**:

1. **Given** a running deployment whose driver declares a component container for `server`, **When** the user sets `server`'s image to `registry.example/acme/simple-app-patched:1.0.0` and applies, **Then** after the next reconcile the `server` component container runs that image.
2. **Given** the state above, **When** the user inspects the `server` pod, **Then** every other container keeps its chart image, the chart's env defaults are unchanged, and the pod has no container it did not have before.
3. **Given** the state above, **When** the user reads the deployment through the API, the SDK, or the UI read summary, **Then** the `server` override shows the stored reference, the resolved reference, and that it is applied.
4. **Given** a deployment being created, **When** the user includes an image override for `server` in the `deploy` request, **Then** the first rollout already runs the overridden image.

---

### User Story 2 - Follow the application version (Priority: P2)

A user writes the override with the `{{ app.version }}` token so the custom build tracks the deployment's application version. Upgrading the application moves the component to the matching custom tag. If an override has no token, the user is warned before the upgrade that it will stay pinned. Action Jobs that take their image from the component see the override too.

**Why this priority**: Without the token, every application upgrade needs a manual override edit. A pinned override that silently lags behind the application is a real hazard (Infrahub's migration Job would run ahead of the server).

**Independent Test**: With an override `…-patched:{{ app.version }}` on `server` at application version 0.1.0, upgrade the deployment to 0.2.0 and assert `server` runs `…-patched:0.2.0` and the upgrade action Job ran the overridden image (the Job assertion waits on opsmill/styrmin#381: action primitives call the API unauthenticated, so the Job does not run under default-deny auth). Separately, set a token-free override and open the upgrade dialog (or run an `apply` that changes the version) and assert the warning lists `server`.

**Acceptance Scenarios**:

1. **Given** the override `registry.example/acme/simple-app-patched:{{ app.version }}` on `server` at application version 1.0.0, **When** the user reads the deployment, **Then** the resolved reference is `registry.example/acme/simple-app-patched:1.0.0`.
2. **Given** the state above, **When** the user upgrades the deployment to application version 1.1.0, **Then** after the upgrade `server` runs `registry.example/acme/simple-app-patched:1.1.0`.
3. **Given** a token-free override `registry.example/acme/simple-app-patched:1.0.0` on `server`, **When** the user opens the upgrade dialog, **Then** the dialog lists `server` as pinned before the user confirms. **When** the user confirms the upgrade, **Then** `server` keeps running the pinned image.
4. **Given** a token-free override on `server`, **When** the user runs `styrminctl apply` with a manifest that changes the application version, **Then** the output names `server` as pinned.
5. **Given** an image override on `server`, **When** the driver's upgrade action reads the component's images to build its Job, **Then** the Job sees the overridden image of the component container, selected as the component container's image rather than by matching an image-name substring.

---

### User Story 3 - Clear the override (Priority: P3)

A user removes the override and applies. The next reconcile restores the chart's image.

**Why this priority**: Reversibility. Without it, an override is a one-way door.

**Independent Test**: Continue from User Story 1: clear `server`'s override, apply, wait for one reconcile, and assert the `server` component container runs the chart's image again.

**Acceptance Scenarios**:

1. **Given** an override on `server`, **When** the user clears it and applies, **Then** the next reconcile restores the chart's image on the `server` component container.
2. **Given** the state above, **When** the user reads the deployment, **Then** `server` shows no image override.

---

### User Story 4 - Mistakes fail loudly, never silently (Priority: P3)

A user or driver author makes a mistake: an invalid reference, an override on a component that has no component container, or a driver that declares a container name the chart does not render. Each one is caught with a typed error that names the component. Styrmin never adds a container to a pod, never falls back to the chart image, and never injects an override that cannot apply.

**Why this priority**: Guards rather than delivers value, but without them the override silently does nothing or, worse, runs an extra container.

**Independent Test**: Submit invalid references and an override on a containerless component and assert typed rejections with no task submitted. Deploy a driver variant whose declared container name is wrong, set an override, and assert the reconcile fails naming the component and the container, with no extra container in the pod.

**Acceptance Scenarios**:

1. **Given** any component, **When** the user writes a reference that fails the image-reference grammar, has no explicit tag or digest, or contains a template expression other than `{{ app.version }}`, **Then** the write (`deploy`, `updateDeployment`, or `apply`) is rejected with a typed error naming the component, and no reconcile starts.
2. **Given** a component whose driver version declares no component container, **When** the user sets or changes its image override, **Then** the write is rejected with `COMPONENT_CONTAINER_NOT_DECLARED`. **When** the user removes a stored override on it, **Then** the write succeeds.
3. **Given** a driver whose declared component container name does not exist in the rendered workload, **When** a deployment of it has an image override (or env vars) on that component and reconciles, **Then** the reconcile fails visibly, naming the component and the container, and no container is added to the pod.
4. **Given** a stored override on a component, **When** a driver upgrade drops that component's component container, **Then** the override is kept, reads back as not applicable, and is never injected.
5. **Given** a stored token override, **When** the user requests an upgrade to an application version that makes the reference invalid after substitution (for example a `+` in the version), **Then** the upgrade is rejected before any task or action starts, with a typed error naming the component. **When** an invalid reference reaches rendering by any other path, **Then** rendering fails with the same typed error. The chart image is never used as a fallback.

---

### Edge Cases

- **Pinned tag during an application-version upgrade**: the upgrade dialog lists the applicable pinned components before confirmation, and `apply` output lists every token-free override (FR-008). The upgrade proceeds; the pinned component keeps its image.
- **Wrong component container name**: hard failure, never an extra container (FR-007). Without this guard, setting an image would also hide the loud failure env vars get today, because the merged-in container would now carry an image and pass API validation.
- **Driver upgrade drops the component container**: override stored, not applicable, not injected (FR-006). If a later version also breaks its `{{ app.version }}` substitution, re-submitting it unchanged still passes (FR-009).
- **Driver upgrade drops the component**: the existing orphaned-component behaviour applies; the override is kept and not applicable.
- **Token yields an invalid reference** (e.g. a `+` build-metadata version): the upgrade request is rejected up front with a typed error, so the driver's upgrade action never stops components for an upgrade that cannot render. Any other path that reaches rendering with an invalid reference fails the render with the same typed error (FR-009).
- **Image cannot be pulled** (typo in the tag, private registry without node credentials): the pod stays in `ImagePullBackOff` and the deployment does not become ready. The waiting reason is visible in the deployment's Pods tab; Styrmin does not pre-check registries.
- **Rebuilt image under the same tag**: Styrmin does not change the chart's `imagePullPolicy`, so with `IfNotPresent` a node keeps the cached image. Rebuilt images need a new tag or a digest.
- **Stranded or orphaned override on an environment clone source**: the counterpart's write validation rejects it, exactly as it does for env vars today.
- **Override and version change in one `apply`**: the config is written first, but the upgrade action may read the workload before the override is rendered, so its first Job can use the previous image repository (the same race env vars have). Setting the override in a separate apply avoids it.
- **Components that share an image** (infrahub `server` and `task-worker`): each needs its own override. Release-wide redirection belongs to the registry-mirror issue.
- **Digest references** (`repo@sha256:…`, or `repo:tag@sha256:…`): accepted as explicit references; they pin the image like a literal tag.
- **Multi-container pods**: only the component container's image changes; sidecars and init containers keep their chart images.
- **Env vars and an image override on the same component**: both reach the component container in the same reconcile.
- **Disabled component** (scaled to zero): the override is still applied to the workload; its replica count is governed independently.
- **Clearing**: post-render patches are regenerated on every render, so clearing needs no marker.
- **Environment clone**: the counterpart deployment carries the source's image overrides with the rest of the deployment config.
- **`apply` that switches driver version and sets an override in one manifest**: validated against the pre-switch driver version, exactly as for env vars (#388).
- **Deployment without an override after a Styrmin upgrade**: its rendered workloads are unchanged, so no pod restarts (SC-002).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Users MUST be able to set one image reference string per component on a deployment. A literal tag (or digest) pins the image. *Verify: propagation test, User Story 1 E2E.*
- **FR-002**: System MUST replace every `{{ app.version }}` token (whitespace inside the braces tolerated) with the deployment's application version at render time. This is plain substitution, not template rendering: any other `{{ … }}` or `{% … %}` expression MUST be rejected on write. *Verify: unit tests on substitution and rejection, User Story 2 E2E.*
- **FR-003**: System MUST apply the override only to the component's component container. The override exists at component scope only; there is no environment- or deployment-scope image override and no layering. *Verify: render unit test, User Story 1 E2E (other containers unchanged).*
- **FR-004**: System MUST patch only `Deployment` and `StatefulSet` workloads. Init containers, sidecars, `Job`, `CronJob`, and `DaemonSet` workloads MUST be left untouched. *Verify: render unit test.*
- **FR-005**: System MUST reject setting or changing an image override on a component that has no component container in the deployment's driver version, with `COMPONENT_CONTAINER_NOT_DECLARED`, before any reconcile starts. Removing a stored override, or re-submitting it unchanged, MUST pass. *Verify: mutation error tests for add / change / remove / unchanged, asserting no task submitted on rejection.*
- **FR-006**: System MUST keep an image override stranded by a driver upgrade (component container no longer declared, or component no longer declared), show it as not applicable, and never inject it. *Verify: propagation test, render unit test.*
- **FR-007**: System MUST NOT add a container to a workload. When a post-render override (image or env vars) targets a declared component container that is missing from the rendered workload, the reconcile MUST fail visibly with a typed error naming the component and the container, on a new deployment and on an update of a running one. *Verify: render-level test, operator unit test, User Story 4 E2E (`api_only`).*
- **FR-008**: The UI upgrade dialog MUST list, before the user confirms, every component whose stored override is applicable and has no `{{ app.version }}` token. `styrminctl apply` MUST name, in its output, every component whose effective override has no token when a manifest changes a deployment's application version; it does not consult applicability (it holds the raw config, and listing a stranded override is harmless), so it can list more components than the dialog. Both are computed client-side. The SDK reports them as `ApplyOutcome.pinned_image_components`, with `ApplyOutcome.target_version` set on an `updated` outcome that changes the version. *Verify: frontend component test, CLI and SDK unit tests, User Story 2 E2E.*
- **FR-009**: System MUST reject on write (`deploy`, `updateDeployment`, `apply`), with a typed error naming the component, any reference that fails the image-reference grammar or lacks an explicit tag or digest, both as stored and after substituting the deployment's current application version. On `updateDeployment`, an entry equal to the stored reference is not re-checked: it was checked when written, and applicable stored references are re-checked on every version change, so a stranded override that the current version breaks never blocks an unrelated edit. A version change (`updateDeploymentVersion`, `apply`) that would make a stored, applicable reference invalid after substitution MUST be rejected with the same typed error before any task or action starts. A reference that is invalid after substitution at render time MUST fail the render with a typed error. There is no fallback to the chart image. *Verify: mutation error tests (write and version change, no task created; unchanged stranded entry accepted), render unit test.*
- **FR-010**: Users MUST be able to read, per component, the stored reference, the resolved reference, and whether the override is applicable, through the GraphQL API, the SDK, and the UI read summary. *Verify: propagation test, frontend component test, User Story 1 E2E.*
- **FR-011**: Users MUST be able to set and clear the override through GraphQL, the SDK, a `styrminctl apply` manifest (`spec.config.components.<name>.image`), and the deployment's configuration editor. For a component without a component container, the editor MUST show a stored override read-only and allow removing it, and MUST NOT offer setting one. The editor MUST disable Review & apply while an image field is invalid, naming the components to fix. *Verify: propagation tests, CLI apply test, frontend component test, User Story 1 and 3 E2E.*
- **FR-012**: Action Jobs that take their image from the component's images MUST see the override. The in-repo `upgrade` actions MUST select the component container's image instead of matching an image-name substring. *Verify: unit tests on `get_component_images` ordering and on the in-repo actions; User Story 2 E2E action Job image assertion pending opsmill/styrmin#381 (tasks T077).*

### Key Entities *(include if feature involves data)*

- **Image override** (new `CONTEXT.md` term, no new table): a new slot on `DeploymentConfig.components[<name>]`, alongside env vars and the **container override**. One full image reference with an explicit tag or digest, optionally containing the `{{ app.version }}` token. Read back with its resolved reference and applicability.
- **Component container** (existing, ADR-057): the target container of the override, reused unchanged. Its declaration in the driver specification file is the driver's opt-in.
- **Application version** (existing): the value the `{{ app.version }}` token resolves to.
- **Deployment config / component overrides** (existing): the override is stored with the rest of the deployment's component config and travels with it (environment clone, `apply` manifests).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The overridden image runs on the component container within one reconcile, in 100% of User Story 1 runs.
- **SC-002**: Upgrading Styrmin restarts zero pods on deployments without an image override.
- **SC-003**: Steady-state reconciles restart zero pods. Setting then clearing an override restores the chart image within one reconcile.
- **SC-004**: 100% of invalid writes are rejected before any pod restarts, with a typed error naming the component.
- **SC-005**: A wrong component container name never adds a container to a pod. The error is visible to the user within one reconcile.
- **SC-006**: A custom build runs on a component whose driver declares a component container, with zero driver changes.

## Assumptions

- The override's registry is pullable by the cluster nodes (public, or node-level credentials). This is documented; image pull secrets are a separate issue.
- An environment clone carries image overrides with the deployment config, like every other component config field.
- #388 (`apply` validates its config write against the pre-switch driver version) affects the FR-005 check the same way it affects env vars.
- The deploy and update permission gates already in place cover setting and clearing overrides; no new role or permission.
- Overrides are stored in the existing deployment config JSON; no database schema change.
- The image-reference grammar check is hand-written (backend and frontend); no new dependency.
- `styrminctl apply` keeps its non-interactive behaviour: the FR-008 warning is informational output, not a prompt.

## Out of Scope (v1)

- Release-wide registry mirror (air-gapped redirection of every image): separate issue.
- Image pull secrets: separate issue.
- Partial overrides (registry, repository, or tag only).
- Environment- or deployment-scope image overrides.
- Init containers, sidecars, `Job`, `CronJob`, `DaemonSet`.
- A new action primitive.
- Warnings on SDK upgrade calls.

## Dependencies

- ADR-057's component container declaration and the post-render patch pipeline it extends (env var patches, scheduling, labels, backup annotations).
- The existing deployment-config write path (`deploy`, `updateDeployment`, `apply`) and its `COMPONENT_CONTAINER_NOT_DECLARED` check.
- Testing: `test_deployment_image_override.py` in `shard_configuration`, with three tests: (1) User Stories 1 and 3, dual-entrypoint; (2) User Story 2 plus the action Job image (the Job assertion pending opsmill/styrmin#381), dual-entrypoint; (3) SC-005 with a misnamed-container driver variant, `api_only`. Override images are the locally built `simple-app` 0.1.0 and 0.2.0 re-tagged under a distinct reference. Below E2E: GraphQL propagation tests and unit tests.
- Documentation (Constitution §VII): a new ADR extending ADR-057 that records the `{{ app.version }}` token, the wrong-name guard, and the narrowing of ADR-057's "a wrong container name fails the release, but only once env vars are set"; user docs for setting image overrides (deployment configuration, `apply` manifests, driver authoring note on the component container, pull failures in the Pods tab, unique tags for rebuilt images, admission policies for registry allow-lists, clearing overrides before a platform rollback); `CONTEXT.md` (**Image override**, **Component container**, **Component overrides**); a towncrier `added` fragment for #20.

### Revision: Implementation Sync 2026-10-04

- Reason: reconciled drift found after implementation. FR-008 now states that the UI dialog lists applicable pinned overrides while `apply` lists every token-free override, and names `ApplyOutcome.target_version` (as research D-011 already decided). FR-009 skips re-checking an unchanged reference on `updateDeployment` (review finding R1). FR-011 records that the editor blocks Review & apply on an invalid image. FR-012 and User Story 2 note that the action Job E2E assertion waits on opsmill/styrmin#381 (task T077).
