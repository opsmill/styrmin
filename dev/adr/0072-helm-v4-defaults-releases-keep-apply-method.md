# ADR-072: helm-controller Runs with Helm v4 Defaults; Releases Keep Their Apply Method

**Status**: Accepted
**Date**: 2026-10-16
**Source**: [specs/024-helm-v4-defaults/](../../specs/024-helm-v4-defaults/) (spec, plan D-001 to D-006,
[research R-001 to R-008](../../specs/024-helm-v4-defaults/research.md), and the evidence files
[e2e-evidence.md](../../specs/024-helm-v4-defaults/e2e-evidence.md) and
[agent-upgrade-check.md](../../specs/024-helm-v4-defaults/agent-upgrade-check.md));
[issue #435](https://github.com/opsmill/styrmin/issues/435)
**Reverses**: the `--feature-gates=UseHelm3Defaults=true` argument that
[PR #434](https://github.com/opsmill/styrmin/pull/434) added to helm-controller when it moved the agent
to helm-controller v1.6.5 to fix [#432](https://github.com/opsmill/styrmin/issues/432) and
[#433](https://github.com/opsmill/styrmin/issues/433).
**Related**: [ADR-057](0057-post-render-component-overrides.md) and
[ADR-058](0058-image-overrides-and-component-container-guard.md) (the post-render patches and the
component-container guard), [ADR-060](0060-steps-and-derived-task-result.md) (the operator's
HelmRelease rules and the steps a user views).

## Context

The agent chart installs FluxCD's helm-controller v1.6.5, which uses Helm v4 from v1.5.0. PR #434
ran it with `--feature-gates=UseHelm3Defaults=true`, so every HelmRelease kept Helm v3 behaviour.
It is not known whether or when FluxCD removes the gate (#435).

The gate changes three defaults of a HelmRelease, all on fields that the operator does not write
(research R-001):

| Behaviour | HelmRelease field | With the gate | Without the gate |
| --- | --- | --- | --- |
| Apply method of a new install | `spec.install.serverSideApply` | `false`, client-side apply | `true`, server-side apply |
| Health checks | `spec.waitStrategy.name` | `legacy`, Helm v3's checks | `poller`, kstatus |
| Helm hooks sent to the post-renderers | `spec.postRenderStrategy` | `nohooks` | `combined` |

Upgrades and rollbacks use `auto` with or without the gate: the apply method of the release's
previous install or upgrade (`spec.upgrade.serverSideApply`, `spec.rollback.serverSideApply`).

Styrmin had checked these parts with Helm v3 behaviour only:

- the operator's readiness, rollback and failure rules for a HelmRelease, which decide the task
  result and the steps a user views;
- the post-render patches for labels, scheduling settings, env vars, image overrides and container
  overrides, and the component-container guard;
- the operator's readiness timeout of 270 seconds, set below FluxCD's 5-minute HelmRelease timeout
  so that the failed step names the pods' reason before FluxCD rolls the release back.

## Decision

### 1. helm-controller runs without the gate, for every HelmRelease (plan D-001)

The agent chart (`helm/agent/templates/helm-controller/deployment.yaml`) and the integration fixture
copy run helm-controller without `--feature-gates=UseHelm3Defaults=true`. The operator keeps writing
none of `install.serverSideApply`, `upgrade.serverSideApply`, `rollback.serverSideApply`,
`waitStrategy` and `postRenderStrategy`, so FluxCD's defaults apply to every HelmRelease, including
internal deployments such as the ingress controller. Two unit tests pin this:
`test_helm_controller_runs_with_helm_v4_defaults` (`backend/tests/unit/test_helm_agent_crd_upgrade.py`)
and `test_minimal_helm_release_leaves_the_helm_v4_defaults_to_flux`
(`backend/tests/unit/agent/test_custom_resources.py`).

### 2. Releases keep their apply method; existing releases are not moved (R-003, R-004)

Upgrades and rollbacks keep `auto`. helm-controller resolves it from the newest stored revision's
`apply_method` (a rollback from its target revision). A release installed with the gate records
`csa`, or has no such field when Helm v3 wrote it, so it keeps client-side apply on every later
upgrade and rollback. A release installed without the gate records `ssa` and keeps server-side
apply. Styrmin does not set `spec.upgrade.serverSideApply: enabled` to move existing releases.

Removing the gate does not upgrade a release that is in sync, because the release digest has no
apply method, wait strategy or post-render strategy (R-003).

### 3. Helm hooks receive Styrmin's post-render patches (R-007)

With `combined`, Helm runs the post-renderers once on the hooks and the templates together, and
kustomize cannot tell them apart, so every patch whose target matches a Helm hook applies to it.
This is intended: a Helm hook `Job` gets the deployment's scheduling settings and Styrmin's labels,
as the chart's other `Job`s do. The driver guide
([Creating a driver](../../docs/docs/drivers/creating-a-driver.md), Step 1) lists which patches reach
which hooks.

### 4. No handling of server-side apply conflicts (R-002)

helm-controller always forces field ownership conflicts under server-side apply, with field manager
`helm-controller`, and no HelmRelease field turns this off. A field of a chart resource that
`kubectl`, a driver action or an autoscaler changed returns to the chart's value at the next
install, upgrade or rollback; the upgrade does not fail. A field the chart does not set stays as
the other field manager left it. Styrmin changes workloads only through post-render patches, so it
causes no such conflict itself. The driver guide states this for actions.

### 5. The every-resource label patch is a strategic merge (R-008, plan D-006)

The patch that adds Styrmin's labels to every resource (`Target(name=".*")` in
`build_target_for_label_patches`) was a JSON patch with one `add` per key under
`/metadata/labels/`. JSON patch `add` needs the parent to exist, so a resource without
`metadata.labels` failed the whole render with `add operation does not apply: doc is missing path`.
Under `combined`, a chart hook without labels would have failed every install and upgrade of that
driver. The patch is now `MetadataLabelsMergePatch`
(`agent/service/kubernetes/resources/blocks/patches.py`), a strategic merge that creates the map
when it is missing and keeps the labels a resource has. The per-component label patch and the pod
template label patch keep their JSON form, because they select resources by label or target pod
templates, which always have labels.

### 6. The operator's rules do not change (spec FR-002)

Local E2E runs with Helm v4 defaults produced the same CR status for every FluxCD state they reached
as the operator's rules give (e2e-evidence.md, "Operator rules under Helm v4 defaults"). No rule was
changed.

## Consequences

- Deployments created from this change are installed with server-side apply. In the E2E runs every
  new release record has `apply_method: ssa`, and the workloads' `metadata.managedFields` have
  manager `helm-controller` with operation `Apply` (e2e-evidence.md, runs 1 and 2).
- Deployments created before keep client-side apply. They use kstatus health checks and `combined`
  post-rendering from their next install or upgrade. The agent chart upgrade check found no new
  release revision and no pod restart after the chart upgrade, and the next change created release
  v2 with `apply_method: csa` and `managedFields` with `helm-controller` `Update`
  (agent-upgrade-check.md).
- Open point: that check used the same server and agent image before and after the chart upgrade.
  A real upgrade from an earlier release also replaces the agent image, whose label patch
  (decision 5) changes `spec.postRenderers` in each HelmRelease the operator writes. A
  post-renderers change makes helm-controller upgrade the release (agent-upgrade-check.md, step 5),
  and the release stays on client-side apply under `auto`. R-008 states that the operator writes the
  HelmRelease of an existing deployment again only for a new rollout or when it resumes a
  deployment that is not `Ready`. When this upgrade happens after an agent upgrade was not checked.
- The kstatus wait ends before the HelmRelease timeout when a resource is `Failed` for kstatus, for
  example a failed template `Job` or a `Deployment` past its `progressDeadlineSeconds` (R-005). A
  chart that sets `progressDeadlineSeconds` below 270 seconds gets FluxCD's
  `ProgressDeadlineExceeded` failure in the failed step instead of the pods' reason. A `Deployment`
  whose pods are in `ImagePullBackOff`, or whose container exits at once, stays `InProgress`, and
  FluxCD waited the full HelmRelease timeout in E2E (e2e-evidence.md, runs 1 and 2).
- FluxCD's message for an upgrade that reached the HelmRelease timeout now ends with kstatus's
  `timeout waiting for: [Deployment/<namespace>/<name> status: 'InProgress']`, and the failed
  HelmRelease step shows it. The operator does not parse this text.
- helm-controller v1.6.5 with Helm v4 defaults still reports FluxCD's rollback of a post-renderers
  change as `Ready=True` with reason `UpgradeSucceeded`. The operator's rollback rule answers it with
  `Ready=False`, reason `RolledBack` (e2e-evidence.md, run 1).
- Turning the gate on again leaves the releases installed in the meantime on server-side apply,
  because their newest revision records `ssa` and upgrades and rollbacks use `auto` (R-004). Only
  new installs go back to client-side apply.
- Rollback path for administrators: downgrade the agent chart to a release that runs helm-controller
  with the gate. Deployments created while the gate was off keep server-side apply, as above.
- The backup `TemplateAnnotationPatch` adds keys under `/spec/template/metadata/annotations/` with
  JSON patch `add`, so it fails on a `Deployment` or `StatefulSet` that matches a backup component
  and has no pod annotations. That was already true for templates; under `combined` it also applies
  to Helm hooks of those kinds. This change does not alter it (R-008).
- A Helm hook `Deployment` or `StatefulSet` of a third-party chart that matches a component but does
  not render its component container fails the install or upgrade with
  `COMPONENT_CONTAINER_NOT_FOUND` once an override applies to that component, as a template would.
- `Stalled` and the readiness timeout keep coverage by unit tests with recorded FluxCD states only;
  the E2E runs did not reach them (spec Clarifications).
- The E2E suite has a `hook-job` test driver, the `simple-app` chart with a pre-upgrade Helm hook
  `Job` and an unlabelled hook `ConfigMap` turned on, which `test_pod_scheduling.py` uses to check
  that both receive the patches (e2e-evidence.md, run 3).

## Alternatives Considered

- Drop the gate but set Helm v3's behaviour on each HelmRelease (`install.serverSideApply: false`,
  `waitStrategy.name: legacy`, `postRenderStrategy: nohooks`). Rejected: it keeps Helm v3 behaviour
  under another name, and #435 asks for Helm v4's behaviour (R-001).
- Exclude Helm hooks from Styrmin's patches with `annotationSelector: "!helm.sh/hook"` on the patch
  targets, which helm-controller passes to kustomize, or with `postRenderStrategy: nohooks` per
  HelmRelease. Rejected: a Helm hook `Job` would then run without the deployment's scheduling
  settings and could stay pending on a cluster where only the pinned nodes accept the deployment's
  pods (spec User Story 2), and the decision taken on #435 is that Helm hooks receive the patches
  (R-007).
- Move existing releases to server-side apply with `spec.upgrade.serverSideApply: enabled`.
  Rejected: the decision taken on #435 keeps each release's apply method, and the spec leaves the
  move out of scope.
- Keep the JSON label patch and require driver charts to label every Helm hook. Rejected: a
  third-party driver that works today would fail every install and upgrade after the agent upgrade
  (R-008).
- Ask FluxCD for an option to stop forcing server-side apply conflicts. Rejected: nothing in Styrmin
  needs it, and forcing avoids an upgrade that fails on a conflict (R-002).

## Out of Scope

The spec leaves these out; no decision was taken on them:

- an E2E test of the agent chart upgrade;
- the `separate` post-render strategy, which Helm 4.2 offers;
- using kstatus to improve readiness, for example for the ingress controller's LoadBalancer;
- E2E coverage of `Stalled` and of the readiness timeout.
