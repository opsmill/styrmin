# Feature Specification: Per-Component Replica Counts

**Feature Branch**: `fac/per-component-replica-1jel3`

**Created**: 2026-10-15

**Status**: Draft

**Input**: PRD "Per-component replica counts" — [opsmill/styrmin#202 (comment)](https://github.com/opsmill/styrmin/issues/202#issuecomment-6187621046). Seed issue: [#202](https://github.com/opsmill/styrmin/issues/202). Builds on [ADR-029](../../dev/adr/0029-config-additions-via-baseconfigsection-no-migration.md) (config additions without a migration), [ADR-057](../../dev/adr/0057-post-render-component-overrides.md) (post-render component overrides), [ADR-058](../../dev/adr/0058-image-overrides-and-component-container-guard.md) (image overrides and the check before a version change) and [ADR-069](../../dev/adr/0069-container-command-args-by-post-render.md) (container `command` and `args` by post-render).

## Context

A user who runs a deployment can change how many pods a component runs only when the driver author added a driver parameter for it and wired that parameter into the values template. Of the example drivers in `driver/examples/`, only `infrahub` and `infrahub-enterprise` do this, for the `server` and `task-worker` components (`replicas_server`, `replicas_task_worker`). No driver can mark a component, such as a database, as one that must never run more than one replica. Once every component accepts a replica count, nothing would stop a user from scaling such a component by mistake.

This feature adds:

- A **replica override**: the count a user sets on one component of one deployment. Styrmin applies it with a post-render patch to `spec.replicas` of every `Deployment` and `StatefulSet` that matches the component's label selector. It needs no component container and no template code in the driver. Stopping a component already uses this kind of patch (`spec.replicas: 0`).
- A **driver default**: `replicas` on a component in the driver specification file.
- A **singleton component**: `singleton: true` on a component in the driver specification file. Its count is fixed at 1.
- A rule for **parameters** that a target driver version no longer declares, so that the `infrahub` drivers can retire their two replica parameters without a manual step for deployments that kept the defaults.

The PRD corrects these parts of the issue description, and this spec follows the PRD:

- No deployment-wide `config.replicas` setting exists. Replica counts are driver parameters today.
- The override is stored in the deployment config with the other per-component overrides. There is no `replicas` column and no Alembic migration ([ADR-029](../../dev/adr/0029-config-additions-via-baseconfigsection-no-migration.md)).
- The override reaches pods through a post-render patch, not the values template ([ADR-057](../../dev/adr/0057-post-render-component-overrides.md)).
- An unset count means "no patch": the chart's count applies. Patching 1 by default would scale down every chart that renders more than one pod.
- The readiness polling needs no change: it already compares each `Deployment` and `StatefulSet` with its own `spec.replicas`.
- The person who sets the count is a "user". In [CONTEXT.md](../../CONTEXT.md), the "operator" is a Styrmin component.

## Clarifications

### Session 2026-10-15 (autonomous, from the PRD's open questions)

The PRD lists three open questions. They are answered here so that later phases do not reopen them.

- Q: Does infrahub chart 4.33.2 ship an autoscaler for `server` or `task-worker`? → A: No. The chart's own templates (`infrahub-server.yaml`, `infrahub-task-worker.yaml`) render a `Deployment` with `replicas: {{ .Values.<component>.replicas | default N }}` and no `HorizontalPodAutoscaler`. The only autoscaler templates in the chart's dependencies belong to the `prefect-server` and `redis` subcharts, and both are off by default (`autoscaling.enabled: false`), and the `infrahub` driver's values do not turn them on. The `infrahub-enterprise` chart 4.19.2 wraps the same `infrahub` subchart and adds no autoscaler. Checked by pulling both charts on 2026-10-15. The PRD assumption "no infrahub deployment depends on an autoscaler for `server` or `task-worker`" holds for the shipped drivers.
- Q: Can the frontend's driver-upgrade dialog send the replica override and the removal of the parameter in one submit? → A: Not today, and this feature does not add it. The upgrade dialog sends only the application version and the driver version (`updateDeploymentVersion` with `version` and `driverVersionId`). The API, the SDK and `styrminctl deployments apply` can resolve a rejection in one request, because `updateDeploymentVersion` already accepts `parameters` and `input.components`. In the UI, a user resolves the rejection in two steps, and no pod count changes in either step: first, in the deployment edit drawer, set the replica override to the stored parameter value and reset the parameter to its default; then run the upgrade. This works because the replica override applies on the current driver version too: the post-render patch overrides the count that the values template renders. The rejection error states both ways to resolve it (FR-010a).
- Q: Which existing E2E test and shard hold the coverage, and does the infrahub driver upgrade (SC-004) need E2E coverage on the infrahub shard? → A: The coverage goes in `shard_configuration` next to the other per-component override tests ([`test_deployment_image_override.py`](../../backend/tests/e2e/test_deployment_image_override.py), [`test_deployment_container_overrides.py`](../../backend/tests/e2e/test_deployment_container_overrides.py)), and reuses a `simple-app` deployment. The scaling journey goes through a new dual-entrypoint scenario driver method (like `set_component_image`), so it runs under both `[api-chromium]` and `[ui-chromium]`, and CI runs its UI variant: CI excludes the `api / configuration` cell, so an `api_only` test in this shard never runs in CI. The infrahub driver upgrade (SC-004, SC-005) gets no E2E on the infrahub shard. Functional tests cover it instead: they load the old and the new `infrahub` driver versions, run the version change, and check that the parameters are dropped and the resolved count for each component equals the count the old version rendered. The infrahub shard boots Infrahub for each scenario, and an upgrade between two driver versions of the same chart adds no Kubernetes behaviour that the `simple-app` scenario does not already cover.

## User Scenarios & Testing *(mandatory)*

Two people use this feature:

- A **user** who runs a deployment and needs one component to run more or fewer pods. They set the count through the deployment create and edit forms, GraphQL, the SDK or a `styrminctl deployments apply` manifest.
- A **driver author** who declares each component's default count and which components must run a single replica.

The user needs from the PRD, numbered as there:

1. As a user, I want to set the replica count of one component of my deployment, so that I can scale that component without asking the driver author for a new parameter.
2. As a user, I want to set replica counts when I create a deployment, so that the deployment starts with the counts I need.
3. As a user, I want to set replica counts in a declarative deployment manifest, so that `styrminctl deployments apply` manages them with the rest of the config.
4. As a user, I want to clear a replica override, so that the component returns to the driver default or to the chart's count.
5. As a user, I want to view each component's replica count and where it comes from, so that I know whether my override, the driver default or the chart sets it.
6. As a user, I want Styrmin to reject a count above 1 on a singleton component before any Kubernetes work starts, so that I cannot break a component that must run a single replica.
7. As a user, I want Styrmin to reject a count of 0 and tell me to stop the component instead, so that a stopped component and a scaled component stay distinct.
8. As a user, I want a stopped component to stay at 0 pods after I set an override, and to return to its count when I start it, so that stopping and scaling do not interfere.
9. As a user, I want the update task to finish only when the requested number of pods are ready, so that a completed task means the scale change is done.
10. As a driver author, I want to declare a default replica count per component, so that new deployments start with that count without user input.
11. As a driver author, I want to mark a component as a singleton component, so that no user can run it with more than one replica.
12. As a driver author, I want Styrmin to refuse to load a driver version that marks a component as singleton and sets its replica count above 1, so that I find the mistake when I load the driver.
13. As a user of the infrahub driver who kept the default replica parameter values, I want to move to the new driver version without editing parameters, so that the upgrade needs no manual step.
14. As a user of the infrahub driver who changed a replica parameter, I want the version change to be rejected with the parameter name and its stored value, so that I can carry the value over as a replica override and no pod count changes without my knowledge.
15. As a user, I want an override on a component that the new driver version removed to be kept but not applied, so that I do not lose it and it does not fail the reconciliation.

### User Story 1 - Set a component's replica count, with the singleton guard (Priority: P1)

A user sets a replica override on one component through the create or edit form, the SDK or `styrminctl deployments apply`. Styrmin reconciles the deployment, and the component runs that number of ready pods. A component that the driver marks as singleton cannot go above 1. Covers needs 1, 2, 3, 6, 7, 8, 9 and 11.

**Why this priority**: it is the user-visible change that the issue asks for, and the singleton guard must ship with it: without the guard, a user can scale a database by mistake as soon as every component accepts a count.

**Independent Test**: on a running `simple-app` deployment whose driver marks `database` as singleton, set `server` to 2 and check that 2 pods are ready, set it back to 1 and check the scale-down, check that `database` stays at 1, and check that `database` set to 2 is rejected.

**Acceptance Scenarios**:

1. **Given** a running deployment whose `server` component has 1 ready pod and no override, **When** the user sets the `server` replica override to 2, **Then** the update task completes only after the `server` workload has 2 updated, ready and available pods, and reading the deployment returns 2 with the source "override".
2. **Given** the `server` component runs 2 pods because of an override of 2, **When** the user sets the override to 1, **Then** the update task completes after the workload has 1 ready pod and no extra pods remain.
3. **Given** a driver version that marks `database` as `singleton: true`, **When** a user submits a `database` override of 2 through create, update, `styrminctl deployments apply` or a driver version change, **Then** Styrmin rejects the request before any Kubernetes work starts, with an error that names the component and the requested count, and stores nothing.
4. **Given** a singleton component, **When** a user submits an override of exactly 1, **Then** Styrmin accepts it.
5. **Given** any component, **When** a user submits an override of 0 or a negative number, **Then** Styrmin rejects the request with an error that tells the user to stop the component instead.
6. **Given** a stopped component with an override of 3, **When** the deployment is reconciled, **Then** the component stays at 0 pods and the override stays stored; **When** the user starts the component, **Then** it returns to 3 pods.
7. **Given** a user creates a deployment with an override of 2 on `server`, **When** the create task completes, **Then** `server` runs 2 ready pods.
8. **Given** a `styrminctl deployments apply` manifest that sets `components[].replicas` on `server`, **When** the user applies it, **Then** the override is stored and applied like an update, and applying the same manifest again changes nothing.

---

### User Story 2 - A driver author declares a default replica count (Priority: P2)

A driver author sets `replicas` on a component in the driver specification file, and new deployments run that count without a user override. Covers needs 10 and 12.

**Why this priority**: the default lets a driver ship a sensible count, and the `infrahub` drivers need it to replace their replica parameters. Story 1 works without it: the chart's count applies when there is no default.

**Independent Test**: load a driver version that declares `components.server.replicas: 2`, create a deployment with no override, and check that `server` runs 2 pods and the configuration view shows "2 (driver default)".

**Acceptance Scenarios**:

1. **Given** a driver version that declares `components.server.replicas: 2`, **When** a user creates a deployment with no override, **Then** `server` runs 2 pods and the configuration view shows "2 (driver default)".
2. **Given** a driver specification file that sets `singleton: true` and `replicas: 3` on one component, **When** Styrmin loads it, **Then** the load fails with an error that names the component, and no driver version is stored.
3. **Given** a driver specification file that sets `replicas: 0` or a non-integer on a component, **When** Styrmin loads it, **Then** the load fails with an error that names the component.
4. **Given** a driver version that marks a component `singleton: true` with no `replicas`, and a chart that renders 2 pods for it, **When** a deployment is reconciled, **Then** the component runs 1 pod and the configuration view shows "1 (driver default)".
5. **Given** a driver version that declares no `replicas` and no `singleton` on a component, **When** a deployment is reconciled, **Then** Styrmin builds no replica patch and the component runs the chart's count, and the configuration view shows the source "chart".
6. **Given** a driver version, **When** a user opens its page or reads it through the API, **Then** each component shows its `replicas` and `singleton` values.

---

### User Story 3 - Clear a replica override and view the source of each count (Priority: P3)

A user removes an override, and the component returns to the next value in the order of precedence. The configuration view and `styrminctl deployments get` show each component's count and its source. Covers needs 4 and 5.

**Why this priority**: clearing is part of the full override lifecycle, and the source tells the user why a component runs the count it runs. Story 1 delivers the scaling change without it.

**Independent Test**: on a component with an override of 3 and a driver default of 2, clear the override and check that the component returns to 2 pods and the configuration view shows "2 (driver default)".

**Acceptance Scenarios**:

1. **Given** a component with an override of 3 and a driver default of 2, **When** the user clears the override, **Then** the component returns to 2 pods.
2. **Given** a component with an override of 3 and no driver default, **When** the user clears the override, **Then** Styrmin builds no replica patch and the component returns to the chart's count, and the source is "chart".
3. **Given** a deployment, **When** the user runs `styrminctl deployments get`, **Then** the output shows each component's replica count and its source.
4. **Given** a component whose source is "chart", **When** the user views the configuration view, **Then** the view shows that the chart sets the count, without a number, because Styrmin does not read the chart's rendered count.

---

### User Story 4 - Move the infrahub drivers to the replica mechanism (Priority: P2)

The `infrahub` and `infrahub-enterprise` drivers ship a new version that retires `replicas_server` and `replicas_task_worker` and uses driver defaults instead. A deployment that kept the default parameter values moves to the new version without a manual edit. A deployment that changed a value is rejected with the parameter name and its value, so that the user carries the value over as a replica override. Covers needs 13, 14 and 15.

**Why this priority**: the two infrahub parameters and a per-component override would otherwise both set the same count, and users would not know which one wins. The rule for retired parameters is also what lets any driver retire a parameter safely.

**Independent Test**: functional tests that load the old and the new `infrahub` driver versions and run a driver version change for a deployment with default parameter values and for one with a changed value.

**Acceptance Scenarios**:

1. **Given** an `infrahub` deployment on the old driver version whose stored `replicas_server` is 1 and `replicas_task_worker` is 2 (the defaults), **When** the user changes to the new driver version, **Then** Styrmin drops both stored values, the change succeeds, and `server` resolves to 1 and `task-worker` to 2 (driver default), so no pod count changes.
2. **Given** an `infrahub` deployment whose stored `replicas_task_worker` is 4, **When** the user changes to the new driver version without changing parameters, **Then** Styrmin rejects the change before any Kubernetes work starts, with an error that names `replicas_task_worker` and the value 4, and the deployment stays on the old driver version with 4 `task-worker` pods.
3. **Given** the rejection in scenario 2, **When** the user resubmits the version change with a `task-worker` replica override of 4 and without `replicas_task_worker` in the parameters, in one API, SDK or `styrminctl deployments apply` request, **Then** the change succeeds and `task-worker` keeps 4 pods.
4. **Given** the rejection in scenario 2, **When** the user, in the edit drawer, sets the `task-worker` override to 4 and resets `replicas_task_worker` to its default, then runs the upgrade, **Then** both steps succeed and `task-worker` runs 4 pods throughout.
5. **Given** a deployment with an override on a component that the target driver version no longer declares, **When** the user changes the driver version, **Then** the change succeeds, Styrmin keeps the override, does not apply it, and reports it as not applicable.
6. **Given** a deployment whose stored `database` override is 2 on a driver version that does not mark `database` as singleton, **When** the user changes to a version that marks it as singleton, **Then** the change is rejected with the component and the count; **When** the user lowers the override to 1 or clears it in the same request, **Then** the change succeeds.

---

### Edge Cases

- A stopped component with an override stays at 0 pods (FR-005).
- A singleton component whose chart renders more than one pod is patched to 1 (FR-007).
- A deployment that stores an override greater than 1 moves to a driver version that marks the component as singleton: the version change is rejected, and the user can lower or clear the override in the same request (FR-008).
- An override on a component that the target driver version removed is kept and not applied (FR-009).
- A user adds or changes an override on a component that the driver version does not declare: Styrmin rejects it and names the component and the components the driver version declares. An override that was stored before the component was removed is kept (FR-009).
- A label selector that matches several workloads: each matching `Deployment` and `StatefulSet` gets the count.
- A label selector that matches no `Deployment` or `StatefulSet` (for example, a component that runs only as a `DaemonSet` or a `Job`): Styrmin builds no replica patch, and the reconciliation does not fail.
- A scale-up that leaves pods `Pending` because the cluster lacks capacity: the update task fails when its existing wait limit runs out.
- A rolling update of a singleton component can run 2 pods for a short time, because the chart's update strategy controls this. The documentation states this limit.
- An update resubmits, unchanged, a stored override above 1 on a component that the bound driver version marks as singleton: Styrmin rejects it (FR-008). Unlike the component container check, which accepts stored values resubmitted unchanged, the singleton check does not, because the stored count breaks the singleton rule.
- A stored retired parameter value that is a string or a different type from the current default (for example `"1"` instead of `1`): it does not equal the default, so the change is rejected and names the value.
- A request that changes the driver version and still submits a retired parameter (for example a `styrminctl deployments apply` manifest written for the old version): the FR-010 rule applies to the submitted value as it does to a stored one, so a default value is dropped and any other value is rejected with the parameter and its value.
- A parameter that neither the current nor the target driver version declares is rejected as an unknown parameter, as today.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Users MUST be able to set `replicas` on any component when they create a deployment, update it, change its driver version, or apply a declarative deployment manifest.
- **FR-002**: Styrmin MUST resolve each component's count in this order: the replica override, then the driver default, then no patch, so that the chart's count applies.
- **FR-003**: Styrmin MUST apply the resolved count to `spec.replicas` of every `Deployment` and `StatefulSet` that matches the component's label selector, through a post-render patch. It MUST NOT require a component container.
- **FR-004**: Styrmin MUST reject a count below 1, with an error that tells the user to stop the component instead.
- **FR-005**: A stopped component MUST stay at 0 pods whatever its override is. When the user starts it again, it MUST return to the resolved count.
- **FR-006**: The driver specification file MUST accept `replicas` (an integer of 1 or more) and `singleton` (a boolean, default `false`) on each component. Styrmin MUST refuse to load a driver version that combines `singleton: true` with `replicas` greater than 1.
- **FR-007**: For a singleton component without `replicas`, Styrmin MUST patch the count to 1, even when the chart renders more pods.
- **FR-008**: Styrmin MUST reject an override greater than 1 on a singleton component on create, update, `styrminctl deployments apply` and driver version change, before any Kubernetes work starts. It MUST accept an override of exactly 1.
- **FR-009**: Styrmin MUST keep, but not apply, an override on a component that the bound driver version no longer declares, and report it as not applicable.
- **FR-010**: On a driver version change, Styrmin MUST drop a stored parameter value that the target version no longer declares when the value equals that parameter's default in the current version. Otherwise it MUST reject the change with an error that names the parameter and its stored value.
- **FR-010a**: The FR-010 rejection error MUST tell the user how to resolve it: remove the parameter or reset it to its default, and, when the value set a replica count, carry it over as a replica override.
- **FR-011**: A new version of the `infrahub` and `infrahub-enterprise` drivers MUST remove `replicas_server` and `replicas_task_worker`, declare `server` with `replicas: 1` and `task-worker` with `replicas: 2`, and mark the database component as singleton.
- **FR-012**: Reading a deployment MUST return each component's replica count, its source (override, driver default or chart) and whether the override applies. Reading a driver version MUST return `replicas` and `singleton` for each component.
- **FR-013**: The frontend MUST offer a replica count field per component in the create and edit forms, show singleton components as fixed at 1, and show the count and its source on the configuration view and the driver version page.
- **FR-014**: `styrminctl deployments get` MUST show each component's replica count and its source.
- **FR-015**: A replica override MUST apply to one component of one deployment only. It MUST NOT be set at environment or cluster level, and it MUST NOT layer.
- **FR-016**: Changing a replica count MUST need the same role as any other deployment config edit.

### Key Entities

- **Component** (existing): the driver declares `replicas` and `singleton` on it in the driver specification file.
- **Replica override** (new term): the count a user sets on one component of one deployment, an integer of 1 or more. It is stored in the deployment config with the other per-component overrides, so no new table is needed.
- **Singleton component** (new term): a component that the driver version marks `singleton: true`. Its count is fixed at 1.
- **Resolved replica count** (derived, not stored): the count Styrmin applies to a component and its source (override, driver default or chart), or "no patch" when the source is the chart.
- **Parameter** (existing): gains the rule in FR-010 for values whose parameter the target driver version no longer declares.

The `CONTEXT.md` entries for the replica override, the singleton component, and the FR-010 rule on parameters are drafted on branch `fac/per-component-replica-1jel3`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On a deployment of any example driver shipped in `driver/examples/`, a user can change the replica count of any component that is not a singleton, without any change to the driver.
- **SC-002**: The update task reports success only when the requested number of pods are ready. Scaling from 1 to 2 pods and from 2 to 1 pod both complete within the update task's existing wait limit.
- **SC-003**: No path accepts a count above 1 on a singleton component. Tests cover create, update, `styrminctl deployments apply` and driver version change, and none of these writes succeeds.
- **SC-004**: An infrahub deployment that kept the default replica parameter values moves to the new driver version with no manual edit, and no component's pod count changes.
- **SC-005**: For an infrahub deployment with a changed replica parameter value, the version change is rejected with an error that names the parameter and its value, and no pod count changes until the user resubmits.
- **SC-006**: For a deployment whose driver declares no `replicas` and no `singleton`, upgrading Styrmin does not change any workload's replica count.

## Assumptions

- No infrahub deployment depends on an autoscaler for `server` or `task-worker`. Verified for the shipped charts (see Clarifications).
- The update task's existing wait limit is long enough for a normal scale-up.
- The post-render replica patch runs after the values template, so an override wins over a count that a driver parameter sets in the values template. This is what lets a user carry a parameter value over as an override before the upgrade (Clarifications, question 2).
- Styrmin does not read the count the chart renders. When the source is "chart", the configuration view and `styrminctl deployments get` show the source without a number.
- The existing stop and start patch keeps working as it does today: a stopped component gets `spec.replicas: 0`.

## Out of Scope

- Detecting a `HorizontalPodAutoscaler` that a chart ships, and working with it.
- Replica defaults at environment or cluster level. Overrides apply to one component only and are not layered, like image overrides.
- A separate "scale" lifecycle action. Users change the count by editing the deployment config.
- A driver format feature that maps a parameter to an override.
- Making sure only one pod of a singleton component runs at a time during a rolling update.
- Checking cluster capacity before a scale-up.
- Changing the upgrade dialog so that it sends config with the version change (Clarifications, question 2).
- An E2E test of the infrahub driver upgrade on the infrahub shard (Clarifications, question 3).

## Documentation

Constitution §VII requires these in the same change:

- A concept page for the replica override, modelled on the image overrides page under `docs/`.
- The driver format page: `replicas` and `singleton` on a component.
- An upgrade note for the `infrahub` and `infrahub-enterprise` drivers that explains FR-010 and both ways to resolve a rejection.
- The `CONTEXT.md` entries (already drafted on this branch).
- An ADR that records the order of precedence (FR-002) and the rule for retired parameters (FR-010).
- A towncrier changelog fragment for issue #202.
