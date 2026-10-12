---
title: Reconciliation
sidebar_position: 3
description: How Styrmin closes the gap between what you asked for and what's actually running.
---

## Reconciliation

Styrmin is a **declarative** system. You say "I want Infrahub 1.6.0
running in this environment with these settings", and Styrmin makes it
happen. You don't tell it to install a chart, then run a migration, then
restart a worker — that's its job.

The way it lives up to that promise is **reconciliation**: a loop that
compares what you asked for against what's actually running, figures out
the difference, and closes the gap.

### Two states, one loop

There are always two states in play:

- **Desired state** — what you wrote down. The `Deployment` row in the
  database, plus everything it pins (driver version, application
  version, configuration).
- **Current state** — what's actually running. Held as the **active
  Application Instance**: a frozen snapshot of what was last deployed,
  with its full resolved configuration.

Reconciliation is what happens between them:

```text
            ┌────────────────────┐
            │     Deployment     │   ← you edit this
            │   (desired state)  │
            └─────────┬──────────┘
                      │
                      │ generate a new Instance
                      ▼
            ┌────────────────────┐
            │    New Instance    │
            │  (desired snapshot)│
            └─────────┬──────────┘
                      │
                      │  compare against
                      ▼
            ┌────────────────────┐
            │  Active Instance   │   ← what's running now
            │  (current state)   │
            └─────────┬──────────┘
                      │
                      │ produce a plan
                      ▼
            ┌────────────────────┐
            │   Remediation      │  → create / update / upgrade flow
            │     (the plan)     │
            └────────────────────┘
```

### Step by step

1. **You change something** — edit a deployment, change a parameter,
   pick a new driver version. The server writes the change to the
   database. Version upgrades also re-resolve which driver version the
   deployment binds to: unless you pin one explicitly, the latest loaded
   driver version supporting the requested application version wins
   (deterministically — see
   [Selecting a driver version](../drivers/loading-drivers.md#selecting-a-driver-version-when-deploying-or-upgrading)),
   so re-running an upgrade at the same application version moves the
   deployment onto a newly loaded driver build.
2. **The server generates a new Instance** from the updated deployment.
   This is a frozen snapshot of what _would_ be running if the change
   took effect: the resolved configuration, the driver version, the
   chart values, everything.
3. **The server compares** the new Instance against the active Instance
   (the one currently running) and produces a **diff** — a small
   structured description of what's changed.
4. **The server decides what to do** based on the diff. Different kinds
   of change trigger different workflows: a config tweak is an update,
   a driver version change is an upgrade, a brand-new deployment is a
   create.
5. **The agent runs the chosen workflow** through Prefect. The driver's
   actions (start/stop components, run migrations, etc.) execute in the
   order the driver declares.
6. **The new Instance becomes the active Instance** once the work
   succeeds. The next change starts from there.

### When an environment or cluster config changes

A deployment takes every value that it does not set itself from its
environment's config, and every value that neither sets from the
cluster's config. A change to an environment or cluster config therefore
starts a reconciliation of each deployment that it affects. These
redeploys are called a config fan-out, and there are two:

- The environment config fan-out. After you update an environment's
  config, Styrmin redeploys each deployment of the environment that is
  not yet at the new environment config.
- The cluster config fan-out. After you update the cluster's config
  with `styrminctl clusters update`, the SDK, the API or the cluster
  detail page, Styrmin redeploys each deployment, in every environment
  of the cluster, whose resolved config differs from the config of its
  active Instance. The resolved config is the cluster config, then the
  environment config, then the deployment config, where the deepest
  value wins. So a deployment in an environment that sets the changed
  value itself is not redeployed. When `dedicated_ingress` changes, the
  redeploys are ordered around each environment's ingress controller;
  see
  [Changing the dedicated ingress on the cluster](./ingress-and-networking.md#changing-the-dedicated-ingress-on-the-cluster).

Both fan-outs redeploy each deployment at its current application
version and driver version, through the steps above. Both skip deleted
deployments and deployments with a restore in progress, and the cluster
config fan-out also skips deployments that are being deleted. Neither
redeploys an internal deployment, such as an ingress controller, as an
application; the cluster config fan-out handles ingress controllers by
their own rules, which the ingress page describes. A redeploy that cannot be
started does not stop the others. Because each deployment is compared on
its own, submitting the same config again redeploys only the deployments
that are not yet at it, which also recovers a redeploy that could not be
started.

### Several changes in quick succession

Each change to a deployment starts its own workflow, whether you make it
on the deployment page, with `styrminctl` or through the API. When you
make changes one after another, their workflows can still run at the
same time and reach the cluster in any order.

Styrmin numbers the Instances of each deployment in the order it saves
them, and the `StyrminDeployment` records the number of the Instance it
holds, in the `styrmin.io/instance-sequence` annotation. A workflow
leaves a `StyrminDeployment` that holds a higher number unchanged. For
changes made one after another, the deployment therefore runs the
configuration of the last change, in whatever order the workflows
finish.

What you view for the earlier change:

- Its task ends as `superseded` on the deployment page and in
  `styrminctl tasks get`.
- When its workflow left the `StyrminDeployment` unchanged, its "Write
  the StyrminDeployment resource" step shows the reason under "Show
  output", and `kubectl describe styrmindeployment` shows a
  `NewerInstanceKept` event.
- Its workflow still runs the driver actions of that change, such as
  its setup or upgrade hooks. See
  [Hooks of an earlier change](hooks-and-actions.md#hooks-of-an-earlier-change).

#### Changes made at the same time

When two changes to the same deployment are made at the same time, for
example from two browser windows, both can start from the same active
Instance. The change that Styrmin saves second does not include the
first one. The deployment runs that second change, and the deployment
page shows its Instance as the active Instance. To apply the first
change, make it again after both tasks have ended.

#### Do not edit `styrmin.io/instance-sequence`

Styrmin manages this annotation. If it holds a number higher than any
Instance of the deployment, for example after someone edits it with
`kubectl`, every workflow leaves the `StyrminDeployment` unchanged: the
deployment stays `pending` and its newest task keeps running. To
recover, remove the annotation, then make a change to the deployment:

```bash
kubectl annotate styrmindeployment <namespace> -n <namespace> styrmin.io/instance-sequence-
```

The workflow of that change writes the deployment's whole
configuration, including the changes that did not reach the cluster.

### Why two Instances, not just "the deployment"?

Two reasons.

**Reproducibility.** An Instance freezes the full resolved configuration
at a point in time — the merged context, the chart values, the driver
version. If something goes wrong, you know exactly what was meant to be
running.

**Smart upgrades.** Comparing two Instances lets Styrmin tell the
difference between "the user changed one parameter" and "the user moved
to a new driver version". The kind of change determines the kind of
workflow — you don't run a full upgrade for a one-line config edit.

### What about drift?

Reconciliation in the database is one side of the loop. The other side
runs inside the cluster: the operator periodically re-checks the actual
Kubernetes resources against what the active Instance says should be
there, and fixes them if they've drifted (someone deleted a pod, a
ConfigMap got modified). See
[The operator and `StyrminDeployment`](./operator-and-crds.md).

Together, the two halves give you a system that converges _from any
state_: change the deployment, drift the cluster, restart the agent — it
all heads back toward the desired state on its own.

### Next

- [**The operator and `StyrminDeployment`**](./operator-and-crds.md) —
  the in-cluster half of reconciliation.
- [**Lifecycle hooks and actions**](./hooks-and-actions.md) — the code
  that runs during a workflow.
