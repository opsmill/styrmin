---
title: Reconciliation
sidebar_position: 3
description: How Styrmin makes the cluster match the deployment you configured.
---

## Reconciliation

Styrmin is **declarative**. You declare the result, such as Infrahub 1.6.0
with these settings in this environment, and Styrmin runs the steps to
reach it: it installs the chart, runs the migration, and restarts the
workers.

Styrmin reaches the declared result through **reconciliation**: a loop
that compares the configuration you set with what runs in the cluster,
and applies the difference.

### Desired state and current state

Reconciliation compares two states:

- **Desired state**: the configuration you set. It is the deployment row
  in the database, with the driver version, the application version, and
  the configuration it pins.
- **Current state**: what runs now. Styrmin records it as the **active
  instance**: a fixed record of what was last deployed, with its full
  resolved configuration.

Reconciliation runs between them:

```text
            ┌────────────────────┐
            │     Deployment     │   ← you edit this
            │   (desired state)  │
            └─────────┬──────────┘
                      │
                      │ generate a new instance
                      ▼
            ┌────────────────────┐
            │    New instance    │
            │  (desired snapshot)│
            └─────────┬──────────┘
                      │
                      │  compare with
                      ▼
            ┌────────────────────┐
            │  Active instance   │   ← what runs now
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

1. **You change the deployment**: you edit its configuration, change a
   parameter, or select a new driver version. The server writes the
   change to the database. An application version upgrade also selects
   the driver version again. Unless you pin one, Styrmin selects the
   newest loaded driver version that supports the requested application
   version, by a fixed rule (see
   [Selecting a driver version](../drivers/loading-drivers.md#selecting-a-driver-version-when-deploying-or-upgrading)).
   An upgrade to the same application version therefore moves the
   deployment to a newly loaded driver build.
2. **The server generates a new instance** from the updated deployment.
   The instance is a fixed record of what would run after the change: the
   resolved configuration, the driver version, and the chart values.
3. **The server compares** the new instance with the active instance
   (the one that runs now) and produces a **diff**: a structured list of
   the changes.
4. **The server selects a workflow from the diff.** A configuration
   change starts an update, a driver version change starts an upgrade,
   and a new deployment starts a create.
5. **The agent runs the workflow** through Prefect. The driver's actions,
   such as stopping or starting components and running migrations, run in
   the order that the driver declares.
6. **The new instance becomes the active instance** when the work
   succeeds. The next change starts from it.

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
  active instance. The resolved config is the cluster config, then the
  environment config, then the deployment config, where the most
  specific value wins. So a deployment in an environment that sets the changed
  value itself is not redeployed. When `dedicated_ingress` changes, the
  redeploys are ordered around each environment's ingress controller;
  see
  [Changing the dedicated ingress on the cluster](./ingress-and-networking.md#changing-the-dedicated-ingress-on-the-cluster).

Both fan-outs redeploy each deployment at its current application
version and driver version, through the steps above. Both skip deleted
deployments and deployments with a restore in progress, and the cluster
config fan-out also skips deployments that are being deleted. Neither
redeploys an internal deployment, such as an ingress controller, as an
application. The cluster config fan-out redeploys ingress controllers by
the rules in
[Ingress and networking](./ingress-and-networking.md#changing-the-dedicated-ingress-on-the-cluster).
A redeploy that cannot start does not stop the others. Because Styrmin
compares each deployment on its own, submitting the same config again
redeploys only the deployments that are not yet at it. This also retries
a redeploy that could not start.

### Several changes in quick succession

Each change to a deployment starts its own workflow, whether you make it
on the deployment page, with `styrminctl` or through the API. When you
make changes one after another, their workflows can still run at the
same time and reach the cluster in any order.

Styrmin numbers the instances of each deployment in the order it saves
them, and the `StyrminDeployment` records the number of the instance it
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
instance. The change that Styrmin saves second does not include the
first one. The deployment runs that second change, and the deployment
page shows its instance as the active instance. To apply the first
change, make it again after both tasks have ended.

#### Do not edit `styrmin.io/instance-sequence`

Styrmin manages this annotation. If it holds a number higher than any
instance of the deployment, for example after someone edits it with
`kubectl`, every workflow leaves the `StyrminDeployment` unchanged: the
deployment stays `pending` and its newest task keeps running. To
recover, remove the annotation, then make a change to the deployment:

```bash
kubectl annotate styrmindeployment <namespace> -n <namespace> styrmin.io/instance-sequence-
```

The workflow of that change writes the deployment's whole
configuration, including the changes that did not reach the cluster.

### Why Styrmin compares two instances

**Reproducible state.** An instance records the full resolved
configuration at one point in time: the merged context, the chart values,
and the driver version. When something fails, you can read what was meant
to run.

**The workflow matches the change.** Comparing two instances shows
whether you changed one parameter or moved to a new driver version.
Styrmin selects the workflow from the kind of change, so a one-line
configuration edit does not run a full upgrade.

### Drift in the cluster

Reconciliation in the database is one part of the loop. The other part
runs inside the cluster: the operator periodically compares the
Kubernetes resources with what the active instance declares, and
corrects them when they differ, for example when someone deleted a pod or
edited a ConfigMap. See
[The operator and `StyrminDeployment`](./operator-and-crds.md).

After a change to the deployment, a change in the cluster, or an agent
restart, the two loops return the cluster to the desired state.

### Next steps

- [**The operator and `StyrminDeployment`**](./operator-and-crds.md):
  reconciliation inside the cluster.
- [**Lifecycle hooks and actions**](./hooks-and-actions.md): the code
  that runs during a workflow.
