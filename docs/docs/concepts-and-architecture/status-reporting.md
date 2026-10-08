---
title: Status reporting
sidebar_position: 8
description: How the Styrmin UI stays up-to-date with what's actually running in the cluster.
---

## Status reporting

When you open the Styrmin UI and see a deployment marked `RUNNING` with
three healthy pods, the server didn't guess that. The agent saw it,
wrote it down, and sent it back. This page explains how.

### Why a separate reporter

The server never talks to the cluster directly (see
[Architecture](./architecture.md)). So how does it know whether a pod is
healthy?

The agent runs a third coroutine called the **status reporter**, side by
side with the Prefect worker and the operator. Its only job is:

1. Every ~5 seconds, look at the cluster.
2. Collect the state of every pod and `StyrminDeployment`.
3. Post the snapshot back to the server via GraphQL.

The server writes it into its `PodStatus` and `DeploymentStatus` tables.
That's what the UI reads.

```text
                 every ~5 seconds
   ┌─────────┐  ◄────────────────────  ┌─────────────┐
   │ Agent's │   pod & deployment      │ Kubernetes  │
   │ status  │   state (read-only)     │     API     │
   │reporter │                         └─────────────┘
   └────┬────┘
        │
        │  reportPodStatuses / reportDeploymentStatuses
        │  (GraphQL mutations)
        ▼
   ┌─────────┐
   │ Server  │  → DB → UI
   └─────────┘
```

### Why polling, not watching

Kubernetes can _push_ events as things change ("watches"). The reporter
uses polling instead, for two reasons:

- **Simpler.** No long-lived connections, no resync logic, no missed
  events.
- **Same outcome at this cadence.** Five seconds is faster than any
  user can react to. There's no operational benefit to event-driven
  reporting here.

### "Observed" vs "declared"

This is the one piece of vocabulary worth knowing.

- **Declared state** is what _should_ be running. That lives in the
  `Deployment` row and the `StyrminDeployment` CRD.
- **Observed state** is what _is_ running. That's what the status
  reporter posts back, and what the UI shows.

The two can disagree, briefly, in normal operation: you just rolled out
an update, the pods are still starting. The UI will show "DEPLOYING"
until the observed state catches up with the declared state.

The two can also disagree because something is wrong — a pod is
`CrashLoopBackOff`, an image pull failed, a node went down. That
disagreement is what the UI is showing you.

### Pruning stale state

Pods and deployments come and go. The reporter doesn't just append — it
sends the full current state every cycle, and the server prunes rows
that no longer exist in the cluster. So if you delete a deployment, the
pods stop reporting and disappear from the UI within a few seconds.

### Which instance a report is about

Each `StyrminDeployment` report carries an `instanceId`: the application
instance whose spec the operator last handled. The reporter reads it from
the CR's `status.instanceId`, which the operator writes when it starts
working on a new spec. A CR that no operator handler has touched since
Styrmin was upgraded has no `status.instanceId`, so the reporter sends
`spec.instanceId` instead.

Right after a flow writes a new spec, the CR still shows the phase of the
previous rollout. Because `status.instanceId` changes only when the
operator acts on the new spec, the server never reads the previous
rollout's `Ready` phase as the result of the new instance.

### When a deployment becomes RUNNING

A report with `displayState: Running` sets the deployment to `RUNNING`
only when the task that rolled out the reported instance has finished.
When a hook step of another task started that task, the starting task
must have finished too.

This matters for upgrades whose driver hook calls `stop_components` and
`start_components`. Each call rolls out its own instance while the upgrade
task is still running. Without the check, the operator's `Running` report
for the stopped instance would set the deployment to `RUNNING` in the
middle of the upgrade, and `styrminctl deployments apply --wait` would
return at that point. The first report after the upgrade task finishes sets
`RUNNING`, within one reporting cycle.

### Steps from status reports

The operator's work appears on the deployment page as the steps of the
task that rolled out the instance. For each report, the server finds that
task by the reported `instanceId` and moves its four operator-phase steps
forward:

- `CreatingPrerequisites`: "Create network policies and secrets" runs.
- `CreatingHelmRelease`: "Install or upgrade the HelmRelease" runs.
- `CreatingServices`: "Create services and middlewares" runs.
- `Ready`: every step succeeds, including "Wait for the deployment to be
  ready".

A report can skip phases between two polls; the steps in between then
succeed. A step ends at the time its CR condition became `True` when the
report carries that condition, and at the time of the report otherwise.

Reports in the `Deleting` and `Deleted` phases go to the newest delete
task of the deployment instead: its step "Remove the deployment's
resources and namespace" runs during `Deleting` and succeeds at
`Deleted`.

Once a newer task has written the `StyrminDeployment` or requested the
deletion, the operator no longer works on the earlier instance. Reports
that still name the earlier instance then change none of the earlier
task's steps, so a step that failed keeps its failure. Until then,
reports for the earlier instance still move the earlier task's steps.

When a report shows the phase `Failed` or the display state `Error`, the
first unfinished step fails with the CR's message. For the HelmRelease
step and the ready step, the error also names up to five pods from the
stored pod statuses, with each container that waits or ended with one of
these reasons: `ImagePullBackOff`, `ErrImagePull`, `InvalidImageName`,
`CrashLoopBackOff`, `CreateContainerConfigError`, `CreateContainerError`,
`Error` or `OOMKilled`. The error does not name a pod without such a
container, for example a pod that fails its readiness probe, or a pod that
has finished. When a later report shows the operator working on the step
again, the step runs again as a new attempt; when a later phase is
reported, the failed step succeeds.

The reporter also reports internal deployments, such as the
per-environment ingress controller, so their status stays current. Their
tasks have no operator-phase steps.

`reportDeploymentStatuses`, the mutation the reporter calls, accepts calls
without credentials
([issue #396](https://github.com/opsmill/styrmin/issues/396) tracks
adding authentication). Anyone who can reach the server's API can
therefore change a deployment's state and its operator-phase steps.

### When the agent stops reporting

While an operator-phase step is running, the server checks when the
agent last reported the deployment. When that was more than 60
seconds ago (or, without any report, when the step started more than 60
seconds ago), the step shows "No report from the agent since" followed
by that time. The notice goes away with the next report. It tells a
stopped agent apart from a phase that is slow.

The deployment page reloads its data every 10 seconds. With the 5-second
report interval, a change of an operator-phase step appears on the page
within about 15 seconds.

### What this means in practice

- The UI is _eventually consistent_ on a ~5-second cadence. A pod that
  crashed half a second ago will show as healthy until the next poll.
- If the agent is unhealthy, status updates stop. The UI keeps showing
  the last known state, and a running operator-phase step shows "No
  report from the agent since" and the time of the last report after 60
  seconds without one.
- The same data is available through the GraphQL API — `podStatuses`
  and `deploymentStatuses` fields — so external dashboards can consume
  it too.

### Next

- [**The operator and `StyrminDeployment`**](./operator-and-crds.md) —
  what the reporter is observing.
- [**Architecture**](./architecture.md) — where the reporter sits in
  the bigger picture.
