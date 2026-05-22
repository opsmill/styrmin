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
   ready when the application's pods are healthy.
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

### What this means in practice

- A `StyrminDeployment` is what Styrmin's operator acts on. If you're
  debugging Styrmin, that's the object to look at.
- A `HelmRelease` is what FluxCD acts on. If a chart fails to install,
  that's where the error message will be.
- "Drift correction" — the operator periodically re-checking the
  cluster — is the reason you can't just delete a pod to make Styrmin
  forget about it. It'll come back.

### Next

- [**Reconciliation**](./reconciliation.md) — how the server decides
  when to update the `StyrminDeployment`.
- [**Status reporting**](./status-reporting.md) — how the agent tells
  the server what the operator is seeing.
