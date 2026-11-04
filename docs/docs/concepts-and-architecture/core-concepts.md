---
title: Core concepts
sidebar_position: 2
description: The terms you need to use Styrmin (driver, cluster, environment, deployment, instance, context, hooks) and how they relate.
---

## Core concepts

The docs, the GraphQL API, the SDK, the CLI, and the UI use the terms
below.

> For a one-sentence definition of every term, see the
> [Glossary](./glossary.md).

### The platform

#### Server

The Styrmin **server** is the central backend process. It owns the
database, exposes the public GraphQL API, and records _what should run_.
The CLI, the SDK, and the frontend are clients of this API. The server
does not connect to a target cluster: it records the intended state, and
the agent reads it (see [Recorded intent](#recorded-intent)).

#### Agent

The **agent** is the single container that Styrmin runs _inside_ a
target Kubernetes cluster. It reads the recorded intent, changes the
cluster to match, and reports the observed state to the server. There is
**one agent per cluster**.

#### CLI and SDK

`styrminctl` is the command-line client, and `styrmin-sdk` is the async
Python SDK. Both call the GraphQL API and do not connect to the database
or the agent.

### What you deploy

#### Application driver

An **application driver** is a versioned, self-contained specification
of how Styrmin deploys an application: which Helm chart, which
components, which user-facing parameters, which services to expose, and
which lifecycle **actions** to run.

Styrmin deploys an application only through its driver. Every
deployment step comes from the driver.

See [What is an application driver?](./what-is-a-driver.md) for the
parts of a driver.

#### Application driver version

Drivers are versioned. An **application driver version** is one
revision of a driver, loaded from a directory or a git repository, with
its own Helm chart version, components, parameters, services, and
actions. It is one revision of one driver, not a version number. An
upgrade usually moves a deployment to a newer application driver
version.

#### Application version

The **application version** is the version of the deployed application
itself (for example, Infrahub `1.6.0`). It is different from the
application driver version, which is the specification that deploys the
application. One application driver version usually supports a range of
application versions, declared as a PEP 440 version specifier.

### Where you deploy

#### Cluster

A **cluster** is a Kubernetes cluster registered with Styrmin. Every
application deployed on the cluster uses the cluster-level settings
(storage classes, ingress, …). You set them when you create the cluster,
and you can change them later with
[`styrminctl clusters update`](../reference/styrminctl.md#clusters-update--change-a-clusters-config),
which redeploys the applications that use a changed value. Styrmin
supports one cluster at a time. Support for several clusters is on the
roadmap.

#### Environment

An **environment** is a logical deployment target in one cluster, such as
`dev`, `staging`, `prod`, or `team-a`. An environment groups
applications that share a lifecycle and a backup storage location.
Backup, upgrade, and clone operations can apply to a whole environment.
Applications connect to the other applications of their environment (for
example, Infrahub connecting to Semaphore), so the applications in a
cloned environment connect only to each other.

```text
Cluster ─┬─ Environment "dev"      ─── Deployment "infrahub-dev"
         │                          └─ Deployment "semaphore-dev"
         └─ Environment "staging"   ─── Deployment "infrahub-staging"
```

#### Deployment

A **deployment** is the long-lived record of _one_ application in _one_
environment: _one_ application driver version, _one_ application version,
and the user's configuration. Editing a deployment records a new intent
and starts a reconciliation.

A deployment is the record of the desired state. It does not include
what _currently_ runs: that is the **instance**.

#### Instance

An **instance** is a fixed record of what was deployed at one point in
time. Styrmin generates it from the deployment at reconciliation time,
and it contains the resolved **context** (see below).

A deployment has at most one **active instance** at a time. Styrmin
keeps older instances for the timeline and for auditing. When you
upgrade or edit a deployment, Styrmin generates a new instance and
compares it with the active one: the difference is the reconciliation
diff.

### How it runs

#### Reconciliation

**Reconciliation** is the loop that Styrmin runs for each change: it
compares a newly generated instance (desired) with the active instance
(current), lists the changes, and applies them. When the two instances
are the same, there are no changes and Styrmin does nothing.

[Reconciliation](./reconciliation.md) explains the loop.

#### Recorded intent

The server does not call the agent. It writes the intent into the
database and into a `StyrminDeployment` resource, which the agent's
operator reconciles. Because Styrmin stores the intent instead of
sending direct calls, the agent can restart or fail partway and continue
from the stored intent.

[The operator and `StyrminDeployment`](./operator-and-crds.md) explains
the `StyrminDeployment` resource.

#### Context (GlobalContext)

The **context** is the resolved configuration that the agent uses:
the cluster defaults, the environment overrides, the deployment's
configuration and parameters, and the driver's defaults, merged into one
hierarchical object. It is embedded in both the instance and the
`StyrminDeployment` resource.

Drivers render Helm values and run Python actions with the context.
Styrmin builds it from the values the user sets, and the driver turns it
into Kubernetes objects.

See [The context (GlobalContext)](../drivers/context.md) for its
structure.

### How drivers extend the lifecycle

#### Hooks and modes

A driver's Python code runs at **hooks**: `setup` (when a deployment is
created) and `upgrade` (when it is upgraded). Each hook has three
**modes**: `pre`, `core`, and `post`. The modes run in this order. The
order of the actions inside one mode is not defined.

#### Action

An **action** is the Python function that a driver registers at a hook
and mode. Actions run in a Prefect flow on the agent and can call
built-in primitives (`stop_components`, `start_components`,
`execute_commands`, `upgrade_deployment_version`, …). With actions, a
driver defines an upgrade procedure (stop workers, run migrations,
restart, verify) as a sequence that Styrmin runs the same way on every
upgrade.

[Lifecycle hooks and actions](./hooks-and-actions.md) explains hooks,
modes, and the action primitives.

### How the concepts relate

```text
                       Application driver
                              │ versioned as
                              ▼
                   Application driver version
                              │ pinned by
                              ▼
Cluster ─── Environment ─── Deployment ──generates──► Instance
                                │                          │
                                │ embeds                   │ embeds
                                ▼                          ▼
                           Context (resolved configuration)
                                │
                                ▼
                       StyrminDeployment resource
                                │ watched by
                                ▼
                            Agent operator
                                │ reconciles
                                ▼
                       Kubernetes resources
                                │
                                ▼
                        Observed state
                    (PodStatus / DeploymentStatus)
                                │
                                ▼
                        reported to the server
```

### Next steps

- [**Glossary**](./glossary.md): every Styrmin term, in alphabetical
  order.
- [**What is an application driver?**](./what-is-a-driver.md): the
  application driver in detail.
- [**Architecture**](./architecture.md): the server, the agent, and how
  they connect.
- [**Reconciliation**](./reconciliation.md): the loop that compares the
  desired and the current state.
