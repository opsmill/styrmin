---
title: The operator and StyrminDeployment
sidebar_position: 4
description: What the agent's operator does inside the cluster — explained without Kubernetes background.
---

## The operator and `StyrminDeployment`

This page explains two pieces of Kubernetes vocabulary you don't have to
know to use Styrmin, but that show up everywhere once you start poking
around: **custom resources** and **operators**.

### A 60-second primer

**Kubernetes**, deep down, is a database of "things that should exist"
plus a bunch of programs that make those things exist. You write a YAML
file that says "I want a Deployment with three pods", you hand it to the
cluster, and a built-in program (the Deployment controller) makes it
happen.

A **custom resource** is just a new kind of "thing that should exist",
defined by you instead of by Kubernetes. It's a way of teaching the
cluster a new vocabulary word.

An **operator** is the matching program — the one that watches for
changes to that custom resource and reacts.

You write the custom resource. The operator does whatever you wrote
needs doing. That's it.

### What Styrmin adds

Styrmin defines one custom resource type, called **`StyrminDeployment`**.
There is one `StyrminDeployment` object in the cluster for every
deployment you create in Styrmin.

Inside the `StyrminDeployment` you'll find:

- which driver and version this deployment uses;
- which application version it's running;
- the fully resolved **configuration context** — every value the driver
  needs to render its Helm chart (see
  [The Context](../drivers/context.md) for the full structure);
- the lifecycle phase it should be in (running, stopped, deleting).

Think of it as "the deployment, in a form Kubernetes can read".

### What the operator does with it

The operator (which lives inside the agent — see
[Architecture](./architecture.md)) watches every `StyrminDeployment` in
the cluster and works through a small set of phases:

