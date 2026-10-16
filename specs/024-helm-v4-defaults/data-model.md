# Data Model: helm-controller Runs with Helm v4 Defaults

No database table, column, GraphQL type, SDK model or context model changes (spec FR-012). This page lists the Kubernetes objects whose content or treatment changes, and the one test chart value that is added.

## HelmRelease (FluxCD, existing)

Built by `build_minimal_helm_release()` in [`builders/base.py`](../../backend/styrmin_backend/agent/service/kubernetes/resources/builders/base.py) for every HelmRelease the operator writes, including internal deployments such as the ingress controller.

| Field | Written by Styrmin | Before (gate on) | After (gate off) |
| --- | --- | --- | --- |
| `spec.install.remediation.retries` | yes, `3` | unchanged | unchanged |
| `spec.upgrade.remediation.retries` | yes, `3` | unchanged | unchanged |
| `spec.install.serverSideApply` | no | defaults to `false` | defaults to `true` |
| `spec.upgrade.serverSideApply`, `spec.rollback.serverSideApply` | no | defaults to `auto` | defaults to `auto` |
| `spec.waitStrategy` | no | defaults to `legacy` | defaults to `poller` (kstatus) |
| `spec.postRenderStrategy` | no | defaults to `nohooks` | defaults to `combined` |
| `spec.postRenderers` | yes | applied to templates only | applied to templates and Helm hooks |

Validation rule (FR-001): the rendered spec never contains `serverSideApply`, `waitStrategy` or `postRenderStrategy`. A unit test pins this.

## Helm release record (Helm storage, existing)

A Secret of type `helm.sh/release.v1` per release revision, labelled `owner=helm`, holding `base64(gzip(release JSON))` under `data.release` ([`restore_recovery.py`](../../backend/styrmin_backend/operator/restore_recovery.py)). The restore and clone path rewrites these Secrets and keeps every field of the JSON record, so a field Helm v4 adds (see [research.md](research.md) R-004) passes through unchanged.

State relevant to this feature: the apply method that `auto` reads for the next upgrade or rollback. A release written with the gate on records client-side apply (or no method, which Helm reads as client-side apply); a release installed with the gate off records server-side apply.

## Helm hook (glossary entry, not a Styrmin entity)

A chart resource annotated `helm.sh/hook`, created by Helm at a set point of an install, upgrade, rollback, uninstall or test. After this change, every post-render patch whose target matches a Helm hook applies to it:

| Patch | Target | Reaches a Helm hook when |
| --- | --- | --- |
| Styrmin labels (strategic merge on `metadata.labels`, D-006; a JSON-patch `LabelPatch` before) | every name (`.*`) | always, including resources without `metadata.labels` |
| Component label (`LabelPatch`) | the component's identifier label selector | the hook carries the component's identifier label |
| Pod template labels and annotations (`TemplateLabelPatch`, backup `TemplateAnnotationPatch`) | `Deployment`, `StatefulSet` | the hook is a `Deployment` or `StatefulSet` (and matches the selector, for component and backup patches) |
| Scheduling (affinity, resources, tolerations, topology spread, node affinity, runtime class) | `Deployment`, `StatefulSet`, `DaemonSet`, `Job`, `CronJob`, `ReplicaSet`, narrowed by the component's identifier label selector when the driver declares components | the hook has one of these kinds and, for a driver with components, carries a component's identifier label |
| Stopped component (`replicas: 0`) | `Deployment`, `StatefulSet` with the component's selector | the hook is a matching `Deployment` or `StatefulSet` |
| Env var, image and container overrides, and the component-container guard | `Deployment`, `StatefulSet` with the component's selector | the hook is a matching `Deployment` or `StatefulSet` |

## `simple-app` test chart value (new)

In [`driver/examples/simple-app/src/helm/values.yaml`](../../driver/examples/simple-app/src/helm/values.yaml):

| Value | Type | Default | Effect |
| --- | --- | --- | --- |
| `preUpgradeHookJob.enabled` | boolean | `false` | Renders one `batch/v1` Job annotated `helm.sh/hook: pre-upgrade` and `helm.sh/hook-delete-policy: before-hook-creation`. The Job's `metadata.labels` carry the server component's identifier label (`app.kubernetes.io/name: simple-app`); its pod template does not, so the simple-app Service and pod affinity rules do not select the hook's pod. The container runs the chart's image and exits 0. |

The value is turned on only by the `hook-job` E2E test driver (see [plan.md](plan.md)). `driver/examples/simple-app/values.j2.yml` does not set it, so the 22 E2E test files that deploy `simple-app` render no Helm hook.
