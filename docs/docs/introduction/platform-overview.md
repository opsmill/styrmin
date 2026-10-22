---
title: Platform overview
sidebar_position: 2
description: Styrmin's components (server, agent, drivers) and its core terms (cluster, environment, deployment).
---

## Platform overview

For how Styrmin compares to Argo CD, Flux, and manual Helm, see
[Why Styrmin?](./why-styrmin.md).

### What you can do with Styrmin

After you install Styrmin on a Kubernetes cluster and load a driver for
an application, you can:

1. **Deploy an application** by choosing a driver, an environment, and a
   version. The driver sets the Kubernetes-specific configuration
   (storage classes, ingress, chart version), so you set driver
   parameters instead of chart values.
2. **Back up, upgrade, and restore** with the procedures that the driver
   defines. For example, the driver contains the backup steps for Neo4j
   and the upgrade steps for Infrahub.
3. **Manage an environment as one unit.** Group applications into
   environments. Back up every application in an environment with one
   operation. Clone an environment, including its production data, to
   test an upgrade. Applications in a cloned environment connect only to
   each other.

You run day-to-day operations from the UI, the CLI, or the API.
`kubectl` still works. Styrmin does not change how applications expose
their APIs or accept traffic from external systems.

### Components

```text
   ┌────────────┐   GraphQL   ┌──────────┐    recorded intent     ┌────────┐
   │  CLI / UI  │ ──────────► │  Server  │ ─────────────────────► │ Agent  │
   │   / SDK    │             │ (Python) │   Prefect flows +      │ (in    │
   └────────────┘             └────┬─────┘   StyrminDeployment    │ cluster│
                                   │              resources       │   )    │
                                   ▼                              └───┬────┘
                              PostgreSQL                              │
                                                                      ▼
                                                                Kubernetes
                                                                resources
```

- The **server** owns the database and the public GraphQL API. It
  records what _should_ run.
- The **agent** runs inside the target cluster. It reads the recorded
  intent (Prefect flows and `StyrminDeployment` resources) and changes
  the cluster to match. There is one agent per cluster.
- The **status reporter**, inside the agent, sends the observed state of
  pods and deployments to the server, so the API and the UI show what
  runs in the cluster.
- The **CLI** (`styrminctl`), the **SDK** (`styrmin-sdk`), and the
  **frontend** are clients of the same GraphQL API.

For the principles behind this design, see the
[Styrmin Constitution](https://github.com/opsmill/styrmin/blob/develop/dev/constitution.md).

### Core terms

The GraphQL schema, the SDK, the CLI, the UI, and these docs use the
terms below. For the full list, see [Core concepts](../concepts-and-architecture/core-concepts.md)
and the [Glossary](../concepts-and-architecture/glossary.md).

#### Application driver

An **application driver** is a versioned specification of how Styrmin
deploys, configures, backs up, and upgrades one application. Each
application has one driver, and Styrmin deploys only applications that
have a driver.

See [What is an application driver?](../concepts-and-architecture/what-is-a-driver.md).

#### Cluster

A **cluster** is a Kubernetes cluster that Styrmin manages. You set the
cluster-level settings (storage classes, ingress, …) once, and every
application deployed on the cluster uses them.

Styrmin supports one cluster at a time. Support for several clusters is
on the roadmap.

#### Environment

An **environment** is a logical deployment target in one cluster, such as
`dev`, `staging`, `prod`, or `team-a`. An environment groups applications
that share a lifecycle and a backup storage location. Backup, upgrade,
and clone operations can apply to a whole environment.

```text
Cluster ─┬─ Environment "dev"      ─── Deployment "infrahub-dev"
         │                          └─ Deployment "semaphore-dev"
         └─ Environment "staging"   ─── Deployment "infrahub-staging"
```

#### Deployment

A **deployment** is one application deployed in one environment.

#### Actions and hooks

A driver attaches Python **actions** to lifecycle **hooks**. There are
two hooks, `setup` and `upgrade`, and each has three modes: `pre`,
`core`, and `post`. Actions run in Prefect flows on the agent and can
call built-in primitives (`stop_components`, `start_components`,
`execute_commands`, `upgrade_deployment_version`, …). With actions, a
driver defines an upgrade procedure (stop workers, run migrations,
restart, verify) as a sequence that Styrmin runs the same way on every
upgrade.

### Next steps

- [**Quickstart**](../installation/quickstart.md): start the bundled
  vCluster demo with two commands.
- [**What is an application driver?**](../concepts-and-architecture/what-is-a-driver.md):
  the application driver in detail.
- [**Install Styrmin on a local vCluster**](../installation/vcluster-local.md):
  the same install as the Quickstart, one step at a time.
- [**Install Styrmin on DigitalOcean**](../installation/digitalocean.md):
  an install on DOKS with backups stored in DigitalOcean Spaces.
