---
title: Architecture
sidebar_position: 2
description: The big picture — what Styrmin is made of and how the pieces talk to each other.
---

## Architecture

Styrmin is made of two long-running processes: a **server** that you and
your tools talk to, and an **agent** that runs inside the Kubernetes
cluster and does the actual work. Everything else — the UI, the CLI, the
SDK — is just a client of the server.

```text
   ┌────────────┐   GraphQL    ┌────────────┐   recorded intent   ┌────────────┐
   │  CLI / UI  │ ───────────► │   Server   │ ──────────────────► │   Agent    │
   │   / SDK    │              │  (Python)  │   (Prefect flows    │ (in the    │
   └────────────┘              └─────┬──────┘    + CRDs)          │  cluster)  │
                                     │                            └─────┬──────┘
                                     ▼                                  │
                                PostgreSQL                              ▼
                                                                 Kubernetes
                                                                 resources
```

### The server

The **server** is a Python process running FastAPI and a GraphQL API. It:

- Holds the database. All Styrmin state — clusters, environments,
  deployments, drivers, backups — lives in a PostgreSQL database that
  only the server reads and writes.
- Exposes the public GraphQL API at `/graphql`. The frontend, the
  `styrminctl` CLI, and the `styrmin-sdk` Python SDK all talk to it.
- Decides _what should be running_ — but never directly touches the
  Kubernetes cluster.

If the cluster is the kitchen, the server is the front-of-house: it
takes orders and writes them down. It doesn't cook.

### The agent

The **agent** is one container running _inside_ the Kubernetes cluster.
It's the only thing in Styrmin that talks to Kubernetes directly.
Specifically, the agent runs three coroutines side by side:

- **A Prefect worker**, which picks up workflows the server has
  scheduled (deploys, upgrades, backups, restores) and runs them.
- **An operator** (built on a library called `kopf`), which watches for
  changes to Styrmin's own custom resources and reconciles them into
  Kubernetes objects. See
  [The operator and `StyrminDeployment`](./operator-and-crds.md).
- **A status reporter**, which polls the cluster every few seconds for
  pod health and posts a snapshot back to the server. See
  [Status reporting](./status-reporting.md).

There is exactly **one agent per cluster**. Today, Styrmin supports one
cluster at a time; multi-cluster is on the roadmap.

### Recorded intent — how the server talks to the agent

This is the one architectural rule worth memorising:

> **The server never calls the agent directly. It writes down what it
> wants, and the agent picks the work up on its own schedule.**

This is what we mean by "recorded intent". There are two paths the
server uses:

1. **Prefect flows.** For one-off jobs (deploy, upgrade, backup,
   restore), the server submits a Prefect flow run and writes a `Task`
   row in the database to track it. The agent's Prefect worker pulls
   the flow from Prefect and runs it.
2. **`StyrminDeployment` custom resources.** For "this is the
   long-running desired state of a deployment", the server writes a
   Kubernetes custom resource into the cluster. The agent's operator
   watches that resource and converges the cluster to match it.

Why this design? Two reasons:

- **Crash safety.** If the agent crashes, the recorded intent is still
  there. When the agent restarts, it picks up where it left off.
- **No coupling.** The server doesn't need to know whether the agent is
  online, busy, or restarting. It just writes the intent and moves on.

### Where everything lives

| Thing | Where | What it does |
|-------|-------|--------------|
| Database (PostgreSQL) | Outside or alongside the server | Source of truth for everything Styrmin knows |
| Server | Anywhere that can reach the database and Kubernetes API | GraphQL API, writes recorded intent |
| Prefect | Runs alongside the server (and a worker inside the agent) | Workflow engine for one-off jobs |
| Agent | A pod inside the target Kubernetes cluster | Talks to Kubernetes, runs Prefect flows, reports status |
| Drivers | Either baked into the server image or fetched from git | Application-specific deployment specifications |

### What this means in practice

- When you click "deploy" in the UI, the server writes a `Deployment`
  row, kicks off a Prefect flow, and the agent does the work — you're
  not waiting on a long synchronous call.
- The UI always reflects what the agent _observed_ in the cluster, not
  what the server _hoped_ would be there. That's the
  [status reporting](./status-reporting.md) loop at work.
- If the cluster gets out of sync with what was declared (someone
  deleted a pod, a node restarted), the operator notices and
  reconciles. The server doesn't need to be involved.

### Next

- [**Reconciliation**](./reconciliation.md) — the loop Styrmin runs over
  and over to converge desired state with reality.
- [**The operator and `StyrminDeployment`**](./operator-and-crds.md) —
  what the agent's operator actually does inside the cluster.
