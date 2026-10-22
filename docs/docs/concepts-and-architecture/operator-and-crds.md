---
title: The operator and StyrminDeployment
sidebar_position: 4
description: What the agent's operator does inside the cluster, for readers without Kubernetes experience.
---

## The operator and `StyrminDeployment`

Styrmin uses two Kubernetes mechanisms that you see when you inspect a
cluster: **custom resources** and **operators**. You do not need to know
them to use Styrmin.

### Custom resources and operators

**Kubernetes** stores the objects that should exist, and controllers
create them. You apply a YAML file that declares a Deployment with three
pods, and the built-in Deployment controller creates the pods.

A **custom resource** is an object of a type that you define, not a
built-in Kubernetes type.

An **operator** is the controller for a custom resource type. It watches
the objects of that type and changes the cluster to match them.

### The `StyrminDeployment` resource

Styrmin defines one custom resource type, **`StyrminDeployment`**. The
cluster has one `StyrminDeployment` object for each deployment that you
create in Styrmin.

A `StyrminDeployment` contains:

- the driver and the driver version that the deployment uses;
- the application version it runs;
- the fully resolved **context**: every value that the driver needs to
  render its Helm chart (see [The context](../drivers/context.md) for the
  full structure);
- the lifecycle phase it should be in (running, stopped, deleting).

It describes the deployment in a form that Kubernetes can read.

### What the operator does with it

The operator runs inside the agent (see [Architecture](./architecture.md)).
It watches every `StyrminDeployment` in the cluster and runs these
phases:

1. **Render**: turn the context into Kubernetes resources: a
   `HelmRelease` for the application's chart, services, network policies,
   and secrets.
2. **Apply**: write those resources into the cluster. The built-in
   Kubernetes controllers, and FluxCD for the `HelmRelease`, then create
   the objects they describe.
