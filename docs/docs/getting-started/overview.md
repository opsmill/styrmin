---
title: Platform Overview
sidebar_position: 2
description: How Styrmin works — server, agent, drivers, clusters, environments, and deployments.
---

## Platform Overview

Styrmin is an **application platform that manages the full lifecycle of your
infrastructure automation stack** — Infrahub, Ansible, Grafana, Prometheus,
and the tooling around them — as one system, not one application at a time.

For the framing of _why_ that matters and _how_ it compares to ArgoCD, Flux,
and manual Helm, see [Why Styrmin?](./why-styrmin.md). This page focuses on
_how the platform works_ and the vocabulary you'll see across the docs, the
GraphQL API, the SDK, and the CLI.

### What the platform does

Once Styrmin is running on a Kubernetes cluster and you've loaded a driver
for an application, three things fundamentally change:

1. **Deploying applications becomes simple.** Pick a driver, an environment,
   and a version — Styrmin handles the Kubernetes-specific configuration
   (storage classes, ingress, version mapping). No need to learn each
   chart's value schema.
2. **Operating them becomes safe and repeatable.** Day-2 operations
   (backups, upgrades, restores) run through driver-defined procedures.
   The "right way" to back up Neo4j or to upgrade Infrahub is encoded in
   the driver, not in a tribal-knowledge runbook.
3. **The full stack can be managed as one system.** Group applications
   into environments. Back up an environment in a single operation. Clone
   an environment — production data and all — to test upgrades safely.
   Connectivity between applications is environment-aware, so a cloned
   environment is self-contained.

Kubernetes is the underlying infrastructure layer. You will not interact
with `kubectl` to run day-to-day operations — though you can, and Styrmin
does not change how applications expose their APIs or accept traffic from
external systems.

### How the pieces fit together

```text
   ┌────────────┐   GraphQL   ┌──────────┐    recorded intent     ┌────────┐
   │  CLI / UI  │ ──────────► │  Server  │ ─────────────────────► │ Agent  │
   │   / SDK    │             │ (Python) │   Prefect flows +      │ (in    │
   └────────────┘             └────┬─────┘   StyrminDeployment    │ cluster│
                                   │              CRD             │   )    │
                                   ▼                              └───┬────┘
                              PostgreSQL                              │
                                                                      ▼
                                                                Kubernetes
                                                                resources
```

- The **server** owns the database and the public GraphQL API. It is the
  source of truth for what _should_ be running.
- The **agent** runs inside the target cluster. It picks up _recorded
  intent_ (Prefect flows and `StyrminDeployment` CRDs) and reconciles the
  cluster to match. There is one agent per cluster.
- A **status reporter** inside the agent continuously posts observed pod
  and deployment state back to the server, so the API and UI always
  reflect what is actually running.
- The **CLI** (`styrminctl`), the **SDK** (`styrmin-sdk`), and the
  **frontend** are all clients of the same GraphQL API.

For the prescriptive principles behind this design, see the
[Styrmin Constitution](https://github.com/opsmill/styrmin/blob/develop/dev/constitution.md).

### Core concepts

The vocabulary below is canonical: these terms show up unchanged in the
GraphQL schema, the SDK, the CLI, the UI, and the rest of these docs.

#### Application Driver

An **Application Driver** is a versioned specification that tells Styrmin
how to deploy, configure, back up, and upgrade a given application. One
driver per application; without one, Styrmin doesn't know how to handle
the app.

Read more in [What is an Application Driver?](../drivers/what-is-a-driver.md).

#### Cluster

A **Cluster** is a Kubernetes cluster that Styrmin manages. Cluster-level
settings (storage classes, ingress, …) are configured once and inherited
by every application deployed on it.

Styrmin currently supports one cluster at a time; multi-cluster is on the
roadmap.

#### Environment

An **Environment** is a named slice of a cluster — `dev`, `staging`,
`prod`, `team-a`. Environments group applications that share a lifecycle
and a backup storage location. Backup, upgrade, and clone operations can
target an entire environment at once.

```text
Cluster ─┬─ Environment "dev"      ─── Deployment "infrahub-dev"
         │                          └─ Deployment "semaphore-dev"
         └─ Environment "staging"   ─── Deployment "infrahub-staging"
```

#### Deployment

A **Deployment** is an application deployed in a specific environment.

#### User actions and hooks

Drivers attach Python **actions** to lifecycle **hooks** —
`pre`/`core`/`post` slots for `setup`, `upgrade`, `backup`, etc. Actions
run inside Prefect flows on the agent, and have access to a set of
built-in primitives (`stop_component`, `start_component`,
`execute_commands`, `upgrade_deployment_version`, …). This is how Styrmin
encodes a real-world upgrade procedure — stop workers, run migrations,
restart, verify — as a repeatable, driver-defined sequence rather than a
human-executed runbook.

### What you'll do next

- [**Quickstart**](./quickstart.md) — bring up the bundled vCluster demo
  end-to-end in two commands.
- [**What is an Application Driver?**](../drivers/what-is-a-driver.md) —
  the unit of deployment, in depth.
- [**Local laptop (vcluster)**](../installation/vcluster-local.md) — the
  manual version of the quickstart, with every step unpacked.
- [**DigitalOcean**](../installation/digitalocean.md) — production-style
  install on DOKS with Spaces-backed backups.
