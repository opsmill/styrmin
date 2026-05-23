---
title: What is an Application Driver?
sidebar_position: 1
description: Understand Application Drivers and their role in Styrmin deployments.
---

## What is an Application Driver?

An **Application Driver** is a versioned, self-contained deployment
specification that tells Styrmin everything it needs to know about how to
deploy a given application. Drivers are the unit of deployment in Styrmin:
no application can be deployed without one, and all deployment behavior
flows from the driver — there is no ad-hoc deployment logic outside it.

If you've used Helm, the easiest one-liner is:

> A driver is a Helm chart reference, plus the metadata Styrmin needs to
> deploy, observe, configure, and upgrade it as a first-class application.

### What a driver provides

A driver bundles up the following:

- **A Helm chart reference.** Either an OCI registry URL or an HTTP
  repository, pinned to a specific chart version.
- **Component definitions.** Logical sub-parts of the application
  (e.g. `server`, `task-worker`), identified by a Kubernetes label
  selector. Components are what Styrmin starts, stops, scales, and reports
  status on as a unit.
- **User-facing parameters.** Typed inputs (string, integer, boolean,
  enum) the user fills in when creating a deployment. Parameters are
  surfaced in the UI and SDK, and flow into the Helm values via Jinja2.
- **Services.** Network-addressable endpoints declared by the driver
  (kind, scope, port, owning component). Styrmin materialises these as
  Kubernetes `Service` objects.
- **Lifecycle actions.** Python functions that run inside a Prefect flow
  at well-defined points (`setup` or `upgrade`, in `pre` / `core` / `post`
  mode). Use these for migrations, seeding, smoke tests, and any other
  glue an application needs around its Helm release.
- **Supported application versions.** A semver specifier describing which
  versions of the underlying application this driver knows how to deploy.

### Drivers, driver versions, and deployments

Three terms come up together. They are not interchangeable:

| Term | What it is |
|------|------------|
| **Application Driver** | A named driver, identified by `metadata.name` (e.g. `infrahub`). |
| **Application Driver Version** | A specific revision of a driver, with its own Helm chart, components, parameters, services, and actions. Sourced from a directory or a git repository. |
| **Deployment** | A long-lived record of intent that pins a specific driver _version_ + application version into one specific environment, with its config. |

When you upgrade a deployment, you change which driver version it points
at. The driver itself doesn't mutate — every change is a new version.

### File layout

A driver is just a directory:

```text
my-driver/
├── driver.styrmin.yml   # required — the specification
├── values.j2.yml        # optional — Jinja2 template for Helm values
└── actions.py           # required only if the spec declares actions
```

`driver.styrmin.yml` is the single source of truth: it declares metadata,
the Helm chart, components, parameters, services, _and_ the action
declarations (with `actions.py` implementing them). See
[ADR-002](https://github.com/opsmill/styrmin/blob/develop/dev/adr/adr-002-consolidate-driver-single-yaml.md)
for why the spec was consolidated into a single file.

A minimal example:

```yaml
apiVersion: "styrmin.io/v1"
kind: ApplicationDriver
metadata:
  name: infrahub
spec:
  version: "0.4.0"
  supported_versions: ">=1.6.0,<2.0.0"
  info:
    description: "Infrahub deployment driver"
    authors: ["OpsMill"]
  helm:
    main:
      location: oci://registry.opsmill.io/charts/infrahub
      version: "1.6.0"
  components:
    server:
      identifier:
        label:
          styrmin/component: server
    task-worker:
      identifier:
        label:
          styrmin/component: task-worker
  parameters:
    - name: storage_size
      label: "Storage size (Gi)"
      kind: integer
      default: 10
  services:
    - name: web
      kind: http
      scope: external
      port: 8000
      component: server
```

[Creating a Driver](./creating-a-driver.md) walks through writing one
from scratch.

### How a driver becomes a deployment

A driver on disk is inert. To run an application, Styrmin needs to:

1. **Load** the driver — register an Application Driver Version in the
   database, either from a local directory or from a git repository.
2. **Pick an environment** — drivers are not bound to a cluster; the
   _deployment_ is what places the driver version into one specific
   **Environment**, which is in turn bound to one **Cluster**.
3. **Reconcile** — the agent sees the new intent (via a `StyrminDeployment`
   CRD) and reconciles the cluster to match: it renders the Helm values,
   creates the release, schedules lifecycle actions, and reports observed
   state back to the server.

```text
Driver on disk  ──load──►  Application Driver Version
                                 │
                                 │  pinned by
                                 ▼
                          Deployment ── in ──► Environment ── in ──► Cluster
```

### Where to find drivers

#### Bundled examples

The reference repository ships a set of example drivers under
[`driver/examples/`](https://github.com/opsmill/styrmin/tree/develop/driver/examples):

| Driver | Purpose |
|--------|---------|
| [`infrahub`](https://github.com/opsmill/styrmin/tree/develop/driver/examples/infrahub) | OpsMill's Infrahub deployment driver — full-featured reference. |
| [`semaphore`](https://github.com/opsmill/styrmin/tree/develop/driver/examples/semaphore) | Semaphore CI deployment driver. |
| [`slurpit`](https://github.com/opsmill/styrmin/tree/develop/driver/examples/slurpit) | Slurpit network discovery driver. |
| [`simple-app`](https://github.com/opsmill/styrmin/tree/develop/driver/examples/simple-app) | Minimal driver used in tests — read this first if you want a small, complete example. |
| [`db-test`](https://github.com/opsmill/styrmin/tree/develop/driver/examples/db-test) | A driver fixture used by the test suite. |

When you run [`uv run invoke start`](../installation/quickstart.md), the
bootstrap step loads `infrahub` and `semaphore` automatically so you have
something to deploy out of the box.

#### Loading your own

Anywhere you can put a directory that follows the layout above, you can
register it with Styrmin — either as a path mounted into the server
container or as a git repository (public or private). See
[Loading a Driver](./loading-drivers.md) for the full walkthrough,
including the GraphQL mutations, the `styrminctl` commands, and how to
configure the private-repo token.

The [Driver overview in the main repository](https://github.com/opsmill/styrmin/blob/develop/driver/DRIVERS.md)
is the authoritative, version-controlled description of the driver
format.

### Next steps

- [**Loading a Driver**](./loading-drivers.md) — register a driver with
  Styrmin from a local directory or a git repository.
- [**The Context**](./context.md) — the data structure every driver
  template and action receives at runtime.
- [**Creating a Driver**](./creating-a-driver.md) — write your first
  driver, step by step.
