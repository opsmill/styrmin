# Feature Specification: Container `command` and `args` Overrides Applied by Post-Render

**Feature Branch**: `fac/check-container-cmd-arg-post-render-2yje1`

**Created**: 2026-10-14

**Status**: Draft

**Input**: PRD "Container overrides applied by a post-render patch" — [opsmill/styrmin#457 (comment)](https://github.com/opsmill/styrmin/issues/457#issuecomment-6166451728). Seed issue: [#457](https://github.com/opsmill/styrmin/issues/457). Original feature: [#283](https://github.com/opsmill/styrmin/issues/283) ([`specs/archive/014-component-container-overrides`](../archive/014-component-container-overrides/spec.md)). Builds on [#385](https://github.com/opsmill/styrmin/issues/385) / [ADR-057](../../dev/adr/0057-post-render-component-overrides.md) (env vars by post-render) and [#20](https://github.com/opsmill/styrmin/issues/20) / [ADR-058](../../dev/adr/0058-image-overrides-and-component-container-guard.md) (image overrides by post-render).

## Context

A user can set a **container override**: the `command` or `args` of one **component** in one **deployment** ([#283](https://github.com/opsmill/styrmin/issues/283)). Today the override reaches the pod only when the driver's `values.j2.yml` passes the `component_command` or `component_args` filter to a value that the Helm chart exposes ([driver container override guide](../../dev/guides/driver-container-override-consumption.md)). This has three effects:

- When a driver does not call the filters, Styrmin stores the override, never applies it and reports no error. The deployment edit drawer shows the Command and Args editors for every component, whether or not the driver calls the filters ([`ComponentOverridesSection.tsx`](../../frontend/src/components/deployment/configuration/sections/edit/ComponentOverridesSection.tsx)).
- A user can override only the fields that the chart exposes as values. The infrahub chart has no `command` value, so the `server` and `task-worker` components of the `infrahub` and `infrahub-enterprise` drivers accept `args` only ([`driver.styrmin.yml`](../../driver/examples/infrahub/driver.styrmin.yml)).
- Each driver author writes template code that matches how the chart reads the value, so that the chart's default applies when no override is set. `simple-app` sends an empty list, because its chart skips an empty `command` or `args`. `infrahub` and `infrahub-enterprise` send `null`, because the infrahub chart renders `args` without a check and an empty list would replace the chart's default `args` ([#457](https://github.com/opsmill/styrmin/issues/457)).

Env var overrides ([#385](https://github.com/opsmill/styrmin/issues/385)) and image overrides ([#20](https://github.com/opsmill/styrmin/issues/20)) already reach pods through a post-render patch to the **component container** that the driver declares, with no template code ([ADR-057](../../dev/adr/0057-post-render-component-overrides.md), [ADR-058](../../dev/adr/0058-image-overrides-and-component-container-guard.md)). `command` and `args` are the only per-component container overrides that still go through the values template ([ADR-045](../../dev/adr/0045-container-override-no-layering-and-omit-marker.md) status note).

This feature moves `command` and `args` onto the same post-render path:

- A component accepts a container override when the driver declares its component container (`components.<name>.container`). This is the same rule as for env vars and image overrides.
- Styrmin applies the override with the post-render patches it already builds for env vars and images. The driver needs no template code, and a user can override `command` and `args` whatever values the chart exposes.
- When a user clears an override, Styrmin builds no patch for it, and the pod runs the chart's own `command` and `args`.
- The `component_command` and `component_args` filters are retired. A template that calls them fails to render, with an error that links a migration guide.
- `spec.container_overrides` is removed from the driver specification file.
- The `simple-app`, `infrahub` and `infrahub-enterprise` example drivers stop calling the filters.
- All three user stories below ship in one release.

## Clarifications

### Session 2026-10-14 (autonomous, from the PRD)

The PRD lists no open questions. Its decisions were taken in a review session on 2026-10-14 that started from the open questions in [#457](https://github.com/opsmill/styrmin/issues/457). The answers to the four "Not decided" points in #457 are recorded here so later phases do not reopen them.

- Q: Do the `component_command` and `component_args` filters stay, become deprecated or get removed? → A: They are retired with no deprecation period. A template that calls either one fails to render with `RETIRED_TEMPLATE_FILTER`, as `component_env_vars` did ([ADR-057](../../dev/adr/0057-post-render-component-overrides.md) §4). The three in-repo drivers that call them move in the same change.
- Q: How does clearing an override restore the chart's or the image's default `command` and `args`? → A: Styrmin builds the patches again on every render. With no stored value it builds no `command` or `args` patch, so the chart's rendered values reach the pod unchanged. No empty-list or `null` marker is needed.
- Q: What happens to `spec.container_overrides` in `driver.styrmin.yml`? → A: It is removed from the driver specification file, from the stored driver version and from the API. A driver file that still contains it fails to load with the unknown-key error.
- Q: Does a component without a declared component container still accept a `command` or `args` override? → A: No. The same rule as for env vars and image overrides applies: an added or changed value is rejected with `COMPONENT_CONTAINER_NOT_DECLARED`, and stored values are reported with `isApplicable: false`.
- Q: Which write paths carry the `COMPONENT_CONTAINER_NOT_DECLARED` rejection for `command` and `args`? → A: Every path that already carries it for env vars and image overrides (GraphQL, the SDK, `styrminctl apply` and the UI), because they share the deployment service check.

## User Scenarios & Testing *(mandatory)*

Two people use this feature:

- A **user** (application owner or operator) who needs one component to start with a different `command` or `args`, for example to run a debug mode or change worker flags, without forking the driver. They set the override through GraphQL, the SDK, a `styrminctl apply` manifest or the deployment edit drawer.
- A **driver author** who declares which container of each component Styrmin may change.

The user needs from the PRD, numbered as there:

1. As a user, I want to set `command` or `args` on one component of a deployment, so that I can run a debug mode or change the worker flags without forking the driver.
2. As a user, I want to set `command` on the infrahub `server` and `task-worker` components, so that I am not limited to the values that the infrahub chart exposes.
3. As a user, I want to clear an override, so that the component runs the chart's own `command` and `args` again.
4. As a user, I want Styrmin to reject an override on a component without a component container, so that I do not save a value that never reaches the pod.
5. As a user, I want to view which stored overrides do not apply and remove them, so that I can clean up after a driver upgrade.
6. As a user, I want a deployment pinned to a driver version that calls the retired filters to fail with an error that names the filter and a migration guide, so that I know how to fix it.
7. As a user, I want an override that I set before this change to keep reaching the pod after I move the deployment to a migrated driver version.
8. As a driver author, I want to declare only the component container, so that I do not write override code in `values.j2.yml` or copy chart defaults into it.
9. As a driver author, I want a wrong component container name to fail the reconcile with an error that names the component and the container, so that I find the mistake when a user first sets an override.
10. As a driver author, I want a driver file that still contains `spec.container_overrides` to fail to load, so that I remove a block that no longer has an effect.

### User Story 1 - Set, change and clear a container override without template code (Priority: P1)

Covers needs 1, 2, 3 and 8. A user sets `command`, `args` or both on a component that has a component container, and its pods run with those values. The user later clears the override, and the pods run the chart's own `command` and `args` again. The driver's `values.j2.yml` contains no override code.

**Why this priority**: This is the reason for the change. An override that the driver template does not pass to the chart has no effect today, and a user cannot override a field that the chart does not expose.

**Independent Test**: Deploy `simple-app` from the migrated driver version, whose `server` component declares a component container and whose `values.j2.yml` calls neither filter. Set, change and clear `command` and `args` on `server`, and after each reconcile read the pod's container spec.

**Acceptance Scenarios**:

1. **Given** a deployment of a driver whose `server` component declares a component container and whose `values.j2.yml` does not call `component_command` or `component_args`, **When** the user sets `args: ["--log-level", "debug"]` on `server`, **Then** after the reconcile the component container of each `server` pod has exactly those `args`, and the other containers in the pod are unchanged.
2. **Given** that override, **When** the user clears `args`, **Then** after the reconcile the component container has the `args` that the chart renders, byte for byte, as if no override had been set.
3. **Given** the same deployment, **When** the user sets `command` and `args` together and later changes `command`, **Then** after each reconcile the component container runs the latest stored `command` and `args`.
4. **Given** a deployment of the migrated `infrahub` driver version, **When** the user sets `command` on the `server` or `task-worker` component, **Then** the rendered component container has that `command`, although the infrahub chart exposes no `command` value.
5. **Given** a component whose chart renders a `command`, **When** the user sets only `args`, **Then** the chart's `command` stays and the user's `args` replace the chart's `args`.

---

### User Story 2 - Move driver versions off the retired filters (Priority: P2)

Covers needs 6, 7 and 10. A deployment pinned to a driver version that calls the retired filters fails its next render with an error that links the migration guide. The user moves it to a migrated driver version, and its stored overrides keep reaching the pod. A driver author who loads a driver file that still contains `spec.container_overrides` gets a load error.

**Why this priority**: Retiring the filters breaks every deployment pinned to an old version of `simple-app`, `infrahub` or `infrahub-enterprise`. The user needs a clear error and a way forward that keeps their stored overrides.

**Independent Test**: Render a deployment pinned to a driver version whose template calls `component_args`, and check the error and that no HelmRelease is applied. Load a driver file that contains `spec.container_overrides`, and check the load error. Render the same stored config with an old template and with the migrated template, and compare the component container's `command` and `args`.

**Acceptance Scenarios**:

1. **Given** a deployment pinned to a driver version whose `values.j2.yml` calls `component_args`, **When** the deployment is rendered again, **Then** the render fails with `RETIRED_TEMPLATE_FILTER`, Styrmin does not apply the HelmRelease, and the deployment message names the filter and the migration guide.
2. **Given** a driver file that contains `spec.container_overrides`, **When** a driver author loads it, **Then** the load fails with the unknown-key error.
3. **Given** an `infrahub` deployment with a stored `args` override on `server`, **When** the user moves it to the migrated driver version, **Then** the `server` pods run with the same `args` as before the move.

---

### User Story 3 - Reject and report overrides that cannot reach the pod (Priority: P3)

Covers needs 4, 5 and 9. A user cannot add or change `command` or `args` on a component without a component container, and can view and remove values stored there before. A driver that declares a component container name that the rendered workload does not contain fails the reconcile, even when `command` or `args` is the only override on the component.

**Why this priority**: These rules keep the promise that no override is reported as applied without reaching the pod. They reuse the rules that env vars and image overrides already follow.

**Independent Test**: Write `args` to a component without a component container and check the rejection. Move a deployment that stores a `command` to a driver version that no longer declares the component container, and read the deployment. Render a component whose declared container name is wrong, with only an `args` override set.

**Acceptance Scenarios**:

1. **Given** a component that declares no component container, **When** a user adds `args` to it, **Then** Styrmin rejects the write with `COMPONENT_CONTAINER_NOT_DECLARED` and starts no task.
2. **Given** a stored `command` on a component whose new driver version no longer declares its container, **When** the user views the deployment, **Then** the override is reported with `isApplicable: false`, is never applied, and is shown as read-only and removable.
3. **Given** that stored `command`, **When** the user removes it or sends the same value again, **Then** Styrmin accepts the write.
4. **Given** a component whose driver declares a component container name that the rendered workload does not contain, **When** a user sets only `args` on it and the deployment reconciles, **Then** the reconcile fails with `COMPONENT_CONTAINER_NOT_FOUND`, and the error names the component and the container.
5. **Given** a component without a component container, **When** the user opens the deployment edit drawer, **Then** the Command and Args editors are not offered for that component.

---

### Edge Cases

- A user sets only `args`, and the chart renders a `command`: the chart's `command` stays, and the user's `args` replace the chart's `args`.
- The first time a `command` or `args` override applies, the component container moves to `containers[0]`, as it does for env vars and images ([ADR-057](../../dev/adr/0057-post-render-component-overrides.md) §3). This changes the default container that `kubectl logs` reads.
- The component's label matches several workloads: the component container must exist in each one, or the render fails ([ADR-058](../../dev/adr/0058-image-overrides-and-component-container-guard.md)).
- A driver upgrade removes the component: the override is kept, reported as orphaned, and never applied.
- Styrmin is rolled back to an earlier version after migrated drivers are loaded: stored `command` and `args` overrides are kept but not applied, because the migrated templates no longer call the filters.
- A deployment pinned to an old version of `simple-app`, `infrahub` or `infrahub-enterprise` fails its next render, also when it has no override set. These three are the only in-repo drivers that call the filters.
- Some deployments may store an override that their template never passed to the chart, for example `command` on the infrahub `server` component. When the user moves such a deployment to a migrated driver version, Styrmin applies the override for the first time. The migration guide and the changelog entry tell users to review their stored `command` and `args` overrides before the move.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST apply a component's `command` and `args` overrides to its component container, in its `Deployment` and `StatefulSet` workloads, through the post-render patches, with no driver template code.
  - Verified by: an E2E reads the values from the pod's container spec.
- **FR-002**: System MUST replace the whole `command` or `args` list of the component container, and MUST leave other containers and init containers unchanged.
  - Verified by: an integration test that runs `kubectl kustomize` on a pod with two containers.
- **FR-003**: When a user clears an override, System MUST restore the `command` and `args` that the chart renders.
  - Verified by: an E2E compares the container spec after the clear with a render that never had an override.
- **FR-004**: When the declared component container is missing from the rendered workload, System MUST fail the reconcile with `COMPONENT_CONTAINER_NOT_FOUND`, also when `command` or `args` is the only override on the component.
  - Verified by: an integration test with a wrong container name.
- **FR-005**: The `component_command` and `component_args` filters MUST fail rendering with `RETIRED_TEMPLATE_FILTER`, and the error MUST link the container override migration guide.
  - Verified by: a unit test that renders a template calling each filter.
- **FR-006**: System MUST reject a driver file that contains `spec.container_overrides`, with the same unknown-key error as any other unknown key.
  - Verified by: a driver loader unit test.
- **FR-007**: For `command` and `args` on a component without a component container, System MUST apply the same rule as for env vars and image overrides:
  - reject an added or changed value with `COMPONENT_CONTAINER_NOT_DECLARED`, with the metadata `override: "command"` or `override: "args"`;
  - accept a removed value, or the same value sent again;
  - report stored values with `ComponentContainerOverrides.isApplicable`, which is true only when the component is not orphaned and declares a component container.
  - Verified by: deployment service unit tests and a GraphQL propagation test.
- **FR-008**: Users MUST NOT be offered the Command and Args editors on a component without a component container, and MUST be able to remove values stored there.
  - Verified by: a frontend test.
- **FR-009**: The `simple-app`, `infrahub` and `infrahub-enterprise` example drivers MUST stop calling `component_command` and `component_args`, and MUST NOT contain `spec.container_overrides`.
  - Verified by: SC-002, and the E2E and render tests that use these drivers.
- **FR-010**: System MUST stop storing and exposing the `spec.container_overrides` block: the driver version loses its stored copy, and the API loses `ApplicationDriverVersion.containerOverrides` and the `DriverContainerOverrideDoc` type. The SDK query for the block is removed. No CLI command changes.
  - Verified by: the schema export, the SDK type generation and a database migration test.
- **FR-011**: System MUST NOT add a new error code. `RETIRED_TEMPLATE_FILTER` covers the two filters, `COMPONENT_CONTAINER_NOT_DECLARED` gains the `override` values `command` and `args`, and `COMPONENT_CONTAINER_NOT_FOUND` also fires when `command` or `args` is the only override.
  - Verified by: the tests of FR-004, FR-005 and FR-007.
- **FR-012**: The documentation MUST change in the same release (Constitution §VII):
  - a new user-facing page for migrating container overrides, which the `RETIRED_TEMPLATE_FILTER` error links to. It follows the sections of [Migrating Env Var Wiring](../../docs/docs/drivers/migrating-env-vars.md) and includes the step to review stored overrides. The env var migration page stays separate, so the URL in the existing env var error stays valid;
  - a rewritten section on container `command` and `args` overrides in [Creating a driver](../../docs/docs/drivers/creating-a-driver.md);
  - updated concept pages and user-facing glossary entries that mention the filters or the block;
  - deletion of the [driver container override guide](../../dev/guides/driver-container-override-consumption.md) and its links;
  - a new ADR that supersedes [ADR-045](../../dev/adr/0045-container-override-no-layering-and-omit-marker.md) §2 (the empty-list marker) and §5 (the `null` marker) and extends ADR-058 to `command` and `args`. ADR-045 §1, §3 and §4 stay valid;
  - in [`CONTEXT.md`](../../CONTEXT.md), updated Component overrides, Component container and Container override entries;
  - a towncrier fragment that marks the filter retirement and the block removal as breaking changes, and tells users to review their stored `command` and `args` overrides before moving to a migrated driver version.
  - Verified by: review of the change.

### Key Entities *(include if feature involves data)*

No new entity is needed. Names follow [`CONTEXT.md`](../../CONTEXT.md).

- **Container override** (existing): the stored value in `DeploymentConfig.components[<name>]` does not change. Styrmin applies it with a post-render patch instead of through the values template. The read field `ComponentContainerOverrides` gains `isApplicable`.
- **Component container** (existing): now also the target of container overrides, next to env vars and image overrides.
- **Application driver version** (existing): loses `spec.container_overrides`, its stored copy and its API field.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For every in-repo component that declares a component container, a user can set `command` and `args`, and the pod runs with them after one reconcile. This includes `command` on the infrahub `server` and `task-worker` components.
- **SC-002**: No driver in the repository contains code for `command` or `args` overrides, either in `values.j2.yml` or in `driver.styrmin.yml`.
- **SC-003**: After a user clears an override, the component container's `command` and `args` equal the chart's rendered values in every tested case.
- **SC-004**: No `command` or `args` override is reported as applicable without reaching the pod. A value that cannot apply is either rejected on write or reported with `isApplicable: false`.
- **SC-005**: A deployment that had an override before the change, and moves to a migrated driver version, runs with the same `command` and `args` as before the move.

## Verification Approach

From the PRD's testing decisions:

- A good test here checks the rendered workload or the pod's container spec, not the text of the patch.
- Unit tests, each for its own module:
  - the applicable overrides for one component;
  - the component container patch builder;
  - the retired template filters;
  - the write check for components without a component container;
  - the driver specification model and loader.
- Integration and contract tests:
  - `kubectl kustomize` on the builder's real output, for FR-002 and FR-004;
  - render the same stored config with an old template and with the migrated template, and compare the container's `command` and `args`, for SC-005. An E2E cannot cover SC-005, because a deployment on an old driver version fails its render before it can run;
  - a GraphQL propagation test for `isApplicable`, which the project requires for every schema change.
- E2E scenario: on `simple-app`, a user sets, changes and clears `command` and `args`, and the test reads the pod's container spec after each step. This extends [`test_deployment_container_overrides.py`](../../backend/tests/e2e/test_deployment_container_overrides.py) on the `shard_configuration` shard, with these changes:
  - `test_us6_driver_declares_overridable_component` is deleted, because it tests the removed block;
  - `test_us3` also checks the pod's container spec after the clear, not only the API response.
- Prior art: the existing container override E2E above, and the `kubectl kustomize` integration tests that ADR-058 describes.

## Constitution Alignment

Principles from [`dev/constitution.md`](../../dev/constitution.md):

- I. Declarative state reconciliation: Styrmin builds the patches again on every render, and the output is the same for the same config, so a clear needs no marker.
- II. Driver-based deployment: the driver still declares where an override goes, through the component container.
- IV. Type safety and typed errors: the change reuses existing error codes and adds none.
- V. Test-first development: the change extends an existing E2E instead of adding a test that starts a new stack, and adds a propagation test for the schema change.
- VII. Documentation accuracy: the documentation changes in FR-012 ship in the same change.

## Governance Gates Crossed

From the "Ask First" list in [`AGENTS.md`](../../AGENTS.md). Both crossed gates were approved in the PRD review session on 2026-10-14.

- Database schema or migration change: crossed. The driver version table loses the column that stores `spec.container_overrides`, with an Alembic revision whose downgrade recreates the column empty. The deployment config storage does not change.
- GraphQL schema change: crossed. `ApplicationDriverVersion.containerOverrides` and `DriverContainerOverrideDoc` are removed, and `ComponentContainerOverrides.isApplicable: Boolean!` is added.
- New dependency: not crossed.
- CI/CD workflow change: not crossed.
- Authentication or authorization change: not crossed.

## Assumptions

- **A-001**: The strategic merge replaces the whole `command` and `args` list, because these fields have no merge key in the Kubernetes schema. This was checked in the PRD review session with kustomize v5.7.1: an `args` patch replaced the whole list, kept the chart's `command`, left the other container unchanged and moved the component container to `containers[0]`. Whether helm-controller v1.6.5, which the agent chart installs, behaves the same is not known yet. The E2E confirms it.
- **A-002**: In the in-repo charts, `command` and `args` values reach only the component container. This was checked in the PRD review session for the infrahub chart 4.33.2, which was pulled and searched, and for the `simple-app` chart.
- **A-003**: Styrmin is before version 1.0 and few third-party drivers exist, so the filters are retired with no deprecation period. This follows [ADR-057](../../dev/adr/0057-post-render-component-overrides.md) §4.

## Out of Scope

- Removing a `command` or `args` that the chart renders, so that the image's `ENTRYPOINT` or `CMD` applies. An empty list stays rejected ([ADR-045](../../dev/adr/0045-container-override-no-layering-and-omit-marker.md) §4).
- Overrides on init containers, other containers, `Job`, `CronJob` or `DaemonSet` workloads.
- More than one component container per component.
- Environment-scope or deployment-scope `command` and `args` ([ADR-045](../../dev/adr/0045-container-override-no-layering-and-omit-marker.md) §1).
- A UI or CLI list of the overrides that start to apply after the move to a migrated driver version.
- A way to find the deployments that are pinned to driver versions that call the retired filters.
- `{{ app.version }}` substitution in `command` and `args`. The values still pass through unchanged.

## Dependencies

- The post-render patch builder and component container check from [ADR-057](../../dev/adr/0057-post-render-component-overrides.md) and [ADR-058](../../dev/adr/0058-image-overrides-and-component-container-guard.md) (PRs [#387](https://github.com/opsmill/styrmin/pull/387) and [#390](https://github.com/opsmill/styrmin/pull/390)).
- The `RETIRED_TEMPLATE_FILTER` error introduced for `component_env_vars` ([ADR-057](../../dev/adr/0057-post-render-component-overrides.md) §4).
- Related specs: [`014-component-container-overrides`](../archive/014-component-container-overrides/spec.md), [`017-post-render-env-vars`](../archive/017-post-render-env-vars/spec.md), [`018-component-image-overrides`](../archive/018-component-image-overrides/spec.md).