3. **Wait**: wait until the resources are ready. Mark the
   `StyrminDeployment` as ready when FluxCD reports the new release ready,
   or as failed when FluxCD stops retrying (see
   [When a rollout is ready or failed](#when-a-rollout-is-ready-or-failed)).
4. **Check periodically**: compare the cluster with the declared state
   again. When something differs (a pod was deleted, a ConfigMap was
   edited), restore it.

When the `StyrminDeployment` changes, because the server recorded a
change to the deployment (see [Reconciliation](./reconciliation.md)), the
operator runs the phases again.

### Why Styrmin uses a custom resource

The server does not call the Kubernetes API to deploy an application. It
goes through a custom resource, for two reasons:

- **The cluster stores the desired state.** When the agent restarts, or
  the server stops, the `StyrminDeployment` stays in the cluster. The
  operator continues from it.
- **Kubernetes tools can read it.** `kubectl`, GitOps tools, and
  monitoring tools that read custom resources show Styrmin deployments
  without a Styrmin integration.

<!-- Keeps the anchor that earlier releases of CHANGELOG.md link to. -->
<a id="the-helmrelease--styrmins-other-crd"></a>

### The HelmRelease

Each deployment also has a second custom resource, a **`HelmRelease`**.
Its type comes from [FluxCD](https://fluxcd.io/), an open-source toolkit
that the agent chart installs, not from Styrmin.

A `HelmRelease` declares a Helm chart, its version, and its values.
FluxCD's operator, the **helm-controller**, watches `HelmRelease` objects
and runs `helm install` and `helm upgrade` for them. Styrmin does not run
Helm itself.

The agent chart installs FluxCD's helm-controller v1.6.5 and
source-controller v1.9.6, the controllers of Flux v2.9.6. They support
Kubernetes 1.34.1 and later. helm-controller runs with the defaults of
Helm v4:

- A deployment created since the agent runs helm-controller with these
  defaults is installed with server-side apply. helm-controller is the
  field manager and forces field ownership conflicts, so at each upgrade
  a field that the chart sets returns to the chart's value, even when
  `kubectl` or a driver action changed it. The upgrade does not fail.
- A deployment created before, when helm-controller ran with the
  `UseHelm3Defaults` feature gate, keeps client-side apply: an upgrade uses
  the apply method recorded in the release's newest revision, and a
  rollback uses the method of the revision it returns to. From its next
  upgrade, the two items below apply to it too.
- Installs and upgrades wait for the chart's resources with kstatus,
  FluxCD's library that computes the status of each Kubernetes resource.
  The wait ends before the HelmRelease timeout when kstatus reports a
  resource as failed, for example a `Job` that failed or a `Deployment`
  past its `progressDeadlineSeconds`. A `Deployment` whose pods cannot
  pull their image, or whose container exits immediately, is not failed for
  kstatus, so FluxCD waits the full timeout.
- Helm hooks of the driver's chart, the resources annotated
  `helm.sh/hook`, receive Styrmin's post-render patches, as the chart's
  other resources do: Styrmin's labels, the deployment's scheduling
  settings and, on a `Deployment` or `StatefulSet` that matches a
  component, the component overrides. See
  [Step 1 of Create a driver](../drivers/creating-a-driver.md#step-1-analyze-the-helm-chart)
  for which patches reach which hooks.

To go back to Helm v3's behavior, downgrade the agent chart to a
release that runs helm-controller with the `UseHelm3Defaults` gate.
Deployments created while the gate was off keep server-side apply on
their later upgrades and rollbacks, because they keep the apply method
of their previous release.

Helm installs the CRDs in a chart's `crds/` directory only when they do
not exist yet, and never updates them. The agent chart therefore applies
its CRDs (FluxCD's, kopf's and the `StyrminDeployment` CRD) in a Job
before each `helm install` and `helm upgrade`. When a new CRD no longer
lists a version that the cluster stored objects in, the Job deletes and
creates that CRD again if it has no objects, and fails the install or
upgrade if it has some. To apply the CRDs yourself, set
`styrmin-agent.crdUpgrade.enabled` to `false` and apply the files of
`helm/agent/crds/` before each upgrade.

Inside the cluster, the work passes through these components:

```text
StyrminDeployment  ──►  Styrmin operator  ──►  HelmRelease  ──►  FluxCD helm-controller  ──►  Helm install / upgrade
   (Styrmin CRD)        (in the agent)         (FluxCD CRD)      (separate pod)
```

Each operator handles different work:

- **Styrmin's operator** handles the driver, the version, the resolved
  context, the ingress of the environment, and when to run lifecycle
  actions.
- **FluxCD's helm-controller** handles Helm: it renders the chart,
  templates the values, orders the install and upgrade steps, and rolls
  back a failed release.

To list both:

```shell
kubectl get styrmindeployments -A
kubectl get helmreleases -A
```

In short, FluxCD creates the application's resources from the
`HelmRelease`, and Styrmin creates and updates the `HelmRelease` from your
deployment.

### When a rollout is ready or failed

Each time the operator starts a rollout, for a new `StyrminDeployment` or
a changed spec, it:

- sets the `HelmReleaseReady` condition to `Unknown` with the reason
  `Progressing`, so that the `True` value of the previous rollout does not
  count for the new one;
- removes the `HelmReleaseRemediated` condition of the previous rollout;
- records the start of the rollout in `status.rolloutStartedAt`;
- writes the application instance it is rolling out to
  `status.instanceId`, even when the handler fails. The status reporter
  sends this value to the server (see
  [Status reporting](./status-reporting.md#which-instance-a-report-is-about)).

While the phase is `CreatingHelmRelease`, the operator reads the
HelmRelease once per timer run (every 60 seconds by default). It uses only
FluxCD's conditions for the HelmRelease's current generation: a condition
counts when its `observedGeneration`, or the HelmRelease's
`status.lastAttemptedGeneration` when the condition has none, equals the
HelmRelease's `metadata.generation`. A `Ready=True` left from the previous
release therefore does not make the new release ready.

- When FluxCD reports the current generation `Ready=True`, the operator
  sets `HelmReleaseReady` to `True` with the reason `FluxReady`, creates
  the services and moves the `StyrminDeployment` to `Ready`.
- Until then, `HelmReleaseReady` copies the status and transition time of
  FluxCD's `Ready` condition. When `Ready` is `False`, the reason and
  message come from FluxCD's `Released=False` condition when there is one,
  which names the failed install or upgrade, and from `Ready` otherwise.
- When FluxCD's `Remediated` condition is `True` for the current
  generation, FluxCD has rolled back or uninstalled the failed release.
  The operator copies that condition into `HelmReleaseRemediated`. This is
  not a final failure: Styrmin's HelmReleases allow FluxCD 3 retries for
  an install or an upgrade, and a later attempt can succeed.
- When FluxCD's `Stalled` condition is `True` for the current generation,
  FluxCD has used all its retries. The operator sets the phase `Failed`
  and the display state `Error`. The message of the `StyrminDeployment` is the message of
  FluxCD's `Stalled` condition followed by the failure message, in the
  form `<Stalled message>: <failure message>`. The `Ready` condition
  becomes `False` with the reason of FluxCD's `Stalled` condition, for
  example `RetriesExceeded`.

The operator writes a condition only when its content changed. An internal
deployment, such as the per-environment ingress controller, also counts as
ready as soon as one of its pods is ready, even when FluxCD reports
`Stalled`.

Styrmin's HelmReleases give FluxCD
`STYRMIN_OPERATOR_HELM_RELEASE_TIMEOUT` seconds (300, that is 5 minutes,
by default) for each install or upgrade. At that timeout FluxCD fails the
attempt and rolls the release back, which removes its pods.

The readiness timeout applies when FluxCD never reports `Stalled`. When a rollout has not reached `Ready` or `Failed` within
`STYRMIN_OPERATOR_DEPLOYMENT_READY_TIMEOUT` seconds (270 by default), the
operator sets the display state `Error` with the message "Deployment did
not reach Ready within" followed by the timeout and the phase. The phase
does not change, so the rollout can still become `Ready` later. Keep the
readiness timeout below the HelmRelease timeout, as the defaults are: a
failed rollout then reports the pods that are not ready and why before
FluxCD's rollback removes them. This holds while FluxCD waits the full
HelmRelease timeout, which it does for pods that cannot pull their image
(see the kstatus item in
[The HelmRelease](#the-helmrelease)). The
timeout counts from `status.rolloutStartedAt`, or from the creation time of the
`StyrminDeployment` when that field is missing. When the operator restarts and resumes a
rollout, it keeps the recorded start, so a restart does not extend the
timeout. When a step of the rollout fails with a temporary error, for
example when the operator cannot create a network policy, kopf runs the
create or update handler again `STYRMIN_OPERATOR_RETRY_DELAY` seconds
(30 by default) later, and the handler records a new start.

FluxCD can also report the release `Ready` after it rolled back the
failed upgrade. This happens when a change only adds or changes
post-render overrides, such as an [image override](./image-overrides.md)
or environment variables: after the rollback, FluxCD compares only the
chart and the values with the HelmRelease, finds the rolled-back release
in sync, and reports it as a successful upgrade, although the override
was never applied. The operator recognizes this state from FluxCD's
release history: FluxCD counted a failed install or upgrade for the
current generation of the HelmRelease, and the newest release is
`deployed` right after a `failed` one, so it is the rollback. The
operator then sets the phase `Failed` and the display state `Error`,
with the message
`FluxCD rolled the release back after release v<N> failed` followed by
the failure message when it recorded one, and the
`Ready` condition becomes `False` with the reason `RolledBack`. The
HelmRelease step and the task stay failed. A retry by FluxCD that
succeeds creates a newer release after the rollback, so the deployment
still reaches `Ready`.

FluxCD can also report a change in sync after it failed to apply it.
When an install or upgrade fails before Helm stores a release, for
example because a post-render patch fails, helm-controller v1.6.5 still
records the new post-renderers as applied. On its next run it compares
only the chart and the values, reports the previous release `Ready`, and
does not try again. The operator recognizes this state: FluxCD counted a
failure for the current generation of the HelmRelease
(`status.failures`), and FluxCD's newest `InstallFailed` or
`UpgradeFailed` event of the HelmRelease is newer than its newest
release. The operator then sets the phase `Failed` and the display state
`Error`. When the event names a component container that the chart does
not render, the message is the `COMPONENT_CONTAINER_NOT_FOUND` message
(see [Image overrides](./image-overrides.md)). Otherwise it is
`FluxCD reported the release in sync after the change failed:` followed
by FluxCD's message, and the `Ready` condition becomes `False` with the
reason of the event.

### A `StyrminDeployment` that keeps its finalizer

The agents of Styrmin v0.1.48 and earlier can keep the
`styrmin.io/kopf-finalizer` finalizer of a `StyrminDeployment` that is
being deleted ([#446](https://github.com/opsmill/styrmin/issues/446),
[#461](https://github.com/opsmill/styrmin/issues/461)). This happens
when the deployment's namespace is deleted while the operator's timer
is checking that `StyrminDeployment`. Kubernetes does not delete the
namespace while the custom resource in it keeps a finalizer, so the
namespace stays `Terminating`.

You see one of these symptoms:

- A restore fails in its "Delete the namespace" step with
  `Namespace <namespace> was not deleted within 600s`.
- An application deployment stays `DELETING`.
- A dedicated ingress controller stays `DELETING`. See
  [A controller that stays `DELETING`](./ingress-and-networking.md#a-controller-that-stays-deleting)
  for the steps that follow the recovery.

To read the version of the agent that runs on a cluster, list the image
of the agent pod. The image tag is the Styrmin version:

```bash
kubectl get pods -A -l app.kubernetes.io/name=styrmin-agent \
  -o jsonpath='{range .items[*]}{.spec.containers[0].image}{"\n"}{end}'
```

#### Check whether the finalizer or slow pods block the namespace

A namespace also stays `Terminating` while its pods stop, and a pod can
need longer than 600 seconds. The
[Neo4j Helm chart](https://github.com/neo4j/helm-charts/blob/dev/neo4j/values.yaml),
for example, gives the Neo4j pod up to 3600 seconds to stop. List the
pods and the finalizers of the `StyrminDeployment` in the namespace:

```bash
kubectl get pods -n <namespace>
kubectl get styrmindeployments -n <namespace> \
  -o jsonpath='{range .items[*]}{.metadata.name}{": "}{.metadata.finalizers}{"\n"}{end}'
```

- No pods are left, and the `StyrminDeployment` still lists
  `styrmin.io/kopf-finalizer`: the operator kept the finalizer. Follow
  the recovery steps below.
- Pods are still `Terminating`: Kubernetes deletes the namespace once
  they stop.

In both cases, a restore that failed with `Namespace <namespace> was not
deleted within 600s` does not continue. Start it again after the
namespace is deleted.

#### Remove the finalizer

- Upgrade the agent to a Styrmin release later than v0.1.48. When the
  new agent starts, it removes the finalizer that the earlier agent
  kept, and Kubernetes finishes deleting the namespace. You do not need
  to add an annotation.
- Until you upgrade, add any annotation to the `StyrminDeployment`. The
  operator then checks the custom resource again and removes the
  finalizer:

  ```bash
  kubectl annotate styrmindeployments.styrmin.io <name> -n <namespace> \
    styrmin.io/retry-delete="$(date +%s)" --overwrite
  ```

#### When an agent later than v0.1.48 keeps the finalizer

The agent keeps the finalizer only until the timer's current check of
the `StyrminDeployment` ends, which normally takes a few seconds. The
agent log then shows this line once:

```text
StyrminDeployment <namespace>/<name> keeps its finalizer until its timer run ends
```

If the finalizer stays for more than a few minutes, the timer's check
does not end, for example because a request to the Kubernetes API does
not return. Restart the agent: the new agent removes the finalizer when
it starts. Restarting the agent also stops the tasks it runs at that
moment, such as a backup or a restore. Then open an
[issue](https://github.com/opsmill/styrmin/issues) and attach the agent
log.

### What this means in practice

- Styrmin's operator reconciles `StyrminDeployment` objects. To debug a
  deployment, start with its `StyrminDeployment`.
- FluxCD reconciles `HelmRelease` objects. If a chart fails to install,
  FluxCD's reason is copied into the `StyrminDeployment`'s
  `HelmReleaseReady` condition, and the deployment page shows it on the
  step "Install or upgrade the HelmRelease".
- Because the operator checks the cluster periodically, a pod that you
  delete is created again.

### Next steps

- [**Reconciliation**](./reconciliation.md): when the server updates the
  `StyrminDeployment`.
- [**Status reporting**](./status-reporting.md): how the agent reports
  the cluster state to the server.
