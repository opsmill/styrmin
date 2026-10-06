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

The readiness timeout is the safety net when FluxCD never reports
`Stalled`. When a rollout has not reached `Ready` or `Failed` within
`STYRMIN_OPERATOR_DEPLOYMENT_READY_TIMEOUT` seconds (300 by default), the
operator sets the display state `Error` with the message "Deployment did
not reach Ready within" followed by the timeout and the phase. The phase
does not change, so the rollout can still become `Ready` later. The
timeout counts from `status.rolloutStartedAt`, or from the CR's creation
time when that field is missing. When the operator restarts and resumes a
rollout, it keeps the recorded start, so a restart does not extend the
timeout. When kopf runs the create or update handler again after a
temporary error, the handler records a new start.

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
with the message "FluxCD rolled the release back after release v<N>
failed" followed by the failure message when it recorded one, and the
`Ready` condition becomes `False` with the reason `RolledBack`. The
HelmRelease step and the task stay failed. A retry by FluxCD that
succeeds creates a newer release after the rollback, so the deployment
still reaches `Ready`.

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
