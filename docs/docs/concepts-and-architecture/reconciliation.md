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
   database.
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
