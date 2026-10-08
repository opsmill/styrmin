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

#### Changes to environment variables or image overrides only

Styrmin applies environment variables and image overrides through
post-render patches of the deployment's HelmRelease. With the FluxCD
helm-controller that Styrmin installs (v1.1.0), a change that changes
only these patches can be dropped when it reaches the cluster while
FluxCD still upgrades the previous change. The deployment then shows
`running`, but its pods keep the previous values until the next change
([#433](https://github.com/opsmill/styrmin/issues/433)). To apply the
last values, make another change to the deployment after both tasks
have ended.

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
