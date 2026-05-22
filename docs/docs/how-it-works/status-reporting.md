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

### What this means in practice

- The UI is _eventually consistent_ on a ~5-second cadence. A pod that
  crashed half a second ago will show as healthy until the next poll.
- If the agent is unhealthy, status updates stop. The UI will keep
  showing the last known state. There's no "is the agent alive" signal
  beyond fresh status updates.
- The same data is available through the GraphQL API — `podStatuses`
  and `deploymentStatuses` fields — so external dashboards can consume
  it too.

### Next

- [**The operator and `StyrminDeployment`**](./operator-and-crds.md) —
  what the reporter is observing.
- [**Architecture**](./architecture.md) — where the reporter sits in
  the bigger picture.
