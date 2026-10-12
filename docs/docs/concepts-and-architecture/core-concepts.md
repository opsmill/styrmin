---
title: Core concepts
sidebar_position: 2
description: The vocabulary you need to use Styrmin — driver, cluster, environment, deployment, instance, context, hooks, and how they fit together.
---

## Core concepts

Styrmin's docs, GraphQL API, SDK, CLI, and UI all use the same set of
nouns. The list below is canonical: if you know these terms, the rest
of the documentation reads cleanly. If you've already skimmed the
[Platform Overview](../introduction/platform-overview.md), this page
formalises the same vocabulary in one place.

> Looking for a quick lookup of every term Styrmin uses? See the
> [Glossary](./glossary.md).

### The platform

#### Server

The Styrmin **server** is the central backend process. It owns the
database, exposes the public GraphQL API, and is the source of truth
for _what should be running_. The CLI, the SDK, and the frontend are
all clients of this same API. The server never talks to a target
cluster directly — direction flows through **recorded intent** (see
below).

#### Agent

An **agent** is the single container Styrmin runs _inside_ a target
Kubernetes cluster. It picks up recorded intent, reconciles the
cluster to match, and continuously reports observed state back to the
server. There is **one agent per cluster**.

#### CLI and SDK

`styrminctl` is the command-line client; `styrmin-sdk` is the async
Python SDK. Both are thin wrappers over the GraphQL API — they don't
talk to the database or the agent directly.

### What you deploy

#### Application Driver

An **Application Driver** is a versioned, self-contained deployment
specification that tells Styrmin _everything it needs to know_ to
deploy a given application: which Helm chart, which components, which
user-facing parameters, which services to expose, and which lifecycle
**actions** to run.

Drivers are the unit of deployment in Styrmin. No application can be
deployed without one, and all deployment behaviour flows from the
driver — there is no ad-hoc deployment logic outside it.

See [What is an Application Driver?](./what-is-a-driver.md) for the
full anatomy.

#### Application Driver Version

Drivers are versioned. An **Application Driver Version** is one
revision of a driver — sourced from a directory or a git tag — with
its own Helm chart pin, components, parameters, services, and actions.
"Upgrading a deployment" almost always means pointing it at a newer
Application Driver Version.

The capitalised form is a proper noun: when you see it in the docs,
think "specific revision of a specific driver", not "any old version
number".

#### Application Version

The user-facing version of the deployed _application itself_ (e.g.
Infrahub `1.6.0`). Distinct from the Application Driver Version, which
is the spec that knows how to deploy it. One Application Driver
Version typically supports a range of Application Versions, declared
as a semver specifier.

### Where you deploy

#### Cluster

A **Cluster** is a Kubernetes cluster registered with Styrmin.
Cluster-level settings (storage classes, ingress, ...) are inherited by
every application deployed on it. You set them when you create the
cluster and can change them later with
[`styrminctl clusters update`](../reference/styrminctl.md#clusters-update--change-a-clusters-config),
which redeploys the applications that take a changed value. Styrmin
currently supports one cluster at a time; multi-cluster is on the
roadmap.

#### Environment

An **Environment** is a named slice of a cluster — `dev`, `staging`,
`prod`, `team-a`. Environments group applications that share a
lifecycle and a backup storage location. Backup, upgrade, and clone
operations can target an entire environment at once. Cross-application
connectivity (e.g. Infrahub talking to Semaphore) is environment-aware:
a cloned environment is self-contained.

```text
Cluster ─┬─ Environment "dev"      ─── Deployment "infrahub-dev"
         │                          └─ Deployment "semaphore-dev"
         └─ Environment "staging"   ─── Deployment "infrahub-staging"
```

#### Deployment

A **Deployment** is the long-lived record that pins _one_ Application
Driver Version, _one_ Application Version, and the user's config into
_one_ Environment. Editing a deployment expresses a new intent and
triggers reconciliation.

A Deployment is the desired-state record. It does not include
information about what is _currently_ running — that's the
**Instance**.

#### Instance

An **Instance** is a frozen snapshot of what was actually deployed at
a point in time. It's generated from the Deployment at reconciliation
time and carries the resolved **Context** (see below).

A Deployment owns at most one **active instance** at any moment; older
instances stay around for timeline and audit. When you upgrade or
edit, a new instance is generated and compared against the active
one — that's the reconciliation diff.

### How it runs

#### Reconciliation

**Reconciliation** is the loop Styrmin runs over and over: compare a
newly generated Instance (desired) against the active Instance
(current), plan the convergence work, and execute it. A converged
deployment produces no diff, no plan, and no work — by construction.

[Reconciliation](./reconciliation.md) covers the loop in detail.

#### Recorded intent

The server never calls the agent directly. Instead it writes intent
into the database and into a **StyrminDeployment** CRD, which the
agent's operator picks up and reconciles. This indirection — direction
flowing through recorded artefacts rather than RPC calls — is what
makes the system resilient to restarts and partial failures.

[The operator and `StyrminDeployment`](./operator-and-crds.md) covers
the CRD side.

#### Context (GlobalContext)

The **Context** is the resolved configuration snapshot the agent
actually acts on: cluster defaults, environment overrides, the
Deployment's config and parameters, the driver's defaults — all
merged into one hierarchical object and embedded in both the Instance
and the StyrminDeployment CRD.

Drivers render Helm values and run Python actions against the Context.
It's the bridge between "the user filled in a form" and "the cluster
has these Kubernetes objects".

See [the Context page](../drivers/context.md) for the full structure.

### How drivers extend lifecycle

#### Hooks and modes

Driver Python code runs at **hooks** — lifecycle slots like `setup`
(during create) and `upgrade` (during upgrade). Each hook has three
**modes**: `pre`, `core`, and `post`. Ordering across modes is strict;
ordering inside a mode is unspecified.

#### Action

An **action** is the Python function the driver registers at a given
hook/mode. Actions run inside a Prefect flow on the agent and have
access to a set of built-in primitives (`stop_component`,
`start_component`, `execute_commands`,
`upgrade_deployment_version`, ...). This is how Styrmin encodes a
real-world upgrade procedure — stop workers, run migrations, restart,
verify — as a repeatable, driver-defined sequence rather than a
human-executed runbook.

[Lifecycle hooks and actions](./hooks-and-actions.md) covers the
hook/mode model and the action primitives.

### How it all fits together

```text
                       Application Driver
                              │ versioned as
                              ▼
                   Application Driver Version
                              │ pinned by
                              ▼
Cluster ─── Environment ─── Deployment ──generates──► Instance
                                │                          │
                                │ embeds                   │ embeds
                                ▼                          ▼
                           Context (resolved configuration)
                                │
                                ▼
                       StyrminDeployment CRD
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
                        reported back to server
```

### Where to go next

- [**Glossary**](./glossary.md) — every term Styrmin uses, in one
  alphabetical list.
- [**What is an Application Driver?**](./what-is-a-driver.md) — the
  unit of deployment, in depth.
- [**Architecture**](./architecture.md) — the big picture of server,
  agent, and how they talk to each other.
- [**Reconciliation**](./reconciliation.md) — the desired-vs-current
  loop in detail.
