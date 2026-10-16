# Feature Specification: helm-controller Runs with Helm v4 Defaults

**Feature Branch**: `fac/helm-v4-end3k`

**Created**: 2026-10-16

**Status**: Draft

**Input**: PRD "Run helm-controller with Helm v4 defaults" — [opsmill/styrmin#435 (comment)](https://github.com/opsmill/styrmin/issues/435#issuecomment-6210811102). Seed issue: [#435](https://github.com/opsmill/styrmin/issues/435). The gate was set by [#434](https://github.com/opsmill/styrmin/pull/434), which fixes [#432](https://github.com/opsmill/styrmin/issues/432) and [#433](https://github.com/opsmill/styrmin/issues/433).

## Context

The agent chart installs FluxCD's helm-controller v1.6.5, which uses Helm v4 from v1.5.0 ([helm-controller changelog](https://github.com/fluxcd/helm-controller/blob/v1.6.5/CHANGELOG.md)). The chart runs it with `--feature-gates=UseHelm3Defaults=true` ([`helm/agent/templates/helm-controller/deployment.yaml`](../../helm/agent/templates/helm-controller/deployment.yaml)), so every HelmRelease is installed and upgraded with Helm v3 behaviour. It is not known whether or when FluxCD removes the gate ([#435](https://github.com/opsmill/styrmin/issues/435)).

The gate changes these defaults of the HelmRelease CRD ([`helm/agent/crds/helm.toolkit.fluxcd.io_helmreleases.yaml`](../../helm/agent/crds/helm.toolkit.fluxcd.io_helmreleases.yaml)):

| Behaviour | HelmRelease field | With the gate (Helm v3) | Without the gate (Helm v4) |
| --- | --- | --- | --- |
| Apply method of a new install | `spec.install.serverSideApply` | `false`, client-side apply | `true`, server-side apply |
| Apply method of an upgrade or rollback | `spec.upgrade.serverSideApply`, `spec.rollback.serverSideApply` | `auto`: the method of the release's previous install or upgrade | `auto`, unchanged |
| Health checks | `spec.waitStrategy.name` | `legacy`, Helm v3's checks | `poller`, kstatus |
| Helm hooks sent to the post-renderers | `spec.postRenderStrategy` | `nohooks` | `combined`: hooks and templates together |

These parts of Styrmin were checked with Helm v3 behaviour only:

- The operator's readiness, rollback and failure rules for a HelmRelease. They decide the task result and the steps a user views ([operator knowledge page](../../dev/knowledge/agent/operator.md), [ADR-060](../../dev/adr/0060-steps-and-derived-task-result.md)).
- The post-render patches for labels, scheduling settings, env vars, image overrides and container overrides, and the component-container guard ([ADR-057](../../dev/adr/0057-post-render-component-overrides.md), [ADR-058](../../dev/adr/0058-image-overrides-and-component-container-guard.md)).
- The operator's readiness timeout of 270 seconds. It is set below FluxCD's 5-minute HelmRelease timeout so that the failed step still names the pods' reason before FluxCD rolls the release back ([operator knowledge page, "Readiness timeout"](../../dev/knowledge/agent/operator.md)).

This feature removes the gate:

- The agent chart runs helm-controller without the gate. The operator sets none of the fields in the table, so FluxCD's defaults apply.
- Deployments created after the change are installed with server-side apply. Deployments created before keep client-side apply, because upgrades and rollbacks reuse the method of the previous release (`auto`).
- Every release uses kstatus health checks and sends Helm hooks to the post-renderers from its next install or upgrade.
- Users view the same task results and steps as today, for successful and failed changes.
- Helm hooks of a deployment's chart receive Styrmin's labels. Helm hook Jobs also receive the deployment's scheduling settings.
- All four user stories below ship in one change.

## Clarifications

### Session 2026-10-16 (autonomous, from the PRD)

The PRD's decisions were taken in a review session of [#435](https://github.com/opsmill/styrmin/issues/435) on 2026-10-15 and 2026-10-16. The answers to the three "Not decided" points of #435 are recorded here so later phases do not reopen them.

- Q: Drop the gate, or set Helm v4's behaviour on each HelmRelease with the fields above? → A: Drop the gate for all HelmReleases at once. The operator keeps writing none of the fields.
- Q: How do existing releases move from client-side to server-side apply? → A: They do not. Upgrades and rollbacks keep `auto`, so a release keeps the apply method of its previous install or upgrade. Moving existing releases (`spec.upgrade.serverSideApply: enabled`) is out of scope.
- Q: Which E2E tests need to run, or be added? → A: The full E2E suite in CI, both variants as marked; the `api` cell of `shard_configuration` run locally, because CI excludes it; and `test_pod_scheduling.py` extended with a Helm hook Job check. No new heavy E2E test is added.
- Q: Do Helm hooks receiving post-render patches count as a defect to prevent? → A: No. It is intended behaviour, and the driver documentation states which patches reach Helm hooks.
- Q: Do server-side apply field ownership conflicts get special handling? → A: No. helm-controller v1.6.5 always forces conflicts under server-side apply (see the planning session below), so a conflict does not fail an upgrade.
- Q: Add E2E checks for `Stalled` and the readiness timeout, or accept the unit tests that use recorded FluxCD states? → A: Accept the unit tests (`test_styrmin_deployment_timer.py`, `steps/test_operator_history_failures.py`) for these two outcomes, and record the gap. This feature changes no operator rule, and reaching either outcome in E2E needs FluxCD to use all its retries or the 270-second timeout to pass, in a session that other tests share. The PRD leaves this open; the decision is flagged for the maintainer to confirm, as AGENTS.md asks before E2E coverage is left out.

### Session 2026-10-16 (planning research, [research.md](research.md))

- Q: Does helm-controller v1.6.5 force field ownership conflicts under server-side apply? → A: Yes, always, with field manager `helm-controller`, and no HelmRelease field turns it off (R-002). A field of a chart resource that another tool changed returns to the chart's value at the next upgrade; the upgrade does not fail. The driver documentation says this instead of "can make the next upgrade fail".
- Q: Does Helm v4's kstatus wait end early on a failed resource? → A: Yes for a resource kstatus reports `Failed`, but a Deployment with pods in `ImagePullBackOff` stays `InProgress`, so FluxCD still waits the full 5 minutes and the failed step keeps the pods' reason (R-005).
- Q: Does helm-controller upgrade an in-sync release when only its defaults change? → A: No (R-003). Releases installed with the gate keep client-side apply on every later upgrade and rollback (R-004).
- Q: Does Helm v4 write release Secrets of type `helm.sh/release.v1`? → A: Yes, with the same labels and encoding, and one new record field, `apply_method` (R-006).
- Q: Does any post-render patch fail on a Helm hook? → A: The patch that adds Styrmin's labels to every resource fails the whole render when a resource has no `metadata.labels` (R-008). Today only templates reach it, and chart templates carry labels; a chart hook without labels would fail every install and upgrade of that driver. The patch becomes a strategic merge that adds the labels map when it is missing (FR-013).
- Q: The PRD's FR-003 names the hook Job's "node selector". → A: Styrmin's scheduling settings have no node selector; nodes are chosen with node affinity and tolerations. The check covers those (R-009). The E2E vcluster has one node, so the check is that the hook Job's pod has the settings and completed.

## User Scenarios & Testing *(mandatory)*

Four people use this feature:

- A **user** who creates, updates and upgrades deployments, and reads the task to find why a change failed.
- An **administrator** who upgrades the agent chart on a cluster that already runs deployments.
- A **driver author** whose chart can contain Helm hooks, and whose actions can change resources the chart owns.
- A **Styrmin maintainer** who keeps Styrmin working across FluxCD releases.

The user needs from the PRD, numbered as there:

1. As a user who changes a deployment, I want a failed change to show the same failed step, reason and message as today, so that I can find the cause in the task without reading FluxCD's state.
2. As a user whose change uses an image that cannot be pulled, I want the failed HelmRelease step to name the pods' reason, such as `ImagePullBackOff`, so that I can correct the image reference.
3. As a user who creates a deployment, I want it to reach `Running` with the same steps as today.
4. As an administrator who upgrades the agent chart, I want the upgrade to leave existing deployments unchanged, with no new Helm release revision and no pod restarts, so that the agent upgrade does not interrupt the applications users run.
5. As a driver author whose chart has Helm hook Jobs, I want those Jobs to run with the deployment's scheduling settings, so that they can run on the nodes the deployment is pinned to, including nodes with taints that only the deployment's tolerations allow.
6. As a driver author, I want the driver documentation to state which post-render patches reach Helm hooks, and that an action which changes a resource the chart owns can make the next upgrade fail, so that I can write charts and actions that work with Styrmin. (Research R-002: the upgrade does not fail; the changed field returns to the chart's value. The documentation states what happens.)
7. As a Styrmin maintainer, I want Styrmin to stop depending on the `UseHelm3Defaults` gate, so that a FluxCD release without the gate does not change how deployments behave.

The PRD defines one user journey (P1). The stories below split it so each part can be checked on its own; all four ship in one change.

### User Story 1 - Users view the same task results with Helm v4 defaults (Priority: P1)

A user creates, updates and upgrades deployments on an agent whose helm-controller runs without `UseHelm3Defaults`. They view the same task results and steps as with Helm v3 behaviour, for successful and failed changes. Covers needs 1, 2, 3 and 7.

**Why this priority**: the task result and its steps are how a user learns whether a change worked and why it failed. If Helm v4's defaults changed them, users would lose that without any change to Styrmin's own code.

**Independent Test**: run the existing E2E suite against an agent without the gate and compare the task results and steps with the runs that had the gate.

**Acceptance Scenarios**:

1. **Given** an agent without the gate, **When** a user creates a deployment, **Then** FluxCD installs the HelmRelease with server-side apply, the "Install or upgrade the HelmRelease" step succeeds and the deployment reaches `Running`.
2. **Given** a running deployment, **When** a user changes it to an image that cannot be pulled, **Then** the task fails, FluxCD rolls the release back, and the failed HelmRelease step shows `RolledBack`, with `HelmReleaseRemediated`, and names the pods' reason (`ImagePullBackOff`).
3. **Given** a running deployment, **When** a user sets an image override whose component container is missing, **Then** the task fails with `COMPONENT_CONTAINER_NOT_FOUND`, naming the component and the container.
4. **Given** a running deployment, **When** FluxCD uses all its retries for a change, **Then** the task fails with `Stalled` and FluxCD's reason, as today. (Covered by unit tests with recorded FluxCD states; see Clarifications.)
5. **Given** a running deployment, **When** a change does not reach `Ready` within the readiness timeout, **Then** the deployment shows "Deployment did not reach Ready within 270s", as today. (Covered by unit tests with recorded FluxCD states; see Clarifications.)

---

### User Story 2 - Helm hook Jobs run with the deployment's scheduling settings (Priority: P1)

A driver author's chart has a Helm hook Job. A user pins the deployment to nodes with a node selector and tolerations. The Helm hook Job's pod runs on those nodes and carries Styrmin's labels, as the chart's other Jobs already do. Covers need 5.

**Why this priority**: with `postRenderStrategy: combined`, Helm hooks reach the post-renderers. A Helm hook Job that ignored the deployment's scheduling settings could stay pending on a cluster where only the pinned nodes accept the deployment's pods.

**Independent Test**: deploy a chart with a pre-upgrade Helm hook Job on a deployment with a node selector and tolerations, upgrade it, and check the node selector, tolerations and node of the hook Job's pod.

**Acceptance Scenarios**:

1. **Given** a deployment pinned to nodes with a node selector and tolerations, and a chart with a pre-upgrade Helm hook Job, **When** the deployment is upgraded, **Then** the hook Job's pod has the deployment's node selector and tolerations and runs on a pinned node.
2. **Given** the same deployment, **When** the hook Job is created, **Then** it carries Styrmin's labels.
3. **Given** a chart whose Helm hook has no `metadata.labels`, **When** the deployment is installed or upgraded, **Then** the render succeeds and the hook carries Styrmin's labels.

---

### User Story 3 - Upgrading the agent chart leaves existing deployments unchanged (Priority: P1)

An administrator upgrades the agent chart from a version with the gate to this change. Existing deployments get no new Helm release revision, so their pods do not restart, and they keep client-side apply. Covers need 4.

**Why this priority**: an agent upgrade that restarted every application would interrupt the users who run them.

**Independent Test**: a manual check recorded in the implementing pull request. Install the agent at the current version, create a deployment, upgrade the agent to this change, and confirm the release revision is unchanged. An E2E test would need a fixture that installs the agent twice, which is out of scope.

**Acceptance Scenarios**:

1. **Given** a deployment created with the gate, **When** the administrator upgrades the agent chart, **Then** the deployment's Helm release revision does not change and its pods do not restart.
2. **Given** the same deployment, **When** a user later changes it, **Then** FluxCD upgrades it with client-side apply, because the upgrade reuses the previous release's method.

---

### User Story 4 - Driver authors and operators read what changed (Priority: P1)

The documentation states the new behaviour in the same change: which post-render patches reach Helm hooks, that an action which changes a resource the chart owns can make the next upgrade fail, that helm-controller runs with Helm v4 defaults, and what a Helm hook is. Covers need 6.

**Why this priority**: driver authors write charts and actions against this behaviour. Constitution §VII forbids deferring the documentation.

**Independent Test**: read the updated pages and check each item listed in FR-006 to FR-010.

**Acceptance Scenarios**:

1. **Given** the driver documentation, **When** a driver author reads it, **Then** it lists which post-render patches reach Helm hooks and states that, for a deployment installed with server-side apply, a field of a chart resource that an action changes returns to the chart's value at the next upgrade.
2. **Given** the operator and CRDs page, **When** an operator reads it, **Then** it states that helm-controller runs with Helm v4 defaults, not with `UseHelm3Defaults`.

---

### Edge Cases

- **Existing releases**: they keep client-side apply. They switch to kstatus health checks and `combined` post-rendering at their next install or upgrade.
- **Restore and environment clone**: the operator rewrites restored release Secrets of type `helm.sh/release.v1` and keeps every field of the release record ([`operator/restore_recovery.py`](../../backend/styrmin_backend/operator/restore_recovery.py)). Helm v4 writes Secrets of the same type and encoding, with one new field, `apply_method`, which the restore keeps (R-006). The backup and clone E2E tests confirm it.
- **Field ownership conflicts under server-side apply**: for deployments created after the change, a field that the chart sets and that `kubectl`, a driver action or an autoscaler changed returns to the chart's value at the next upgrade, because helm-controller always forces conflicts (R-002). A field the chart does not set stays as the other tool left it. Styrmin changes workloads only through post-render patches, so it causes no such conflict itself.
- **Helm hook without labels**: a chart resource without `metadata.labels` fails the current label patch (R-008). After the change it renders and receives Styrmin's labels (FR-013).
- **Which post-render patches reach Helm hooks with `combined`** ([`application.py` patch assembly](../../backend/styrmin_backend/agent/service/kubernetes/resources/builders/application.py)):
  - Styrmin's labels reach every resource, because the label patch targets every name.
  - Scheduling settings reach `Deployment`, `StatefulSet`, `DaemonSet`, `Job`, `CronJob` and `ReplicaSet` resources ([`scheduling/patch_builder.py`](../../backend/styrmin_backend/services/scheduling/patch_builder.py)).
  - Env var, image and container overrides and the component-container guard reach a Helm hook `Deployment` or `StatefulSet` that matches a component's labels ([`component_container/patch_builder.py`](../../backend/styrmin_backend/services/component_container/patch_builder.py)).
- **Example drivers**: rendered with default values on 2026-10-15, the infrahub chart has no Helm hook, and the semaphore chart has one `test-success` Pod, which Helm runs only for a Helm test. Neither changes. Third-party driver charts can have Helm hooks.
- **Ingress controller**: its HelmRelease can stay `Progressing` while a LoadBalancer gets no external IP, so the operator counts it as ready when one of its pods is ready. It is not known whether kstatus waits for the external IP. The result the user views is the same either way.
- **Early end of the kstatus wait**: FluxCD's wait ends early when a resource reaches kstatus `Failed`, for example a failed template `Job` or a Deployment whose `progressDeadlineSeconds` passed (R-005). The task then shows FluxCD's failure sooner than before. A Deployment with pods in `ImagePullBackOff` stays `InProgress`, so that case still waits the full 5 minutes. A chart that sets `progressDeadlineSeconds` below 270 seconds gets FluxCD's `ProgressDeadlineExceeded` failure in the failed step instead of the pods' reason.
- **Turning the gate on again**: releases installed while the gate was off keep server-side apply, because upgrades use `auto`. The new ADR records this.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The agent chart MUST run helm-controller without `--feature-gates=UseHelm3Defaults=true`. The operator MUST NOT set `install.serverSideApply`, `upgrade.serverSideApply`, `rollback.serverSideApply`, `waitStrategy` or `postRenderStrategy` on HelmReleases.
  - Verification: a chart unit test that fails when helm-controller runs with the gate, and the existing comparison of the integration fixture with the chart (`backend/tests/unit/test_helm_agent_crd_upgrade.py`). The fixture copy drops the gate in the same change.
- **FR-002**: The operator MUST report each HelmRelease outcome its rules describe with the same phase, `displayState`, conditions and message as with Helm v3 behaviour ([outcomes table in the operator knowledge page](../../dev/knowledge/agent/operator.md)). The operator's rules do not change unless an E2E run shows a different result.
  - Verification: the existing E2E suite, including `test_task_steps.py::test_helmrelease_failure_shows_fluxcd_reason` for the rollback and the pods' reason, and the `api` cell of `shard_configuration` run locally for the component-container guard (`test_deployment_image_override.py::test_misnamed_container_never_added`). `Stalled` and the readiness timeout are covered by unit tests with recorded FluxCD states (see Clarifications).
- **FR-003**: Helm hook Jobs of a deployment's chart MUST receive the deployment's scheduling settings and Styrmin's labels, as the chart's other Jobs already do.
  - Verification: `test_pod_scheduling.py` extended to check the node selector, tolerations and node of a Helm hook Job's pod.
- **FR-004**: Upgrading the agent chart MUST NOT upgrade existing releases or change their apply method.
  - Verification: a manual check recorded in the implementing pull request (SC-003).
- **FR-005**: The `simple-app` test chart MUST offer a pre-upgrade Helm hook Job that carries a component's labels, behind a chart value that is off by default, so that only the scheduling test turns it on. The 22 E2E test files that deploy `simple-app` MUST NOT get the Job.
- **FR-006**: The operator and CRDs page (`docs/docs/concepts-and-architecture/operator-and-crds.md`) MUST state that helm-controller runs with Helm v4 defaults, replacing the text that says it runs with `UseHelm3Defaults`.
- **FR-007**: The "Creating a driver" page (`docs/docs/drivers/creating-a-driver.md`) MUST state which post-render patches reach Helm hooks, and that, for a deployment installed with server-side apply, a field of a chart resource that an action changes returns to the chart's value at the next upgrade (R-002).
- **FR-008**: The operator knowledge page (`dev/knowledge/agent/operator.md`) MUST replace the "Helm v3 behaviour" item and the statement that the rules were observed with Helm v3 behaviour. Its statement that it was not checked whether v1.6.5 still reports the rollback of a post-renderers change as ready MUST be updated if the E2E runs answer that.
- **FR-009**: `CONTEXT.md` MUST gain a **Helm hook** entry, and the **Hook** entry MUST list "Helm hook" among the terms to avoid.
- **FR-010**: A new ADR MUST record the decisions: "helm-controller runs with Helm v4 defaults; releases keep their apply method". It MUST state that if the gate were turned on again, releases installed in the meantime would keep server-side apply.
- **FR-011**: A towncrier fragment MUST record that new installs use server-side apply and that Helm hooks receive post-render patches.
- **FR-012**: The GraphQL API, SDK, CLI, frontend, database schema and error types MUST NOT change.
- **FR-013**: Styrmin's labels MUST reach every chart resource, including a Helm hook or template without `metadata.labels`, without failing the render, and MUST keep the resource's existing labels (R-008).
  - Verification: a kustomize integration test with a labelled resource, an unlabelled resource and an unlabelled hook Job.

### Key Entities

- **HelmRelease** (existing): its spec does not change. helm-controller's defaults for it change.
- **Operator** (existing): its rules do not change. They are checked again with Helm v4 defaults.
- **Component container** (existing): env var, image and container overrides and the component-container guard still reach only `Deployment` and `StatefulSet` resources.
- **Helm hook** (new glossary entry, not a new Styrmin entity): a chart resource annotated `helm.sh/hook` that Helm creates at a set point of an install, upgrade, rollback, uninstall or test. It is distinct from a Styrmin **hook**, which is a lifecycle slot for actions.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For every failure the existing E2E tests cover, the task shows the same failed step, reason and message as before the change.
- **SC-002**: When a change fails because an image cannot be pulled, the failed HelmRelease step names the pods' reason (`ImagePullBackOff`) in every run.
- **SC-006**: A driver whose chart has a Helm hook without labels installs and upgrades without a render error.
- **SC-003**: Upgrading the agent chart creates no new Helm release revision for any existing deployment, so no pod restarts. Research R-003 shows helm-controller does not upgrade a release that is in sync when only its own defaults change; the manual check confirms it.
- **SC-004**: The Helm hook Job of a deployment pinned to nodes runs on those nodes in every run.
- **SC-005**: A deployment created after the change reaches `Running` with the same steps as before the change.

## Assumptions

- Existing installs that keep client-side apply are covered by the E2E tests from before the change, because only the health checks and post-rendering change for them.
- The backup and clone E2E tests answer whether Helm v4 writes release Secrets of type `helm.sh/release.v1`.
- `test_task_steps.py::test_helmrelease_failure_shows_fluxcd_reason` answers whether kstatus ends its wait early on a failed resource.
- The PRD's links were checked against `develop` commit `fd17ffb7`, which this branch starts from.

## Out of Scope

- Moving existing releases to server-side apply (`spec.upgrade.serverSideApply: enabled`).
- Setting the Helm v4 fields on each HelmRelease.
- An E2E test of the agent upgrade.
- The `separate` post-render strategy, which Helm 4.2 offers.
- Using kstatus to improve readiness, for example for the ingress controller's LoadBalancer.
- Special handling of server-side apply conflicts.

## Dependencies

- helm-controller v1.6.5 and its `UseHelm3Defaults` feature gate, as installed by [#434](https://github.com/opsmill/styrmin/pull/434).
- The scheduling, label and component-container post-render patches ([ADR-057](../../dev/adr/0057-post-render-component-overrides.md), [ADR-058](../../dev/adr/0058-image-overrides-and-component-container-guard.md)).
- The operator's HelmRelease rules ([ADR-060](../../dev/adr/0060-steps-and-derived-task-result.md)).