1. **Render** — turn the configuration context into actual Kubernetes
   resources: a HelmRelease (for the application's chart), services,
   network policies, secrets.
2. **Apply** — write those resources into the cluster. Kubernetes's
   built-in controllers (and FluxCD, for the HelmRelease) take it from
   there.
3. **Wait** — let everything come up. Mark the `StyrminDeployment` as
   ready when FluxCD reports the new release ready, or as failed when
   FluxCD gives up (see
   [When a rollout is ready or failed](#when-a-rollout-is-ready-or-failed)).
4. **Re-check periodically** — every so often, look at the cluster
   again. If something drifted from what was declared (a pod was
   deleted, a ConfigMap was edited), put it back.

If you update the `StyrminDeployment` (because the server detected a
change in the deployment — see [Reconciliation](./reconciliation.md)),
the operator notices and re-runs the phases.

### Why this design?

Going through a custom resource may look indirect — why not have the
server just talk to Kubernetes? Two reasons:

- **The desired state lives in the cluster.** If the agent restarts, or
  even the server goes down, the `StyrminDeployment` is still there. The
  operator picks up where it left off.
- **It composes with Kubernetes.** Tools that already understand
  custom resources (kubectl, GitOps engines, monitoring) can see Styrmin
  deployments without any special integration.

### The HelmRelease — Styrmin's other CRD

You'll also see a second custom resource per deployment, called
**`HelmRelease`**. That one is not Styrmin's — it comes from
[FluxCD](https://fluxcd.io/), an open-source toolkit that ships with
Styrmin.

A `HelmRelease` is FluxCD's way of saying "install this Helm chart, at
this version, with these values, and keep it that way." FluxCD's own
operator (the **helm-controller**) watches `HelmRelease` objects and
does the actual `helm install` / `helm upgrade` work. Styrmin doesn't
run Helm itself — it asks Flux to do it.

The agent chart installs FluxCD's helm-controller v1.6.5 and
source-controller v1.9.6, the controllers of Flux v2.9.6. They support
Kubernetes 1.34.1 and later. helm-controller runs with the
`UseHelm3Defaults` feature gate, so it installs and upgrades releases
with Helm v3's client-side apply and health checks.

Helm installs the CRDs in a chart's `crds/` directory only when they do
not exist yet, and never updates them. The agent chart therefore applies
its CRDs (FluxCD's, kopf's and the `StyrminDeployment` CRD) in a Job
before each `helm install` and `helm upgrade`. When a new CRD no longer
lists a version that the cluster stored objects in, the Job deletes and
creates that CRD again if it has no objects, and fails the install or
upgrade if it has some. To apply the CRDs yourself, set
`styrmin-agent.crdUpgrade.enabled` to `false` and apply the files of
`helm/agent/crds/` before each upgrade.

So the chain inside the cluster is:

```text
StyrminDeployment  ──►  Styrmin operator  ──►  HelmRelease  ──►  FluxCD helm-controller  ──►  Helm install / upgrade
   (Styrmin CRD)        (in the agent)         (FluxCD CRD)      (separate pod)
```

Why split it? Two operators, two clear jobs:

- **Styrmin's operator** owns the application-shaped concerns: which
  driver, which version, what the resolved context says, what the
  per-environment ingress looks like, when to run lifecycle actions.
- **FluxCD's helm-controller** owns the Helm-shaped concerns: chart
  rendering, install/upgrade ordering, value templating, rollback on
  failure.

Both halves are visible if you go looking:

```shell
kubectl get styrmindeployments -A
kubectl get helmreleases -A
```

For day-to-day use you only need to know that the `HelmRelease` is what
actually puts the application's resources into the cluster, and that
it's created and updated by Styrmin in response to your deployment.

### When a rollout is ready or failed

Each time the operator starts a rollout, for a new `StyrminDeployment` or
a changed spec, it:

- sets the `HelmReleaseReady` condition to `Unknown` with the reason
  `Progressing`, so that the `True` value of the previous rollout does not
  count for the new one;
- removes the `HelmReleaseRemediated` condition of the previous rollout;
- records the start of the rollout in `status.rolloutStartedAt`;
- writes the application instance it is rolling out to
  `status.instanceId`, also when the handler fails. The status reporter
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
  the services and moves the CR to `Ready`.
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
  and the display state `Error`. The CR's message is the message of
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

The readiness timeout is the safety net when FluxCD never reports
`Stalled`. When a rollout has not reached `Ready` or `Failed` within
`STYRMIN_OPERATOR_DEPLOYMENT_READY_TIMEOUT` seconds (270 by default), the
operator sets the display state `Error` with the message "Deployment did
not reach Ready within" followed by the timeout and the phase. The phase
does not change, so the rollout can still become `Ready` later. Keep the
readiness timeout below the HelmRelease timeout, as the defaults are: a
failed rollout then reports the pods that are not ready and why before
FluxCD's rollback removes them. The
timeout counts from `status.rolloutStartedAt`, or from the CR's creation
time when that field is missing. When the operator restarts and resumes a
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
was never applied. The operator recognises this state from FluxCD's
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
does not try again. The operator recognises this state: FluxCD counted a
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

#### Tell the finalizer apart from pods that take long to stop

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
  they have stopped.

In both cases, a restore that failed with `Namespace <namespace> was not
deleted within 600s` does not continue. Start it again once the
namespace is gone.

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

- A `StyrminDeployment` is what Styrmin's operator acts on. If you're
  debugging Styrmin, that's the object to look at.
- A `HelmRelease` is what FluxCD acts on. If a chart fails to install,
  FluxCD's reason is copied into the `StyrminDeployment`'s
  `HelmReleaseReady` condition, and the deployment page shows it on the
  step "Install or upgrade the HelmRelease".
- "Drift correction" — the operator periodically re-checking the
  cluster — is the reason you can't just delete a pod to make Styrmin
  forget about it. It'll come back.

### Next

- [**Reconciliation**](./reconciliation.md) — how the server decides
  when to update the `StyrminDeployment`.
- [**Status reporting**](./status-reporting.md) — how the agent tells
  the server what the operator is seeing.
