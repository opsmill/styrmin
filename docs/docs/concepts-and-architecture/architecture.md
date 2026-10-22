---
title: Architecture
sidebar_position: 2
description: Styrmin's components and how they connect.
---

## Architecture

Styrmin has two long-running processes: a **server**, which your tools
call, and an **agent**, which runs inside the Kubernetes cluster and
changes it. The UI, the CLI, and the SDK are clients of the server.

```text
   ┌────────────┐   GraphQL    ┌────────────┐   recorded intent   ┌────────────┐
   │  CLI / UI  │ ───────────► │   Server   │ ──────────────────► │   Agent    │
   │   / SDK    │              │  (Python)  │   (Prefect flows    │ (in the    │
   └────────────┘              └─────┬──────┘    + custom         │  cluster)  │
                                     │             resources)     └─────┬──────┘
                                     ▼                                  │
                                PostgreSQL                              ▼
                                                                 Kubernetes
                                                                 resources
```

### The server

The **server** is a Python process that runs FastAPI and a GraphQL API.
It:

- Holds the database. Styrmin stores all of its data (clusters,
  environments, deployments, drivers, backups) in a PostgreSQL database.
  Only the server reads and writes it.
- Serves the public GraphQL API at `/graphql`. The frontend, the
  `styrminctl` CLI, and the `styrmin-sdk` Python SDK all call it.
- Records what should run. It does not change the Kubernetes cluster
  itself.

### The agent

The **agent** is one container that runs inside the Kubernetes cluster.
It is the only Styrmin component that changes the cluster through the
Kubernetes API. The agent runs three coroutines side by side:

- **A Prefect worker**, which runs the flows that act on the cluster,
  such as the flow that writes a deployment's `StyrminDeployment` or the
  flow that runs a Velero backup, and the actions of drivers. It polls
  the work pool `user-work-pool`.
- **An operator**, built on the `kopf` library, which watches Styrmin's
  custom resources and creates the Kubernetes objects they describe. See
  [The operator and `StyrminDeployment`](./operator-and-crds.md).
- **A status reporter**, which reads pod health from the cluster every
  few seconds and sends it to the server. See
  [Status reporting](./status-reporting.md).

There is exactly **one agent per cluster**. Styrmin supports one cluster
at a time; support for several clusters is on the roadmap.

### Recorded intent: how the server sends work to the agent

The server does not call the agent. It records the work, and the agent
starts it when it polls. This is called **recorded intent**. The server
records intent in two ways:

1. **Prefect flows.** For one-off jobs (deploy, upgrade, backup,
   restore), the server submits a Prefect flow run and writes a `Task`
   row in the database to track it. The `task-worker` of the server's
   Helm chart runs this flow, such as `apply_state`, from the work pool
   `styrmin-work-pool`. That flow submits the flows that act on the
   cluster, and the driver's actions, to the work pool `user-work-pool`.
   The agent's Prefect worker reads them from Prefect and runs them.
2. **`StyrminDeployment` custom resources.** For the long-running
   desired state of a deployment, a flow writes a `StyrminDeployment`
   custom resource into the cluster. The agent's operator watches that
   resource and changes the cluster to match it.

This design has two effects:

- **No work is lost when the agent restarts.** The recorded intent stays
  in Prefect and in the cluster. When the agent restarts, it continues
  the recorded work.
- **The server does not wait for the agent.** It records the intent
  whether the agent is online, busy, or restarting.

### Where each component runs

| Component | Where it runs | What it does |
|-------|-------|--------------|
| Database (PostgreSQL) | Outside or next to the server | Stores all Styrmin data |
| Server | Anywhere that can reach the database and the Kubernetes API | Serves the GraphQL API, records intent |
| Prefect | Next to the server, with a worker inside the agent | Runs one-off jobs as workflows |
| Agent | A pod inside the target Kubernetes cluster | Calls the Kubernetes API, runs Prefect flows, reports status |
| Drivers | Included in the server image or loaded from git | Describe how to deploy each application |

### What this means in practice

- When you deploy an application from the UI, the server writes a
  deployment row and starts a Prefect flow, and the agent does the work.
  The UI does not wait for a long synchronous call.
- The UI shows what the agent observed in the cluster, not the state the
  server recorded. See [Status reporting](./status-reporting.md).
- When the cluster no longer matches the declared state (someone deleted
  a pod, a node restarted), the operator detects the difference and
  reconciles it. The server is not involved.

### Next steps

- [**Reconciliation**](./reconciliation.md): the loop that makes the
  cluster match the desired state.
- [**The operator and `StyrminDeployment`**](./operator-and-crds.md):
  what the operator does inside the cluster.
