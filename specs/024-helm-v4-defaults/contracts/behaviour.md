# Behaviour Contracts: helm-controller Runs with Helm v4 Defaults

Styrmin's GraphQL API, SDK, CLI and frontend do not change (spec FR-012). The contracts below are the observable behaviours that tests pin.

## C-001: helm-controller arguments (agent chart and integration fixture)

`helm template` of `helm/agent` renders the helm-controller Deployment with these container arguments, in this order, and no other:

```yaml
args:
  - --watch-all-namespaces
  - --log-level=info
  - --log-encoding=json
  - --enable-leader-election
```

- No argument contains `UseHelm3Defaults`, and no `--feature-gates` argument is set.
- `backend/tests/integration/fixtures/templates/helm-controller/deployment.yaml` has the same `image` and `args` (existing test `test_fixture_controllers_run_the_chart_images`).

## C-002: HelmRelease spec written by the operator

Every HelmRelease built from `build_minimal_helm_release()` renders `spec.install` and `spec.upgrade` as `{"remediation": {"retries": 3}}` only. The rendered `spec` has no `waitStrategy`, `postRenderStrategy` or `rollback` key, and neither `install` nor `upgrade` has `serverSideApply`.

## C-003: Outcomes the operator reports (unchanged)

For each FluxCD state in the "What the timer writes in `CreatingHelmRelease`" table of [`dev/knowledge/agent/operator.md`](../../../dev/knowledge/agent/operator.md), the StyrminDeployment CR gets the same phase, `displayState`, conditions and message as before the change. Users view, per task:

| Change | Failed step | Reason or message |
| --- | --- | --- |
| Image that cannot be pulled, FluxCD rolls back | "Install or upgrade the HelmRelease" | `RolledBack`, `HelmReleaseRemediated`, and the pods' `ImagePullBackOff` or `ErrImagePull` |
| Image override on a missing component container | "Install or upgrade the HelmRelease" | `COMPONENT_CONTAINER_NOT_FOUND`, naming the component and the container |
| FluxCD uses all retries | "Install or upgrade the HelmRelease" | `Stalled` reason, for example `RetriesExceeded` |
| Readiness timeout | "Install or upgrade the HelmRelease" | "Deployment did not reach Ready within 270s (phase: …)" |

## C-004: Helm hook Job of a deployment's chart

Given a driver whose chart renders a `Job` annotated `helm.sh/hook` that carries a component's identifier label in `metadata.labels`, and a deployment whose scheduling sets tolerations and node affinity:

- the Job's `metadata.labels` include Styrmin's labels and the `component` label;
- the Job's `spec.template.spec` has the deployment's tolerations, node affinity, pod affinity, topology spread constraints, runtime class and the first container's resources, as the chart's other Jobs do;
- env var, image and container overrides, and the component-container guard, do not apply to it, because they target `Deployment` and `StatefulSet` only.

## C-004a: Styrmin labels on a resource without labels

`kubectl kustomize` with the post-renderers of a deployment, run on a stream holding a labelled `Deployment`, a `ConfigMap` without `metadata.labels` and a hook `Job` without `metadata.labels`, succeeds. All three carry Styrmin's labels, and the `Deployment` keeps its own labels (FR-013).

## C-005: `simple-app` chart value `preUpgradeHookJob.enabled`

- `false` (default): `helm template` renders no resource annotated `helm.sh/hook` other than the existing ones (none in the simple-app chart today).
- `true`: `helm template` renders exactly one extra Job, annotated `helm.sh/hook: pre-upgrade` and `helm.sh/hook-delete-policy: before-hook-creation`, labelled `app.kubernetes.io/name: <simple-app.name>` in `metadata.labels` and not in its pod template labels.

## C-006: Agent chart upgrade

Upgrading the agent chart from a version with the gate creates no new Helm release revision for an unchanged HelmRelease, and the next upgrade of a release installed with the gate keeps client-side apply (`apply_method: csa` or unset). Checked manually ([quickstart.md](../quickstart.md) §4) and backed by the source evidence in [research.md](../research.md) R-003.
