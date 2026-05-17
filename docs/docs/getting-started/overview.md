---
title: Platform Overview
sidebar_position: 1
description: Learn what Styrmin is, the problems it solves, and its core concepts.
---

## Platform Overview

Styrmin is a **deployment orchestration platform** for Kubernetes. It deploys
applications declaratively, reconciles them against a desired state, and gives
you a single place to manage their lifecycle across one or more clusters.

Where a Helm chart describes _how_ to render Kubernetes objects, Styrmin
describes _which application_ should be running, _where_, _at which version_,
and _with which configuration_ — and then drives the cluster toward that state.

### Why Styrmin

- **Declarative deployments.** You describe the intent (driver, version,
  environment, config); Styrmin renders, applies, and reconciles.
- **Versioned, reusable application packaging.** Application Drivers are
  versioned specifications that wrap a Helm chart with components, parameters,
  services, and lifecycle actions.
- **Operational visibility.** The agent continuously reports pod and
  deployment state back to the server, so the API and UI always reflect
  what is actually running.
- **API-first.** The server exposes a GraphQL API; the CLI (`styrminctl`),
  the SDK (`styrmin-sdk`), and the frontend are all clients of that API.

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

- The **server** owns the database and the public GraphQL API.
- The **agent** runs inside the target cluster, picks up _recorded intent_
  (Prefect flows and `StyrminDeployment` CRDs), and reconciles the cluster.
- The **agent** also runs a _status reporter_ that posts observed pod and
  deployment state back to the server.

For the prescriptive principles behind this design, see the
[Styrmin Constitution](https://github.com/opsmill/styrmin/blob/develop/dev/constitution.md).

### Key concepts

The terms below are the canonical vocabulary. They show up unchanged in the
GraphQL schema, the SDK, the CLI, and the rest of this documentation.

#### Application Driver

An **Application Driver** is a versioned, self-contained deployment
specification. A driver wraps a Helm chart with everything Styrmin needs to
deploy it: component definitions, user-facing parameters, network services,
and lifecycle actions.

Each driver lives in a directory containing at least a
`driver.styrmin.yml` file:

```yaml
apiVersion: "styrmin.io/v1"
kind: ApplicationDriver
metadata:
  name: infrahub
spec:
  version: "0.4.0"
  supported_versions: ">=1.6.0,<2.0.0"
  helm:
    main:
      location: oci://registry.opsmill.io/charts/infrahub
      version: "1.6.0"
  components:
    server:
      identifier:
        label:
          styrmin/component: server
  parameters:
    - name: storage_size
      label: "Storage size (Gi)"
      kind: integer
      default: 10
```

Read more in [What is an Application Driver?](../drivers/what-is-a-driver.md).

##### Where to find drivers

Styrmin ships a set of reference drivers in the
[`driver/examples/`](https://github.com/opsmill/styrmin/tree/develop/driver/examples)
directory of the main repository, including `infrahub`, `semaphore`,
`slurpit`, and `simple-app`. These are loaded as
**Application Driver Versions** during the demo bootstrap (see the
[Quickstart](./quickstart.md)) and are a good starting point for writing
your own.

You can also point Styrmin at any directory or git repository that follows
the driver layout.

#### Application Driver Version

A driver is identified by its `name` (e.g. `infrahub`). Each release of that
driver is an **Application Driver Version** — a specific revision of the
spec, with its own Helm chart reference, components, parameters, services
and actions. Deployments always pin to a specific driver version, so
upgrading the driver is an explicit, reviewable action.

#### Cluster

A **Cluster** is a Kubernetes cluster that Styrmin manages. It is
represented by a row in the database and carries:

- a **config** dict (URLs, FQDN suffix, scheme, …);
- a computed **capabilities** dict (what the cluster can do — ingress,
  backups, …);
- exactly one running **agent**.

Currently Styrmin supports exactly **one cluster at a time**. Multi-cluster
support is planned.

#### Environment

An **Environment** is a logical deployment target bound to exactly one
cluster. Think `dev`, `staging`, `prod`, or `team-a` — environments are how
you slice a cluster into named, configurable buckets.

- Names are unique per cluster, not globally.
- Environments carry their own **config** and **capabilities**, which
  override the cluster's values when they overlap.
- A backup storage location (S3-compatible) is assigned per environment;
  every deployment in that environment backs up there.

In short: **a cluster contains environments, and every deployment lives in
exactly one environment**.

```text
Cluster ─┬─ Environment "dev"      ─── Deployment "infrahub-dev"
         │                          └─ Deployment "semaphore-dev"
         └─ Environment "staging"   ─── Deployment "infrahub-staging"
```

#### Deployment

A **Deployment** is the long-lived record of intent: _"run this driver
version, of this application version, in this environment, with this
configuration."_ Editing a deployment expresses new intent and triggers
reconciliation. The agent then drives the cluster to match.

A deployment owns at most one **active Application Instance** — a frozen
snapshot of what was actually deployed at a point in time, including the
full resolved configuration context.

### Next steps

- [**Quickstart**](./quickstart.md) — bring up the built-in demo cluster
  end-to-end with two commands.
- [**What is an Application Driver?**](../drivers/what-is-a-driver.md) —
  learn the driver model in depth.
- [**Specification Reference**](../drivers/specification.md) — full reference
  for every field in `driver.styrmin.yml`.
